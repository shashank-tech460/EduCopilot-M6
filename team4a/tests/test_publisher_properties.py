"""Task 8.3: Optional property-based tests for the Publisher.

Covers the official Team 4A correctness properties applicable to the
Publisher, exactly as numbered/worded in the source specification
(re-verified directly against the uploaded requirements document before
writing this file, not assumed from memory):

    Property 20: Source-specific metadata completeness
        "For any chunk from a PDF source, metadata SHALL contain
         page_number, headings, filename, and chunk_position. For any
         chunk from an MP4 source, metadata SHALL contain
         start_timestamp, end_timestamp, filename, and frame_reference.
         For any chunk from a YouTube source, metadata SHALL contain
         start_timestamp, duration, video_title, channel_name,
         source_url, and publication_date."
        Validates: Requirements 6.1, 6.2, 6.3
        (Established at the MetadataEnricher level in Task 8.1; tested
        here at the *published payload* level -- the Publisher's own
        responsibility is to not lose or mangle this metadata when
        building a Qdrant record.)

    Property 21: Common metadata invariant
        "For any chunk regardless of source type, metadata SHALL contain
         a unique chunk_id (UUID), source_type in {pdf, mp4, youtube},
         job_id (non-empty), ingestion_timestamp (valid ISO-8601),
         embedding_model (non-empty), and embedding_model_version
         (non-empty)."
        Validates: Requirements 6.4, 6.5
        (Tested here at the published payload level, same rationale as
        Property 20.)

        TASK 8.3 REMEDIATION: this property previously only tested
        `embedding_model`, not `embedding_model_version` -- which did not
        exist as a field at all. `embedding_model_version` is now
        populated from `Settings.embedding_model_revision` (a pinned
        Hugging Face Hub commit SHA for the configured embedding model,
        passed to sentence-transformers' `revision=` so the value
        reflects what is actually loaded, not just a label). Remediation
        also found that `chunk_id` itself was a raw SHA-256 hex digest,
        not a UUID as this property literally requires; `chunk_id` is now
        a deterministic, name-based UUID (`uuid.uuid5`, RFC 4122) instead
        -- see the Task 8.3 remediation report for both fixes.

    Property 22: Publication record completeness
        "For any record published to the Vector Database, it SHALL
         contain exactly three components: a vector embedding (384-dim
         float array), raw text content (non-empty string), and the full
         metadata object."
        Validates: Requirement 7.2
        (This property test exposed a genuine gap in the original Task
        8.2 implementation -- see the Task 8.3 report for the fix.)

    Property 23: Publication batch size constraint
        "For any publication operation with N total chunks, all write
         batches SHALL contain at most 100 records, and the sum of all
         batch sizes SHALL equal N."
        Validates: Requirement 7.6

    Property 24: Retry with exponential backoff
        "For any Vector DB write failure, the Publisher SHALL retry up to
         3 times with delays of 2s, 4s, and 8s (exponential backoff with
         base 2s). If all retries fail, the job status SHALL be set to
         publish_failed and an alert event SHALL be emitted."
        Validates: Requirements 7.4, 7.5

Properties 25-29 (job completion status, job ID uniqueness, job progress
mapping, API validation, pagination) belong to Task 10.x (orchestration/
API), not the Publisher, and are out of scope here.

Uses the same `FakeQdrantClient`/fixture helpers already established in
tests/test_publisher.py (imported, not duplicated). No network, no live
Qdrant, no Redis, no Docker, no real model downloads.
"""

from __future__ import annotations

import string
import time
import uuid
from datetime import date, datetime, timezone

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.models.schemas import JobStatus, PDFSegment, VideoSegment, YouTubeMetadata, YouTubeSegment
from app.pipeline.chunker import Chunker
from app.pipeline.metadata import MetadataEnricher
from app.pipeline.publisher import Publisher
from tests.test_publisher import FakeQdrantClient, make_settings

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

_word_strategy = st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8)
_sentence_strategy = st.lists(_word_strategy, min_size=2, max_size=6).map(lambda words: " ".join(words) + ".")


@pytest.fixture
def chunker() -> Chunker:
    return Chunker()


@pytest.fixture
def enricher() -> MetadataEnricher:
    return MetadataEnricher()


def _make_pdf_enriched(chunker, enricher, page_numbers, job_id="job-1", filename="doc.pdf"):
    enriched = []
    for page in page_numbers:
        segment = PDFSegment(text=f"Distinct content for page {page} appears right here today.", page_number=page)
        chunks = chunker.chunk(segment.text)
        enriched.extend(enricher.enrich_pdf_chunks(job_id, filename, NOW, segment, chunks))
    return enriched


# ---------------------------------------------------------------------------
# Property 23: Publication batch size constraint
# ---------------------------------------------------------------------------


@given(
    num_records=st.integers(min_value=0, max_value=250),
    batch_size=st.integers(min_value=1, max_value=100),
)
@hyp_settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_23_batch_size_constraint(chunker, enricher, num_records, batch_size):
    """For any N total chunks, every write batch has at most `batch_size`
    records, and the sum of all batch sizes equals N -- generated over a
    bounded but broad range including 0, 1, exactly-100-like boundaries,
    and multi-hundred counts.
    """

    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=range(1, num_records + 1))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=batch_size), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    batch_sizes = [len(points) for _, points in client.calls]
    assert all(size <= batch_size for size in batch_sizes)
    assert sum(batch_sizes) == num_records
    assert result.published_count == num_records


# ---------------------------------------------------------------------------
# Property 22: Publication record completeness
# ---------------------------------------------------------------------------


@given(page_numbers=st.lists(st.integers(min_value=1, max_value=500), min_size=1, max_size=10, unique=True))
@hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_22_published_record_has_exactly_three_components(chunker, enricher, page_numbers):
    """Every published record must contain a vector, non-empty raw text,
    and the full metadata object -- exactly the three components
    Requirement 7.2 names. This is the property that caught the original
    Task 8.2 gap (missing raw text) -- see the Task 8.3 report.
    """

    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=page_numbers)
    embeddings = [[0.2] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    published_points = [p for _, batch in client.calls for p in batch]
    assert len(published_points) == len(enriched)

    for point, source_enriched in zip(published_points, enriched):
        # Component 1: vector embedding.
        assert isinstance(point.vector, list)
        assert len(point.vector) == 384

        # Component 2: raw text content, non-empty.
        assert "text" in point.payload
        assert isinstance(point.payload["text"], str)
        assert point.payload["text"] != ""
        assert point.payload["text"] == source_enriched.chunk.text

        # Component 3: the full metadata object (common fields present).
        for common_field in ("chunk_id", "source_type", "job_id", "ingestion_timestamp", "embedding_model"):
            assert common_field in point.payload


# ---------------------------------------------------------------------------
# Property 20: Source-specific metadata completeness (at the published-payload level)
# ---------------------------------------------------------------------------


@given(page=st.integers(min_value=1, max_value=1000), filename=st.text(alphabet=string.ascii_letters, min_size=1, max_size=20))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_20_pdf_metadata_survives_publication(chunker, enricher, page, filename):
    segment = PDFSegment(text="Generated PDF page content goes here for this test.", page_number=page)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_pdf_chunks("job-1", f"{filename}.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["page_number"] == page
    assert payload["filename"] == f"{filename}.pdf"
    assert "chunk_position" in payload
    assert "headings" in payload


@given(
    heading_texts=st.lists(_word_strategy, min_size=1, max_size=4, unique=True),
    page=st.integers(min_value=1, max_value=1000),
)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_20_pdf_headings_and_chunk_position_values_are_correct(chunker, enricher, heading_texts, page):
    """Strengthens the presence-only check above: generates ACTUAL heading
    values (not the default empty list) and enough content to produce
    multiple chunks, then verifies the published payload's `headings` and
    `chunk_position` VALUES -- not merely their key presence -- correctly
    match what MetadataEnricher actually produced for each chunk.
    """

    from app.models.schemas import Heading

    headings = [Heading(text=text, level=1) for text in heading_texts]
    long_text = " ".join(f"Sentence number {i} has some real content here today." for i in range(1, 60))
    segment = PDFSegment(text=long_text, page_number=page, headings=headings)
    chunks = chunker.chunk(segment.text)
    assert len(chunks) >= 1
    enriched = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    published_points = [p for _, batch in client.calls for p in batch]
    expected_headings_json = [{"text": h.text, "level": h.level} for h in headings]

    for i, point in enumerate(published_points):
        assert point.payload["chunk_position"] == i  # matches this chunk's real chunk_index
        assert point.payload["headings"] == expected_headings_json  # exact generated values, not just present


@given(start=st.floats(min_value=0, max_value=10_000, allow_nan=False), duration=st.floats(min_value=0.1, max_value=60, allow_nan=False))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_20_video_metadata_survives_publication(chunker, enricher, start, duration):
    segment = VideoSegment(text="Generated spoken segment content for this test.", start_time=start, end_time=start + duration)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_video_chunks("job-1", "video.mp4", NOW, segment, chunks, keyframes=[])
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["start_timestamp"] == start
    assert payload["end_timestamp"] == start + duration
    assert payload["filename"] == "video.mp4"
    assert "frame_reference" not in payload  # None -> correctly omitted, not fabricated


@given(start=st.floats(min_value=0, max_value=10_000, allow_nan=False), duration=st.floats(min_value=0.1, max_value=60, allow_nan=False))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_20_youtube_metadata_survives_publication_including_none_publication_date(
    chunker, enricher, start, duration
):
    segment = YouTubeSegment(text="Generated transcript segment content for this test.", start_time=start, duration=duration)
    video_metadata = YouTubeMetadata(title="A Title", channel="A Channel", duration_seconds=1000.0, publication_date=None)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_youtube_chunks("job-1", "https://youtu.be/xyz", NOW, video_metadata, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["start_timestamp"] == start
    assert payload["duration"] == duration
    assert payload["video_title"] == "A Title"
    assert payload["channel_name"] == "A Channel"
    assert payload["source_url"] == "https://youtu.be/xyz"
    assert "publication_date" not in payload  # None -> never fabricated


@given(
    start=st.floats(min_value=0, max_value=10_000, allow_nan=False),
    duration=st.floats(min_value=0.1, max_value=60, allow_nan=False),
    year=st.integers(min_value=2005, max_value=2026),
    month=st.integers(min_value=1, max_value=12),
    day=st.integers(min_value=1, max_value=28),
)
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_20_youtube_real_publication_date_value_survives_publication(
    chunker, enricher, start, duration, year, month, day
):
    """Strengthens the None-only coverage above: for a genuinely present,
    generated (year, month, day) publication date, verify the exact
    ISO-8601 date string actually appears in the published payload --
    Property 20 requires publication_date to be present and correct for
    YouTube chunks that genuinely have one, not merely to be correctly
    omitted when absent.
    """

    from datetime import date as date_cls

    real_date = date_cls(year, month, day)
    segment = YouTubeSegment(text="Generated transcript content for date test today.", start_time=start, duration=duration)
    video_metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=500.0, publication_date=real_date)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_youtube_chunks("job-1", "https://youtu.be/xyz", NOW, video_metadata, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["publication_date"] == real_date.isoformat()


def test_property_20_no_cross_source_metadata_contamination(chunker, enricher):
    """"No source's fields are accidentally substituted by another
    source's metadata": verifies at the actual published-payload level
    (not merely at MetadataEnricher's own output, which Task 8.1 already
    covers) that a PDF record never carries video/YouTube-only fields and
    a video record never carries PDF/YouTube-only fields.

    NOTE on `headings`: `ChunkMetadata.headings` defaults to an empty list
    (`Field(default_factory=list)`), not `None` like `page_number`/
    `duration` -- by design (Task 8.1), so it structurally survives
    `model_dump(exclude_none=True)` and appears as `[]` on every record
    regardless of source type. This is not a contamination bug (no real
    PDF heading content ever appears on a non-PDF record -- verified
    explicitly below) and does not violate Property 20, which specifies
    what a record SHALL contain, not an exhaustive list of what it must
    exclude. `headings` is therefore checked for emptiness rather than
    absence on non-PDF records, while the genuinely source-exclusive
    fields (`page_number`, `duration`, and all video-only fields) are
    checked for true absence.
    """

    pdf_enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    video_segment = VideoSegment(text="Some spoken content for contamination test.", start_time=0.0, end_time=5.0)
    video_chunks = chunker.chunk(video_segment.text)
    video_enriched = enricher.enrich_video_chunks("job-1", "video.mp4", NOW, video_segment, video_chunks, keyframes=[])

    embeddings = [[0.1] * 384 for _ in (pdf_enriched + video_enriched)]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(pdf_enriched + video_enriched, embeddings)

    published_points = [p for _, batch in client.calls for p in batch]
    pdf_payload = published_points[0].payload
    video_payload = published_points[len(pdf_enriched)].payload

    video_only_fields = {"start_timestamp", "end_timestamp", "frame_reference", "video_title", "channel_name", "source_url"}
    pdf_exclusive_fields = {"page_number", "duration"}  # `headings` handled separately, see docstring

    assert not (video_only_fields & pdf_payload.keys())
    assert not (pdf_exclusive_fields & video_payload.keys())
    assert video_payload["headings"] == []  # present (by design) but genuinely empty -- no PDF content leaked
    assert pdf_payload["page_number"] == 1  # the PDF record's own real field is untouched by the check above


# ---------------------------------------------------------------------------
# Property 21: Common metadata invariant (at the published-payload level)
# ---------------------------------------------------------------------------


@given(job_id=st.text(alphabet=string.ascii_letters + string.digits + "-", min_size=1, max_size=20))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_21_common_metadata_survives_publication(chunker, enricher, job_id):
    """Exhaustively tests every field Property 21 names, exactly as worded:
    chunk_id is a UUID, source_type is one of pdf/mp4/youtube, job_id is
    non-empty, ingestion_timestamp is valid ISO-8601, embedding_model is
    non-empty, and embedding_model_version is non-empty.
    """

    segment = PDFSegment(text="Some page content for the common-metadata test.", page_number=1)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_pdf_chunks(job_id, "doc.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload

    # chunk_id (UUID)
    assert payload["chunk_id"]
    uuid.UUID(payload["chunk_id"])  # must parse as a real UUID, not just any string

    # source_type in {"pdf", "mp4", "youtube"}
    assert payload["source_type"] in ("pdf", "mp4", "youtube")

    # job_id (non-empty)
    assert payload["job_id"] == job_id
    assert payload["job_id"] != ""

    # ingestion_timestamp (valid ISO-8601)
    datetime.fromisoformat(payload["ingestion_timestamp"].replace("Z", "+00:00"))

    # embedding_model (non-empty)
    assert payload["embedding_model"] != ""

    # embedding_model_version (non-empty)
    assert "embedding_model_version" in payload
    assert payload["embedding_model_version"] != ""


def test_property_21_chunk_id_is_a_deterministic_uuid_not_random(chunker, enricher):
    """chunk_id must be a UUID (Property 21's literal format requirement)
    AND deterministic (Task 8.1's "no random IDs" requirement). A
    name-based UUID (uuid5, version 5) satisfies both simultaneously --
    verified here via the UUID version bits, which independently prove
    this was not produced by `uuid.uuid4()` (random, version 4).
    """

    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]

    client_a = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client_a).publish(enriched, embeddings)
    client_b = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client_b).publish(enriched, embeddings)

    chunk_id_a = client_a.calls[0][1][0].payload["chunk_id"]
    chunk_id_b = client_b.calls[0][1][0].payload["chunk_id"]

    assert chunk_id_a == chunk_id_b  # deterministic across independent publish() calls
    assert uuid.UUID(chunk_id_a).version == 5


def test_property_21_embedding_model_version_reflects_configured_revision(chunker, enricher):
    """embedding_model_version must come from configuration (the pinned
    model revision), not be hardcoded or blank.
    """

    from app.config.settings import Settings

    settings = Settings(embedding_model_revision="0123456789abcdef0123456789abcdef01234567", _env_file=None)
    from app.pipeline.metadata import MetadataEnricher as _MetadataEnricher

    enricher_with_custom_revision = _MetadataEnricher(settings=settings)
    segment = PDFSegment(text="Some content for the version test.", page_number=1)
    chunks = chunker.chunk(segment.text)
    enriched = enricher_with_custom_revision.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["embedding_model_version"] == "0123456789abcdef0123456789abcdef01234567"


@given(page_numbers=st.lists(st.integers(min_value=1, max_value=2000), min_size=2, max_size=15, unique=True))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_21_chunk_ids_are_unique_across_published_records(chunker, enricher, page_numbers):
    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=page_numbers)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client).publish(enriched, embeddings)

    published_chunk_ids = [p.payload["chunk_id"] for _, batch in client.calls for p in batch]
    assert len(published_chunk_ids) == len(set(published_chunk_ids))


# ---------------------------------------------------------------------------
# Property 24: Retry with exponential backoff
# ---------------------------------------------------------------------------


@given(fail_count=st.integers(min_value=0, max_value=3))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_24_transient_failure_recovers_within_retry_budget(chunker, enricher, fail_count):
    """For any number of transient failures within the retry budget
    (0, 1, 2, or 3 -- i.e. up to and including the 3rd retry), the
    Publisher SHALL eventually succeed once the underlying write starts
    working again.
    """

    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_first_n_calls=fail_count)
    sleeps: list[float] = []
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3, publisher_initial_backoff_seconds=2.0),
        qdrant_client=client,
        sleep_fn=lambda s: sleeps.append(s),
    )

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.COMPLETED
    assert client._call_count == fail_count + 1
    # Delays follow the exact 2s/4s/8s exponential schedule for however
    # many retries were actually needed.
    assert sleeps == [2.0, 4.0, 8.0][:fail_count]


def test_property_24_retries_are_bounded_no_infinite_loop(chunker, enricher):
    """A permanently-failing write SHALL make exactly 1 + 3 = 4 total
    attempts, never more -- no infinite retry loop.
    """

    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3), qdrant_client=client, sleep_fn=lambda s: None
    )

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert client._call_count == 4


@given(configured_retries=st.integers(min_value=0, max_value=5))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_24_backoff_delays_follow_configured_exponential_schedule(configured_retries):
    """For any configured retry count, the calculated backoff delay before
    retry N follows base * 2^(N-1) -- verified as pure calculation, no
    sleeping performed at all.
    """

    publisher = Publisher(
        settings=make_settings(publisher_retry_count=configured_retries, publisher_initial_backoff_seconds=2.0),
        qdrant_client=FakeQdrantClient(),
    )

    for retry_number in range(1, configured_retries + 1):
        expected = 2.0 * (2 ** (retry_number - 1))
        assert publisher._backoff_delay(retry_number) == expected


def test_property_24_permanent_failure_after_retries_sets_publish_failed_and_alerts(chunker, enricher):
    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    alerts = []
    publisher = Publisher(
        settings=make_settings(),
        qdrant_client=client,
        sleep_fn=lambda s: None,
        alert_callback=lambda msg, detail: alerts.append((msg, detail)),
    )

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert len(alerts) == 1


def test_property_24_property_tests_never_actually_sleep(chunker, enricher):
    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3, publisher_initial_backoff_seconds=2.0),
        qdrant_client=client,
        sleep_fn=lambda s: None,
    )

    start = time.monotonic()
    publisher.publish(enriched, embeddings)
    elapsed = time.monotonic() - start

    assert elapsed < 1.0  # would be 14s of real backoff if sleep_fn were live


# ---------------------------------------------------------------------------
# Count invariants / ordering / empty input / alert-on-success
# (supporting invariants named in the Task 8.3 brief; each still maps to
# the official properties above -- Property 22/23 for count/ordering,
# Property 24 for alert behavior.)
# ---------------------------------------------------------------------------


@given(page_numbers=st.lists(st.integers(min_value=1, max_value=2000), min_size=0, max_size=60, unique=True))
@hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_count_and_ordering_invariants_hold_for_successful_publication(chunker, enricher, page_numbers):
    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=page_numbers)
    embeddings = [[float(i)] * 384 for i in range(len(enriched))]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=10), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert result.published_count == result.total_count == len(enriched)
    published_points = [p for _, batch in client.calls for p in batch]
    # No drops, no duplicates, ordering preserved.
    assert [p.vector for p in published_points] == embeddings
    assert [p.payload["chunk_id"] for p in published_points] == [e.metadata.chunk_id for e in enriched]


def test_empty_publication_never_calls_qdrant():
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    result = publisher.publish([], [])

    assert result.status == JobStatus.COMPLETED
    assert result.published_count == 0 == result.total_count
    assert client.calls == []  # no invalid empty-batch write attempted


def test_successful_publication_never_triggers_alert(chunker, enricher):
    enriched = _make_pdf_enriched(chunker, enricher, page_numbers=range(1, 6))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    alerts = []
    publisher = Publisher(
        settings=make_settings(), qdrant_client=client, alert_callback=lambda m, d: alerts.append((m, d))
    )

    publisher.publish(enriched, embeddings)

    assert alerts == []
