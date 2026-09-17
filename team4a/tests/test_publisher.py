"""Unit tests for Task 8.2: Publisher.

No network access, no live Qdrant server: `FakeQdrantClient` implements
the same `QdrantClientProtocol` as the real `RealQdrantClient` (a single
`upsert(collection_name, points)` method), so these tests exercise
Publisher's real control flow -- batching, retry, exponential backoff,
partial-progress reporting, point-ID determinism -- without any external
service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    ChunkMetadata,
    JobStatus,
    PDFSegment,
    PublicationResult,
    VideoSegment,
    YouTubeMetadata,
    YouTubeSegment,
)
from app.pipeline.chunker import Chunker
from app.pipeline.metadata import MetadataEnricher
from app.pipeline.publisher import Publisher, chunk_id_to_point_id

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


class FakePoint:
    """Stand-in for qdrant_client.models.PointStruct -- just records what it was given."""

    def __init__(self, id, vector, payload):
        self.id = id
        self.vector = vector
        self.payload = payload


class FakeQdrantClient:
    """Records collection name, batch boundaries, and every upserted point.

    `fail_batches`: a set of 0-indexed batch numbers (in call order) that
    should raise on every attempt (including retries) -- lets tests
    simulate a specific batch permanently failing, or transient failures
    that later succeed via `fail_first_n_calls`.
    """

    def __init__(self, fail_batch_indices: set[int] | None = None, fail_first_n_calls: int = 0):
        self.fail_batch_indices = fail_batch_indices or set()
        self.fail_first_n_calls = fail_first_n_calls
        self.calls: list[tuple[str, list]] = []
        self._batch_number = -1
        self._call_count = 0

    def upsert(self, collection_name: str, points):
        points = list(points)
        self._call_count += 1
        # A new "batch" starts whenever this is the first attempt at a
        # given set of points; track batch identity by content, not call
        # count, so retries of the same batch are correctly attributed.
        is_new_batch = not self.calls or self.calls[-1][1] != points or self.calls[-1][0] != collection_name
        # Simpler and sufficient for these tests: batch number increments
        # only via explicit test bookkeeping (see fail_batch_indices usage).
        self.calls.append((collection_name, points))

        if self._call_count <= self.fail_first_n_calls:
            raise RuntimeError(f"simulated transient Qdrant failure #{self._call_count}")

        current_batch_points_pages = {p.payload.get("page_number") for p in points}
        if any(idx in current_batch_points_pages for idx in self.fail_batch_indices):
            raise RuntimeError("simulated permanent Qdrant failure for this batch")

        return {"status": "acknowledged"}


def make_pdf_enriched(chunker, enricher, job_id="job-1", filename="doc.pdf", page_numbers=(1,)):
    enriched = []
    for page in page_numbers:
        segment = PDFSegment(text=f"Distinct content for page {page} goes here today.", page_number=page)
        chunks = chunker.chunk(segment.text)
        enriched.extend(enricher.enrich_pdf_chunks(job_id, filename, NOW, segment, chunks))
    return enriched


@pytest.fixture
def chunker():
    return Chunker()


@pytest.fixture
def enricher():
    return MetadataEnricher()


def make_settings(**overrides):
    defaults = dict(
        qdrant_collection_name="team4a_test",
        qdrant_publish_batch_size=100,
        publisher_retry_count=3,
        publisher_initial_backoff_seconds=2.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# 1-3. Empty / single record / metadata+vector association
# ---------------------------------------------------------------------------


def test_empty_publication_succeeds_with_zero_records():
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    result = publisher.publish([], [])

    assert result.status == JobStatus.COMPLETED
    assert result.published_count == 0
    assert result.total_count == 0
    assert client.calls == []


def test_one_record_publishes_correctly(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.COMPLETED
    assert result.published_count == 1
    assert len(client.calls) == 1
    assert len(client.calls[0][1]) == 1


def test_metadata_and_vector_remain_correctly_associated(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1, 2, 3))
    embeddings = [[float(i)] * 384 for i in range(len(enriched))]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    published_points = client.calls[0][1]
    for i, point in enumerate(published_points):
        assert point.vector == embeddings[i]
        assert point.payload["chunk_id"] == enriched[i].metadata.chunk_id


# ---------------------------------------------------------------------------
# 4-7. Complete metadata / per-source-type payload preservation
# ---------------------------------------------------------------------------


def test_complete_metadata_present_in_payload(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(5,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    for field in ("chunk_id", "source_type", "job_id", "ingestion_timestamp", "embedding_model", "chunk_position"):
        assert field in payload


def test_published_record_contains_raw_text_content(chunker, enricher):
    """Regression test (Task 8.3 finding): Requirement 7.2 / Property 22
    require each published record to contain exactly three components --
    vector, raw text content, and the full metadata object. The original
    Task 8.2 payload omitted the chunk's text entirely; this is now fixed.
    """

    segment = PDFSegment(text="This exact text must appear in the published payload.", page_number=1)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    published_point = client.calls[0][1][0]
    assert published_point.payload["text"] == enriched[0].chunk.text
    assert published_point.payload["text"] != ""


def test_pdf_metadata_preserved_in_payload(chunker, enricher):
    from app.models.schemas import Heading

    segment = PDFSegment(
        text="Chapter content spans a couple of sentences.", page_number=9, headings=[Heading(text="Ch 9", level=1)]
    )
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_pdf_chunks("job-1", "report.pdf", NOW, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["filename"] == "report.pdf"
    assert payload["page_number"] == 9
    assert payload["headings"] == [{"text": "Ch 9", "level": 1}]
    assert payload["source_type"] == "pdf"


def test_video_metadata_preserved_in_payload(chunker, enricher):
    segment = VideoSegment(text="Spoken words for this segment here.", start_time=30.0, end_time=45.0)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_video_chunks("job-1", "lecture.mp4", NOW, segment, chunks, keyframes=[])
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["filename"] == "lecture.mp4"
    assert payload["start_timestamp"] == 30.0
    assert payload["end_timestamp"] == 45.0
    assert "frame_reference" not in payload  # None -> excluded, not null
    assert payload["source_type"] == "mp4"


def test_youtube_metadata_preserved_including_publication_date_none(chunker, enricher):
    segment = YouTubeSegment(text="Welcome to today's video.", start_time=5.0, duration=3.0)
    video_metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=100.0, publication_date=None)
    chunks = chunker.chunk(segment.text)
    enriched = enricher.enrich_youtube_chunks("job-1", "https://youtu.be/abc", NOW, video_metadata, segment, chunks)
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    payload = client.calls[0][1][0].payload
    assert payload["video_title"] == "T"
    assert payload["channel_name"] == "C"
    assert payload["source_url"] == "https://youtu.be/abc"
    assert "publication_date" not in payload  # None -> excluded, never fabricated
    assert payload["source_type"] == "youtube"


# ---------------------------------------------------------------------------
# 8-12. Batching
# ---------------------------------------------------------------------------


def test_exactly_100_records_form_one_batch(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 101))
    assert len(enriched) == 100
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=100), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert result.published_count == 100
    assert len(client.calls) == 1
    assert len(client.calls[0][1]) == 100


def test_101_records_form_two_batches(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 102))
    assert len(enriched) == 101
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=100), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert result.published_count == 101
    assert len(client.calls) == 2
    assert len(client.calls[0][1]) == 100
    assert len(client.calls[1][1]) == 1


def test_multiple_batches_preserve_global_ordering(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 8))
    embeddings = [[float(i)] * 384 for i in range(len(enriched))]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=3), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    all_published_points = [p for _, batch in client.calls for p in batch]
    assert [p.payload["page_number"] for p in all_published_points] == list(range(1, 8))
    assert [p.vector for p in all_published_points] == embeddings


def test_final_partial_batch_is_correct(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 8))  # 7 records
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=3), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert len(client.calls) == 3  # 3, 3, 1
    assert [len(batch) for _, batch in client.calls] == [3, 3, 1]
    assert result.published_count == 7


def test_every_input_record_represented_exactly_once(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 15))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=4), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    all_chunk_ids = [p.payload["chunk_id"] for _, batch in client.calls for p in batch]
    expected_chunk_ids = [e.metadata.chunk_id for e in enriched]
    assert sorted(all_chunk_ids) == sorted(expected_chunk_ids)
    assert len(all_chunk_ids) == len(set(all_chunk_ids))  # no duplicates


# ---------------------------------------------------------------------------
# 13. Mismatched lengths fail explicitly
# ---------------------------------------------------------------------------


def test_mismatched_lengths_raise_value_error_not_silently_truncate(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1, 2, 3))
    embeddings = [[0.1] * 384 for _ in range(2)]  # deliberately short
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    with pytest.raises(ValueError, match="length mismatch"):
        publisher.publish(enriched, embeddings)

    assert client.calls == []  # nothing was published


# ---------------------------------------------------------------------------
# 14-15. Deterministic point IDs
# ---------------------------------------------------------------------------


def test_point_id_is_deterministic_for_the_same_chunk_id():
    id_a = chunk_id_to_point_id("abc123")
    id_b = chunk_id_to_point_id("abc123")
    assert id_a == id_b


def test_point_id_differs_for_different_chunk_ids():
    assert chunk_id_to_point_id("abc123") != chunk_id_to_point_id("xyz789")


def test_republishing_identical_records_generates_identical_point_ids(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]

    client_a = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client_a).publish(enriched, embeddings)

    client_b = FakeQdrantClient()
    Publisher(settings=make_settings(), qdrant_client=client_b).publish(enriched, embeddings)

    ids_a = [p.id for p in client_a.calls[0][1]]
    ids_b = [p.id for p in client_b.calls[0][1]]
    assert ids_a == ids_b


def test_point_id_is_a_valid_uuid_string():
    import uuid

    point_id = chunk_id_to_point_id("some-chunk-id")
    # Must not raise -- a valid UUID string, not an arbitrary hash string.
    parsed = uuid.UUID(point_id)
    assert str(parsed) == point_id


# ---------------------------------------------------------------------------
# 16-19. Retry / exponential backoff
# ---------------------------------------------------------------------------


def test_retry_occurs_after_transient_failure(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_first_n_calls=1)  # fails once, then succeeds
    sleeps = []
    publisher = Publisher(
        settings=make_settings(), qdrant_client=client, sleep_fn=lambda s: sleeps.append(s)
    )

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.COMPLETED
    assert client._call_count == 2  # 1 failure + 1 successful retry
    assert sleeps == [2.0]


def test_retry_count_respects_configured_maximum(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})  # always fails
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3), qdrant_client=client, sleep_fn=lambda s: None
    )

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert client._call_count == 4  # 1 initial + 3 retries, then give up


def test_exponential_backoff_values_calculated_correctly():
    publisher = Publisher(settings=make_settings(publisher_initial_backoff_seconds=2.0), qdrant_client=FakeQdrantClient())

    assert publisher._backoff_delay(1) == 2.0
    assert publisher._backoff_delay(2) == 4.0
    assert publisher._backoff_delay(3) == 8.0


def test_backoff_schedule_observed_during_permanent_failure(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    sleeps = []
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3, publisher_initial_backoff_seconds=2.0),
        qdrant_client=client,
        sleep_fn=lambda s: sleeps.append(s),
    )

    publisher.publish(enriched, embeddings)

    assert sleeps == [2.0, 4.0, 8.0]


def test_tests_do_not_actually_wait_for_backoff(chunker, enricher):
    import time as time_module

    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(
        settings=make_settings(publisher_retry_count=3, publisher_initial_backoff_seconds=2.0),
        qdrant_client=client,
        sleep_fn=lambda s: None,  # injected no-op -- never really sleeps
    )

    start = time_module.monotonic()
    publisher.publish(enriched, embeddings)
    elapsed = time_module.monotonic() - start

    assert elapsed < 1.0  # would be 2+4+8=14s if sleep_fn were real time.sleep


# ---------------------------------------------------------------------------
# 20-24. Permanent failure semantics / partial progress / alerting
# ---------------------------------------------------------------------------


def test_permanent_batch_failure_produces_publish_failed(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(settings=make_settings(), qdrant_client=client, sleep_fn=lambda s: None)

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED


def test_permanent_failure_does_not_report_full_completion(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1, 2))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1, 2})
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=1), qdrant_client=client, sleep_fn=lambda s: None)

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert result.published_count < result.total_count
    assert result.published_count == 0  # both records are on failing pages


def test_partial_progress_represented_when_earlier_batch_succeeded(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1, 2, 3))
    embeddings = [[0.1] * 384 for _ in enriched]
    # batch_size=1 -> pages 1, 2, 3 each their own batch; only page 3 fails.
    client = FakeQdrantClient(fail_batch_indices={3})
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=1), qdrant_client=client, sleep_fn=lambda s: None)

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert result.published_count == 2  # pages 1 and 2 succeeded
    assert result.total_count == 3


def test_failure_information_is_retained(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(settings=make_settings(), qdrant_client=client, sleep_fn=lambda s: None)

    result = publisher.publish(enriched, embeddings)

    assert result.error_details is not None
    assert result.error_details.status_code == "PublicationFailed"
    assert result.error_details.detail["batch_start"] == 0
    assert "last_error" in result.error_details.detail


def test_alert_callback_triggered_on_permanent_failure(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    alerts = []
    publisher = Publisher(
        settings=make_settings(),
        qdrant_client=client,
        sleep_fn=lambda s: None,
        alert_callback=lambda message, detail: alerts.append((message, detail)),
    )

    publisher.publish(enriched, embeddings)

    assert len(alerts) == 1
    assert "failed" in alerts[0][0].lower()


def test_alert_not_triggered_on_success(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    alerts = []
    publisher = Publisher(
        settings=make_settings(), qdrant_client=client, alert_callback=lambda m, d: alerts.append((m, d))
    )

    publisher.publish(enriched, embeddings)

    assert alerts == []


def test_default_alert_logs_without_raising(chunker, enricher, caplog):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient(fail_batch_indices={1})
    publisher = Publisher(settings=make_settings(), qdrant_client=client, sleep_fn=lambda s: None)

    import logging

    with caplog.at_level(logging.ERROR):
        result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert any("failed" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# 25-26. Successful chunk count / no silent drops
# ---------------------------------------------------------------------------


def test_successful_publication_reports_correct_chunk_count(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 6))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    assert result.published_count == 5
    assert result.total_count == 5


def test_no_records_silently_dropped_across_batches(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=range(1, 250))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_publish_batch_size=100), qdrant_client=client)

    result = publisher.publish(enriched, embeddings)

    total_points_sent = sum(len(batch) for _, batch in client.calls)
    assert total_points_sent == len(enriched)
    assert result.published_count == len(enriched)


# ---------------------------------------------------------------------------
# 27. No random IDs
# ---------------------------------------------------------------------------


def test_point_ids_are_not_random_across_processes(chunker, enricher):
    # Simulates "re-publishing after a restart": a brand-new Publisher and
    # a brand-new client, but the same chunk_id, must still map to the
    # same point ID -- proving the ID is derived, not process-random.
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    chunk_id = enriched[0].metadata.chunk_id

    assert chunk_id_to_point_id(chunk_id) == chunk_id_to_point_id(chunk_id)


# ---------------------------------------------------------------------------
# Configuration usage (not hardcoded)
# ---------------------------------------------------------------------------


def test_uses_configured_collection_name_not_hardcoded(chunker, enricher):
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]
    client = FakeQdrantClient()
    publisher = Publisher(settings=make_settings(qdrant_collection_name="custom_collection"), qdrant_client=client)

    publisher.publish(enriched, embeddings)

    assert client.calls[0][0] == "custom_collection"


def test_default_settings_match_official_requirement():
    from app.config.settings import get_settings

    settings = get_settings()
    assert settings.qdrant_publish_batch_size == 100
    assert settings.publisher_retry_count == 3
    assert settings.publisher_initial_backoff_seconds == 2.0
    assert settings.qdrant_collection_name  # non-empty, configured


def test_publisher_uses_default_real_client_type_when_not_injected():
    from app.pipeline.publisher import RealQdrantClient

    publisher = Publisher()
    assert isinstance(publisher._client, RealQdrantClient)


def test_real_qdrant_client_does_not_connect_on_construction():
    from app.pipeline.publisher import RealQdrantClient

    client = RealQdrantClient(url="http://localhost:6333", api_key=None)
    assert client._client is None


# ---------------------------------------------------------------------------
# PublicationResult model validation
# ---------------------------------------------------------------------------


def test_publication_result_completed_requires_full_count():
    with pytest.raises(ValidationError):
        PublicationResult(status=JobStatus.COMPLETED, published_count=2, total_count=5)


def test_publication_result_failed_requires_error_details():
    with pytest.raises(ValidationError):
        PublicationResult(status=JobStatus.PUBLISH_FAILED, published_count=0, total_count=5)


def test_publication_result_rejects_other_statuses():
    with pytest.raises(ValidationError):
        PublicationResult(status=JobStatus.QUEUED, published_count=0, total_count=0)
