"""Task 2.2 -- official Vector Store correctness properties P1-P3.

    Property 1: Context_Chunk storage round-trip
    Property 2: Document deletion completeness
    Property 3: Collection-scoped retrieval isolation

These are genuine property-based tests (Hypothesis), exercising
VectorStoreManager's own public methods (`ensure_collection`,
`upsert_chunk`/`upsert_batch`, `search_similar`, `delete_by_document`)
against `tests.fakes.InMemoryQdrantClient` -- a fake that genuinely
stores and queries data, not one that merely records calls (that fake,
`FakeQdrantClient` in `test_vector_store.py`, is for Task 2.1's own
control-flow tests and is not reused here, since these properties must
validate real store-then-retrieve behavior, not just argument-passing).

Every test below validates the properties against the ACTUAL approved
Team 4A -> Team 4B contract (docs/CONTRACT_DECISIONS.md): raw Team 4A
source_type vocabulary (pdf/mp4/youtube), the job_id-as-document_id
compatibility identity, and the approved read-side adapter -- not
implementation internals in isolation.
"""

from __future__ import annotations

from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.services.vector_store import ContextChunk, VectorStoreManager
from tests.fakes import InMemoryQdrantClient

# Keep property runs fast and deterministic-ish for CI; correctness, not
# performance, is what's under test here.
_HYPOTHESIS_SETTINGS = settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def _make_manager() -> tuple[VectorStoreManager, InMemoryQdrantClient]:
    client = InMemoryQdrantClient()
    # mypy note: pydantic-settings' `_env_file` init kwarg is only
    # recognized by the pydantic mypy plugin (not enabled in this
    # project); it is a genuine, supported runtime kwarg (already used
    # the same way in the approved Task 1.1/2.1 test suites), just not
    # visible to mypy's static stub for BaseSettings.__init__ without
    # that plugin. Suppressed narrowly here rather than enabling the
    # plugin project-wide as an out-of-scope Task 2.2 change.
    manager_settings = Settings(_env_file=None, vector_store_initial_backoff_seconds=0.001)  # type: ignore[call-arg]
    manager = VectorStoreManager(settings=manager_settings, qdrant_client=client, sleep_fn=lambda _s: None)
    manager.ensure_collection()
    return manager, client


# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

_chunk_id = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
_text = st.text(min_size=1, max_size=200)
_job_id = st.uuids().map(str)
_document_id = st.uuids().map(str)
_filename = st.text(min_size=1, max_size=40).filter(lambda s: s.strip() != "")
_embedding = st.lists(
    st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False), min_size=3, max_size=3
)
_page_number = st.integers(min_value=1, max_value=5000)
_timestamp = st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)
_heading = st.fixed_dictionaries({"text": st.text(min_size=1, max_size=20), "level": st.integers(min_value=1, max_value=5)})
_headings_list = st.lists(_heading, max_size=4)


@st.composite
def _pdf_chunk_kwargs(draw: Any) -> dict[str, Any]:
    return {
        "chunk_id": draw(_chunk_id),
        "text": draw(_text),
        "embedding": draw(_embedding),
        "job_id": draw(_job_id),
        "document_id": draw(_document_id),
        "filename": draw(_filename),
        "page_number": draw(_page_number),
        "headings": draw(_headings_list),
    }


@st.composite
def _mp4_chunk_kwargs(draw: Any) -> dict[str, Any]:
    start = draw(_timestamp)
    end = start + draw(st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False))
    return {
        "chunk_id": draw(_chunk_id),
        "text": draw(_text),
        "embedding": draw(_embedding),
        "job_id": draw(_job_id),
        "document_id": draw(_document_id),
        "filename": draw(_filename),
        "start_timestamp": start,
        "end_timestamp": end,
    }


@st.composite
def _youtube_chunk_kwargs(draw: Any, *, omit_end_timestamp: bool) -> dict[str, Any]:
    start = draw(_timestamp)
    duration = draw(st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False))
    kwargs: dict[str, Any] = {
        "chunk_id": draw(_chunk_id),
        "text": draw(_text),
        "embedding": draw(_embedding),
        "job_id": draw(_job_id),
        "document_id": draw(_document_id),
        "video_title": draw(_filename),
        "start_timestamp": start,
        "duration": duration,
    }
    if not omit_end_timestamp:
        kwargs["end_timestamp"] = draw(_timestamp)
    return kwargs


def _pdf_chunk(kwargs: dict[str, Any]) -> ContextChunk:
    return ContextChunk(
        chunk_id=kwargs["chunk_id"],
        text=kwargs["text"],
        embedding=kwargs["embedding"],
        metadata={
            "job_id": kwargs["job_id"],
            "document_id": kwargs.get("document_id", "doc-1"),
            "workspace_id": kwargs.get("workspace_id", "ws-1"),
            "source_type": "pdf",
            "filename": kwargs["filename"],
            "page_number": kwargs["page_number"],
            "headings": kwargs["headings"],
        },
    )


def _mp4_chunk(kwargs: dict[str, Any]) -> ContextChunk:
    return ContextChunk(
        chunk_id=kwargs["chunk_id"],
        text=kwargs["text"],
        embedding=kwargs["embedding"],
        metadata={
            "job_id": kwargs["job_id"],
            "document_id": kwargs.get("document_id", "doc-1"),
            "workspace_id": kwargs.get("workspace_id", "ws-1"),
            "source_type": "mp4",
            "filename": kwargs["filename"],
            "start_timestamp": kwargs["start_timestamp"],
            "end_timestamp": kwargs["end_timestamp"],
        },
    )


def _youtube_chunk(kwargs: dict[str, Any]) -> ContextChunk:
    metadata: dict[str, Any] = {
        "job_id": kwargs["job_id"],
        "document_id": kwargs.get("document_id", "doc-1"),
        "workspace_id": kwargs.get("workspace_id", "ws-1"),
        "source_type": "youtube",
        "video_title": kwargs["video_title"],
        "start_timestamp": kwargs["start_timestamp"],
        "duration": kwargs["duration"],
    }
    if "end_timestamp" in kwargs:
        metadata["end_timestamp"] = kwargs["end_timestamp"]
    return ContextChunk(chunk_id=kwargs["chunk_id"], text=kwargs["text"], embedding=kwargs["embedding"], metadata=metadata)


def _find_result(results: list[Any], chunk_id: str) -> Any:
    matches = [r for r in results if r.chunk_id == chunk_id]
    assert len(matches) == 1, f"expected exactly one result for chunk_id={chunk_id!r}, found {len(matches)}"
    return matches[0]


# ---------------------------------------------------------------------------
# Property 1: Context_Chunk storage round-trip
#
# "For any valid Context_Chunk with arbitrary text content and metadata,
#  storing it in the Vector_Store and then retrieving it by chunk_id
#  SHALL return identical text, embedding vector, document_id,
#  page_number, timestamp, and chunk_id." (Validates Requirement 1.1)
#
# LIMITATION, documented rather than silently worked around: the official
# `RetrievalResult` dataclass (returned by `search_similar`, Task 1.2's
# only fully-specified model Task 2.1 depends on) does not itself carry
# the raw embedding vector -- only chunk_id/text/relevance_score/metadata.
# There is therefore no VectorStoreManager *read* method whose public
# return type could ever expose "the embedding vector" for direct
# comparison. To still validate the vector genuinely round-trips through
# the Vector_Store (not just through search_similar's narrower return
# type), these tests use `InMemoryQdrantClient.all_points()` -- a
# test-only introspection helper into the fake's storage -- to confirm
# the persisted vector matches exactly what was upserted, in addition to
# validating every other field through VectorStoreManager's real
# `search_similar` path.
# ---------------------------------------------------------------------------


class TestPropertyOneStorageRoundTrip:
    @_HYPOTHESIS_SETTINGS
    @given(kwargs=_pdf_chunk_kwargs())
    def test_pdf_chunk_round_trip(self, kwargs: dict[str, Any]) -> None:
        manager, client = _make_manager()
        chunk = _pdf_chunk(kwargs)

        manager.upsert_chunk(chunk)

        # Vector round-trip, via direct storage introspection (see class docstring limitation note).
        stored_points = client.all_points(manager._collection_name)
        assert len(stored_points) == 1
        (stored,) = stored_points.values()
        assert stored["vector"] == chunk.embedding

        # Everything else, via VectorStoreManager's real read path.
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, chunk.chunk_id)

        assert result.text == chunk.text
        assert result.metadata["document_id"] == kwargs["document_id"]
        assert result.metadata["job_id"] == kwargs["job_id"]  # both preserved, distinctly
        assert result.metadata["page_number"] == kwargs["page_number"]
        assert result.metadata["source_type"] == "document"  # normalized from pdf

    @_HYPOTHESIS_SETTINGS
    @given(kwargs=_mp4_chunk_kwargs())
    def test_mp4_chunk_round_trip(self, kwargs: dict[str, Any]) -> None:
        manager, client = _make_manager()
        chunk = _mp4_chunk(kwargs)

        manager.upsert_chunk(chunk)

        stored_points = client.all_points(manager._collection_name)
        (stored,) = stored_points.values()
        assert stored["vector"] == chunk.embedding

        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, chunk.chunk_id)

        assert result.text == chunk.text
        assert result.metadata["document_id"] == kwargs["document_id"]
        assert result.metadata["job_id"] == kwargs["job_id"]  # both preserved, distinctly
        assert result.metadata["start_timestamp"] == kwargs["start_timestamp"]
        assert result.metadata["end_timestamp"] == kwargs["end_timestamp"]
        assert result.metadata["source_type"] == "video"  # normalized from mp4

    @_HYPOTHESIS_SETTINGS
    @given(kwargs=_youtube_chunk_kwargs(omit_end_timestamp=False))
    def test_youtube_chunk_round_trip_with_explicit_end_timestamp(self, kwargs: dict[str, Any]) -> None:
        manager, _client = _make_manager()
        chunk = _youtube_chunk(kwargs)

        manager.upsert_chunk(chunk)
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, chunk.chunk_id)

        assert result.metadata["document_id"] == kwargs["document_id"]
        assert result.metadata["job_id"] == kwargs["job_id"]  # both preserved, distinctly
        assert result.metadata["start_timestamp"] == kwargs["start_timestamp"]
        # end_timestamp was explicitly provided -- must be returned as-is,
        # never overwritten by the start+duration fallback, even when it
        # happens to be 0.0 (edge case explicitly required: never treat
        # 0.0 as missing).
        assert result.metadata["end_timestamp"] == kwargs["end_timestamp"]
        assert result.metadata["source_type"] == "video"  # normalized from youtube
        assert result.metadata["document_title"] == kwargs["video_title"]

    @_HYPOTHESIS_SETTINGS
    @given(kwargs=_youtube_chunk_kwargs(omit_end_timestamp=True))
    def test_youtube_chunk_round_trip_with_missing_end_timestamp_falls_back(self, kwargs: dict[str, Any]) -> None:
        manager, _client = _make_manager()
        chunk = _youtube_chunk(kwargs)

        manager.upsert_chunk(chunk)
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, chunk.chunk_id)

        # Approved fallback: start_timestamp + per-segment duration,
        # applied because end_timestamp was genuinely absent.
        assert result.metadata["end_timestamp"] == kwargs["start_timestamp"] + kwargs["duration"]

    def test_youtube_zero_start_timestamp_edge_case(self) -> None:
        """Explicit non-Hypothesis example: start_timestamp=0.0 must
        still be used (not treated as missing) when computing the
        fallback end_timestamp."""

        manager, _client = _make_manager()
        chunk = ContextChunk(
            chunk_id="edge-1",
            text="segment at the very start",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "job_id": "job-edge-1",
                "workspace_id": "ws-1",
                "source_type": "youtube",
                "video_title": "Edge Case Video",
                "start_timestamp": 0.0,
                "duration": 12.0,
            },
        )

        manager.upsert_chunk(chunk)
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, "edge-1")

        assert result.metadata["start_timestamp"] == 0.0
        assert result.metadata["end_timestamp"] == 12.0

    def test_youtube_zero_end_timestamp_edge_case(self) -> None:
        """Explicit non-Hypothesis example: an explicit end_timestamp=0.0
        must be preserved exactly, never recomputed as if it were
        missing."""

        manager, _client = _make_manager()
        chunk = ContextChunk(
            chunk_id="edge-2",
            text="degenerate zero-length segment",
            embedding=[1.0, 0.0, 0.0],
            metadata={
                "job_id": "job-edge-2",
                "workspace_id": "ws-1",
                "source_type": "youtube",
                "video_title": "Edge Case Video 2",
                "start_timestamp": 0.0,
                "duration": 5.0,
                "end_timestamp": 0.0,
            },
        )

        manager.upsert_chunk(chunk)
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, "edge-2")

        assert result.metadata["end_timestamp"] == 0.0  # not recomputed to 5.0

    def test_metadata_not_explicitly_asserted_is_still_preserved(self) -> None:
        """Property 1 names specific fields, but the round-trip must not
        silently drop other captured metadata (e.g. headings) either."""

        manager, _client = _make_manager()
        chunk = ContextChunk(
            chunk_id="pres-1",
            text="body",
            embedding=[0.5, 0.5, 0.0],
            metadata={
                "job_id": "job-pres-1",
                "workspace_id": "ws-1",
                "source_type": "pdf",
                "filename": "manual.pdf",
                "page_number": 9,
                "headings": [{"text": "Setup", "level": 1}, {"text": "Sub", "level": 2}],
            },
        )

        manager.upsert_chunk(chunk)
        results = manager.search_similar(query_vector=chunk.embedding, top_k=10, score_threshold=0.0, workspace_id="ws-1")
        result = _find_result(results, "pres-1")

        assert result.metadata["headings"] == [{"text": "Setup", "level": 1}, {"text": "Sub", "level": 2}]
        assert result.metadata["section_heading"] == "Setup"  # adapter-derived, alongside the raw list


# ---------------------------------------------------------------------------
# Property 2: Document deletion completeness
#
# "For any document_id associated with N Context_Chunks in the
#  Vector_Store, after a deletion request for that document_id, querying
#  the Vector_Store for that document_id SHALL return zero results."
#  (Validates Requirement 1.6)
#
# APPROVED CONTRACT INTERPRETATION, asserted explicitly by these tests,
# not merely assumed:
#   Team 4B document_id := Team 4A job_id (docs/CONTRACT_DECISIONS.md #1)
#   "This identifies an ingestion event rather than a persistent document
#    across re-ingestion."
# The tests below therefore delete by job_id (never by filename or any
# other proxy for "the same file"), and explicitly verify that a
# different job_id -- even one representing what a human would call a
# re-ingested copy of the same file (same filename, different job_id) --
# is NOT deleted. This is the ingestion-scoped guarantee actually being
# implemented; it is deliberately NOT a "delete this file everywhere"
# guarantee, and these tests would fail (correctly) if the implementation
# ever tried to be "smarter" about that.
# ---------------------------------------------------------------------------


class TestPropertyTwoDeletionCompleteness:
    @_HYPOTHESIS_SETTINGS
    @given(
        target_job_id=_job_id,
        other_job_id=_job_id,
        target_chunks=st.lists(_pdf_chunk_kwargs(), min_size=1, max_size=6),
        other_chunks=st.lists(_pdf_chunk_kwargs(), min_size=1, max_size=6),
    )
    def test_deleting_by_job_id_removes_exactly_that_jobs_chunks(
        self,
        target_job_id: str,
        other_job_id: str,
        target_chunks: list[dict[str, Any]],
        other_chunks: list[dict[str, Any]],
    ) -> None:
        if target_job_id == other_job_id:
            other_job_id = other_job_id + "-distinct"  # Hypothesis can otherwise draw equal UUID strings by chance

        manager, client = _make_manager()

        target_context_chunks = []
        for i, kwargs in enumerate(target_chunks):
            kwargs = {**kwargs, "job_id": target_job_id, "chunk_id": f"target-{i}-{kwargs['chunk_id']}"}
            target_context_chunks.append(_pdf_chunk(kwargs))

        other_context_chunks = []
        for i, kwargs in enumerate(other_chunks):
            kwargs = {**kwargs, "job_id": other_job_id, "chunk_id": f"other-{i}-{kwargs['chunk_id']}"}
            other_context_chunks.append(_pdf_chunk(kwargs))

        manager.upsert_batch(target_context_chunks + other_context_chunks)

        # This *is* "the approved document_id := job_id mapping", exercised directly.
        manager.delete_by_document(document_id=target_job_id)

        remaining = client.all_points(manager._collection_name)
        remaining_job_ids = {point["payload"]["job_id"] for point in remaining.values()}

        # Completeness: zero chunks remain for the deleted job_id.
        assert target_job_id not in remaining_job_ids
        # No over-deletion: every other job's chunks are untouched.
        assert other_job_id in remaining_job_ids
        assert len(remaining) == len(other_context_chunks)

    def test_ingestion_scoped_identity_does_not_delete_reingested_copies(self) -> None:
        """Explicit, non-Hypothesis test of the documented limitation:
        two ingestion events of what a human would call "the same file"
        (identical filename) get different job_ids, and deleting one does
        NOT delete the other. This is the approved, documented behavior
        -- not a bug -- per docs/CONTRACT_DECISIONS.md item 1.
        """

        manager, client = _make_manager()

        first_ingestion = ContextChunk(
            chunk_id="v1-chunk",
            text="original version",
            embedding=[1.0, 0.0, 0.0],
            metadata={"job_id": "job-v1", "source_type": "pdf", "filename": "syllabus.pdf", "page_number": 1},
        )
        second_ingestion = ContextChunk(
            chunk_id="v2-chunk",
            text="re-uploaded version",
            embedding=[0.0, 1.0, 0.0],
            metadata={"job_id": "job-v2", "source_type": "pdf", "filename": "syllabus.pdf", "page_number": 1},
        )
        manager.upsert_batch([first_ingestion, second_ingestion])

        manager.delete_by_document(document_id="job-v1")

        remaining = client.all_points(manager._collection_name)
        remaining_chunk_ids = {point["payload"]["chunk_id"] for point in remaining.values()}

        assert remaining_chunk_ids == {"v2-chunk"}  # same filename, different job_id -- survives, by design

    def test_delete_by_document_with_no_matching_chunks_is_a_noop(self) -> None:
        manager, client = _make_manager()
        chunk = ContextChunk(
            chunk_id="c1", text="t", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "job-a", "source_type": "pdf"}
        )
        manager.upsert_chunk(chunk)

        manager.delete_by_document(document_id="job-does-not-exist")

        remaining = client.all_points(manager._collection_name)
        assert len(remaining) == 1  # untouched


# ---------------------------------------------------------------------------
# Property 3: Collection-scoped retrieval isolation
#
# "For any query executed with a collection_filter, all returned
#  Context_Chunks SHALL belong exclusively to the specified
#  collection(s), and no chunks from other collections SHALL appear in
#  results." (Validates Requirements 1.4, 7.4)
#
# APPROVED CONTRACT: "collection(s)" is implemented as payload-filtered
# scopes (`source_type`, normalized to Team 4B's "document"/"video"
# vocabulary) within the single shared production collection -- not
# multiple physical Qdrant collections (Final Checkpoint §F). These tests
# validate isolation under that approved interpretation specifically.
# ---------------------------------------------------------------------------


class TestPropertyThreeCollectionScopedIsolation:
    @_HYPOTHESIS_SETTINGS
    @given(
        pdf_chunks=st.lists(_pdf_chunk_kwargs(), min_size=1, max_size=5),
        mp4_chunks=st.lists(_mp4_chunk_kwargs(), min_size=1, max_size=5),
    )
    def test_document_filter_excludes_video_chunks(
        self, pdf_chunks: list[dict[str, Any]], mp4_chunks: list[dict[str, Any]]
    ) -> None:
        manager, _client = _make_manager()

        pdf_context_chunks = [_pdf_chunk({**kwargs, "chunk_id": f"pdf-{i}"}) for i, kwargs in enumerate(pdf_chunks)]
        mp4_context_chunks = [_mp4_chunk({**kwargs, "chunk_id": f"mp4-{i}"}) for i, kwargs in enumerate(mp4_chunks)]
        manager.upsert_batch(pdf_context_chunks + mp4_context_chunks)

        results = manager.search_similar(
            # score_threshold=-1.0: cosine similarity is bounded to
            # [-1.0, 1.0], so this guarantees no chunk is excluded on
            # relevance grounds -- this test is about collection_filter
            # isolation specifically, not about relevance scoring, and
            # must not be sensitive to Hypothesis-generated embeddings
            # that happen to be dissimilar to the fixed query vector.
            query_vector=[0.1, 0.1, 0.1], top_k=50, score_threshold=-1.0, collection_filter=["document"]
        , workspace_id="ws-1")

        assert len(results) == len(pdf_context_chunks)  # every pdf chunk, and nothing else
        assert {r.chunk_id for r in results} == {c.chunk_id for c in pdf_context_chunks}
        for result in results:
            assert result.metadata["source_type"] == "document"  # never "video" leaking through

    @_HYPOTHESIS_SETTINGS
    @given(
        pdf_chunks=st.lists(_pdf_chunk_kwargs(), min_size=1, max_size=5),
        mp4_chunks=st.lists(_mp4_chunk_kwargs(), min_size=1, max_size=5),
        youtube_chunks=st.lists(_youtube_chunk_kwargs(omit_end_timestamp=False), min_size=1, max_size=5),
    )
    def test_video_filter_includes_both_mp4_and_youtube_but_excludes_pdf(
        self,
        pdf_chunks: list[dict[str, Any]],
        mp4_chunks: list[dict[str, Any]],
        youtube_chunks: list[dict[str, Any]],
    ) -> None:
        manager, _client = _make_manager()

        pdf_context_chunks = [_pdf_chunk({**kwargs, "chunk_id": f"pdf-{i}"}) for i, kwargs in enumerate(pdf_chunks)]
        mp4_context_chunks = [_mp4_chunk({**kwargs, "chunk_id": f"mp4-{i}"}) for i, kwargs in enumerate(mp4_chunks)]
        youtube_context_chunks = [
            _youtube_chunk({**kwargs, "chunk_id": f"yt-{i}"}) for i, kwargs in enumerate(youtube_chunks)
        ]
        manager.upsert_batch(pdf_context_chunks + mp4_context_chunks + youtube_context_chunks)

        results = manager.search_similar(
            query_vector=[0.1, 0.1, 0.1], top_k=50, score_threshold=-1.0, collection_filter=["video"]
        , workspace_id="ws-1")

        expected_ids = {c.chunk_id for c in mp4_context_chunks} | {c.chunk_id for c in youtube_context_chunks}
        assert {r.chunk_id for r in results} == expected_ids
        pdf_ids = {c.chunk_id for c in pdf_context_chunks}
        assert pdf_ids.isdisjoint({r.chunk_id for r in results})  # no PDF chunk leaks into the video scope
        for result in results:
            assert result.metadata["source_type"] == "video"

    def test_no_filter_returns_chunks_from_every_scope(self) -> None:
        """Sanity check on the isolation property's own precondition: an
        UNfiltered query must still see everything -- isolation is a
        property of applying a filter, not of the collection being
        inherently partitioned at storage time.
        """

        manager, _client = _make_manager()
        pdf_chunk = _pdf_chunk(
            {
                "chunk_id": "pdf-x",
                "text": "pdf text",
                "embedding": [0.1, 0.1, 0.1],
                "job_id": "job-pdf-x",
                "filename": "notes.pdf",
                "page_number": 1,
                "headings": [],
            }
        )
        mp4_chunk = _mp4_chunk(
            {
                "chunk_id": "mp4-x",
                "text": "video text",
                "embedding": [0.2, 0.2, 0.2],
                "job_id": "job-mp4-x",
                "filename": "clip.mp4",
                "start_timestamp": 1.0,
                "end_timestamp": 2.0,
            }
        )
        manager.upsert_batch([pdf_chunk, mp4_chunk])

        results = manager.search_similar(query_vector=[0.1, 0.1, 0.1], top_k=50, score_threshold=0.0, workspace_id="ws-1")

        assert {r.chunk_id for r in results} == {"pdf-x", "mp4-x"}
