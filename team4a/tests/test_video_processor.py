"""Unit tests for Task 3.1: VideoProcessor.

Video fixtures are synthesized locally with ffmpeg's lavfi virtual inputs
(see video_fixtures.py) -- no binary media files are committed and no
network access is required.

Whisper itself is mocked via a fake TranscriptionEngine in every test
(per Task 3.1 instructions: mock Whisper/model inference, but exercise the
real VideoProcessor control flow around it). ffmpeg/ffprobe are real --
they're required system tools, not something to fake, and are cheap/fast
to invoke on the tiny synthetic fixtures used here.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.models.exceptions import (
    TranscriptionError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnreadableError,
)
from app.models.schemas import VideoProcessingResult, VideoSegment
from app.processors.video_processor import VideoProcessor
from tests.video_fixtures import make_corrupt_video, make_video_with_audio, make_video_without_audio

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

pytestmark = pytest.mark.skipif(
    not FFMPEG_AVAILABLE,
    reason="ffmpeg/ffprobe not found on PATH; required to generate and probe test video fixtures.",
)


class FakeTranscriptionEngine:
    """Deterministic stand-in for Whisper.

    `responses` maps call index (0-based) to either a whisper-shaped result
    dict, or an Exception instance to raise for that call -- lets tests
    simulate a specific chunk failing without any real model inference.
    """

    def __init__(self, responses: list[dict[str, Any] | Exception] | None = None) -> None:
        self._responses = responses or []
        self.calls: list[str] = []

    def transcribe(self, audio_path: str) -> dict[str, Any]:
        self.calls.append(audio_path)
        index = len(self.calls) - 1
        if index < len(self._responses):
            response = self._responses[index]
            if isinstance(response, Exception):
                raise response
            return response
        return {"segments": []}


def default_engine(text: str = "hello world") -> FakeTranscriptionEngine:
    return FakeTranscriptionEngine([{"segments": [{"start": 0.2, "end": 1.8, "text": f" {text} "}]}])


# ---------------------------------------------------------------------------
# 1-3. Basic processing / timestamped segments / valid timestamps
# ---------------------------------------------------------------------------


def test_basic_video_processing_returns_result(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    processor = VideoProcessor(transcription_engine=default_engine())

    result = processor.process(path)

    assert isinstance(result, VideoProcessingResult)
    assert result.audio_absent is False


def test_timestamped_transcription_segments_produced(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    processor = VideoProcessor(transcription_engine=default_engine("hello world"))

    result = processor.process(path)

    assert len(result.segments) == 1
    assert isinstance(result.segments[0], VideoSegment)
    assert result.segments[0].text == "hello world"


def test_segment_start_and_end_timestamps_are_valid(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    processor = VideoProcessor(transcription_engine=default_engine())

    result = processor.process(path)

    segment = result.segments[0]
    assert segment.start_time >= 0
    assert segment.end_time > segment.start_time
    assert segment.start_time == pytest.approx(0.2, abs=1.0)
    assert segment.end_time == pytest.approx(1.8, abs=1.0)


# ---------------------------------------------------------------------------
# 4. Whisper invoked with configured model
# ---------------------------------------------------------------------------


def test_whisper_transcription_engine_uses_configured_model():
    from app.config.settings import Settings
    from app.processors.video_processor import WhisperTranscriptionEngine

    settings = Settings(whisper_model_name="small", whisper_device="cpu", _env_file=None)
    processor = VideoProcessor(settings=settings)

    assert isinstance(processor._engine, WhisperTranscriptionEngine)
    assert processor._engine._model_name == "small"
    assert processor._engine._device == "cpu"


def test_whisper_engine_lazily_imports_whisper_only_on_first_transcribe_call():
    from app.processors.video_processor import WhisperTranscriptionEngine

    engine = WhisperTranscriptionEngine(model_name="base", device="cpu")
    assert engine._model is None


# ---------------------------------------------------------------------------
# 5-6. Size / duration limits
# ---------------------------------------------------------------------------


def test_configured_size_limit_is_respected(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    tiny_limit_settings = SimpleNamespace(
        video_max_size_gb=0,
        video_max_duration_hours=4,
        keyframe_interval_seconds=30,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=tiny_limit_settings, transcription_engine=default_engine())

    with pytest.raises(VideoTooLargeError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "VideoTooLarge"
    assert not isinstance(exc_info.value, VideoUnreadableError)


def test_configured_duration_limit_is_respected(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=5)
    tiny_duration_settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=0.0005,  # ~1.8 seconds
        keyframe_interval_seconds=30,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=tiny_duration_settings, transcription_engine=default_engine())

    with pytest.raises(VideoTooLongError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "VideoTooLong"
    assert not isinstance(exc_info.value, VideoUnreadableError)


def test_video_within_limits_is_accepted(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=30,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=settings, transcription_engine=default_engine())

    result = processor.process(path)

    assert result.audio_absent is False


def test_uses_configured_settings_not_hardcoded_defaults():
    from app.config.settings import get_settings

    settings = get_settings()
    processor = VideoProcessor(transcription_engine=default_engine())
    assert processor._settings.video_max_size_gb == settings.video_max_size_gb
    assert processor._settings.video_max_duration_hours == settings.video_max_duration_hours
    assert processor._settings.keyframe_interval_seconds == settings.keyframe_interval_seconds


# ---------------------------------------------------------------------------
# 7. Audio-absent handling
# ---------------------------------------------------------------------------


def test_audio_absent_video_is_marked_and_not_treated_as_failure(tmp_path):
    path = make_video_without_audio(tmp_path / "silent.mp4", duration=2)
    engine = FakeTranscriptionEngine()
    processor = VideoProcessor(transcription_engine=engine)

    result = processor.process(path)

    assert result.audio_absent is True
    assert result.segments == []
    assert engine.calls == []


def test_audio_absent_video_still_produces_keyframes(tmp_path):
    path = make_video_without_audio(tmp_path / "silent.mp4", duration=65)
    processor = VideoProcessor(transcription_engine=FakeTranscriptionEngine())

    result = processor.process(path)

    assert result.audio_absent is True
    assert len(result.keyframes) == 2  # floor(65/30)


# ---------------------------------------------------------------------------
# 8-9. Transcription failure isolation
# ---------------------------------------------------------------------------


def test_transcription_failure_isolated_to_affected_segment(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=65)  # chunks: 0-30, 30-60, 60-65
    engine = FakeTranscriptionEngine(
        [
            {"segments": [{"start": 1.0, "end": 2.0, "text": "first chunk ok"}]},
            RuntimeError("simulated whisper crash"),
            {"segments": [{"start": 0.5, "end": 1.5, "text": "third chunk ok"}]},
        ]
    )
    processor = VideoProcessor(transcription_engine=engine)

    result = processor.process(path)

    assert len(result.segments) == 3
    assert result.segments[0].transcription_failed is False
    assert result.segments[0].text == "first chunk ok"
    assert result.segments[1].transcription_failed is True
    assert result.segments[1].text == ""
    assert result.segments[1].start_time == 30.0
    assert result.segments[1].end_time == 60.0
    assert result.segments[2].transcription_failed is False
    assert result.segments[2].text == "third chunk ok"


def test_successful_segments_preserved_despite_a_failing_segment(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=65)
    engine = FakeTranscriptionEngine(
        [
            {"segments": [{"start": 0.0, "end": 1.0, "text": "ok one"}]},
            RuntimeError("boom"),
            {"segments": [{"start": 0.0, "end": 1.0, "text": "ok two"}]},
        ]
    )
    processor = VideoProcessor(transcription_engine=engine)

    result = processor.process(path)

    successful_texts = [s.text for s in result.segments if not s.transcription_failed]
    assert successful_texts == ["ok one", "ok two"]


def test_engine_is_called_once_per_chunk(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=65)
    engine = FakeTranscriptionEngine()
    processor = VideoProcessor(transcription_engine=engine)

    processor.process(path)

    assert len(engine.calls) == 3  # 0-30, 30-60, 60-65


# ---------------------------------------------------------------------------
# 10-11. Keyframes
# ---------------------------------------------------------------------------


def test_keyframes_generated_using_configured_interval(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=95)
    custom_interval_settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=30,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(
        settings=custom_interval_settings, transcription_engine=FakeTranscriptionEngine()
    )

    result = processor.process(path)

    assert len(result.keyframes) == 3  # floor(95 / 30)


def test_keyframe_timestamps_are_multiples_of_the_interval(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=95)
    processor = VideoProcessor(transcription_engine=FakeTranscriptionEngine())

    result = processor.process(path)

    timestamps = [kf.timestamp for kf in result.keyframes]
    assert timestamps == [30.0, 60.0, 90.0]


def test_no_keyframes_beyond_video_duration(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=95)
    processor = VideoProcessor(transcription_engine=FakeTranscriptionEngine())

    result = processor.process(path)

    assert all(kf.timestamp < 95 for kf in result.keyframes)


def test_no_keyframes_for_video_shorter_than_interval(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    processor = VideoProcessor(transcription_engine=default_engine())

    result = processor.process(path)

    assert result.keyframes == []


def test_keyframe_at_exact_duration_multiple_boundary_does_not_raise(tmp_path):
    """Regression test for the pre-existing boundary defect: when duration
    is an exact multiple of interval, the last calculated keyframe
    timestamp (k*interval) lands exactly at the video's encoded duration,
    where no real ffmpeg frame exists ("Output file is empty, nothing was
    encoded"). `process()` must complete successfully, the documented
    floor(D/I) count must be preserved exactly, and `Keyframe.timestamp`
    must still report the original, documented k*interval value (90.0),
    NOT the internally-nudged ffmpeg-facing extraction timestamp."""

    path = make_video_with_audio(tmp_path / "video_90.mp4", duration=90)
    settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=10,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=settings, transcription_engine=FakeTranscriptionEngine())
    actual_duration = VideoProcessor._probe(str(path)).duration_seconds

    result = processor.process(path)  # must not raise VideoUnreadableError

    assert len(result.keyframes) == int(actual_duration // 10)  # floor(D/I), unchanged formula
    timestamps = [kf.timestamp for kf in result.keyframes]
    assert timestamps == [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0], (
        "Keyframe.timestamp must still report the original k*interval value, "
        "including the exact-duration boundary case -- only the internal "
        "ffmpeg-facing extraction call is nudged, never this reported value"
    )


@pytest.mark.parametrize("duration,interval", [(90, 10), (90, 15), (30, 15), (60, 30), (30, 30)])
def test_other_exact_multiple_boundaries_do_not_raise(tmp_path, duration, interval):
    """Every combination in this parametrization has duration % interval == 0,
    i.e. every one of them hits the exact same boundary condition -- swept
    across several of the interval values the existing property-test
    strategy already samples from ({10, 15, 30}, per
    tests/test_video_processor_properties.py)."""

    path = make_video_with_audio(tmp_path / f"video_{duration}_{interval}.mp4", duration=duration)
    settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=interval,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=settings, transcription_engine=FakeTranscriptionEngine())
    actual_duration = VideoProcessor._probe(str(path)).duration_seconds

    result = processor.process(path)  # must not raise

    assert len(result.keyframes) == int(actual_duration // interval)
    if result.keyframes:
        assert result.keyframes[-1].timestamp == pytest.approx(actual_duration, abs=1.0)


@pytest.mark.parametrize(
    "duration,interval,expected_extraction_timestamp",
    [
        (90, 10, 89.8),
        (30, 15, 29.8),
        (60, 30, 59.8),
    ],
)
def test_boundary_extraction_timestamp_is_frame_rate_derived_not_a_fixed_epsilon(
    tmp_path, duration, interval, expected_extraction_timestamp, monkeypatch
):
    """Direct regression test for the real ffmpeg-9.0.1 finding: the
    fixture's 5 FPS video has a real frame spacing of exactly 0.2s, so the
    last real frame of a 90s/30s/60s video sits at 89.8s/29.8s/59.8s
    respectively -- NOT `duration - 0.1s`, which was the prior (incorrect)
    fixed-epsilon fix and does not correspond to any real frame at 5 FPS.

    Verifies the actual ffmpeg-facing extraction timestamp directly (by
    spying on `_capture_keyframe`), while separately confirming
    `Keyframe.timestamp` -- the public/logical value -- remains exactly
    the original `duration` value, completely unaffected by the internal
    extraction-margin correction.
    """

    path = make_video_with_audio(tmp_path / f"video_{duration}_{interval}_fps.mp4", duration=duration)
    settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=interval,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=settings, transcription_engine=FakeTranscriptionEngine())

    captured_timestamps: list[float] = []
    real_capture = VideoProcessor._capture_keyframe

    def spying_capture(source, timestamp):
        captured_timestamps.append(timestamp)
        return real_capture(source, timestamp)

    monkeypatch.setattr(VideoProcessor, "_capture_keyframe", staticmethod(spying_capture))
    result = processor.process(path)

    # The public/logical Keyframe.timestamp is unaffected -- still the
    # original `duration` value for the last (boundary) keyframe.
    assert result.keyframes[-1].timestamp == pytest.approx(float(duration), abs=1e-9)

    # The actual ffmpeg-facing extraction timestamp used for that last
    # keyframe is the frame-rate-derived value, not a fixed constant.
    assert captured_timestamps[-1] == pytest.approx(expected_extraction_timestamp, abs=1e-9)


class TestParseFrameRate:
    """Unit coverage for VideoProcessor._parse_frame_rate -- the isolated
    ffprobe `r_frame_rate` rational-string parser introduced by the
    frame-rate-derived boundary fix. Every case here must return `None`
    (never raise, never silently return 0 or a negative value) for
    anything that isn't a valid, strictly-positive rational rate.
    """

    @pytest.mark.parametrize(
        "r_frame_rate,expected_fps",
        [
            ("5/1", 5.0),
            ("30/1", 30.0),
            ("30000/1001", pytest.approx(29.97002997, abs=1e-6)),
            ("25/1", 25.0),
        ],
    )
    def test_valid_rational_strings_parse_correctly(self, r_frame_rate, expected_fps):
        assert VideoProcessor._parse_frame_rate(r_frame_rate) == expected_fps

    @pytest.mark.parametrize(
        "invalid_value",
        [
            None,
            "",
            "not-a-rate",
            "5",  # missing the "/denominator" part entirely
            "5/0",  # denominator == 0
            "0/0",  # ffprobe's own documented sentinel for "unknown"
            "-5/1",  # non-positive resulting rate
            "0/1",  # non-positive resulting rate
            "abc/1",  # non-numeric numerator
            "5/xyz",  # non-numeric denominator
            42,  # not a string at all
            [],  # not a string at all
        ],
    )
    def test_invalid_values_return_none_never_raise(self, invalid_value):
        assert VideoProcessor._parse_frame_rate(invalid_value) is None


def test_unknown_frame_rate_falls_back_to_the_documented_conservative_margin(tmp_path, monkeypatch):
    """When `_probe` cannot determine a frame rate at all (simulated here
    directly, since forcing a real ffprobe response with no r_frame_rate
    field is impractical), `_extract_keyframes` must fall back to the
    isolated, explicitly-documented fallback margin rather than crashing
    or silently treating unknown as 0."""

    from app.processors.video_processor import _UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS

    settings = SimpleNamespace(
        video_max_size_gb=2,
        video_max_duration_hours=4,
        keyframe_interval_seconds=10,
        whisper_model_name="base",
        whisper_device="cpu",
    )
    processor = VideoProcessor(settings=settings, transcription_engine=FakeTranscriptionEngine())

    captured_timestamps: list[float] = []
    monkeypatch.setattr(
        VideoProcessor,
        "_capture_keyframe",
        staticmethod(lambda source, timestamp: captured_timestamps.append(timestamp)),
    )

    keyframes = processor._extract_keyframes("unused-source", 90.0, frame_duration_seconds=None)

    assert len(keyframes) == 9  # unchanged count formula
    assert keyframes[-1].timestamp == 90.0  # unchanged logical timestamp
    assert captured_timestamps[-1] == pytest.approx(
        90.0 - _UNKNOWN_FRAME_RATE_FALLBACK_MARGIN_SECONDS, abs=1e-9
    )


# ---------------------------------------------------------------------------
# 13. Temporary file cleanup
# ---------------------------------------------------------------------------


def test_temporary_audio_chunk_files_are_cleaned_up(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    engine = FakeTranscriptionEngine()
    processor = VideoProcessor(transcription_engine=engine)

    processor.process(path)

    assert len(engine.calls) == 1
    chunk_path = Path(engine.calls[0])
    assert not chunk_path.exists()


def test_temporary_files_cleaned_up_even_when_transcription_fails(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    engine = FakeTranscriptionEngine([RuntimeError("boom")])
    processor = VideoProcessor(transcription_engine=engine)

    processor.process(path)

    chunk_path = Path(engine.calls[0])
    assert not chunk_path.exists()


# ---------------------------------------------------------------------------
# 14. Invalid/unreadable video
# ---------------------------------------------------------------------------


def test_corrupt_video_raises_video_unreadable_error(tmp_path):
    path = make_corrupt_video(tmp_path / "corrupt.mp4")
    processor = VideoProcessor(transcription_engine=default_engine())

    with pytest.raises(VideoUnreadableError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "VideoUnreadable"


def test_unreadable_video_error_does_not_leak_raw_bytes(tmp_path):
    path = make_corrupt_video(tmp_path / "corrupt.mp4")
    processor = VideoProcessor(transcription_engine=default_engine())

    with pytest.raises(VideoUnreadableError) as exc_info:
        processor.process(path)

    assert "This is not a real MP4 file" not in exc_info.value.message


# ---------------------------------------------------------------------------
# 15. Output model contract
# ---------------------------------------------------------------------------


def test_output_segments_are_video_segment_instances(tmp_path):
    path = make_video_with_audio(tmp_path / "video.mp4", duration=2)
    processor = VideoProcessor(transcription_engine=default_engine())

    result = processor.process(path)

    assert isinstance(result, VideoProcessingResult)
    for segment in result.segments:
        assert isinstance(segment, VideoSegment)
        payload = segment.model_dump()
        assert set(payload.keys()) == {
            "text",
            "start_time",
            "end_time",
            "frame_reference",
            "transcription_failed",
        }


# ---------------------------------------------------------------------------
# Global transcription-engine failure (distinct from per-segment isolation)
# ---------------------------------------------------------------------------


def test_transcription_error_raised_when_whisper_cannot_be_loaded():
    from app.processors.video_processor import WhisperTranscriptionEngine

    class BrokenWhisperEngine(WhisperTranscriptionEngine):
        def transcribe(self, audio_path: str) -> dict[str, Any]:
            raise TranscriptionError("Failed to load Whisper model 'base'")

    engine = BrokenWhisperEngine(model_name="base", device="cpu")
    with pytest.raises(TranscriptionError):
        engine.transcribe("does-not-matter.wav")
