"""Unit tests for Task 4.1: YouTubeProcessor.

No network access, no real YouTube calls: TranscriptClient and
MetadataClient are always fakes/test doubles implementing the same
Protocol as the real `YouTubeTranscriptApiClient`/`YtDlpMetadataClient`,
per Task 4.1's explicit "unit tests MUST NOT depend on YouTube being
reachable" instruction.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from app.models.exceptions import TranscriptUnavailableError, VideoInaccessibleError
from app.models.schemas import YouTubeProcessingResult, YouTubeSegment
from app.processors.youtube_processor import (
    YouTubeProcessor,
    YouTubeTranscriptApiClient,
    YtDlpMetadataClient,
    _extract_video_id,
    _parse_metadata,
)


class FakeTranscriptClient:
    """Records the (video_id, language) it was called with."""

    def __init__(self, entries=None, error: Exception | None = None) -> None:
        self._entries = entries if entries is not None else [{"text": "hello world", "start": 0.5, "duration": 2.3}]
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def fetch(self, video_id: str, language: str) -> list[dict[str, Any]]:
        self.calls.append((video_id, language))
        if self._error is not None:
            raise self._error
        return self._entries


class FakeMetadataClient:
    def __init__(self, metadata: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._metadata = metadata if metadata is not None else {
            "title": "Test Video",
            "channel": "Test Channel",
            "duration": 125.0,
            "upload_date": "20230115",
        }
        self._error = error
        self.calls: list[str] = []

    def fetch(self, url: str) -> dict[str, Any]:
        self.calls.append(url)
        if self._error is not None:
            raise self._error
        return self._metadata


def make_processor(transcript_client=None, metadata_client=None, settings=None) -> YouTubeProcessor:
    return YouTubeProcessor(
        settings=settings,
        transcript_client=transcript_client or FakeTranscriptClient(),
        metadata_client=metadata_client or FakeMetadataClient(),
    )


# ---------------------------------------------------------------------------
# 1-4. URL validation / accepted forms
# ---------------------------------------------------------------------------


def test_valid_watch_url_is_accepted():
    assert _extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"


def test_invalid_url_is_rejected():
    with pytest.raises(VideoInaccessibleError) as exc_info:
        _extract_video_id("https://example.com/not-youtube")
    assert exc_info.value.status_code == "VideoInaccessible"


def test_malformed_url_is_rejected():
    with pytest.raises(VideoInaccessibleError):
        _extract_video_id("this is not a url")


def test_standard_watch_url_with_extra_query_params_works():
    assert _extract_video_id("https://www.youtube.com/watch?v=abc123&t=5s&list=PL123") == "abc123"


def test_watch_url_without_www_works():
    assert _extract_video_id("https://youtube.com/watch?v=abc123") == "abc123"


def test_youtu_be_short_url_works():
    assert _extract_video_id("https://youtu.be/xyz789") == "xyz789"


def test_youtu_be_short_url_with_query_param_works():
    assert _extract_video_id("https://youtu.be/xyz789?t=10") == "xyz789"


def test_watch_url_missing_video_id_is_rejected():
    with pytest.raises(VideoInaccessibleError):
        _extract_video_id("https://www.youtube.com/watch?list=PL123")


def test_arbitrary_url_containing_youtube_substring_is_not_accepted():
    with pytest.raises(VideoInaccessibleError):
        _extract_video_id("https://not-youtube.com/youtube/watch?v=abc123")


def test_non_http_scheme_url_is_rejected():
    # Task 4.2 (Property 10) discovered this via property-based testing:
    # YouTube is only ever served over http/https, so a URL with a
    # matching host/path/query but a non-http(s) scheme cannot be a real,
    # accessible YouTube URL and must not be treated as one.
    with pytest.raises(VideoInaccessibleError):
        _extract_video_id("ftp://youtube.com/watch?v=abc123")


# ---------------------------------------------------------------------------
# 5-8. Transcript segments / timestamps / duration
# ---------------------------------------------------------------------------


def test_transcript_segments_are_returned():
    processor = make_processor()
    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert isinstance(result, YouTubeProcessingResult)
    assert len(result.segments) == 1
    assert isinstance(result.segments[0], YouTubeSegment)
    assert result.segments[0].text == "hello world"


def test_transcript_start_timestamp_preserved():
    transcript_client = FakeTranscriptClient(entries=[{"text": "x", "start": 12.75, "duration": 1.0}])
    processor = make_processor(transcript_client=transcript_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.segments[0].start_time == 12.75


def test_transcript_duration_preserved():
    transcript_client = FakeTranscriptClient(entries=[{"text": "x", "start": 0.0, "duration": 3.456}])
    processor = make_processor(transcript_client=transcript_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.segments[0].duration == 3.456


def test_multiple_transcript_segments_all_preserved_in_order():
    entries = [
        {"text": "first", "start": 0.0, "duration": 1.0},
        {"text": "second", "start": 1.0, "duration": 1.5},
        {"text": "third", "start": 2.5, "duration": 2.0},
    ]
    transcript_client = FakeTranscriptClient(entries=entries)
    processor = make_processor(transcript_client=transcript_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert [s.text for s in result.segments] == ["first", "second", "third"]
    assert [s.start_time for s in result.segments] == [0.0, 1.0, 2.5]
    assert [s.duration for s in result.segments] == [1.0, 1.5, 2.0]


def test_timestamps_are_not_unnecessarily_rounded():
    transcript_client = FakeTranscriptClient(entries=[{"text": "x", "start": 1.23456789, "duration": 0.987654321}])
    processor = make_processor(transcript_client=transcript_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.segments[0].start_time == 1.23456789
    assert result.segments[0].duration == 0.987654321


# ---------------------------------------------------------------------------
# 9-10. Language default/configuration
# ---------------------------------------------------------------------------


def test_default_language_is_english():
    from app.config.settings import get_settings

    settings = get_settings()
    assert settings.youtube_default_language == "en"

    transcript_client = FakeTranscriptClient()
    processor = make_processor(transcript_client=transcript_client)
    processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls == [("abc123", "en")]


def test_configured_alternative_language_is_respected():
    from app.config.settings import Settings

    settings = Settings(youtube_default_language="es", _env_file=None)
    transcript_client = FakeTranscriptClient()
    processor = make_processor(transcript_client=transcript_client, settings=settings)

    processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls == [("abc123", "es")]


def test_per_call_language_overrides_configured_default():
    transcript_client = FakeTranscriptClient()
    processor = make_processor(transcript_client=transcript_client)

    processor.process("https://www.youtube.com/watch?v=abc123", language="fr")

    assert transcript_client.calls == [("abc123", "fr")]


def test_language_is_not_hardcoded_in_processor():
    from app.config.settings import Settings

    settings = Settings(youtube_default_language="de", _env_file=None)
    transcript_client = FakeTranscriptClient()
    processor = make_processor(transcript_client=transcript_client, settings=settings)

    processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls[0][1] == "de"


# ---------------------------------------------------------------------------
# 11-14. Metadata: title / channel / duration / publication date
# ---------------------------------------------------------------------------


def test_title_preserved():
    metadata_client = FakeMetadataClient(
        {"title": "My Great Video", "channel": "C", "duration": 10.0, "upload_date": "20200101"}
    )
    processor = make_processor(metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.metadata.title == "My Great Video"


def test_channel_preserved():
    metadata_client = FakeMetadataClient(
        {"title": "T", "channel": "Awesome Channel", "duration": 10.0, "upload_date": "20200101"}
    )
    processor = make_processor(metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.metadata.channel == "Awesome Channel"


def test_video_duration_preserved_and_distinct_from_segment_duration():
    metadata_client = FakeMetadataClient({"title": "T", "channel": "C", "duration": 600.0, "upload_date": "20200101"})
    transcript_client = FakeTranscriptClient(entries=[{"text": "x", "start": 0.0, "duration": 2.5}])
    processor = make_processor(transcript_client=transcript_client, metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.metadata.duration_seconds == 600.0
    assert result.segments[0].duration == 2.5
    assert result.metadata.duration_seconds != result.segments[0].duration


def test_publication_date_preserved():
    metadata_client = FakeMetadataClient({"title": "T", "channel": "C", "duration": 10.0, "upload_date": "20230115"})
    processor = make_processor(metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.metadata.publication_date == date(2023, 1, 15)


def test_publication_date_required_for_accessible_video_missing_raises_video_inaccessible():
    """Task 8.3 remediation: yt-dlp's full-extraction mode returns
    `upload_date` from the same metadata blob as title/channel/duration,
    so a genuinely accessible video always yields all four together. A
    missing date is therefore no longer downgraded to
    `publication_date=None` -- it is treated the same as a missing
    title/channel/duration: the fetch did not produce a complete record,
    so the video is classified inaccessible. This still never fabricates
    a date; it rejects the whole record instead of inventing one field.
    """

    metadata_client = FakeMetadataClient({"title": "T", "channel": "C", "duration": 10.0, "upload_date": None})
    processor = make_processor(metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError) as exc_info:
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.status_code == "VideoInaccessible"


def test_metadata_client_falls_back_to_uploader_field_for_channel():
    metadata_client = FakeMetadataClient(
        {"title": "T", "channel": None, "uploader": "Fallback Uploader", "duration": 10.0, "upload_date": "20230101"}
    )
    processor = make_processor(metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert result.metadata.channel == "Fallback Uploader"


def test_incomplete_metadata_raises_video_inaccessible():
    metadata_client = FakeMetadataClient({"title": "", "channel": "C", "duration": 10.0})
    processor = make_processor(metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError):
        processor.process("https://www.youtube.com/watch?v=abc123")


# ---------------------------------------------------------------------------
# 15-17. TranscriptUnavailable vs VideoInaccessible distinction
# ---------------------------------------------------------------------------


def test_transcript_unavailable_error_raised_for_unavailable_transcript():
    transcript_client = FakeTranscriptClient(error=TranscriptUnavailableError("no transcript"))
    processor = make_processor(transcript_client=transcript_client)

    with pytest.raises(TranscriptUnavailableError) as exc_info:
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.status_code == "TranscriptUnavailable"


def test_video_inaccessible_error_raised_for_inaccessible_video():
    metadata_client = FakeMetadataClient(error=VideoInaccessibleError("video is private"))
    processor = make_processor(metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError) as exc_info:
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.status_code == "VideoInaccessible"


def test_transcript_unavailable_is_not_conflated_with_video_inaccessible():
    transcript_client = FakeTranscriptClient(error=TranscriptUnavailableError("disabled"))
    processor = make_processor(transcript_client=transcript_client)

    with pytest.raises(TranscriptUnavailableError):
        processor.process("https://www.youtube.com/watch?v=abc123")


def test_video_inaccessible_is_not_conflated_with_transcript_unavailable():
    metadata_client = FakeMetadataClient(error=VideoInaccessibleError("removed"))
    transcript_client = FakeTranscriptClient()
    processor = make_processor(transcript_client=transcript_client, metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError):
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls == []


# ---------------------------------------------------------------------------
# 18. Provider exceptions mapped cleanly (real client, mocked provider library)
# ---------------------------------------------------------------------------


def test_real_transcript_client_maps_transcripts_disabled_to_transcript_unavailable(monkeypatch):
    from youtube_transcript_api import TranscriptsDisabled

    class FakeTranscriptList:
        def find_transcript(self, languages):
            raise TranscriptsDisabled("abc123")

    class FakeApi:
        def list(self, video_id):
            return FakeTranscriptList()

    import youtube_transcript_api

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)

    client = YouTubeTranscriptApiClient()
    with pytest.raises(TranscriptUnavailableError):
        client.fetch("abc123", "en")


def test_real_transcript_client_maps_video_unavailable_to_video_inaccessible(monkeypatch):
    from youtube_transcript_api import VideoUnavailable

    class FakeApi:
        def list(self, video_id):
            raise VideoUnavailable(video_id)

    import youtube_transcript_api

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)

    client = YouTubeTranscriptApiClient()
    with pytest.raises(VideoInaccessibleError):
        client.fetch("abc123", "en")


def test_real_metadata_client_maps_download_error_to_video_inaccessible(monkeypatch):
    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError("some provider-internal detail")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    client = YtDlpMetadataClient()
    with pytest.raises(VideoInaccessibleError) as exc_info:
        client.fetch("https://www.youtube.com/watch?v=abc123")

    assert "provider-internal detail" not in exc_info.value.message


def test_real_metadata_client_none_result_raises_video_inaccessible(monkeypatch):
    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            return None

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    client = YtDlpMetadataClient()
    with pytest.raises(VideoInaccessibleError):
        client.fetch("https://www.youtube.com/watch?v=abc123")


# ---------------------------------------------------------------------------
# 19-20. Output model / no fake data
# ---------------------------------------------------------------------------


def test_output_uses_expected_models():
    processor = make_processor()
    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert isinstance(result, YouTubeProcessingResult)
    for segment in result.segments:
        assert isinstance(segment, YouTubeSegment)
        payload = segment.model_dump()
        assert set(payload.keys()) == {"text", "start_time", "duration"}


def test_processor_does_not_return_hardcoded_transcript_regardless_of_input():
    processor = YouTubeProcessor(
        transcript_client=FakeTranscriptClient(entries=[{"text": "AAA", "start": 0.0, "duration": 1.0}]),
        metadata_client=FakeMetadataClient(),
    )
    result_a = processor.process("https://www.youtube.com/watch?v=abc123")

    processor._transcript_client = FakeTranscriptClient(entries=[{"text": "BBB", "start": 5.0, "duration": 1.0}])
    result_b = processor.process("https://www.youtube.com/watch?v=xyz789")

    assert result_a.segments[0].text == "AAA"
    assert result_b.segments[0].text == "BBB"
    assert result_a.segments[0].text != result_b.segments[0].text


# ---------------------------------------------------------------------------
# 21-22. Dependency injection / configuration usage
# ---------------------------------------------------------------------------


def test_external_dependencies_can_be_replaced_by_test_doubles():
    transcript_client = FakeTranscriptClient()
    metadata_client = FakeMetadataClient()
    processor = YouTubeProcessor(transcript_client=transcript_client, metadata_client=metadata_client)

    processor.process("https://www.youtube.com/watch?v=abc123")

    assert len(transcript_client.calls) == 1
    assert len(metadata_client.calls) == 1


def test_default_processor_uses_real_client_types_when_not_injected():
    processor = YouTubeProcessor()
    assert isinstance(processor._transcript_client, YouTubeTranscriptApiClient)
    assert isinstance(processor._metadata_client, YtDlpMetadataClient)


def test_settings_used_instead_of_hardcoded_defaults():
    from app.config.settings import get_settings

    settings = get_settings()
    processor = make_processor()
    assert processor._settings.youtube_default_language == settings.youtube_default_language


# ---------------------------------------------------------------------------
# _parse_metadata unit tests
# ---------------------------------------------------------------------------


def test_parse_metadata_handles_valid_date_string():
    result = _parse_metadata({"title": "T", "channel": "C", "duration": 5.0, "upload_date": "20240229"})
    assert result.publication_date == date(2024, 2, 29)


def test_parse_metadata_handles_malformed_date_string_by_treating_as_inaccessible():
    """Task 8.3 remediation: an unparseable upload_date can't produce a
    real, non-fabricated date, so the whole record is rejected (like a
    missing title/channel/duration) rather than silently downgrading to
    `publication_date=None`.
    """

    with pytest.raises(VideoInaccessibleError):
        _parse_metadata({"title": "T", "channel": "C", "duration": 5.0, "upload_date": "not-a-date"})


def test_parse_metadata_raises_when_upload_date_missing_entirely():
    with pytest.raises(VideoInaccessibleError):
        _parse_metadata({"title": "T", "channel": "C", "duration": 5.0})
