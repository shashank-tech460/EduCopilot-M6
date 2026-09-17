"""Team 4A YouTube_Processor.

Location and class name follow the same pattern as PDFProcessor and
VideoProcessor:
    app/processors/youtube_processor.py ... class YouTubeProcessor

Implements Requirements 3.1-3.6:
    3.1 Fetch the video transcript using the YouTube Transcript API.
    3.2 Preserve timestamp information (start time, duration) per segment.
    3.3 Extract video metadata (title, channel, duration, publication date).
    3.4 Raise TranscriptUnavailable if no transcript exists.
    3.5 Raise VideoInaccessible if the URL is invalid/private/removed.
    3.6 Select the requested language, defaulting to English.

Does not implement chunking, embedding, metadata enrichment, or Qdrant
publication -- those belong to later tasks (6.1, 7.1, 8.1, 8.2). Contains
no Celery task orchestration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from app.config.settings import Settings, get_settings
from app.models.exceptions import TranscriptUnavailableError, VideoInaccessibleError
from app.models.schemas import YouTubeMetadata, YouTubeProcessingResult, YouTubeSegment

_WATCH_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
_SHORT_HOST = "youtu.be"


class TranscriptClient(Protocol):
    """The minimal interface YouTubeProcessor needs for transcript retrieval.

    `YouTubeTranscriptApiClient` (below) is the real implementation. Tests
    inject a fake implementing this same interface, so they exercise
    YouTubeProcessor's real control flow without any network access.
    """

    def fetch(self, video_id: str, language: str) -> list[dict[str, Any]]:
        """Return raw entries: [{"text": str, "start": float, "duration": float}, ...].

        Raises TranscriptUnavailableError or VideoInaccessibleError per the
        mapping documented on `YouTubeTranscriptApiClient`.
        """
        ...


class MetadataClient(Protocol):
    """The minimal interface YouTubeProcessor needs for metadata retrieval.

    `YtDlpMetadataClient` (below) is the real implementation. Tests inject
    a fake implementing this same interface.
    """

    def fetch(self, url: str) -> dict[str, Any]:
        """Return a provider-shaped metadata dict (yt-dlp's `extract_info`
        shape: at least "title", "channel"/"uploader", "duration",
        "upload_date").

        Raises VideoInaccessibleError if the video cannot be reached.
        """
        ...


class YouTubeTranscriptApiClient:
    """Real transcript retrieval via the `youtube-transcript-api` package.

    Error mapping (see Task 4.1 report for the full rationale):
        TranscriptsDisabled, NoTranscriptFound
            -> TranscriptUnavailableError (video is reachable; the
               transcript specifically is what's missing)
        Any other CouldNotRetrieveTranscript subtype (VideoUnavailable,
        VideoUnplayable, AgeRestricted, InvalidVideoId, IpBlocked,
        RequestBlocked, YouTubeRequestFailed, ...)
            -> VideoInaccessibleError (the video itself, or the provider's
               ability to reach it, is the problem -- not the transcript)
    """

    def fetch(self, video_id: str, language: str) -> list[dict[str, Any]]:
        from youtube_transcript_api import (
            CouldNotRetrieveTranscript,
            NoTranscriptFound,
            TranscriptsDisabled,
            YouTubeTranscriptApi,
        )

        api = YouTubeTranscriptApi()

        try:
            transcript_list = api.list(video_id)
            transcript = transcript_list.find_transcript([language])
            fetched = transcript.fetch()
        except (TranscriptsDisabled, NoTranscriptFound) as exc:
            raise TranscriptUnavailableError(
                f"No transcript available for this video in language '{language}'"
            ) from exc
        except CouldNotRetrieveTranscript as exc:
            raise VideoInaccessibleError(
                "YouTube video is inaccessible or could not be retrieved"
            ) from exc

        return [
            {"text": snippet.text, "start": snippet.start, "duration": snippet.duration}
            for snippet in fetched.snippets
        ]


class YtDlpMetadataClient:
    """Real metadata retrieval via yt-dlp, without downloading video content.

    `download=False` means yt-dlp only extracts metadata (via YouTube's
    page/API responses), never fetches the actual media stream.
    """

    def fetch(self, url: str) -> dict[str, Any]:
        import yt_dlp

        options = {"quiet": True, "no_warnings": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise VideoInaccessibleError(
                "YouTube video is inaccessible or could not be retrieved"
            ) from exc

        if info is None:
            raise VideoInaccessibleError("YouTube video is inaccessible or could not be retrieved")
        return info


def _extract_video_id(url: str) -> str:
    """Parse a YouTube URL and return its video ID.

    Supports http(s)://youtube.com/watch?v=ID (with any other query params)
    and http(s)://youtu.be/ID short links. Anything else -- malformed
    URLs, a non-http(s) scheme (e.g. ftp://youtube.com/... -- YouTube is
    only ever served over http/https, so this cannot be a real accessible
    video URL), non-YouTube domains, or a recognized-looking URL with no
    video ID -- is treated as an inaccessible video (Task 4.1's "invalid
    video ID" is explicitly listed as a VideoInaccessible example), not a
    distinct validation error type.

    Uses only `urllib.parse` -- no shell execution, no string
    concatenation of the untrusted URL into a command.
    """

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if scheme not in ("http", "https"):
        raise VideoInaccessibleError("URL is not a recognized YouTube video URL")

    if host in _WATCH_HOSTS and parsed.path == "/watch":
        video_ids = parse_qs(parsed.query).get("v")
        if video_ids and video_ids[0]:
            return video_ids[0]
    elif host == _SHORT_HOST:
        candidate = parsed.path.lstrip("/")
        if candidate:
            return candidate

    raise VideoInaccessibleError("URL is not a recognized YouTube video URL")


def _parse_metadata(raw: dict[str, Any]) -> YouTubeMetadata:
    """Convert a yt-dlp-shaped metadata dict into the typed YouTubeMetadata model.

    Requirement 3.3 / Property 9 / Property 20 require title, channel,
    duration, AND publication date for any accessible video. This was
    revisited in a Task 8.3 remediation: yt-dlp's full-extraction mode
    (`download=False`, not flat/playlist extraction -- the mode this
    client always uses) reads `upload_date` from the same watch-page
    metadata blob as `title`/`channel`/`duration`, so a genuinely
    accessible video that yields those three also yields a parseable
    `upload_date` in practice; the two documented cases where yt-dlp
    omits it (flat playlist extraction; certain extractor bugs) don't
    apply to this client's usage. A missing or unparseable date is
    therefore now treated the same way as a missing title/channel/
    duration: the metadata fetch did not produce a complete, usable
    record, so the video is classified inaccessible -- NOT silently
    downgraded to `publication_date=None`. This still never fabricates a
    date: if a real one can't be obtained, the whole record is rejected
    rather than one field being invented.
    """

    title = raw.get("title")
    channel = raw.get("channel") or raw.get("uploader")
    duration = raw.get("duration")
    upload_date_str = raw.get("upload_date")

    if not title or not channel or duration is None or not upload_date_str:
        raise VideoInaccessibleError("YouTube video metadata is incomplete or unavailable")

    try:
        publication_date = datetime.strptime(upload_date_str, "%Y%m%d").date()
    except ValueError as exc:
        raise VideoInaccessibleError("YouTube video metadata is incomplete or unavailable") from exc

    return YouTubeMetadata(
        title=title,
        channel=channel,
        duration_seconds=float(duration),
        publication_date=publication_date,
    )


class YouTubeProcessor:
    """Fetches a transcript and video-level metadata for one YouTube URL.

    Responsibilities are kept separate: URL/video-ID parsing, transcript
    retrieval (via `TranscriptClient`), metadata retrieval (via
    `MetadataClient`), and result assembly. No chunking, embedding, or
    Qdrant logic lives here.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        transcript_client: TranscriptClient | None = None,
        metadata_client: MetadataClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._transcript_client = transcript_client or YouTubeTranscriptApiClient()
        self._metadata_client = metadata_client or YtDlpMetadataClient()

    def process(self, url: str, language: str | None = None) -> YouTubeProcessingResult:
        """Process one YouTube URL.

        Args:
            url: A YouTube watch URL (youtube.com/watch?v=... or
                youtu.be/...).
            language: Transcript language to request. Defaults to
                `settings.youtube_default_language` (English by default,
                Requirement 3.6) -- never hardcoded here.

        Raises:
            VideoInaccessibleError: if the URL is malformed/not a
                recognized YouTube URL, or the video is invalid, private,
                removed, or otherwise unreachable.
            TranscriptUnavailableError: if the video is accessible but no
                transcript exists in the requested language.
        """

        video_id = _extract_video_id(url)
        effective_language = language or self._settings.youtube_default_language

        raw_metadata = self._metadata_client.fetch(url)
        metadata = _parse_metadata(raw_metadata)

        raw_entries = self._transcript_client.fetch(video_id, effective_language)
        segments = [
            YouTubeSegment(text=entry["text"], start_time=entry["start"], duration=entry["duration"])
            for entry in raw_entries
        ]

        return YouTubeProcessingResult(segments=segments, metadata=metadata)
