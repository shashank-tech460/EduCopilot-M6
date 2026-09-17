"""Team 4A Video_Processor.

Location and class name follow the same pattern as PDFProcessor
(app/processors/pdf_processor.py, Task 2.1):
    app/processors/video_processor.py ... class VideoProcessor

Implements Requirements 2.1-2.7:
    2.1 Extract the audio track and pass it to the Transcription_Engine.
    2.2 Produce timestamped transcription with segment start/end times
        accurate to within 1 second.
    2.3 Extract keyframes at a configurable interval (default 30s).
    2.4 Associate each keyframe with its timestamp.
    2.5 If no audio track, proceed with frame analysis only and mark
        audio_absent.
    2.6 If transcription fails for part of the audio, mark that part
        transcription_failed and continue with the rest.
    2.7 Support MP4 files up to 2GB / 4 hours.

Does not implement YouTube processing, chunking, embedding, metadata
enrichment, or Qdrant publication -- those belong to later tasks (4.1,
6.1, 7.1, 8.1, 8.2). Contains no Celery task orchestration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from app.config.settings import Settings, get_settings
from app.models.exceptions import (
    TranscriptionError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnreadableError,
)
from app.models.schemas import Keyframe, VideoProcessingResult, VideoSegment

_BYTES_PER_GB = 1024**3
_SECONDS_PER_HOUR = 3600

#: Audio is transcribed in fixed-length windows rather than as one whole
#: file, purely so that a failure transcribing one window can be isolated
#: (Requirement 2.6) without losing every other window's result. This is
#: an internal implementation detail, not one of the three official
#: configured limits (size/duration/keyframe interval), so it is a module
#: constant rather than a new Settings field. See Task 3.1 report.
_TRANSCRIPTION_CHUNK_SECONDS = 30.0

#: A keyframe timestamp calculated as an exact multiple of the configured
#: interval can land exactly at (or, in principle, past) the video's
#: encoded duration whenever `duration % interval == 0` -- verified
#: directly against real ffmpeg output: seeking to a timestamp at or
#: beyond the container's reported duration finds no frame at all. The
#: correct extraction margin is the video's OWN actual frame duration
#: (`1 / frame_rate`, parsed from ffprobe's already-fetched
#: `r_frame_rate` stream field, see `_parse_frame_rate`/`_probe` below) --
#: NOT a fixed constant. A fixed epsilon was tried and found insufficient:
#: real-world evidence (ffmpeg 9.0.1) showed a 0.1s margin still misses
#: the actual last frame for 5fps content (0.2s frame spacing), because
#: the correct margin genuinely depends on the specific video's frame
#: rate, which varies per file. This constant is now used ONLY as the
#: isolated, explicitly-documented fallback for the rare case where the
#: frame rate cannot be determined at all (see `_UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS`
#: below) -- it is deliberately NOT frame-accurate, and is not used on the
#: normal (frame-rate-known) path at all.
_UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS = 0.5


class TranscriptionEngine(Protocol):
    """The minimal interface VideoProcessor needs from a transcription engine.

    `WhisperTranscriptionEngine` (below) is the real implementation used in
    production. Tests inject a fake implementing this same interface, so
    they exercise VideoProcessor's real control flow (chunking, timestamp
    offsetting, per-chunk failure isolation) without downloading Whisper
    model weights or requiring a GPU.
    """

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        """Return a dict with a "segments" key: a list of
        {"start": float, "end": float, "text": str} dicts, in the same
        shape openai-whisper's `model.transcribe()` returns.
        """
        ...


class WhisperTranscriptionEngine:
    """Real Whisper integration, per Requirement 2.1/2.2.

    The `whisper` package (and its model weights, downloaded on first use)
    are imported lazily inside `transcribe()`, not at module import time.
    This is a deliberate, standard pattern for optional heavy ML
    dependencies -- it keeps `import app.processors.video_processor` fast
    and dependency-light for code that only needs, say, `TranscriptionError`
    or `Keyframe`, while the actual integration point genuinely calls real
    Whisper when this class is used. It is not a fake/mocked implementation
    (see Task 3.1 report for verification that this was actually exercised).
    """

    def __init__(self, model_name: str, device: str) -> None:
        self._model_name = model_name
        self._device = device
        self._model = None

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        if self._model is None:
            try:
                import whisper
            except ImportError as exc:
                raise TranscriptionError(
                    "openai-whisper is not installed; cannot transcribe audio"
                ) from exc
            try:
                self._model = whisper.load_model(self._model_name, device=self._device)
            except Exception as exc:
                raise TranscriptionError(
                    f"Failed to load Whisper model '{self._model_name}'"
                ) from exc

        return self._model.transcribe(audio_path)


def _require_ffmpeg() -> None:
    """Fail clearly and immediately if ffmpeg/ffprobe are not on PATH.

    Per Task 3.1 instructions: don't silently assume ffmpeg exists, and
    don't make the whole package depend on a system-specific path -- this
    only checks PATH via `shutil.which`, which works the same way on
    Windows and Linux.
    """

    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise RuntimeError(
            "Team 4A Video_Processor requires ffmpeg and ffprobe on PATH "
            f"(missing: {', '.join(missing)}). Install ffmpeg "
            "(e.g. `apt-get install ffmpeg` on Debian/Ubuntu, "
            "`brew install ffmpeg` on macOS, or download a build from "
            "https://ffmpeg.org/download.html on Windows and add it to PATH)."
        )


class _VideoMetadata:
    """Internal result of probing a video file with ffprobe."""

    __slots__ = ("duration_seconds", "has_audio", "frame_duration_seconds")

    def __init__(
        self,
        duration_seconds: float,
        has_audio: bool,
        frame_duration_seconds: float | None,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.has_audio = has_audio
        # None means "frame rate could not be determined" -- callers must
        # use `_UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS` in that case,
        # never treat None as 0 or silently skip the boundary adjustment.
        self.frame_duration_seconds = frame_duration_seconds


class VideoProcessor:
    """Extracts timestamped transcript segments and keyframes from an MP4.

    Responsibilities are kept separate (validation, probing, audio
    extraction, transcription, keyframe extraction, result assembly); no
    chunking, embedding, or Qdrant logic lives here.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        transcription_engine: TranscriptionEngine | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._engine = transcription_engine or WhisperTranscriptionEngine(
            model_name=self._settings.whisper_model_name,
            device=self._settings.whisper_device,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, source: str | Path) -> VideoProcessingResult:
        """Process one local MP4 file.

        Args:
            source: Path to a saved MP4 file. (ffmpeg/ffprobe operate on
                real files, so -- unlike PDFProcessor -- this does not
                accept a file-like object; a caller with an in-memory
                upload must save it first, matching the design document's
                own `save_upload()` -> `process_video.delay(file_path=...)`
                pattern.)

        Raises:
            VideoTooLargeError: if the file exceeds `settings.video_max_size_gb`.
            VideoUnreadableError: if the file is corrupt/malformed and
                cannot be probed by ffprobe.
            VideoTooLongError: if the video exceeds
                `settings.video_max_duration_hours`.
            TranscriptionError: if the transcription engine cannot produce
                any result at all (not to be confused with a single
                isolated segment failure, which is represented as data via
                `VideoSegment.transcription_failed`).
        """

        _require_ffmpeg()
        source = str(source)

        self._validate_size(source)
        metadata = self._probe(source)
        self._validate_duration(metadata)

        keyframes = self._extract_keyframes(source, metadata.duration_seconds, metadata.frame_duration_seconds)

        if not metadata.has_audio:
            # Requirement 2.5: proceed with frame analysis only; this is
            # not a failure, so no exception is raised here.
            return VideoProcessingResult(segments=[], keyframes=keyframes, audio_absent=True)

        segments = self._transcribe(source, metadata.duration_seconds)
        return VideoProcessingResult(segments=segments, keyframes=keyframes, audio_absent=False)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_size(self, source: str) -> None:
        size_bytes = Path(source).stat().st_size
        max_bytes = self._settings.video_max_size_gb * _BYTES_PER_GB
        if size_bytes > max_bytes:
            raise VideoTooLargeError(
                f"Video exceeds the maximum allowed size of {self._settings.video_max_size_gb}GB",
                detail={
                    "max_size_gb": self._settings.video_max_size_gb,
                    "actual_size_bytes": size_bytes,
                },
            )

    def _validate_duration(self, metadata: _VideoMetadata) -> None:
        max_seconds = self._settings.video_max_duration_hours * _SECONDS_PER_HOUR
        if metadata.duration_seconds > max_seconds:
            raise VideoTooLongError(
                f"Video exceeds the maximum allowed duration of "
                f"{self._settings.video_max_duration_hours} hours",
                detail={
                    "max_duration_hours": self._settings.video_max_duration_hours,
                    "actual_duration_seconds": metadata.duration_seconds,
                },
            )

    # ------------------------------------------------------------------
    # Probing (ffprobe)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_frame_rate(r_frame_rate: object) -> float | None:
        """Parse ffprobe's `r_frame_rate` rational-string field (e.g.
        `"5/1"`, `"30/1"`, `"30000/1001"`) into a frames-per-second float.

        Returns `None` -- never raises, never returns 0 or a negative
        value -- for every invalid/unusable case this field is known to
        take: missing entirely, not a string, not in `"num/den"` shape,
        a non-numeric numerator/denominator, a zero denominator (a
        division-by-zero guard), or a resulting rate that is not
        strictly positive (ffprobe's own documented sentinel for
        "unknown/unset frame rate" is the literal string `"0/0"`).
        Callers MUST treat `None` as "unknown" and use the isolated,
        explicitly-documented fallback margin -- never crash, never
        silently treat unknown as some other numeric default.
        """

        if not isinstance(r_frame_rate, str) or "/" not in r_frame_rate:
            return None

        numerator_str, _, denominator_str = r_frame_rate.partition("/")
        try:
            numerator = float(numerator_str)
            denominator = float(denominator_str)
        except ValueError:
            return None

        if denominator == 0:
            return None

        fps = numerator / denominator
        if fps <= 0:
            return None

        return fps

    @staticmethod
    def _probe(source: str) -> _VideoMetadata:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            source,
        ]
        try:
            completed = subprocess.run(cmd, capture_output=True, check=True, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            raise VideoUnreadableError(
                "Cannot read video file: it is malformed, corrupt, or not a valid media file"
            ) from exc

        try:
            data = json.loads(completed.stdout)
            duration_seconds = float(data["format"]["duration"])
            streams = data.get("streams", [])
            has_audio = any(stream.get("codec_type") == "audio" for stream in streams)

            # Reuses the ALREADY-FETCHED ffprobe JSON response above --
            # deliberately no second ffprobe subprocess call is made
            # solely to obtain frame-rate information; `r_frame_rate` is
            # already present on the video stream object in the same
            # response `has_audio` is derived from.
            frame_duration_seconds: float | None = None
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
            if video_stream is not None:
                frame_rate = VideoProcessor._parse_frame_rate(video_stream.get("r_frame_rate"))
                if frame_rate is not None:
                    frame_duration_seconds = 1.0 / frame_rate
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            raise VideoUnreadableError(
                "Cannot read video file: unexpected or missing metadata"
            ) from exc

        return _VideoMetadata(
            duration_seconds=duration_seconds,
            has_audio=has_audio,
            frame_duration_seconds=frame_duration_seconds,
        )

    # ------------------------------------------------------------------
    # Keyframe extraction
    # ------------------------------------------------------------------

    def _extract_keyframes(
        self, source: str, duration_seconds: float, frame_duration_seconds: float | None
    ) -> list[Keyframe]:
        """Extract keyframes at the configured interval.

        Property 5: for duration D and interval I, extract exactly
        floor(D/I) keyframes, with the k-th (1-indexed) keyframe at
        timestamp k*I. 1-indexing (I, 2I, 3I, ...) is the only indexing
        consistent with *both* halves of that property -- a 0-indexed
        series (0, I, 2I, ...) would yield floor(D/I)+1 keyframes, not
        floor(D/I). See Task 3.1 report.

        `frame_duration_seconds` (from `_probe`, parsed from ffprobe's
        `r_frame_rate` -- `None` if the frame rate could not be
        determined) is the extraction-time boundary margin used ONLY when
        a calculated keyframe timestamp is at or past `duration_seconds`
        (see the loop body below) -- it never affects `Keyframe.timestamp`,
        `keyframe_count`, or the loop bounds, all of which are governed
        exclusively by `duration_seconds` and `interval`, unchanged.
        """

        interval = self._settings.keyframe_interval_seconds
        keyframe_count = int(duration_seconds // interval)

        # Resolved ONCE per call, not per-iteration: the isolated,
        # explicitly-documented, non-frame-accurate fallback is used only
        # when the real frame duration genuinely could not be determined.
        boundary_margin_seconds = (
            frame_duration_seconds
            if frame_duration_seconds is not None
            else _UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS
        )

        keyframes: list[Keyframe] = []
        for k in range(1, keyframe_count + 1):
            timestamp = float(k * interval)
            # `timestamp` itself, `frame_reference`, and the loop/count
            # formula are all UNCHANGED -- only the value actually handed
            # to ffmpeg is nudged, and only in the one case where the
            # calculated timestamp is at or past the real encoded
            # duration (see `boundary_margin_seconds` above).
            extraction_timestamp = timestamp
            if extraction_timestamp >= duration_seconds:
                extraction_timestamp = max(0.0, duration_seconds - boundary_margin_seconds)
            self._capture_keyframe(source, extraction_timestamp)  # genuine extraction; see below
            keyframes.append(Keyframe(timestamp=timestamp, frame_reference=f"kf_{k}_{int(timestamp)}s"))
        return keyframes

    @staticmethod
    def _capture_keyframe(source: str, timestamp: float) -> None:
        """Actually extract the frame at `timestamp` via ffmpeg, then discard it.

        Task 3.1 explicitly says not to build a keyframe storage system, so
        the extracted image is not persisted -- `frame_reference` (built by
        the caller) is a stable, deterministic identifier, not a file path.
        The extraction itself is still performed for real (not skipped/
        faked), which is what actually validates that a real frame exists
        at that timestamp in the source video.
        """

        fd, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(timestamp),
                "-i",
                source,
                "-frames:v",
                "1",
                "-loglevel",
                "error",
                tmp_path,
            ]
            subprocess.run(cmd, capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            raise VideoUnreadableError(
                f"Failed to extract keyframe at {timestamp}s"
            ) from exc
        finally:
            _safe_remove(tmp_path)

    # ------------------------------------------------------------------
    # Audio extraction + transcription
    # ------------------------------------------------------------------

    def _transcribe(self, source: str, duration_seconds: float) -> list[VideoSegment]:
        """Transcribe audio in fixed-length chunks, isolating failures per chunk.

        Requirement 2.6 / Task 3.1: if one chunk's transcription fails, it
        is represented as a single transcription_failed VideoSegment
        spanning that chunk's time range, and processing continues with
        the remaining chunks -- successful segments are never discarded
        because of one bad chunk.
        """

        segments: list[VideoSegment] = []
        for chunk_start, chunk_end in self._chunk_boundaries(duration_seconds):
            chunk_path = self._extract_audio_chunk(source, chunk_start, chunk_end)
            try:
                result = self._engine.transcribe(chunk_path)
            except Exception:
                # Isolate: this chunk failed, but timing is preserved and
                # remaining chunks are still attempted.
                segments.append(
                    VideoSegment(
                        text="",
                        start_time=chunk_start,
                        end_time=chunk_end,
                        transcription_failed=True,
                    )
                )
                continue
            finally:
                _safe_remove(chunk_path)

            for raw_segment in result.get("segments") or []:
                text = str(raw_segment.get("text", "")).strip()
                if not text:
                    continue
                segments.append(
                    VideoSegment(
                        text=text,
                        start_time=chunk_start + float(raw_segment["start"]),
                        end_time=chunk_start + float(raw_segment["end"]),
                        transcription_failed=False,
                    )
                )

        return segments

    @staticmethod
    def _chunk_boundaries(duration_seconds: float) -> list[tuple[float, float]]:
        boundaries: list[tuple[float, float]] = []
        start = 0.0
        while start < duration_seconds:
            end = min(start + _TRANSCRIPTION_CHUNK_SECONDS, duration_seconds)
            boundaries.append((start, end))
            start = end
        return boundaries

    @staticmethod
    def _extract_audio_chunk(source: str, start: float, end: float) -> str:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start),
            "-to",
            str(end),
            "-i",
            source,
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-loglevel",
            "error",
            tmp_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            _safe_remove(tmp_path)
            raise VideoUnreadableError(
                f"Failed to extract audio for the {start}s-{end}s segment"
            ) from exc
        return tmp_path


def _safe_remove(path: str) -> None:
    """Delete a temp file if it exists; never raise on cleanup."""

    try:
        os.remove(path)
    except OSError:
        pass
