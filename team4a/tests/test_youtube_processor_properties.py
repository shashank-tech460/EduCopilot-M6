"""Task 4.2: Optional property-based tests for the YouTube_Processor.

Covers exactly the four official properties assigned to Task 4.2:

    Property 8: YouTube transcript timestamp preservation
        "For any YouTube transcript response containing N segments with
         start times and durations, the YouTube_Processor SHALL produce
         exactly N segments where each segment's start_time and duration
         match the source values."
        Validates: Requirement 3.2

    Property 9: YouTube metadata extraction completeness
        "For any accessible YouTube video, the YouTube_Processor SHALL
         return a metadata dict containing all of: title (non-empty
         string), channel (non-empty string), duration (positive number),
         and publication date (valid date string)."
        Validates: Requirement 3.3

    Property 10: YouTube error classification
        "For any YouTube URL that is invalid, private, or removed, the
         YouTube_Processor SHALL raise VideoInaccessible; and for any
         valid URL where no transcript is available, it SHALL raise
         TranscriptUnavailable. These error types SHALL be mutually
         exclusive."
        Validates: Requirements 3.4, 3.5

    Property 11: YouTube language selection
        "For any set of available transcript languages that includes the
         configured preference language, the YouTube_Processor SHALL
         select that language's transcript. When no preference is
         specified, it SHALL default to English."
        Validates: Requirement 3.6

No network access is used anywhere in this file; all provider interaction
goes through fakes/test doubles, exercising the real YouTubeProcessor (and,
for Property 10, the real client classes with only the underlying provider
library's exceptions/objects faked) rather than testing the fakes
themselves.

UPDATE (Task 8.3 remediation): the Task 4.2 report identified a literal
gap between Property 9 (requires a valid publication date for *any*
accessible video) and the original implementation (allowed
`publication_date=None`). That gap is now resolved: `_parse_metadata`
treats a missing/unparseable upload_date the same as a missing
title/channel/duration -- raising `VideoInaccessibleError` rather than
producing an incomplete "accessible" record -- based on yt-dlp's real
full-extraction behavior (upload_date comes from the same metadata blob
as the other three fields). See `test_property_9_missing_publication_date_now_classified_inaccessible`
below and the Task 8.3 report for the full analysis. No date is ever
fabricated.

No production code was changed as a result of the original Task 4.2 task.
"""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import HealthCheck, example, given, settings as hyp_settings
from hypothesis import strategies as st

from app.config.settings import Settings
from app.models.exceptions import TranscriptUnavailableError, VideoInaccessibleError
from app.processors.youtube_processor import (
    YouTubeProcessor,
    YouTubeTranscriptApiClient,
    YtDlpMetadataClient,
    _extract_video_id,
)
from tests.test_youtube_processor import FakeMetadataClient, FakeTranscriptClient

VALID_METADATA = {
    "title": "A Complete Video",
    "channel": "A Real Channel",
    "duration": 300.0,
    "upload_date": "20230601",
}


# ---------------------------------------------------------------------------
# Property 8: YouTube transcript timestamp preservation
# ---------------------------------------------------------------------------


@given(
    entries=st.lists(
        st.tuples(
            st.floats(min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False),
            st.floats(min_value=0, max_value=3600, allow_nan=False, allow_infinity=False),
        ),
        min_size=1,
        max_size=25,
    )
)
@example(entries=[(5.0, 2.0)])  # integer-valued timestamps
@example(entries=[(1.5, 0.75)])  # fractional timestamps
@example(entries=[(1.234567891, 0.987654321)])  # high-precision timestamps
@example(entries=[(0.0, 1.0)])  # single-segment response
@example(entries=[(0.0, 1.0), (1.0, 1.5), (2.5, 2.0), (4.5, 0.3)])  # multiple segments
@hyp_settings(max_examples=75, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_8_transcript_timestamp_preservation(entries):
    raw_entries = [
        {"text": f"segment-{i}", "start": start, "duration": duration}
        for i, (start, duration) in enumerate(entries)
    ]
    transcript_client = FakeTranscriptClient(entries=raw_entries)
    metadata_client = FakeMetadataClient(VALID_METADATA)
    processor = YouTubeProcessor(transcript_client=transcript_client, metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")

    assert len(result.segments) == len(entries)
    for i, ((expected_start, expected_duration), segment) in enumerate(zip(entries, result.segments)):
        assert segment.text == f"segment-{i}"
        assert segment.start_time == expected_start
        assert segment.duration == expected_duration


# ---------------------------------------------------------------------------
# Property 9: YouTube metadata extraction completeness
# ---------------------------------------------------------------------------


@given(
    title=st.text(min_size=1, max_size=100).filter(lambda s: s.strip() != ""),
    channel=st.text(min_size=1, max_size=100).filter(lambda s: s.strip() != ""),
    duration=st.floats(min_value=0.001, max_value=36_000, allow_nan=False, allow_infinity=False),
    year=st.integers(min_value=2005, max_value=2026),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
)
@hyp_settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_9_metadata_complete_when_provider_supplies_all_fields(
    title, channel, duration, year, month, day
):
    """For generated (title, channel, duration, publication date) combinations
    that a provider *does* supply in full, Property 9 holds exactly as worded.
    """

    upload_date_str = f"{year:04d}{month:02d}{day:02d}"
    metadata_client = FakeMetadataClient(
        {"title": title, "channel": channel, "duration": duration, "upload_date": upload_date_str}
    )
    processor = YouTubeProcessor(transcript_client=FakeTranscriptClient(), metadata_client=metadata_client)

    result = processor.process("https://www.youtube.com/watch?v=abc123")
    metadata = result.metadata

    assert isinstance(metadata.title, str) and metadata.title != ""
    assert isinstance(metadata.channel, str) and metadata.channel != ""
    assert isinstance(metadata.duration_seconds, (int, float)) and metadata.duration_seconds > 0
    assert isinstance(metadata.publication_date, date)
    assert metadata.publication_date == date(year, month, day)


def test_property_9_missing_publication_date_now_classified_inaccessible():
    """RESOLUTION of the former Property-9 boundary gap (Task 8.3 remediation).

    The Task 4.2 report identified a literal contradiction: Property 9
    requires a valid publication date for *any accessible video*, but the
    implementation allowed `publication_date=None`. Task 8.3 remediation
    resolved this using the real provider contract: yt-dlp's
    full-extraction mode (used throughout this client) reads
    `upload_date` from the same metadata blob as title/channel/duration,
    so a genuinely accessible video always yields all four together. A
    missing date is therefore evidence the fetch did not produce a
    complete record -- exactly like a missing title/channel/duration --
    so the video is now classified `VideoInaccessibleError` rather than
    silently satisfying Property 9 with a null date. No date is ever
    fabricated; the record is rejected instead.
    """

    metadata_client = FakeMetadataClient(
        {"title": "Accessible Video", "channel": "A Channel", "duration": 100.0, "upload_date": None}
    )
    processor = YouTubeProcessor(transcript_client=FakeTranscriptClient(), metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError):
        processor.process("https://www.youtube.com/watch?v=abc123")


@given(
    title=st.text(min_size=1, max_size=50).filter(lambda s: s.strip() != ""),
    channel=st.text(min_size=1, max_size=50).filter(lambda s: s.strip() != ""),
    duration=st.floats(min_value=0.001, max_value=36_000, allow_nan=False, allow_infinity=False),
)
@hyp_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_9_missing_date_raises_inaccessible_across_generated_titles_channels_durations(
    title, channel, duration
):
    """Generalizes the resolution: no matter what else is valid, a missing
    upload_date always raises VideoInaccessibleError -- now treated
    identically to a missing title/channel/duration (Property 9's
    publication-date requirement is honored, never silently downgraded,
    and never fabricated).
    """

    metadata_client = FakeMetadataClient(
        {"title": title, "channel": channel, "duration": duration, "upload_date": None}
    )
    processor = YouTubeProcessor(transcript_client=FakeTranscriptClient(), metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError):
        processor.process("https://www.youtube.com/watch?v=abc123")


@given(
    malformed_date=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=20).filter(
        lambda s: s.strip() != "" and not (len(s) == 8 and s.isdigit())
    ),
    title=st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
    channel=st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
)
@example(malformed_date="not-a-date", title="T", channel="C")
@example(malformed_date="2023-13-45", title="T", channel="C")  # looks date-like but invalid month/day
@example(malformed_date="20231301", title="T", channel="C")  # 8 digits but invalid month (13)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_9_malformed_publication_date_raises_inaccessible_never_fabricated(malformed_date, title, channel):
    """Generalizes the malformed-date case (previously only a single fixed
    example in tests/test_youtube_processor.py) into a genuine property:
    for any generated string that is not a valid YYYYMMDD date, the
    processor must raise VideoInaccessibleError rather than silently
    falling back to `publication_date=None` (which Task 8.3 already
    established is itself unacceptable) or, worse, fabricating a
    plausible-looking date.
    """

    metadata_client = FakeMetadataClient(
        {"title": title, "channel": channel, "duration": 100.0, "upload_date": malformed_date}
    )
    processor = YouTubeProcessor(transcript_client=FakeTranscriptClient(), metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError) as exc_info:
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.message.strip() != ""


@given(
    missing_field=st.sampled_from(["title", "channel", "duration"]),
    title=st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
    channel=st.text(min_size=1, max_size=30).filter(lambda s: s.strip() != ""),
    duration=st.floats(min_value=0.001, max_value=36_000, allow_nan=False, allow_infinity=False),
)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_9_any_single_missing_required_field_raises_inaccessible(
    missing_field, title, channel, duration
):
    """Generalizes missing-title/missing-channel/missing-duration (each
    previously only a single fixed example in
    tests/test_youtube_processor.py) into one genuine property: for any
    generated combination of otherwise-valid metadata, omitting exactly
    one required field (title, channel, or duration) always raises
    VideoInaccessibleError rather than silently returning incomplete
    metadata -- the field to omit and the values of the others are both
    varied per example.
    """

    raw_metadata = {"title": title, "channel": channel, "duration": duration, "upload_date": "20230601"}
    raw_metadata[missing_field] = None

    metadata_client = FakeMetadataClient(raw_metadata)
    processor = YouTubeProcessor(transcript_client=FakeTranscriptClient(), metadata_client=metadata_client)

    with pytest.raises(VideoInaccessibleError) as exc_info:
        processor.process("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.message.strip() != ""


# ---------------------------------------------------------------------------
# Property 10: YouTube error classification
# ---------------------------------------------------------------------------


def _video_inaccessible_provider_exceptions() -> list[Exception]:
    from youtube_transcript_api import (
        AgeRestricted,
        InvalidVideoId,
        IpBlocked,
        RequestBlocked,
        VideoUnavailable,
        VideoUnplayable,
        YouTubeRequestFailed,
    )

    return [
        VideoUnavailable("vid"),
        VideoUnplayable("vid", reason="blocked", sub_reasons=[]),
        AgeRestricted("vid"),
        InvalidVideoId("vid"),
        IpBlocked("vid"),
        RequestBlocked("vid"),
        YouTubeRequestFailed("vid", http_error=None),
    ]


def _transcript_unavailable_provider_exceptions() -> list[Exception]:
    from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled

    return [
        TranscriptsDisabled("vid"),
        NoTranscriptFound("vid", requested_language_codes=["en"], transcript_data=None),
    ]


@given(url=st.sampled_from(["", "not a url", "https://example.com/watch?v=abc", "ftp://youtube.com/watch?v=abc"]))
@hyp_settings(max_examples=10, deadline=None)
def test_property_10_invalid_urls_are_video_inaccessible(url):
    with pytest.raises(VideoInaccessibleError):
        _extract_video_id(url)


@given(index=st.integers(min_value=0, max_value=6))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_10_provider_access_failures_map_to_video_inaccessible(index, monkeypatch):
    """Real YouTubeTranscriptApiClient, real provider exception classes,
    fake provider object -- exercises the actual mapping code path.
    """

    provider_exceptions = _video_inaccessible_provider_exceptions()
    exc = provider_exceptions[index]

    class FakeApi:
        def list(self, video_id):
            raise exc

    import youtube_transcript_api

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)

    client = YouTubeTranscriptApiClient()
    with pytest.raises(VideoInaccessibleError) as exc_info:
        client.fetch("abc123", "en")
    assert exc_info.value.message.strip() != ""


@given(index=st.integers(min_value=0, max_value=1))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_10_transcript_absence_maps_to_transcript_unavailable(index, monkeypatch):
    provider_exceptions = _transcript_unavailable_provider_exceptions()
    exc = provider_exceptions[index]

    class FakeTranscriptList:
        def find_transcript(self, languages):
            raise exc

    class FakeApi:
        def list(self, video_id):
            return FakeTranscriptList()

    import youtube_transcript_api

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)

    client = YouTubeTranscriptApiClient()
    with pytest.raises(TranscriptUnavailableError) as exc_info:
        client.fetch("abc123", "en")
    assert exc_info.value.message.strip() != ""


@given(
    video_inaccessible_index=st.integers(min_value=0, max_value=6),
    transcript_unavailable_index=st.integers(min_value=0, max_value=1),
)
@hyp_settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_10_categories_are_mutually_exclusive(
    video_inaccessible_index, transcript_unavailable_index, monkeypatch
):
    """No generated case from the VideoInaccessible provider-exception set
    ever raises TranscriptUnavailableError, and vice versa.
    """

    video_inaccessible_exc = _video_inaccessible_provider_exceptions()[video_inaccessible_index]
    transcript_unavailable_exc = _transcript_unavailable_provider_exceptions()[transcript_unavailable_index]

    import youtube_transcript_api

    class FakeApiA:
        def list(self, video_id):
            raise video_inaccessible_exc

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApiA)
    client = YouTubeTranscriptApiClient()
    try:
        client.fetch("abc123", "en")
        pytest.fail("expected an exception to be raised")
    except VideoInaccessibleError:
        pass
    except TranscriptUnavailableError:
        pytest.fail(f"{type(video_inaccessible_exc).__name__} was incorrectly classified as TranscriptUnavailable")

    class FakeTranscriptListB:
        def find_transcript(self, languages):
            raise transcript_unavailable_exc

    class FakeApiB:
        def list(self, video_id):
            return FakeTranscriptListB()

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApiB)
    client_b = YouTubeTranscriptApiClient()
    try:
        client_b.fetch("abc123", "en")
        pytest.fail("expected an exception to be raised")
    except TranscriptUnavailableError:
        pass
    except VideoInaccessibleError:
        pytest.fail(
            f"{type(transcript_unavailable_exc).__name__} was incorrectly classified as VideoInaccessible"
        )


def test_property_10_metadata_download_error_maps_to_video_inaccessible(monkeypatch):
    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError("provider failure detail")

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    client = YtDlpMetadataClient()
    with pytest.raises(VideoInaccessibleError):
        client.fetch("https://www.youtube.com/watch?v=abc123")


@given(
    raw_provider_message=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)), min_size=20, max_size=200
    ).filter(lambda s: s.strip() != "")
)
@example(raw_provider_message="internal stack trace: connection reset by peer at socket.py:142")
@hyp_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_10_raw_provider_message_never_leaks_into_public_error(raw_provider_message, monkeypatch):
    """Generalizes the single fixed-string leak check already in
    tests/test_youtube_processor.py
    (`test_real_metadata_client_maps_download_error_to_video_inaccessible`)
    into a genuine property: for any generated raw provider error text
    (arbitrary content, length, punctuation), the resulting public
    VideoInaccessibleError's message must be non-empty and must never
    contain that raw provider text verbatim.

    `min_size=20` keeps the generated raw text long/distinctive enough
    that it cannot coincidentally already be a substring of the fixed,
    generic public message (e.g. a 1-character generated message like
    "Y" is trivially "contained in" "YouTube video is..." and would be a
    false-positive failure of this property, not a real leak -- an
    earlier version of this test used `min_size=1` and hit exactly that
    false positive, see the Task 4.2 report).
    """

    import yt_dlp

    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            raise yt_dlp.utils.DownloadError(raw_provider_message)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)

    client = YtDlpMetadataClient()
    with pytest.raises(VideoInaccessibleError) as exc_info:
        client.fetch("https://www.youtube.com/watch?v=abc123")

    assert exc_info.value.message.strip() != ""
    assert raw_provider_message not in exc_info.value.message


# ---------------------------------------------------------------------------
# Property 11: YouTube language selection
# ---------------------------------------------------------------------------


@given(language=st.sampled_from(["en", "es", "fr", "de", "hi", "ja", "pt"]))
@hyp_settings(max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_11_configured_language_is_forwarded_to_transcript_client(language):
    settings = Settings(youtube_default_language=language, _env_file=None)
    transcript_client = FakeTranscriptClient()
    processor = YouTubeProcessor(
        settings=settings, transcript_client=transcript_client, metadata_client=FakeMetadataClient(VALID_METADATA)
    )

    processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls == [("abc123", language)]


@given(language=st.sampled_from(["es", "fr", "de", "hi", "ja"]))
@hyp_settings(max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_11_explicit_language_overrides_configured_default(language):
    settings = Settings(youtube_default_language="en", _env_file=None)
    transcript_client = FakeTranscriptClient()
    processor = YouTubeProcessor(
        settings=settings, transcript_client=transcript_client, metadata_client=FakeMetadataClient(VALID_METADATA)
    )

    processor.process("https://www.youtube.com/watch?v=abc123", language=language)

    assert transcript_client.calls == [("abc123", language)]


def test_property_11_default_is_english_when_nothing_configured_or_requested():
    default_settings = Settings(_env_file=None)
    assert default_settings.youtube_default_language == "en"

    transcript_client = FakeTranscriptClient()
    processor = YouTubeProcessor(
        settings=default_settings,
        transcript_client=transcript_client,
        metadata_client=FakeMetadataClient(VALID_METADATA),
    )

    processor.process("https://www.youtube.com/watch?v=abc123")

    assert transcript_client.calls == [("abc123", "en")]


@given(
    available_languages=st.sampled_from(
        [["en", "es"], ["en", "fr"], ["en", "de", "hi"], ["es", "fr"], ["de", "hi", "ja"]]
    ),
    preference=st.sampled_from(["en", "es", "fr", "de"]),
)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_11_real_client_requests_exactly_the_preferred_language(
    available_languages, preference, monkeypatch
):
    """Exercises the real YouTubeTranscriptApiClient: for any set of
    "available" languages (simulated by a fake TranscriptList/Transcript),
    the preferred language is exactly what gets requested via
    `find_transcript`, regardless of what else is available.
    """

    requested_language_lists: list[list[str]] = []

    class FakeTranscript:
        def fetch(self):
            class Snippet:
                def __init__(self, text, start, duration):
                    self.text, self.start, self.duration = text, start, duration

            class Fetched:
                snippets = [Snippet("hi", 0.0, 1.0)]

            return Fetched()

    class FakeTranscriptList:
        def find_transcript(self, languages):
            requested_language_lists.append(list(languages))
            if preference not in available_languages:
                from youtube_transcript_api import NoTranscriptFound

                raise NoTranscriptFound("vid", requested_language_codes=languages, transcript_data=None)
            return FakeTranscript()

    class FakeApi:
        def list(self, video_id):
            return FakeTranscriptList()

    import youtube_transcript_api

    monkeypatch.setattr(youtube_transcript_api, "YouTubeTranscriptApi", FakeApi)

    client = YouTubeTranscriptApiClient()

    if preference in available_languages:
        entries = client.fetch("abc123", preference)
        assert entries == [{"text": "hi", "start": 0.0, "duration": 1.0}]
    else:
        with pytest.raises(TranscriptUnavailableError):
            client.fetch("abc123", preference)

    assert requested_language_lists == [[preference]]
