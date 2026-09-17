"""Focused tests for Task 2.1 (VectorStoreManager).

Scope: unit, integration-style (against a fake Qdrant client, exercising
real control flow), negative/error-path, boundary, and read-side-adapter
tests for Task 2.1 only.

Explicitly OUT of scope here (Task 2.2, not yet implemented):
  - Property 1 (storage round-trip)
  - Property 2 (deletion completeness)
  - Property 3 (collection-scoped retrieval isolation)
These are deferred to Task 2.2 and are not silently substituted with
similarly-shaped tests here -- the tests below check VectorStoreManager's
own control flow and the adapter's pure functions, not the formal
correctness properties themselves.

The fake Qdrant client mirrors Team 4A's own testing convention
(`QdrantClientProtocol` + an injected fake), independently written here
-- not shared code, not an import from Team 4A.
"""

from __future__ import annotations

from typing import Any, Sequence

import pytest
from qdrant_client.models import CollectionInfo, Distance, ScoredPoint, VectorParams

from app.core.config import Settings
from app.services.vector_store import (
    ContextChunk,
    VectorStoreConfigurationError,
    VectorStoreManager,
    VectorStoreUnavailableError,
    normalize_payload,
    normalize_source_type,
    resolve_document_title,
    resolve_youtube_end_timestamp,
    select_section_heading,
)


# ---------------------------------------------------------------------------
# Fake Qdrant client
# ---------------------------------------------------------------------------


class _FakeCollectionsResponse:
    def __init__(self, names: list[str]) -> None:
        self.collections = [_FakeCollectionDescription(name) for name in names]


class _FakeCollectionDescription:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeQdrantClient:
    """Implements QdrantClientProtocol without a live Qdrant server.

    `fail_times` lets tests simulate N transient failures before a given
    method starts succeeding, to exercise VectorStoreManager's own retry
    control flow deterministically.
    """

    def __init__(
        self,
        existing_collection_names: list[str] | None = None,
        existing_vector_size: int = 384,
        existing_distance: Any = Distance.COSINE,
        fail_times: dict[str, int] | None = None,
    ) -> None:
        self.existing_collection_names = existing_collection_names or []
        self.existing_vector_size = existing_vector_size
        self.existing_distance = existing_distance
        self._fail_times = dict(fail_times or {})
        self.created_collections: list[dict[str, Any]] = []
        self.created_indexes: list[dict[str, Any]] = []
        self.upserted_points: list[Any] = []
        self.deleted_selectors: list[Any] = []
        self.search_calls: list[dict[str, Any]] = []
        self.query_points_calls: list[dict[str, Any]] = []
        self.search_results: list[ScoredPoint] = []

    def _maybe_fail(self, method: str) -> None:
        remaining = self._fail_times.get(method, 0)
        if remaining > 0:
            self._fail_times[method] = remaining - 1
            raise ConnectionError(f"simulated transient failure in {method}")

    def get_collections(self) -> Any:
        self._maybe_fail("get_collections")
        return _FakeCollectionsResponse(self.existing_collection_names)

    def get_collection(self, collection_name: str) -> Any:
        self._maybe_fail("get_collection")
        vectors = VectorParams(size=self.existing_vector_size, distance=self.existing_distance)
        config = type("Config", (), {"params": type("Params", (), {"vectors": vectors})()})()
        return type("CollectionInfoLike", (), {"config": config})()

    def create_collection(self, collection_name: str, vectors_config: Any) -> Any:
        self._maybe_fail("create_collection")
        self.created_collections.append({"collection_name": collection_name, "vectors_config": vectors_config})
        self.existing_collection_names.append(collection_name)
        return True

    def create_payload_index(self, collection_name: str, field_name: str, field_schema: Any) -> Any:
        self._maybe_fail("create_payload_index")
        self.created_indexes.append(
            {"collection_name": collection_name, "field_name": field_name, "field_schema": field_schema}
        )
        return True

    def upsert(self, collection_name: str, points: Sequence[Any]) -> Any:
        self._maybe_fail("upsert")
        self.upserted_points.extend(points)
        return True

    def search(
        self,
        collection_name: str,
        query_vector: Sequence[float],
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
    ) -> Any:
        self._maybe_fail("search")
        self.search_calls.append(
            {
                "collection_name": collection_name,
                "query_vector": query_vector,
                "limit": limit,
                "score_threshold": score_threshold,
                "query_filter": query_filter,
            }
        )
        return self.search_results[:limit]

    def query_points(
        self,
        collection_name: str,
        query: Sequence[float],
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
        **kwargs: Any,
    ) -> Any:
        """Modern Qdrant 1.19-compatible query API.

        Reuse the fake's existing search behavior so existing tests
        retain their established result and call-recording semantics.
        """
        self.query_points_calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "limit": limit,
                "score_threshold": score_threshold,
                "query_filter": query_filter,
                **kwargs,
            }
        )

        points = self.search(
            collection_name=collection_name,
            query_vector=query,
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
        )

        return SimpleNamespace(points=points)

    def delete(self, collection_name: str, points_selector: Any) -> Any:
        self._maybe_fail("delete")
        self.deleted_selectors.append(points_selector)
        return True

    def scroll(self, collection_name: str, limit: int, offset: Any | None = None) -> Any:
        # Not exercised by Task 2.1's own tests (scroll_all_chunks was
        # added in Task 3.2 for HybridRetriever's benefit) -- present
        # only so this fake still satisfies QdrantClientProtocol.
        self._maybe_fail("scroll")
        return [], None


def _settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "_env_file": None,
        "vector_store_initial_backoff_seconds": 0.001,  # keep tests fast
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _manager(client: FakeQdrantClient, **settings_overrides: Any) -> VectorStoreManager:
    return VectorStoreManager(settings=_settings(**settings_overrides), qdrant_client=client, sleep_fn=lambda _s: None)


# ---------------------------------------------------------------------------
# Collection provisioning / verification
# ---------------------------------------------------------------------------


class TestEnsureCollection:
    def test_creates_collection_when_missing(self):
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.ensure_collection()

        assert len(client.created_collections) == 1
        created = client.created_collections[0]
        assert created["collection_name"] == "team4b_shared_production_chunks"
        assert created["vectors_config"].size == 384
        assert created["vectors_config"].distance == Distance.COSINE

    def test_creates_payload_indexes_on_new_collection(self):
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.ensure_collection()

        indexed_fields = {index["field_name"] for index in client.created_indexes}
        assert indexed_fields == {"job_id", "source_type"}

    def test_does_not_recreate_existing_compatible_collection(self):
        client = FakeQdrantClient(
            existing_collection_names=["team4b_shared_production_chunks"],
            existing_vector_size=384,
            existing_distance=Distance.COSINE,
        )
        manager = _manager(client)

        manager.ensure_collection()

        assert client.created_collections == []
        # Indexes are still verified/ensured even on an existing collection.
        indexed_fields = {index["field_name"] for index in client.created_indexes}
        assert indexed_fields == {"job_id", "source_type"}

    def test_raises_on_incompatible_existing_vector_size(self):
        client = FakeQdrantClient(
            existing_collection_names=["team4b_shared_production_chunks"],
            existing_vector_size=768,
            existing_distance=Distance.COSINE,
        )
        manager = _manager(client)

        with pytest.raises(VectorStoreConfigurationError):
            manager.ensure_collection()

    def test_raises_on_incompatible_existing_distance(self):
        client = FakeQdrantClient(
            existing_collection_names=["team4b_shared_production_chunks"],
            existing_vector_size=384,
            existing_distance=Distance.EUCLID,
        )
        manager = _manager(client)

        with pytest.raises(VectorStoreConfigurationError):
            manager.ensure_collection()

    def test_dimension_and_distance_are_configurable(self):
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client, embedding_dimensions=768, embedding_distance="Euclid")

        manager.ensure_collection()

        created = client.created_collections[0]
        assert created["vectors_config"].size == 768
        assert created["vectors_config"].distance == Distance.EUCLID


# ---------------------------------------------------------------------------
# Write path
# ---------------------------------------------------------------------------


class TestUpsert:
    def test_upsert_chunk_writes_one_point(self):
        client = FakeQdrantClient()
        manager = _manager(client)
        chunk = ContextChunk(
            chunk_id="chunk-1",
            text="hello world",
            embedding=[0.1, 0.2, 0.3],
            metadata={"job_id": "job-1", "source_type": "pdf"},
        )

        manager.upsert_chunk(chunk)

        assert len(client.upserted_points) == 1
        point = client.upserted_points[0]
        assert point.payload["text"] == "hello world"
        assert point.payload["chunk_id"] == "chunk-1"
        assert point.payload["job_id"] == "job-1"
        assert point.vector == [0.1, 0.2, 0.3]

    def test_upsert_batch_splits_at_configured_batch_size(self):
        client = FakeQdrantClient()
        manager = _manager(client, qdrant_publish_batch_size=2)
        chunks = [
            ContextChunk(chunk_id=f"c{i}", text=f"t{i}", embedding=[0.0], metadata={"job_id": "job-1"})
            for i in range(5)
        ]

        manager.upsert_batch(chunks)

        assert len(client.upserted_points) == 5  # all published, just across multiple batched calls

    def test_upsert_batch_empty_list_is_a_noop(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.upsert_batch([])

        assert client.upserted_points == []

    def test_same_chunk_id_produces_same_point_id_deterministically(self):
        client = FakeQdrantClient()
        manager = _manager(client)
        chunk = ContextChunk(chunk_id="stable-id", text="x", embedding=[0.0], metadata={})

        manager.upsert_chunk(chunk)
        manager.upsert_chunk(chunk)

        first_id, second_id = client.upserted_points[0].id, client.upserted_points[1].id
        assert first_id == second_id


# ---------------------------------------------------------------------------
# Delete path
# ---------------------------------------------------------------------------


class TestDeleteByDocument:
    def test_delete_by_document_filters_on_job_id_field(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.delete_by_document("job-123")

        assert len(client.deleted_selectors) == 1
        selector = client.deleted_selectors[0]
        condition = selector.filter.must[0]
        assert condition.key == "job_id"
        assert condition.match.value == "job-123"


# ---------------------------------------------------------------------------
# Search / collection filtering
# ---------------------------------------------------------------------------


class TestSearchSimilar:
    def test_search_returns_retrieval_results_with_normalized_metadata(self):
        client = FakeQdrantClient()
        client.search_results = [
            ScoredPoint(
                id="p1",
                version=0,
                score=0.87,
                payload={
                    "text": "some pdf text",
                    "chunk_id": "chunk-1",
                    "job_id": "job-1",
                    "document_id": "file-123",
                    "source_type": "pdf",
                    "filename": "notes.pdf",
                    "page_number": 3,
                    "headings": [{"text": "Intro", "level": 1}, {"text": "Sub", "level": 2}],
                },
            )
        ]
        manager = _manager(client)

        results = manager.search_similar(query_vector=[0.1, 0.2], top_k=5, score_threshold=0.3, workspace_id="ws-1")

        assert len(results) == 1
        result = results[0]
        assert result.chunk_id == "chunk-1"
        assert result.text == "some pdf text"
        assert result.relevance_score == 0.87
        # MVP M3 identity correction: document_id is the canonical
        # payload identity, NOT job_id -- both are preserved, distinctly.
        assert result.metadata["document_id"] == "file-123"
        assert result.metadata["job_id"] == "job-1"
        assert result.metadata["source_type"] == "document"  # normalized from "pdf"
        assert result.metadata["document_title"] == "notes.pdf"
        assert result.metadata["section_heading"] == "Intro"  # lowest level

    def test_search_passes_top_k_and_score_threshold_through(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=7, score_threshold=0.42, workspace_id="ws-1")

        call = client.search_calls[0]
        assert call["limit"] == 7
        assert call["score_threshold"] == 0.42

    def test_no_collection_filter_means_only_the_mandatory_workspace_condition(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, collection_filter=None, workspace_id="ws-1")

        # MVP M3: there is no longer a "no filter at all" case -- the
        # mandatory workspace_id condition is always present, even when
        # no OPTIONAL collection_filter was supplied.
        query_filter = client.search_calls[0]["query_filter"]
        assert query_filter is not None
        assert len(query_filter.must) == 1
        assert query_filter.must[0].key == "workspace_id"
        assert query_filter.must[0].match.value == "ws-1"

    def test_collection_filter_document_maps_to_raw_pdf(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, collection_filter=["document"], workspace_id="ws-1")

        query_filter = client.search_calls[0]["query_filter"]
        # must[0] is now always the mandatory workspace_id condition (MVP M3).
        assert query_filter.must[0].key == "workspace_id"
        condition = query_filter.must[1]
        assert condition.key == "source_type"
        assert set(condition.match.any) == {"pdf"}

    def test_collection_filter_video_maps_to_raw_mp4_and_youtube(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, collection_filter=["video"], workspace_id="ws-1")

        query_filter = client.search_calls[0]["query_filter"]
        assert query_filter.must[0].key == "workspace_id"
        condition = query_filter.must[1]
        assert set(condition.match.any) == {"mp4", "youtube"}


# ---------------------------------------------------------------------------
# Retry / error-path (Requirement 1.5)
# ---------------------------------------------------------------------------


class TestRetryAndErrorHandling:
    def test_upsert_succeeds_after_transient_failures_within_retry_budget(self):
        client = FakeQdrantClient(fail_times={"upsert": 2})
        manager = _manager(client, vector_store_retry_count=3)
        chunk = ContextChunk(chunk_id="c1", text="t", embedding=[0.0], metadata={})

        manager.upsert_chunk(chunk)  # should not raise -- 2 failures, then success, within 3 retries

        assert len(client.upserted_points) == 1

    def test_upsert_raises_vector_store_unavailable_after_exhausting_retries(self):
        client = FakeQdrantClient(fail_times={"upsert": 10})
        manager = _manager(client, vector_store_retry_count=3)
        chunk = ContextChunk(chunk_id="c1", text="t", embedding=[0.0], metadata={})

        with pytest.raises(VectorStoreUnavailableError) as exc_info:
            manager.upsert_chunk(chunk)

        assert exc_info.value.status_code == "VectorStoreUnavailable"

    def test_search_raises_vector_store_unavailable_after_exhausting_retries(self):
        client = FakeQdrantClient(fail_times={"search": 10})
        manager = _manager(client, vector_store_retry_count=3)

        with pytest.raises(VectorStoreUnavailableError):
            manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, workspace_id="ws-1")

    def test_delete_raises_vector_store_unavailable_after_exhausting_retries(self):
        client = FakeQdrantClient(fail_times={"delete": 10})
        manager = _manager(client, vector_store_retry_count=3)

        with pytest.raises(VectorStoreUnavailableError):
            manager.delete_by_document("job-1")

    def test_retry_count_is_configurable(self):
        client = FakeQdrantClient(fail_times={"upsert": 5})
        manager = _manager(client, vector_store_retry_count=10)
        chunk = ContextChunk(chunk_id="c1", text="t", embedding=[0.0], metadata={})

        manager.upsert_chunk(chunk)  # 5 failures < 10 retries -- should succeed

        assert len(client.upserted_points) == 1

    def test_backoff_delay_doubles_each_retry(self):
        client = FakeQdrantClient()
        manager = _manager(client, vector_store_initial_backoff_seconds=2.0)

        assert manager._backoff_delay(1) == 2.0
        assert manager._backoff_delay(2) == 4.0
        assert manager._backoff_delay(3) == 8.0


# ---------------------------------------------------------------------------
# Read-side normalization adapter -- pure function tests
# ---------------------------------------------------------------------------


class TestSourceTypeNormalization:
    def test_pdf_maps_to_document(self):
        assert normalize_source_type("pdf") == "document"

    def test_mp4_maps_to_video(self):
        assert normalize_source_type("mp4") == "video"

    def test_youtube_maps_to_video(self):
        assert normalize_source_type("youtube") == "video"


class TestDocumentTitleResolution:
    def test_pdf_uses_filename(self):
        assert resolve_document_title({"source_type": "pdf", "filename": "report.pdf"}) == "report.pdf"

    def test_mp4_uses_filename(self):
        assert resolve_document_title({"source_type": "mp4", "filename": "lecture.mp4"}) == "lecture.mp4"

    def test_youtube_prefers_video_title(self):
        payload = {"source_type": "youtube", "video_title": "Intro to RAG", "filename": None}
        assert resolve_document_title(payload) == "Intro to RAG"

    def test_youtube_falls_back_to_filename_when_video_title_absent(self):
        payload = {"source_type": "youtube", "filename": "fallback.mp4"}
        assert resolve_document_title(payload) == "fallback.mp4"


class TestSectionHeadingSelection:
    def test_empty_list_returns_none(self):
        assert select_section_heading([]) is None

    def test_none_returns_none(self):
        assert select_section_heading(None) is None

    def test_single_heading_returned(self):
        assert select_section_heading([{"text": "Chapter 1", "level": 1}]) == "Chapter 1"

    def test_lowest_level_wins(self):
        headings = [{"text": "Sub-point", "level": 3}, {"text": "Chapter", "level": 1}, {"text": "Section", "level": 2}]
        assert select_section_heading(headings) == "Chapter"

    def test_first_wins_on_tie(self):
        headings = [{"text": "First H1", "level": 1}, {"text": "Second H1", "level": 1}]
        assert select_section_heading(headings) == "First H1"


class TestYoutubeEndTimestampResolution:
    def test_mp4_passes_through_existing_end_timestamp(self):
        payload = {"source_type": "mp4", "end_timestamp": 12.5}
        assert resolve_youtube_end_timestamp(payload) == 12.5

    def test_youtube_uses_existing_end_timestamp_when_present(self):
        payload = {"source_type": "youtube", "end_timestamp": 45.0, "start_timestamp": 30.0, "duration": 20.0}
        assert resolve_youtube_end_timestamp(payload) == 45.0

    def test_youtube_computes_from_start_plus_duration_when_absent(self):
        payload = {"source_type": "youtube", "start_timestamp": 30.0, "duration": 20.0}
        assert resolve_youtube_end_timestamp(payload) == 50.0

    def test_zero_start_timestamp_is_not_treated_as_missing(self):
        # Explicit regression test for the "never treat 0.0 as missing" instruction.
        payload = {"source_type": "youtube", "start_timestamp": 0.0, "duration": 15.0}
        assert resolve_youtube_end_timestamp(payload) == 15.0

    def test_zero_end_timestamp_is_not_overwritten(self):
        # end_timestamp=0.0 is a valid (if unusual) value and must be
        # respected, not treated as "missing" and recomputed.
        payload = {"source_type": "youtube", "end_timestamp": 0.0, "start_timestamp": 5.0, "duration": 10.0}
        assert resolve_youtube_end_timestamp(payload) == 0.0

    def test_returns_none_when_inputs_genuinely_missing(self):
        payload = {"source_type": "youtube"}
        assert resolve_youtube_end_timestamp(payload) is None


class TestNormalizePayloadIntegration:
    def test_full_pdf_payload(self):
        payload = {
            "text": "body text",
            "chunk_id": "c1",
            "job_id": "job-1",
            "document_id": "file-123",
            "source_type": "pdf",
            "filename": "doc.pdf",
            "page_number": 2,
            "headings": [{"text": "Overview", "level": 1}],
        }

        normalized = normalize_payload(payload)

        assert "text" not in normalized  # carried separately on RetrievalResult
        # MVP M3 identity correction: canonical document_id preserved, not replaced by job_id.
        assert normalized["document_id"] == "file-123"
        assert normalized["job_id"] == "job-1"
        assert normalized["source_type"] == "document"
        assert normalized["document_title"] == "doc.pdf"
        assert normalized["section_heading"] == "Overview"
        assert normalized["page_number"] == 2
        assert normalized["headings"] == [{"text": "Overview", "level": 1}]  # preserved, not discarded

    def test_full_youtube_payload_with_missing_end_timestamp(self):
        payload = {
            "text": "transcript text",
            "chunk_id": "c2",
            "job_id": "job-2",
            "source_type": "youtube",
            "video_title": "How RAG Works",
            "start_timestamp": 10.0,
            "duration": 5.0,
        }

        normalized = normalize_payload(payload)

        assert normalized["source_type"] == "video"
        assert normalized["document_title"] == "How RAG Works"
        assert normalized["end_timestamp"] == 15.0


# ---------------------------------------------------------------------------
# Task 10.1: check_health()
# ---------------------------------------------------------------------------


class TestCheckHealth:
    def test_returns_true_when_get_collections_succeeds(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        assert manager.check_health() is True

    def test_returns_false_when_client_raises(self):
        client = FakeQdrantClient(fail_times={"get_collections": 100})
        manager = _manager(client, vector_store_retry_count=0)

        assert manager.check_health() is False

    def test_never_raises_even_on_repeated_failure(self):
        client = FakeQdrantClient(fail_times={"get_collections": 100})
        manager = _manager(client, vector_store_retry_count=0)

        # Calling it multiple times must never raise -- a health check
        # that itself crashes would be worse than useless.
        for _ in range(3):
            assert manager.check_health() is False

    def test_does_not_use_the_retry_mechanism(self):
        # A health check wants the CURRENT state fast, not a value that
        # looks healthy only because retries papered over a real outage
        # for several seconds. Only 1 attempt should ever be made.
        client = FakeQdrantClient(fail_times={"get_collections": 1})
        manager = _manager(client, vector_store_retry_count=5)

        # Even though vector_store_retry_count=5 would allow recovery on
        # a real (retried) operation, check_health() must NOT retry --
        # it should report unhealthy on the very first transient failure.
        assert manager.check_health() is False

    def test_does_not_create_or_modify_the_collection(self):
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.check_health()

        assert client.created_collections == []  # read-only, never provisions anything


# ---------------------------------------------------------------------------
# Task 11.1 corrective fix: lazy, automatic collection provisioning via
# the shared _with_retry() entry point (real Docker runtime verification
# found POST /api/v1/query permanently failing with 503 because nothing
# in the query path ever called the already-correct ensure_collection()
# before search_similar()).
# ---------------------------------------------------------------------------


class TestAutomaticCollectionProvisioningInOperationalPath:
    def test_search_similar_provisions_the_missing_collection_and_succeeds(self):
        # A: collection absent -> the normal query path (search_similar)
        # invokes ensure_collection() and the collection becomes usable,
        # instead of raising VectorStoreUnavailableError as it did before
        # this fix (KeyError against a nonexistent collection, retried
        # 3x by _with_retry, then surfaced as a permanent failure).
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        results = manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")

        assert results == []  # succeeds against a freshly-provisioned, empty collection
        assert len(client.created_collections) == 1
        assert client.created_collections[0]["collection_name"] == "team4b_shared_production_chunks"

    def test_upsert_also_provisions_the_missing_collection(self):
        # The fix lives in the single shared _with_retry() entry point,
        # so it must apply to EVERY operation that goes through it, not
        # just search_similar.
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)
        chunk = ContextChunk(chunk_id="c1", text="hello", embedding=[1.0] * 384, metadata={"job_id": "job-1"})

        manager.upsert_chunk(chunk)

        assert len(client.created_collections) == 1

    def test_collection_is_provisioned_exactly_once_across_multiple_operations(self):
        # Provisioning happens lazily, once per instance lifetime -- not
        # re-checked/re-created on every single call.
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")
        manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")
        manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")

        assert len(client.created_collections) == 1  # not 3

    def test_a_transient_failure_during_provisioning_is_retried_by_the_existing_mechanism(self):
        # The provisioning call runs INSIDE the existing retry loop, so
        # a transient failure while ensuring the collection is retried
        # exactly like any other transient Vector_Store failure --
        # Requirement 1.5's retry behavior is not weakened or bypassed.
        client = FakeQdrantClient(existing_collection_names=[], fail_times={"get_collections": 2})
        manager = _manager(client, vector_store_retry_count=5)

        results = manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")

        assert results == []  # eventually succeeds
        assert len(client.created_collections) == 1

    def test_permanent_provisioning_failure_still_surfaces_vector_store_unavailable(self):
        # Requirement 1.5's existing "permanently failed after N
        # retries" behavior must still apply when the failure is in
        # provisioning, not just in the wrapped operation itself.
        client = FakeQdrantClient(existing_collection_names=[], fail_times={"get_collections": 99})
        manager = _manager(client, vector_store_retry_count=2)

        with pytest.raises(VectorStoreUnavailableError):
            manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")


class TestExistingCompatibleCollectionIsNotRecreated:
    def test_search_against_an_already_existing_compatible_collection_does_not_recreate_it(self):
        # B: collection already exists with the approved 384/Cosine
        # configuration -> the operational path does not recreate it,
        # and compatibility verification still runs (proven by the
        # absence of a VectorStoreConfigurationError, which WOULD raise
        # if the compatibility check were skipped and a mismatch existed).
        client = FakeQdrantClient(
            existing_collection_names=["team4b_shared_production_chunks"],
            existing_vector_size=384,
            existing_distance=Distance.COSINE,
        )
        manager = _manager(client)

        results = manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")

        assert results == []
        assert client.created_collections == []  # never recreated

    def test_search_against_an_incompatible_existing_collection_still_raises(self):
        # Compatibility verification (already-approved, pre-existing
        # behavior) must still run as part of the automatic provisioning
        # path -- an incompatible collection must not be silently used.
        client = FakeQdrantClient(
            existing_collection_names=["team4b_shared_production_chunks"],
            existing_vector_size=768,  # mismatched on purpose
            existing_distance=Distance.COSINE,
        )
        manager = _manager(client)

        with pytest.raises(VectorStoreConfigurationError):
            manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")


class TestTeam4ACollectionRemainsUntouched:
    def test_team_4a_collection_is_never_created_modified_or_queried(self):
        # C: Team 4A's own collection (a different name entirely) must
        # remain completely untouched by the automatic provisioning path
        # -- ensure_collection() only ever creates/inspects Team 4B's
        # OWN configured collection name, never any other.
        client = FakeQdrantClient(
            existing_collection_names=["team4a_ingested_chunks"],
            existing_vector_size=384,
            existing_distance=Distance.COSINE,
        )
        manager = _manager(client)  # configured collection name defaults to team4b_shared_production_chunks

        manager.search_similar(query_vector=[1.0] * 384, top_k=5, score_threshold=0.0, workspace_id="ws-1")

        # Team 4A's collection was never touched by create_collection...
        assert all(c["collection_name"] != "team4a_ingested_chunks" for c in client.created_collections)
        # ...and Team 4B's OWN collection was the only one created.
        assert len(client.created_collections) == 1
        assert client.created_collections[0]["collection_name"] == "team4b_shared_production_chunks"
        # Team 4A's collection name is still present afterward, unchanged.
        assert "team4a_ingested_chunks" in client.existing_collection_names


class TestHealthCheckStillDoesNotProvision:
    def test_check_health_does_not_trigger_automatic_provisioning(self):
        # D: GET /health (check_health()) must remain lightweight and
        # must NOT create the production collection -- confirmed this
        # still holds after the corrective fix, since check_health()
        # never calls _with_retry() or ensure_collection() at all.
        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.check_health()
        manager.check_health()
        manager.check_health()

        assert client.created_collections == []


# ---------------------------------------------------------------------------
# Corrective fix: RealQdrantClient.search() migrated from the removed
# legacy QdrantClient.search() to the current QdrantClient.query_points()
# API (real Docker runtime defect: qdrant-client==1.19.0 has no .search()
# at all -- confirmed via direct inspection, not assumed).
#
# These tests exercise RealQdrantClient itself (bypassing its lazy
# `_ensure_client()` construction by injecting a fake standing in for the
# underlying raw qdrant_client.QdrantClient object) -- distinct from
# every other test in this file, which exercises VectorStoreManager
# through the QdrantClientProtocol-conforming FakeQdrantClient and is
# therefore unaffected by this internal implementation detail either way.
# ---------------------------------------------------------------------------


from types import SimpleNamespace

from app.services.vector_store import RealQdrantClient


class _FakeRawQdrantClient:
    """Stands in for the underlying `qdrant_client.QdrantClient` object
    itself (NOT `QdrantClientProtocol`) -- used only to prove
    `RealQdrantClient`'s own internal implementation calls the current
    `query_points()` API. Deliberately implements ONLY the methods this
    fix and its neighbors actually need; if `RealQdrantClient` ever
    called the removed `.search()` again, calling it here would raise
    a real `AttributeError`, exactly like the genuine bug did.
    """

    def __init__(self, points: list[Any] | None = None) -> None:
        self.query_points_calls: list[dict[str, Any]] = []
        self._points = points if points is not None else []

    def query_points(
        self,
        collection_name: str,
        query: Any,
        limit: int,
        score_threshold: float | None = None,
        query_filter: Any | None = None,
    ) -> Any:
        self.query_points_calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "limit": limit,
                "score_threshold": score_threshold,
                "query_filter": query_filter,
            }
        )
        return SimpleNamespace(points=self._points)


def _wrapper_with_fake_raw_client(raw_client: _FakeRawQdrantClient) -> RealQdrantClient:
    wrapper = RealQdrantClient(url="http://example.invalid:6333", api_key=None)
    wrapper._client = raw_client  # bypass lazy _ensure_client() construction
    return wrapper


class TestRealQdrantClientSearchUsesQueryPoints:
    def test_search_calls_query_points_with_the_correct_arguments(self):
        raw_client = _FakeRawQdrantClient(points=[])
        wrapper = _wrapper_with_fake_raw_client(raw_client)
        fake_filter = object()

        wrapper.search(
            collection_name="team4b_shared_production_chunks",
            query_vector=[0.1, 0.2, 0.3],
            limit=5,
            score_threshold=0.3,
            query_filter=fake_filter,
        )

        assert len(raw_client.query_points_calls) == 1
        call = raw_client.query_points_calls[0]
        assert call["collection_name"] == "team4b_shared_production_chunks"
        assert call["query"] == [0.1, 0.2, 0.3]
        assert call["limit"] == 5
        assert call["score_threshold"] == 0.3
        assert call["query_filter"] is fake_filter

    def test_search_never_calls_the_removed_legacy_method(self):
        # The fake genuinely does not implement `search` at all -- if
        # RealQdrantClient still called it, this would raise the exact
        # AttributeError the real bug produced.
        raw_client = _FakeRawQdrantClient(points=[])
        assert not hasattr(raw_client, "search")
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        wrapper.search(collection_name="c", query_vector=[0.1], limit=1)  # must not raise

    def test_response_points_is_correctly_unwrapped_into_a_bare_list(self):
        point_a = SimpleNamespace(id="a", score=0.9, payload={"text": "alpha"})
        point_b = SimpleNamespace(id="b", score=0.8, payload={"text": "beta"})
        raw_client = _FakeRawQdrantClient(points=[point_a, point_b])
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        result = wrapper.search(collection_name="c", query_vector=[0.1], limit=2)

        assert isinstance(result, list)
        assert result == [point_a, point_b]

    def test_empty_points_response_returns_an_empty_list(self):
        raw_client = _FakeRawQdrantClient(points=[])
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        result = wrapper.search(collection_name="c", query_vector=[0.1], limit=5)

        assert result == []

    def test_query_vector_is_converted_to_a_plain_list(self):
        raw_client = _FakeRawQdrantClient(points=[])
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        wrapper.search(collection_name="c", query_vector=(0.1, 0.2), limit=1)  # a tuple, not a list

        assert raw_client.query_points_calls[0]["query"] == [0.1, 0.2]
        assert isinstance(raw_client.query_points_calls[0]["query"], list)

    def test_none_query_filter_is_passed_through_as_none(self):
        raw_client = _FakeRawQdrantClient(points=[])
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        wrapper.search(collection_name="c", query_vector=[0.1], limit=1, query_filter=None)

        assert raw_client.query_points_calls[0]["query_filter"] is None

    def test_default_score_threshold_is_none_when_not_supplied(self):
        raw_client = _FakeRawQdrantClient(points=[])
        wrapper = _wrapper_with_fake_raw_client(raw_client)

        wrapper.search(collection_name="c", query_vector=[0.1], limit=1)

        assert raw_client.query_points_calls[0]["score_threshold"] is None


class TestRealQdrantClientOtherMethodsUnchanged:
    """The diagnostic confirmed every OTHER method this wrapper calls
    (`get_collections`, `get_collection`, `create_collection`,
    `create_payload_index`, `upsert`, `delete`, `scroll`) still exists
    with a compatible signature in qdrant-client==1.19.0 and was
    therefore NOT touched by this fix. These tests confirm exactly that:
    each still delegates to its own same-named method on the underlying
    client, unchanged.
    """

    class _FakeRawClientAllMethods:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def get_collections(self) -> Any:
            self.calls.append(("get_collections", {}))
            return "collections-result"

        def get_collection(self, collection_name: str) -> Any:
            self.calls.append(("get_collection", {"collection_name": collection_name}))
            return "collection-result"

        def create_collection(self, collection_name: str, vectors_config: Any) -> Any:
            self.calls.append(("create_collection", {"collection_name": collection_name}))
            return True

        def create_payload_index(self, collection_name: str, field_name: str, field_schema: Any) -> Any:
            self.calls.append(("create_payload_index", {"field_name": field_name}))
            return True

        def upsert(self, collection_name: str, points: Any) -> Any:
            self.calls.append(("upsert", {"points": list(points)}))
            return True

        def delete(self, collection_name: str, points_selector: Any) -> Any:
            self.calls.append(("delete", {"points_selector": points_selector}))
            return True

        def scroll(self, collection_name: str, limit: int, offset: Any = None) -> Any:
            self.calls.append(("scroll", {"limit": limit}))
            return ([], None)

    def test_get_collections_still_delegates_unchanged(self):
        raw = self._FakeRawClientAllMethods()
        wrapper = _wrapper_with_fake_raw_client(raw)  # type: ignore[arg-type]

        assert wrapper.get_collections() == "collections-result"
        assert raw.calls == [("get_collections", {})]

    def test_upsert_still_delegates_unchanged(self):
        raw = self._FakeRawClientAllMethods()
        wrapper = _wrapper_with_fake_raw_client(raw)  # type: ignore[arg-type]

        wrapper.upsert(collection_name="c", points=[1, 2, 3])

        assert raw.calls == [("upsert", {"points": [1, 2, 3]})]

    def test_scroll_still_delegates_unchanged(self):
        raw = self._FakeRawClientAllMethods()
        wrapper = _wrapper_with_fake_raw_client(raw)  # type: ignore[arg-type]

        wrapper.scroll(collection_name="c", limit=10)

        assert raw.calls == [("scroll", {"limit": 10})]

    def test_delete_still_delegates_unchanged(self):
        raw = self._FakeRawClientAllMethods()
        wrapper = _wrapper_with_fake_raw_client(raw)  # type: ignore[arg-type]

        wrapper.delete(collection_name="c", points_selector="selector")

        assert raw.calls == [("delete", {"points_selector": "selector"})]


class TestMandatoryWorkspaceFilter:
    """MVP M3: workspace_id is a mandatory, non-overridable Qdrant filter
    condition on every search_similar() call."""

    def test_search_similar_has_no_default_for_workspace_id(self):
        import inspect

        signature = inspect.signature(VectorStoreManager.search_similar)
        assert signature.parameters["workspace_id"].default is inspect.Parameter.empty

    def test_workspace_condition_is_always_present_regardless_of_collection_filter(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, collection_filter=["document"], workspace_id="ws-specific")

        query_filter = client.search_calls[0]["query_filter"]
        workspace_conditions = [c for c in query_filter.must if c.key == "workspace_id"]
        assert len(workspace_conditions) == 1
        assert workspace_conditions[0].match.value == "ws-specific"

    def test_different_workspace_ids_produce_different_filters_on_separate_calls(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, workspace_id="workspace-A")
        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, workspace_id="workspace-B")

        filter_a = client.search_calls[0]["query_filter"]
        filter_b = client.search_calls[1]["query_filter"]
        assert filter_a.must[0].match.value == "workspace-A"
        assert filter_b.must[0].match.value == "workspace-B"


class TestRetrievalConfigCannotOverrideWorkspaceFilter:
    """TEST 7: no value of collection_filter (the one retrieval_config
    knob that reaches search_similar) can change, remove, or replace the
    mandatory workspace_id condition."""

    def test_workspace_condition_survives_regardless_of_collection_filter_value(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        for attempted_override in [None, ["document"], ["video"], ["document", "video"]]:
            client.search_calls.clear()
            manager.search_similar(
                query_vector=[0.1], top_k=5, score_threshold=0.3,
                collection_filter=attempted_override, workspace_id="workspace-real",
            )
            query_filter = client.search_calls[0]["query_filter"]
            workspace_conditions = [c for c in query_filter.must if c.key == "workspace_id"]
            assert len(workspace_conditions) == 1
            assert workspace_conditions[0].match.value == "workspace-real"


class TestLegacyCollectionUntouchedByCanonicalPath:
    """TEST 15: the canonical query path (search_similar/scroll_all_chunks
    with an explicit collection_name override) never touches the legacy
    collection name."""

    def test_search_similar_with_canonical_override_never_addresses_the_legacy_collection(self):
        # MVP M6 pre-flight correction: the canonical collection is
        # verified to exist (never auto-created) before use -- matching
        # a real environment where Phase 0.A has already provisioned it.
        client = FakeQdrantClient(existing_collection_names=["educopilot_chunks"])
        manager = _manager(client)  # configured (legacy) collection_name = team4b_shared_production_chunks

        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="ws-1", collection_name="educopilot_chunks",
        )

        assert client.search_calls[0]["collection_name"] == "educopilot_chunks"
        assert client.search_calls[0]["collection_name"] != "team4b_shared_production_chunks"
        # The legacy collection was never created as a side effect of
        # this canonical-only call.
        assert "team4b_shared_production_chunks" not in [c["collection_name"] for c in client.created_collections]


class TestCanonicalDocumentIdentityCorrection:
    """MVP M3 correction: document_id = permanent Team 4C File identity;
    job_id = individual ingestion attempt. `normalize_payload` must
    preserve the canonical document_id and never substitute job_id."""

    def test_1_canonical_document_id_is_preserved(self):
        payload = {"chunk_id": "c1", "job_id": "job-456", "document_id": "file-123"}
        normalized = normalize_payload(payload)
        assert normalized["document_id"] == "file-123"

    def test_2_job_id_is_not_substituted_for_document_id(self):
        payload = {"chunk_id": "c1", "job_id": "job-456", "document_id": "file-123"}
        normalized = normalize_payload(payload)
        assert normalized["document_id"] != normalized["job_id"]
        assert normalized["job_id"] == "job-456"

    def test_3_reingested_generations_retain_the_same_document_id(self):
        """Generation 1: document_id=file-123, job_id=job-1.
        Generation 2: document_id=file-123, job_id=job-2.
        Both must normalize with document_id=file-123, distinct job_ids."""

        gen1 = normalize_payload({"chunk_id": "c1", "job_id": "job-1", "document_id": "file-123"})
        gen2 = normalize_payload({"chunk_id": "c2", "job_id": "job-2", "document_id": "file-123"})

        assert gen1["document_id"] == "file-123"
        assert gen2["document_id"] == "file-123"
        assert gen1["document_id"] == gen2["document_id"]

    def test_4_job_id_remains_available_and_distinct_across_generations(self):
        gen1 = normalize_payload({"chunk_id": "c1", "job_id": "job-1", "document_id": "file-123"})
        gen2 = normalize_payload({"chunk_id": "c2", "job_id": "job-2", "document_id": "file-123"})

        assert gen1["job_id"] == "job-1"
        assert gen2["job_id"] == "job-2"
        assert gen1["job_id"] != gen2["job_id"]

    def test_5_vector_retrieval_returns_the_canonical_document_id(self):
        """search_similar's returned RetrievalResult.metadata carries the
        canonical document_id, end to end through a real (fake-Qdrant-backed) search."""

        client = FakeQdrantClient()
        client.search_results = [
            ScoredPoint(
                id="c1",
                version=0,
                score=0.9,
                payload={
                    "text": "t", "chunk_id": "c1", "job_id": "job-2",
                    "document_id": "file-123", "source_type": "pdf", "filename": "f.pdf", "page_number": 1,
                },
            )
        ]
        manager = _manager(client)

        results = manager.search_similar(query_vector=[0.1, 0.2], top_k=5, score_threshold=0.3, workspace_id="ws-1")

        assert results[0].metadata["document_id"] == "file-123"
        assert results[0].metadata["job_id"] == "job-2"

    def test_no_document_id_in_payload_is_honestly_absent_not_job_id(self):
        """A payload genuinely missing document_id (e.g. a stale/legacy
        record) must not have job_id silently substituted back in."""

        payload = {"chunk_id": "c1", "job_id": "job-456"}
        normalized = normalize_payload(payload)
        assert normalized.get("document_id") is None
        assert normalized["job_id"] == "job-456"


class TestM6CanonicalCollectionProvisioningIsolation:
    """MVP M6 pre-flight correction: the canonical query path must never
    auto-create or otherwise touch the legacy collection as a lazy-
    provisioning side effect, and must never silently proceed if the
    canonical collection is missing."""

    def test_canonical_search_never_creates_the_legacy_collection_as_a_side_effect(self):
        client = FakeQdrantClient(existing_collection_names=["educopilot_chunks"])
        manager = _manager(client)

        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="ws-1", collection_name="educopilot_chunks",
        )

        assert client.created_collections == []

    def test_missing_canonical_collection_fails_fast_without_creating_it(self):
        client = FakeQdrantClient(existing_collection_names=[])  # educopilot_chunks does NOT exist
        manager = _manager(client)

        with pytest.raises(VectorStoreConfigurationError, match="educopilot_chunks"):
            manager.search_similar(
                query_vector=[0.1], top_k=5, score_threshold=0.3,
                workspace_id="ws-1", collection_name="educopilot_chunks",
            )

        assert client.created_collections == []

    def test_incompatible_canonical_collection_fails_fast(self):
        client = FakeQdrantClient(existing_collection_names=["educopilot_chunks"], existing_vector_size=768)
        manager = _manager(client)  # configured for 384 dimensions

        with pytest.raises(VectorStoreConfigurationError, match="educopilot_chunks"):
            manager.search_similar(
                query_vector=[0.1], top_k=5, score_threshold=0.3,
                workspace_id="ws-1", collection_name="educopilot_chunks",
            )

    def test_legacy_collection_operations_are_completely_unaffected_by_this_correction(self):
        """upsert_chunk/delete_by_document (legacy-collection operations,
        no collection_name override) still trigger the FULL, unmodified
        ensure_collection() -- auto-creating the legacy collection if
        missing, exactly as before this correction."""

        client = FakeQdrantClient(existing_collection_names=[])
        manager = _manager(client)

        manager.upsert_chunk(ContextChunk(chunk_id="c1", text="t", embedding=[0.1], metadata={}))

        assert any(c["collection_name"] == "team4b_shared_production_chunks" for c in client.created_collections)

    def test_canonical_collection_is_verified_only_once_per_instance(self):
        client = FakeQdrantClient(existing_collection_names=["educopilot_chunks"])
        manager = _manager(client)

        get_collections_calls_before = 0

        original_get_collections = client.get_collections
        call_count = {"n": 0}

        def counting_get_collections():
            call_count["n"] += 1
            return original_get_collections()

        client.get_collections = counting_get_collections

        for _ in range(3):
            manager.search_similar(
                query_vector=[0.1], top_k=5, score_threshold=0.3,
                workspace_id="ws-1", collection_name="educopilot_chunks",
            )

        assert call_count["n"] == 1

    def test_legacy_and_canonical_collections_are_each_ensured_independently(self):
        """A manager that performs BOTH a legacy-collection write and a
        canonical-collection search must ensure/verify each of the two
        collections exactly once, independently -- neither short-
        circuits the other."""

        client = FakeQdrantClient(existing_collection_names=["educopilot_chunks"])
        manager = _manager(client)

        manager.upsert_chunk(ContextChunk(chunk_id="c1", text="t", embedding=[0.1], metadata={}))
        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="ws-1", collection_name="educopilot_chunks",
        )

        assert any(c["collection_name"] == "team4b_shared_production_chunks" for c in client.created_collections)
        assert not any(c["collection_name"] == "educopilot_chunks" for c in client.created_collections)


class TestM6DocumentIdsFilter:
    """MVP M6 document-level retrieval scope -- Qdrant filter construction."""

    def test_document_ids_adds_a_mandatory_condition_alongside_workspace(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="ws-1", document_ids=["doc-A", "doc-B"],
        )

        query_filter = client.search_calls[0]["query_filter"]
        keys = {c.key for c in query_filter.must}
        assert keys == {"workspace_id", "document_id"}
        document_condition = next(c for c in query_filter.must if c.key == "document_id")
        assert set(document_condition.match.any) == {"doc-A", "doc-B"}

    def test_document_ids_none_means_no_document_condition_at_all(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(query_vector=[0.1], top_k=5, score_threshold=0.3, workspace_id="ws-1", document_ids=None)

        query_filter = client.search_calls[0]["query_filter"]
        assert {c.key for c in query_filter.must} == {"workspace_id"}

    def test_empty_document_ids_short_circuits_without_querying_qdrant_at_all(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        results = manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3, workspace_id="ws-1", document_ids=[]
        )

        assert results == []
        assert client.search_calls == []

    def test_document_ids_combines_with_collection_filter_as_and(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="ws-1", collection_filter=["document"], document_ids=["doc-A"],
        )

        query_filter = client.search_calls[0]["query_filter"]
        keys = {c.key for c in query_filter.must}
        assert keys == {"workspace_id", "document_id", "source_type"}

    def test_workspace_condition_cannot_be_replaced_by_document_ids(self):
        client = FakeQdrantClient()
        manager = _manager(client)

        manager.search_similar(
            query_vector=[0.1], top_k=5, score_threshold=0.3,
            workspace_id="workspace-real", document_ids=["doc-belonging-to-another-workspace"],
        )

        query_filter = client.search_calls[0]["query_filter"]
        workspace_condition = next(c for c in query_filter.must if c.key == "workspace_id")
        assert workspace_condition.match.value == "workspace-real"
