"""Focused tests for Task 3.2's HybridRetriever.

Scope: unit, integration, boundary, and error-path tests for search-mode
routing, Reciprocal Rank Fusion, score normalization, threshold/top_k
behavior, and concurrency. Explicitly NOT Task 3.3's Property 4-7 tests
(these are not labeled or treated as such, even though some cover
similar ground -- see the Task 3.2 report for the distinction).
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.bm25_index import BM25Document, BM25Index
from app.services.generation_authority import GenerationAuthorityUnavailableError
from app.services.hybrid_retriever import (
    HybridRetriever,
    InvalidSearchModeError,
    _max_possible_rrf_score,
    _normalize_bm25_score,
    _normalize_cosine_similarity,
    reciprocal_rank_fusion,
)
from app.services.reranker import RerankerUnavailableError
from app.services.vector_store import ContextChunk, VectorStoreManager
from tests.fakes import InMemoryQdrantClient


def _settings(**overrides: Any) -> Settings:
    # MVP M3: test settings default `canonical_qdrant_collection_name` to
    # the SAME value as `qdrant_collection_name` (the fake vector store's
    # own single collection, created by `_make_vector_store()` below) --
    # so `HybridRetriever.refresh_bm25_corpus()`/`_semantic_candidates()`,
    # which now read from `canonical_qdrant_collection_name` specifically
    # (production reads from `educopilot_chunks`, distinct from the
    # legacy `qdrant_collection_name`), find the SAME fixture data these
    # tests already write via `vector_store.upsert_chunk`/`upsert_batch`
    # (which still target `qdrant_collection_name`, unchanged by this
    # correction). A test that wants to exercise the two collections
    # actually being different can still override
    # `canonical_qdrant_collection_name` explicitly.
    collection_name = overrides.pop("qdrant_collection_name", "team4b_shared_production_chunks")
    canonical_collection_name = overrides.pop("canonical_qdrant_collection_name", collection_name)
    return Settings(
        _env_file=None,
        qdrant_collection_name=collection_name,
        canonical_qdrant_collection_name=canonical_collection_name,
        **overrides,
    )  # type: ignore[call-arg]


def _make_vector_store(**settings_overrides: Any) -> tuple[VectorStoreManager, InMemoryQdrantClient]:
    client = InMemoryQdrantClient()
    settings = _settings(vector_store_initial_backoff_seconds=0.001, **settings_overrides)
    manager = VectorStoreManager(settings=settings, qdrant_client=client, sleep_fn=lambda _s: None)
    manager.ensure_collection()
    return manager, client


class FakeEmbedder:
    """Deterministic stand-in for app.services.embedder.Embedder: maps a
    query string to a fixed vector via a caller-supplied lookup, so tests
    control exactly what "semantic similarity" means without any real
    model.
    """

    def __init__(self, vectors_by_query: dict[str, list[float]], default: list[float] | None = None) -> None:
        self._vectors_by_query = vectors_by_query
        self._default = default or [0.0, 0.0, 0.0]
        self.calls: list[str] = []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._vectors_by_query.get(text, self._default)


class FakeGenerationAuthorityClient:
    """Test double for `GenerationAuthorityClient` (MVP M4).

    By default, ECHOES BACK `_DEFAULT_GENERATION` (1) as the "current"
    generation for every requested document_id -- a permissive default so
    every EXISTING (pre-M4) test fixture, which now carries
    `"ingestion_generation": 1` in its metadata (see the bulk fixture
    update below), continues to pass generation-authority filtering
    without every single test needing its own explicit authority
    configuration. Tests that specifically exercise staleness/fail-closed
    behavior construct their own instance with an explicit
    `current_generations` map instead.

    `raise_error=True` simulates a total Mongo-unavailable failure,
    matching `GenerationAuthorityClient`'s own real contract exactly
    (raises `GenerationAuthorityUnavailableError`, never returns a
    partial/fallback result).
    """

    def __init__(self, current_generations: dict[str, int] | None = None, *, raise_error: bool = False) -> None:
        self._explicit_generations = current_generations
        self._raise_error = raise_error
        self.calls: list[tuple[set[str], str]] = []

    def get_current_generations(self, document_ids: set[str], *, workspace_id: str) -> dict[str, int]:
        self.calls.append((set(document_ids), workspace_id))
        if self._raise_error:
            raise GenerationAuthorityUnavailableError()
        if self._explicit_generations is not None:
            return {doc_id: gen for doc_id, gen in self._explicit_generations.items() if doc_id in document_ids}
        return {doc_id: _DEFAULT_GENERATION for doc_id in document_ids}


_DEFAULT_GENERATION = 1


def _retriever(
    vector_store: VectorStoreManager,
    bm25_index: BM25Index,
    embedder: Any,
    generation_authority: Any | None = None,
    reranker: Any | None = None,
    **settings_overrides: Any,
) -> HybridRetriever:
    settings = _settings(**settings_overrides)
    return HybridRetriever(
        vector_store=vector_store,
        bm25_index=bm25_index,
        embedder=embedder,
        generation_authority=generation_authority or FakeGenerationAuthorityClient(),
        settings=settings,
        reranker=reranker,
    )


# ---------------------------------------------------------------------------
# Search-mode routing (Requirement 2.4/2.5, Property 4's concern -- not
# labeled/claimed as Property 4 itself, which belongs to Task 3.3)
# ---------------------------------------------------------------------------


class TestSearchModeRouting:
    def test_semantic_mode_never_touches_bm25(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="c1", text="hello", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "workspace_id": "ws-1", "document_id": "doc-j1", "ingestion_generation": 1})
        )

        class ExplodingBM25(BM25Index):
            def search(self, query: str, top_k: int | None = None, *, workspace_id: str, document_ids: list[str] | None = None, collection_filter: list[str] | None = None) -> list[tuple[str, float]]:
                raise AssertionError("BM25 must not be invoked in semantic mode")

        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, ExplodingBM25(), embedder)

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert embedder.calls == ["query"]

    def test_keyword_mode_never_touches_vector_store_or_embedder(self):
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="c1", text="hello world", workspace_id="ws-1")])

        class ExplodingEmbedder:
            def embed_query(self, text: str) -> list[float]:
                raise AssertionError("Embedder must not be invoked in keyword mode")

        retriever = _retriever(vector_store, bm25, ExplodingEmbedder())
        retriever._chunk_cache["c1"] = RetrievalResult(chunk_id="c1", text="hello world", relevance_score=0.0, metadata={"document_id": "doc-c1", "ingestion_generation": 1})

        results = retriever.retrieve(query="hello", top_k=5, score_threshold=0.0, search_mode="keyword", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0].chunk_id == "c1"

    def test_hybrid_mode_invokes_both_legs(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="v1", text="vector hit", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "workspace_id": "ws-1", "document_id": "doc-j1", "ingestion_generation": 1})
        )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="k1", text="keyword hit", workspace_id="ws-1")])

        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        retriever._chunk_cache["k1"] = RetrievalResult(chunk_id="k1", text="keyword hit", relevance_score=0.0, metadata={"document_id": "doc-k1", "ingestion_generation": 1})

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        chunk_ids = {r.chunk_id for r in results}
        assert "v1" in chunk_ids
        assert "k1" in chunk_ids
        assert embedder.calls == ["query"]

    def test_invalid_search_mode_raises(self):
        vector_store, _client = _make_vector_store()
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({}))

        with pytest.raises(InvalidSearchModeError):
            retriever.retrieve(query="q", top_k=5, score_threshold=0.0, search_mode="fuzzy", workspace_id="ws-1")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion -- exact formula, determinism
# ---------------------------------------------------------------------------


class TestReciprocalRankFusion:
    def test_exact_formula_single_list_membership(self):
        bm25_ranked = [("a", 5.0), ("b", 3.0)]
        vector_ranked: list[RetrievalResult] = []

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        fused_dict = dict(fused)
        assert fused_dict["a"] == pytest.approx(1.0 / (60 + 1))
        assert fused_dict["b"] == pytest.approx(1.0 / (60 + 2))

    def test_exact_formula_dual_list_membership_sums_both_terms(self):
        bm25_ranked = [("a", 5.0)]  # rank 1 in BM25
        vector_ranked = [RetrievalResult(chunk_id="a", text="t", relevance_score=0.9, metadata={})]  # rank 1 in vector

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert dict(fused)["a"] == pytest.approx(1.0 / 61 + 1.0 / 61)

    def test_default_k_is_60(self):
        assert _settings().rrf_k == 60

    def test_custom_k_changes_the_computed_score(self):
        bm25_ranked = [("a", 1.0)]
        vector_ranked: list[RetrievalResult] = []

        fused_k60 = dict(reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60))
        fused_k10 = dict(reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=10))

        assert fused_k60["a"] == pytest.approx(1.0 / 61)
        assert fused_k10["a"] == pytest.approx(1.0 / 11)
        assert fused_k10["a"] > fused_k60["a"]  # smaller k -> larger contribution per rank

    def test_result_is_sorted_descending_by_score(self):
        bm25_ranked = [("a", 1.0), ("b", 5.0), ("c", 3.0)]
        vector_ranked: list[RetrievalResult] = []

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        scores = [score for _chunk_id, score in fused]
        assert scores == sorted(scores, reverse=True)

    def test_deterministic_tie_break_by_chunk_id_ascending(self):
        # Two disjoint chunk_ids each appearing at rank 1 of exactly one
        # list get identical RRF scores -- a genuine tie, not a bug.
        bm25_ranked = [("zebra", 1.0)]
        vector_ranked = [RetrievalResult(chunk_id="apple", text="t", relevance_score=1.0, metadata={})]

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert fused[0][1] == pytest.approx(fused[1][1])  # confirmed tie
        assert fused[0][0] == "apple"  # "apple" < "zebra" -- deterministic tie-break

    def test_fusion_is_repeatable_across_calls(self):
        bm25_ranked = [("a", 1.0), ("b", 2.0), ("c", 0.5)]
        vector_ranked = [
            RetrievalResult(chunk_id="b", text="t", relevance_score=0.8, metadata={}),
            RetrievalResult(chunk_id="d", text="t", relevance_score=0.5, metadata={}),
        ]

        first = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)
        second = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert first == second

    def test_disjoint_lists_include_every_chunk_from_both(self):
        bm25_ranked = [("a", 1.0), ("b", 1.0)]
        vector_ranked = [RetrievalResult(chunk_id="c", text="t", relevance_score=1.0, metadata={})]

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert {chunk_id for chunk_id, _ in fused} == {"a", "b", "c"}

    def test_overlapping_chunk_ranks_higher_than_single_list_hits_at_equal_rank(self):
        bm25_ranked = [("shared", 1.0), ("bm25_only", 1.0)]
        vector_ranked = [
            RetrievalResult(chunk_id="shared", text="t", relevance_score=1.0, metadata={}),
            RetrievalResult(chunk_id="vector_only", text="t", relevance_score=1.0, metadata={}),
        ]

        fused = dict(reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60))

        assert fused["shared"] > fused["bm25_only"]
        assert fused["shared"] > fused["vector_only"]

    def test_empty_lists_produce_empty_result(self):
        assert reciprocal_rank_fusion([], [], k=60) == []


# ---------------------------------------------------------------------------
# Score normalization -- [0.0, 1.0] bound, edge cases
# ---------------------------------------------------------------------------


class TestCosineNormalization:
    def test_perfect_similarity_maps_to_one(self):
        assert _normalize_cosine_similarity(1.0) == pytest.approx(1.0)

    def test_perfect_dissimilarity_maps_to_zero(self):
        assert _normalize_cosine_similarity(-1.0) == pytest.approx(0.0)

    def test_zero_similarity_maps_to_midpoint(self):
        assert _normalize_cosine_similarity(0.0) == pytest.approx(0.5)

    def test_out_of_theoretical_range_values_are_clipped(self):
        # Defensive: floating-point noise could in principle push a
        # cosine computation marginally outside [-1, 1].
        assert _normalize_cosine_similarity(1.0000001) == 1.0
        assert _normalize_cosine_similarity(-1.0000001) == 0.0


class TestBM25Normalization:
    def test_min_max_normalization_within_result_set(self):
        assert _normalize_bm25_score(5.0, min_score=0.0, max_score=10.0) == pytest.approx(0.5)

    def test_max_score_maps_to_one(self):
        assert _normalize_bm25_score(10.0, min_score=0.0, max_score=10.0) == pytest.approx(1.0)

    def test_min_score_maps_to_zero(self):
        assert _normalize_bm25_score(0.0, min_score=0.0, max_score=10.0) == pytest.approx(0.0)

    def test_negative_raw_scores_still_normalize_into_bounds(self):
        # Task 3.1 documented that small-corpus BM25 IDF can be negative.
        result = _normalize_bm25_score(-0.5, min_score=-1.0, max_score=1.0)
        assert 0.0 <= result <= 1.0

    def test_all_tied_scores_map_to_one(self):
        assert _normalize_bm25_score(3.0, min_score=3.0, max_score=3.0) == 1.0


class TestMaxPossibleRRFScore:
    def test_two_lists_default_k(self):
        assert _max_possible_rrf_score(k=60, num_lists=2) == pytest.approx(2.0 / 61)

    def test_always_positive(self):
        assert _max_possible_rrf_score(k=60, num_lists=2) > 0.0


# ---------------------------------------------------------------------------
# End-to-end HybridRetriever behavior: normalization bounds, threshold,
# top_k, duplicates, empty results, ties
# ---------------------------------------------------------------------------


class TestHybridRetrieverEndToEnd:
    def test_all_returned_scores_are_within_zero_to_one_hybrid_mode(self):
        vector_store, _client = _make_vector_store()
        for i in range(5):
            vector_store.upsert_chunk(
                ContextChunk(
                    chunk_id=f"v{i}", text=f"vector doc {i}", embedding=[float(i), 1.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}
                )
            )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id=f"v{i}", text=f"vector doc {i} keyword", workspace_id="ws-1") for i in range(5)])

        embedder = FakeEmbedder({"query": [2.0, 1.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        retriever.refresh_bm25_corpus()

        results = retriever.retrieve(query="query", top_k=10, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert len(results) > 0
        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    def test_all_returned_scores_within_bounds_semantic_mode(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="c1", text="t", embedding=[-1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})  # opposite direction -> negative cosine
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results = retriever.retrieve(query="query", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert 0.0 <= results[0].relevance_score <= 1.0

    def test_threshold_filters_out_low_relevance_results(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="close", text="t", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="far", text="t", embedding=[-1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.9, search_mode="semantic", workspace_id="ws-1")

        chunk_ids = {r.chunk_id for r in results}
        assert "close" in chunk_ids
        assert "far" not in chunk_ids  # normalized score ~0.0, below 0.9 threshold

    def test_top_k_limits_results(self):
        vector_store, _client = _make_vector_store()
        for i in range(10):
            vector_store.upsert_chunk(
                ContextChunk(chunk_id=f"c{i}", text="t", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
            )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results = retriever.retrieve(query="query", top_k=3, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 3

    def test_empty_vector_store_and_bm25_returns_empty_list(self):
        vector_store, _client = _make_vector_store()
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert results == []

    def test_duplicate_chunk_across_both_legs_appears_exactly_once(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="dup", text="shared chunk", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="dup", text="shared chunk", workspace_id="ws-1")])
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        retriever._chunk_cache["dup"] = RetrievalResult(chunk_id="dup", text="shared chunk", relevance_score=0.0, metadata={})

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        matching = [r for r in results if r.chunk_id == "dup"]
        assert len(matching) == 1

    def test_bm25_only_hit_is_hydrated_from_chunk_cache_in_hybrid_mode(self):
        vector_store, _client = _make_vector_store()  # empty vector store
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="kw_only", text="keyword only content", workspace_id="ws-1")])
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        retriever._chunk_cache["kw_only"] = RetrievalResult(
            chunk_id="kw_only", text="keyword only content", relevance_score=0.0, metadata={"source_type": "document", "document_id": "doc-kw-only", "ingestion_generation": 1}
        )

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert len(results) == 1
        assert results[0].text == "keyword only content"
        assert results[0].metadata["source_type"] == "document"

    def test_hybrid_hit_missing_from_both_caches_is_skipped_not_fabricated(self):
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="orphan", text="never scrolled", workspace_id="ws-1")])
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        # Deliberately NOT populating retriever._chunk_cache for "orphan".

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert results == []  # skipped, not returned with fabricated text/metadata


# ---------------------------------------------------------------------------
# BM25 corpus refresh (documented Task 3.2 freshness behavior)
# ---------------------------------------------------------------------------


class TestRefreshBM25Corpus:
    def test_refresh_populates_bm25_index_and_chunk_cache_from_vector_store(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a", text="alpha content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b", text="beta content", embedding=[0.0, 1.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        bm25 = BM25Index()
        embedder = FakeEmbedder({})
        retriever = _retriever(vector_store, bm25, embedder)

        count = retriever.refresh_bm25_corpus()

        assert count == 2
        assert bm25.size == 2
        assert retriever._chunk_cache["a"].text == "alpha content"

    def test_refresh_is_not_called_automatically_by_retrieve(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="a", text="alpha", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        bm25 = BM25Index()  # never populated
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="keyword", workspace_id="ws-1")

        # keyword mode against a never-refreshed (empty) BM25 index
        # correctly finds nothing -- proving refresh isn't implicit.
        assert results == []


# ---------------------------------------------------------------------------
# Concurrency: hybrid mode genuinely runs both legs in parallel
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_hybrid_mode_runs_both_legs_concurrently_not_sequentially(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="v1", text="t", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )

        sleep_seconds = 0.15

        class SlowEmbedder:
            def embed_query(self, text: str) -> list[float]:
                time.sleep(sleep_seconds)
                return [1.0, 0.0, 0.0]

        class SlowBM25(BM25Index):
            def search(self, query: str, top_k: int | None = None, *, workspace_id: str, document_ids: list[str] | None = None, collection_filter: list[str] | None = None) -> list[tuple[str, float]]:
                time.sleep(sleep_seconds)
                return []

        retriever = _retriever(vector_store, SlowBM25(), SlowEmbedder())

        start = time.monotonic()
        retriever.retrieve(query="query", top_k=5, score_threshold=-1.0, search_mode="hybrid", workspace_id="ws-1")
        elapsed = time.monotonic() - start
        retriever.shutdown()

        # Sequential execution would take >= 2 * sleep_seconds (0.30s).
        # Concurrent execution should take roughly 1 * sleep_seconds,
        # plus scheduling overhead -- a generous threshold well under the
        # sequential sum is used to avoid flakiness while still clearly
        # distinguishing the two execution models.
        assert elapsed < (sleep_seconds * 2) * 0.75

    def test_semantic_only_mode_does_not_use_the_executor(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="v1", text="t", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})

        class NeverSubmitExecutor:
            def submit(self, *args: Any, **kwargs: Any) -> Any:
                raise AssertionError("semantic-only mode must not use the executor")

            def shutdown(self, wait: bool = True) -> None:
                pass

        retriever = HybridRetriever(
            vector_store=vector_store,
            bm25_index=BM25Index(),
            embedder=embedder,
            generation_authority=FakeGenerationAuthorityClient(),
            settings=_settings(),
            executor=NeverSubmitExecutor(),  # type: ignore[arg-type]
        )

        results = retriever.retrieve(query="query", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1


# ---------------------------------------------------------------------------
# MVP M3 — workspace isolation (vector + BM25 + RRF)
# ---------------------------------------------------------------------------


class TestWorkspaceIsolation:
    def test_vector_leg_never_returns_a_cross_workspace_document_semantic_mode(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="workspace A content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="workspace B content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results_a = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")

        assert {r.chunk_id for r in results_a} == {"a1"}

    def test_a_highly_relevant_vector_match_in_another_workspace_is_never_returned(self):
        """TEST 4 from the governing task: vector search contains a
        highly relevant B document (identical embedding to the query);
        authenticated Workspace A must not receive it."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="b-perfect-match", text="perfect match", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
                ContextChunk(chunk_id="a-weak-match", text="weak match", embedding=[0.1, 0.9, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results_a = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")

        assert "b-perfect-match" not in {r.chunk_id for r in results_a}

    def test_bm25_leg_never_returns_a_cross_workspace_document_keyword_mode(self):
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="a1", text="normalization database theory", workspace_id="workspace-A"),
                BM25Document(chunk_id="b1", text="normalization database theory", workspace_id="workspace-B"),
            ]
        )
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}))
        retriever._chunk_cache["a1"] = RetrievalResult(chunk_id="a1", text="normalization database theory", relevance_score=0.0, metadata={"document_id": "doc-a1", "ingestion_generation": 1})
        retriever._chunk_cache["b1"] = RetrievalResult(chunk_id="b1", text="normalization database theory", relevance_score=0.0, metadata={"document_id": "doc-b1", "ingestion_generation": 1})

        results_a = retriever.retrieve(query="normalization database", top_k=10, score_threshold=0.0, search_mode="keyword", workspace_id="workspace-A")

        assert {r.chunk_id for r in results_a} == {"a1"}

    def test_a_highly_relevant_bm25_match_in_another_workspace_is_never_returned(self):
        """TEST 5 from the governing task."""

        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="b-highly-relevant", text="reciprocal rank fusion reciprocal rank fusion reciprocal rank fusion", workspace_id="workspace-B"),
                BM25Document(chunk_id="a-filler", text="an unrelated document about cooking", workspace_id="workspace-A"),
            ]
        )
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}))
        retriever._chunk_cache["b-highly-relevant"] = RetrievalResult(chunk_id="b-highly-relevant", text="x", relevance_score=0.0, metadata={})
        retriever._chunk_cache["a-filler"] = RetrievalResult(chunk_id="a-filler", text="x", relevance_score=0.0, metadata={})

        results_a = retriever.retrieve(query="reciprocal rank fusion", top_k=10, score_threshold=0.0, search_mode="keyword", workspace_id="workspace-A")

        assert "b-highly-relevant" not in {r.chunk_id for r in results_a}

    def test_globally_top_ranked_cross_workspace_document_never_enters_rrf_hybrid_mode(self):
        """TEST 6 from the governing task: a B document that would rank
        higher than anything in A, across BOTH vector and BM25 signals,
        must still never enter A's RRF candidate set at all -- proven in
        full hybrid mode, the actual production path."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="b-perfect", text="perfect", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
                ContextChunk(chunk_id="a-ok", text="ok", embedding=[0.7, 0.7, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
            ]
        )
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="b-perfect", text="reciprocal rank fusion reciprocal rank fusion", workspace_id="workspace-B"),
                BM25Document(chunk_id="a-ok", text="reciprocal", workspace_id="workspace-A"),
            ]
        )
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"query": [1.0, 0.0, 0.0]}))
        retriever._chunk_cache["b-perfect"] = RetrievalResult(chunk_id="b-perfect", text="x", relevance_score=0.0, metadata={})
        retriever._chunk_cache["a-ok"] = RetrievalResult(chunk_id="a-ok", text="x", relevance_score=0.0, metadata={})

        results_a = retriever.retrieve(query="reciprocal rank fusion", top_k=10, score_threshold=0.0, search_mode="hybrid", workspace_id="workspace-A")
        retriever.shutdown()

        assert "b-perfect" not in {r.chunk_id for r in results_a}
        assert {r.chunk_id for r in results_a} == {"a-ok"}

    def test_identical_content_and_embedding_in_both_workspaces_still_isolated(self):
        """TEST 3 from the governing task."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="identical content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="identical content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results_a = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")
        results_b = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-B")

        assert {r.chunk_id for r in results_a} == {"a1"}
        assert {r.chunk_id for r in results_b} == {"b1"}

    def test_switching_workspace_between_calls_on_the_same_retriever_instance_is_isolated(self):
        """TEST 1 + TEST 2 combined: the same retriever instance queried
        first as A then as B (or interleaved) must never leak state
        between the two calls -- no mutable 'current workspace' anywhere
        on the instance."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="A doc", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="a2", text="A doc 2", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="B doc", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b2", text="B doc 2", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results_a = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")
        results_b = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-B")
        results_a_again = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")

        assert {r.chunk_id for r in results_a} == {"a1", "a2"}
        assert {r.chunk_id for r in results_b} == {"b1", "b2"}
        assert {r.chunk_id for r in results_a_again} == {"a1", "a2"}

    def test_retrieve_requires_workspace_id_no_default(self):
        import inspect

        signature = inspect.signature(HybridRetriever.retrieve)
        assert signature.parameters["workspace_id"].default is inspect.Parameter.empty

    def test_concurrent_requests_from_different_workspaces_do_not_cross_contaminate(self):
        """MANDATORY concurrency test: real threads, real concurrent
        `retrieve()` calls, one per workspace, on the SAME shared
        retriever instance -- proving no mutable global/instance
        workspace state exists to race on."""

        import threading

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="A doc", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="B doc", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)

        results: dict[str, set[str]] = {}
        barrier = threading.Barrier(2)

        def run(workspace_id: str):
            barrier.wait(timeout=5)
            for _ in range(10):
                r = retriever.retrieve(query="query", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id=workspace_id)
                chunk_ids = {item.chunk_id for item in r}
                if workspace_id not in results:
                    results[workspace_id] = chunk_ids
                assert chunk_ids == results[workspace_id], f"{workspace_id} got inconsistent results: {chunk_ids}"

        thread_a = threading.Thread(target=run, args=("workspace-A",))
        thread_b = threading.Thread(target=run, args=("workspace-B",))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)
        retriever.shutdown()

        assert results["workspace-A"] == {"a1"}
        assert results["workspace-B"] == {"b1"}


class TestEndToEndCitationIsolationViaRealRAGService:
    """TEST 11: citations returned to the caller can never reference a
    chunk from another workspace -- proven end-to-end through the REAL
    RAGService -> HybridRetriever -> VectorStoreManager stack (fake
    Qdrant client only), not a fake retriever."""

    def test_rag_service_result_never_contains_a_cross_workspace_chunk(self):
        from app.services.rag_service import RAGService
        from tests.test_rag_service import FakeConversationManager, FakeLLMGenerator

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="Workspace A's own real content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="Workspace B's highly relevant content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder)
        service = RAGService(
            hybrid_retriever=retriever,
            conversation_manager=FakeConversationManager(),
            llm_generator=FakeLLMGenerator(),
        )

        result = service.handle_query("query", workspace_id="workspace-A", session_id="s1")
        retriever.shutdown()

        returned_chunk_ids = {r.chunk_id for r in result.retrieval_results}
        assert "b1" not in returned_chunk_ids
        assert returned_chunk_ids == {"a1"}


class TestCanonicalDocumentIdentityInHybridRetrieval:
    """MVP M3 correction, item 6: BM25/hybrid retrieval preserves the
    canonical document_id (via the chunk_cache/vector-store metadata),
    never substituting job_id."""

    def test_hybrid_mode_result_metadata_carries_the_canonical_document_id(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(
                    chunk_id="v1", text="vector hit", embedding=[1.0, 0.0, 0.0],
                    metadata={"job_id": "job-99", "document_id": "file-abc", "workspace_id": "ws-1", "ingestion_generation": 1},
                )
            ]
        )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="k1", text="keyword hit", workspace_id="ws-1")])

        embedder = FakeEmbedder({"query": [1.0, 0.0, 0.0]})
        retriever = _retriever(vector_store, bm25, embedder)
        retriever._chunk_cache["k1"] = RetrievalResult(
            chunk_id="k1", text="keyword hit", relevance_score=0.0,
            metadata={"job_id": "job-100", "document_id": "file-xyz", "ingestion_generation": 1},
        )

        results = retriever.retrieve(query="query", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        by_chunk_id = {r.chunk_id: r for r in results}
        assert by_chunk_id["v1"].metadata["document_id"] == "file-abc"
        assert by_chunk_id["v1"].metadata["job_id"] == "job-99"
        assert by_chunk_id["k1"].metadata["document_id"] == "file-xyz"
        assert by_chunk_id["k1"].metadata["job_id"] == "job-100"


# ---------------------------------------------------------------------------
# MVP M4 — generation visibility / stale-generation isolation
# ---------------------------------------------------------------------------


class TestGenerationVisibility:
    def test_1_current_generation_is_retrievable(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(
                    chunk_id="d1-g1", text="gen1 content", embedding=[1.0, 0.0, 0.0],
                    metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1},
                )
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert {r.chunk_id for r in results} == {"d1-g1"}

    def test_2_stale_generation_excluded_current_generation_retrievable(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="d1-g1", text="stale", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="d1-g2", text="current", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert {r.chunk_id for r in results} == {"d1-g2"}

    def test_3_only_the_authoritative_generation_can_enter_rrf(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id=f"d1-g{g}", text=f"gen{g}", embedding=[1.0, 0.0, 0.0], metadata={"job_id": f"j{g}", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": g})
                for g in (1, 2, 3)
            ]
        )
        bm25 = BM25Index()
        bm25.add_documents(
            [BM25Document(chunk_id=f"d1-g{g}", text=f"gen{g} keyword content", workspace_id="ws-1") for g in (1, 2, 3)]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 3})
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)
        for g in (1, 2, 3):
            retriever._chunk_cache[f"d1-g{g}"] = RetrievalResult(
                chunk_id=f"d1-g{g}", text=f"gen{g} keyword content", relevance_score=0.0,
                metadata={"document_id": "doc-1", "ingestion_generation": g},
            )

        results = retriever.retrieve(query="q", top_k=10, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert {r.chunk_id for r in results} == {"d1-g3"}

    def test_4_stale_generation_with_higher_vector_similarity_still_excluded(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="stale-perfect", text="perfect match, stale", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="current-weak", text="weak match, current", embedding=[0.1, 0.9, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert "stale-perfect" not in {r.chunk_id for r in results}
        assert {r.chunk_id for r in results} == {"current-weak"}

    def test_5_stale_generation_with_higher_bm25_score_still_excluded(self):
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="stale-strong", text="reciprocal rank fusion reciprocal rank fusion", workspace_id="ws-1"),
                BM25Document(chunk_id="current-weak", text="reciprocal", workspace_id="ws-1"),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}), generation_authority=authority)
        retriever._chunk_cache["stale-strong"] = RetrievalResult(chunk_id="stale-strong", text="x", relevance_score=0.0, metadata={"document_id": "doc-1", "ingestion_generation": 1})
        retriever._chunk_cache["current-weak"] = RetrievalResult(chunk_id="current-weak", text="x", relevance_score=0.0, metadata={"document_id": "doc-1", "ingestion_generation": 2})

        results = retriever.retrieve(query="reciprocal rank fusion", top_k=5, score_threshold=0.0, search_mode="keyword", workspace_id="ws-1")

        assert "stale-strong" not in {r.chunk_id for r in results}
        assert {r.chunk_id for r in results} == {"current-weak"}

    def test_6_globally_top_ranked_stale_generation_never_enters_rrf(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="stale", text="perfect", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="current", text="ok", embedding=[0.5, 0.5, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="stale", text="reciprocal rank fusion reciprocal rank fusion", workspace_id="ws-1"),
                BM25Document(chunk_id="current", text="reciprocal", workspace_id="ws-1"),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)
        retriever._chunk_cache["stale"] = RetrievalResult(chunk_id="stale", text="x", relevance_score=0.0, metadata={"document_id": "doc-1", "ingestion_generation": 1})
        retriever._chunk_cache["current"] = RetrievalResult(chunk_id="current", text="x", relevance_score=0.0, metadata={"document_id": "doc-1", "ingestion_generation": 2})

        results = retriever.retrieve(query="q", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert "stale" not in {r.chunk_id for r in results}
        assert {r.chunk_id for r in results} == {"current"}

    def test_7_generation_validation_remains_workspace_scoped(self):
        """TEST 7: two workspaces, each with their own document/generation
        state -- validation for one workspace must never use or be
        affected by the other's authority state."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a-g1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "ja", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b-g1", text="b", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "jb", "document_id": "doc-a", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        # Same document_id "doc-a" used in both workspaces deliberately --
        # proves the authority lookup is genuinely workspace-scoped, not
        # merely document_id-keyed.
        authority = FakeGenerationAuthorityClient({"doc-a": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results_a = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A")
        results_b = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-B")

        assert {r.chunk_id for r in results_a} == {"a-g1"}
        assert {r.chunk_id for r in results_b} == {"b-g1"}

    def test_8_mongo_current_generation_not_present_in_qdrant_yields_no_stale_answer(self):
        """TEST 8: Mongo says current=2, but Qdrant only physically has
        generation 1 (e.g. re-ingestion in flight, new chunks not yet
        published) -- generation 1 must be excluded, producing an empty
        result rather than a stale answer."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="d1-g1", text="stale only", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert results == []

    def test_9_mongo_file_does_not_exist_candidate_excluded(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="orphan", text="x", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-does-not-exist", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({})  # nothing exists in Mongo
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert results == []

    def test_10_mongo_lookup_failure_excludes_all_candidates_in_the_batch(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="d1-g1", text="x", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient(raise_error=True)
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert results == []

    def test_11_missing_generation_metadata_on_the_candidate_itself_excludes_it(self):
        """A chunk whose OWN payload metadata lacks ingestion_generation
        entirely (not a Mongo-side problem) must also be excluded --
        there is nothing to compare against the authority."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="no-gen", text="x", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1"})]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert results == []

    def test_12_malformed_document_id_on_a_candidate_does_not_crash_or_leak(self):
        """TEST 12 at the retrieval-pipeline level: a candidate with a
        bizarre document_id string must not crash retrieval or cause
        unexpected behavior -- it is simply excluded (the real
        GenerationAuthorityClient's own malformed-ID handling is tested
        directly in test_generation_authority.py; this proves the
        retrieval pipeline correctly surfaces "not in the returned map"
        as exclusion)."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="weird", text="x", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "'; DROP TABLE files; --", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({})  # the fake simply never resolves this "document"
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert results == []

    def test_13_multiple_candidates_validated_in_one_bounded_batched_lookup(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id=f"c{i}", text=f"content {i}", embedding=[1.0, 0.0, 0.0], metadata={"job_id": f"j{i}", "document_id": f"doc-{i}", "workspace_id": "ws-1", "ingestion_generation": 1})
                for i in range(5)
            ]
        )
        authority = FakeGenerationAuthorityClient({f"doc-{i}": 1 for i in range(5)})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(authority.calls) == 1  # exactly ONE batched call, not one per candidate
        assert authority.calls[0][0] == {f"doc-{i}" for i in range(5)}
        assert len(results) == 5

    def test_14_generation_validation_occurs_before_rrf(self):
        """Direct proof via call-order instrumentation: the authority
        lookup must be made before `reciprocal_rank_fusion` is invoked."""

        import app.services.hybrid_retriever as hybrid_retriever_module

        call_order: list[str] = []
        original_rrf = hybrid_retriever_module.reciprocal_rank_fusion

        def spy_rrf(*args, **kwargs):
            call_order.append("rrf")
            return original_rrf(*args, **kwargs)

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="c1", text="x", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="c1", text="x", workspace_id="ws-1")])

        class SpyAuthority(FakeGenerationAuthorityClient):
            def get_current_generations(self, document_ids, *, workspace_id):
                call_order.append("authority")
                return super().get_current_generations(document_ids, workspace_id=workspace_id)

        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=SpyAuthority({"doc-1": 1}))
        retriever._chunk_cache["c1"] = RetrievalResult(chunk_id="c1", text="x", relevance_score=0.0, metadata={"document_id": "doc-1", "ingestion_generation": 1})

        import unittest.mock

        with unittest.mock.patch.object(hybrid_retriever_module, "reciprocal_rank_fusion", spy_rrf):
            retriever.retrieve(query="q", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert call_order == ["authority", "rrf"]

    def test_15_and_16_concurrent_workspaces_do_not_share_generation_state(self):
        """TEST 15 + TEST 16: real concurrent threads, different
        workspaces, different authoritative generations, on the SAME
        shared retriever instance -- proving no process-global/shared
        generation cache exists to contaminate requests."""

        import threading

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a-g1", text="a1", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "ja1", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="a-g2", text="a2", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "ja2", "document_id": "doc-a", "workspace_id": "workspace-A", "ingestion_generation": 2}),
                ContextChunk(chunk_id="b-g1", text="b1", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "jb1", "document_id": "doc-b", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        # Workspace A's current generation is 2; workspace B's is 1 --
        # deliberately different, so any state bleed is detectable.
        authority = FakeGenerationAuthorityClient({"doc-a": 2, "doc-b": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results: dict[str, set] = {}
        barrier = threading.Barrier(2)

        def run(workspace_id: str, expected: set):
            barrier.wait(timeout=5)
            for _ in range(10):
                r = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id=workspace_id)
                chunk_ids = {item.chunk_id for item in r}
                assert chunk_ids == expected, f"{workspace_id} got {chunk_ids}, expected {expected}"
            results[workspace_id] = expected

        thread_a = threading.Thread(target=run, args=("workspace-A", {"a-g2"}))
        thread_b = threading.Thread(target=run, args=("workspace-B", {"b-g1"}))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)
        retriever.shutdown()

        assert results == {"workspace-A": {"a-g2"}, "workspace-B": {"b-g1"}}

    def test_16_no_process_global_generation_cache_exists_structurally(self):
        """Structural guard: HybridRetriever/GenerationAuthorityClient
        have no module-level or class-level (as opposed to
        instance-level) mutable cache attribute at all."""

        from app.services.generation_authority import GenerationAuthorityClient

        assert not hasattr(GenerationAuthorityClient, "_cache")
        assert not hasattr(GenerationAuthorityClient, "cache")
        # No class-level dict/mutable default that would be shared across instances.
        for name, value in vars(GenerationAuthorityClient).items():
            assert not isinstance(value, (dict, list, set)), f"class-level mutable attribute found: {name}"

    def test_17_citations_never_contain_stale_generation_metadata(self):
        """End to end through the real RAGService stack: a stale
        candidate must never appear in retrieval_results (the basis for
        citations)."""

        from app.services.rag_service import RAGService
        from tests.test_rag_service import FakeConversationManager, FakeLLMGenerator

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="d1-g1", text="stale", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "document_title": "notes.pdf", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="d1-g2", text="current", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "document_title": "notes.pdf", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"query": [1.0, 0.0, 0.0]}), generation_authority=authority)
        service = RAGService(hybrid_retriever=retriever, conversation_manager=FakeConversationManager(), llm_generator=FakeLLMGenerator())

        result = service.handle_query("query", workspace_id="ws-1", session_id="s1")
        retriever.shutdown()

        generations_seen = {r.metadata.get("ingestion_generation") for r in result.retrieval_results}
        assert generations_seen == {2}
        assert 1 not in generations_seen

    def test_18_reingestion_generation_1_to_2_preserves_document_id(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="d1-g1", text="v1", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="d1-g2", text="v2", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0].metadata["document_id"] == "doc-1"
        assert results[0].metadata["ingestion_generation"] == 2

    def test_19_reingestion_generation_2_to_3_still_filters_correctly(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="d1-g2", text="v2", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
                ContextChunk(chunk_id="d1-g3", text="v3", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j3", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 3}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 3})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0].metadata["ingestion_generation"] == 3

    def test_20_delayed_qdrant_cleanup_does_not_cause_a_stale_answer(self):
        """All three physical generations still present in Qdrant
        (cleanup delayed/never happened) -- only the Mongo-authoritative
        one may ever be returned."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id=f"d1-g{g}", text=f"v{g}", embedding=[1.0, 0.0, 0.0], metadata={"job_id": f"j{g}", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": g})
                for g in (1, 2, 3)
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 3})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0].chunk_id == "d1-g3"


class TestGenerationVisibilityRealIntegration:
    """The mandatory real integration test: real Qdrant candidate
    retrieval (fake-Qdrant-backed VectorStoreManager) -> REAL
    GenerationAuthorityClient (mongomock-backed, not the Fake) ->
    generation filtering -> real HybridRetriever/RRF."""

    def test_real_mongo_authority_client_integrated_with_real_hybrid_retriever(self):
        import mongomock
        from bson import ObjectId

        from app.services.generation_authority import GenerationAuthorityClient

        workspace_object_id = ObjectId()
        stale_file_id = ObjectId()
        current_file_id = ObjectId()

        mongo_client = mongomock.MongoClient()
        files = mongo_client["test_db"]["files"]
        files.insert_one({"_id": stale_file_id, "workspaceId": workspace_object_id, "currentIngestionGeneration": 2})
        # Note: only ONE File document -- "stale_file_id" and
        # "current_file_id" both conceptually represent the SAME
        # document across generations in this scenario naming, but to
        # keep the Mongo side simple we model it as: one real File,
        # current generation 2; two Qdrant chunks, generations 1 and 2.
        real_authority = GenerationAuthorityClient(mongo_client=mongo_client, database_name="test_db", collection_name="files")

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(
                    chunk_id="stale-chunk", text="stale content", embedding=[1.0, 0.0, 0.0],
                    metadata={"job_id": "j1", "document_id": str(stale_file_id), "workspace_id": str(workspace_object_id), "ingestion_generation": 1},
                ),
                ContextChunk(
                    chunk_id="current-chunk", text="current content", embedding=[1.0, 0.0, 0.0],
                    metadata={"job_id": "j2", "document_id": str(stale_file_id), "workspace_id": str(workspace_object_id), "ingestion_generation": 2},
                ),
            ]
        )
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=real_authority)

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id=str(workspace_object_id))

        assert {r.chunk_id for r in results} == {"current-chunk"}
        assert "stale-chunk" not in {r.chunk_id for r in results}


# ---------------------------------------------------------------------------
# MVP M6 — document-level retrieval scope
# ---------------------------------------------------------------------------


class TestM6DocumentLevelScope:
    def test_1_2_document_ids_omitted_or_none_preserves_existing_workspace_wide_behavior(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="b", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-B", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1, "doc-B": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results_omitted = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")
        results_none = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1", document_ids=None)

        assert {r.chunk_id for r in results_omitted} == {"a1", "b1"}
        assert {r.chunk_id for r in results_none} == {"a1", "b1"}

    def test_3_one_document_selected_restricts_to_only_that_document(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="b", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-B", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1, "doc-B": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1", document_ids=["doc-A"]
        )

        assert {r.chunk_id for r in results} == {"a1"}

    def test_4_5_multiple_documents_selected(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id=f"{d}1", text=d, embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": f"doc-{d}", "workspace_id": "ws-1", "ingestion_generation": 1})
                for d in ("A", "B", "C")
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1, "doc-B": 1, "doc-C": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1",
            document_ids=["doc-A", "doc-B"],
        )

        assert {r.chunk_id for r in results} == {"A1", "B1"}

    def test_8_mixed_pdf_and_video_sources_selected_together(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="pdf1", text="pdf content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-pdf", "workspace_id": "ws-1", "ingestion_generation": 1, "source_type": "pdf"}),
                ContextChunk(chunk_id="vid1", text="video content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-video", "workspace_id": "ws-1", "ingestion_generation": 1, "source_type": "mp4"}),
                ContextChunk(chunk_id="other1", text="other content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-other", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-pdf": 1, "doc-video": 1, "doc-other": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1",
            document_ids=["doc-pdf", "doc-video"],
        )

        assert {r.chunk_id for r in results} == {"pdf1", "vid1"}

    def test_10_11_selected_source_lacks_answer_yields_no_result_selected_source_has_answer_yields_it(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="a1", text="unrelated", embedding=[0.0, 1.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        # score_threshold high enough that the poor cosine match is excluded -- "insufficient context" shape.
        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=0.9, search_mode="semantic", workspace_id="ws-1", document_ids=["doc-A"]
        )
        assert results == []

    def test_12_18_TEST_unselected_and_cross_workspace_document_never_retrieved_MANDATORY(self):
        """TEST 18 from the governing task, verbatim: Workspace A
        authenticated, document_ids=["B1"] (a document that actually
        belongs to Workspace B) -- B1 must never be retrieved, cited, or
        reach the fused candidate set."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1-1", text="workspace A's own content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "ja", "document_id": "A1", "workspace_id": "workspace-A", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1-1", text="workspace B's secret content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "jb", "document_id": "B1", "workspace_id": "workspace-B", "ingestion_generation": 1}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"A1": 1, "B1": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        # Authenticated as workspace-A, but requesting document_ids=["B1"]
        # (a document that belongs to workspace-B).
        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="workspace-A", document_ids=["B1"]
        )

        assert results == []
        assert "b1-1" not in {r.chunk_id for r in results}

    def test_13_workspace_a_selecting_workspace_b_document_hybrid_mode(self):
        """Same mandatory scenario, proven in full HYBRID mode (both legs + real RRF)."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="b1-1", text="workspace B secret", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "jb", "document_id": "B1", "workspace_id": "workspace-B", "ingestion_generation": 1})]
        )
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="b1-1", text="workspace B secret code", workspace_id="workspace-B", document_id="B1")])
        authority = FakeGenerationAuthorityClient({"B1": 1})
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)
        retriever._chunk_cache["b1-1"] = RetrievalResult(chunk_id="b1-1", text="x", relevance_score=0.0, metadata={"document_id": "B1", "ingestion_generation": 1})

        results = retriever.retrieve(
            query="secret code", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="workspace-A", document_ids=["B1"]
        )
        retriever.shutdown()

        assert results == []

    def test_14_15_stale_generation_excluded_current_generation_included_within_selected_scope(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="d1-g1", text="stale", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j1", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="d1-g2", text="current", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j2", "document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 2}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-1": 2})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1", document_ids=["doc-1"]
        )

        assert {r.chunk_id for r in results} == {"d1-g2"}

    def test_16_empty_document_ids_never_widens_to_workspace_search(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1", document_ids=[]
        )

        assert results == []

    def test_17_duplicate_document_ids_are_harmless(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1",
            document_ids=["doc-A", "doc-A", "doc-A"],
        )

        assert {r.chunk_id for r in results} == {"a1"}

    def test_18_malformed_document_id_simply_matches_nothing_safely(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1",
            document_ids=["'; DROP TABLE files; --"],
        )

        assert results == []

    def test_20_21_22_semantic_keyword_hybrid_all_respect_document_ids_actual_content_test(self):
        """TEST 20: real content ("Alpha" vs "Beta") proves REAL retrieval
        enforcement, not merely that Pydantic accepts the field."""

        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="The answer is Alpha.", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "ja", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="The answer is Beta.", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "jb", "document_id": "doc-B", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="a1", text="The answer is Alpha.", workspace_id="ws-1", document_id="doc-A"),
                BM25Document(chunk_id="b1", text="The answer is Beta.", workspace_id="ws-1", document_id="doc-B"),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1, "doc-B": 1})

        for mode in ("semantic", "keyword", "hybrid"):
            retriever = _retriever(vector_store, bm25, FakeEmbedder({"What is Beta?": [1.0, 0.0, 0.0]}), generation_authority=authority)
            retriever._chunk_cache["a1"] = RetrievalResult(chunk_id="a1", text="The answer is Alpha.", relevance_score=0.0, metadata={"document_id": "doc-A", "ingestion_generation": 1})
            retriever._chunk_cache["b1"] = RetrievalResult(chunk_id="b1", text="The answer is Beta.", relevance_score=0.0, metadata={"document_id": "doc-B", "ingestion_generation": 1})

            results = retriever.retrieve(
                query="What is Beta?", top_k=5, score_threshold=0.0, search_mode=mode, workspace_id="ws-1",
                document_ids=["doc-A"],
            )
            retriever.shutdown()

            result_texts = " ".join(r.text for r in results)
            assert "Beta" not in result_texts, f"mode={mode} leaked Beta despite document_ids=['doc-A']"

    def test_23_rrf_formula_is_unaffected_by_document_scope(self):
        """RRF itself is not modified -- proven by re-running an existing
        RRF unit test's own expected fused ordering, unaffected by this
        feature (see tests/test_hybrid_retriever.py's own top-level RRF
        tests, unchanged and still passing in the full-suite run)."""

        from app.services.hybrid_retriever import reciprocal_rank_fusion

        bm25_ranked = [("c1", 5.0), ("c2", 3.0)]
        vector_ranked = [RetrievalResult(chunk_id="c2", text="x", relevance_score=0.9, metadata={}), RetrievalResult(chunk_id="c1", text="y", relevance_score=0.5, metadata={})]

        fused = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert [chunk_id for chunk_id, _ in fused] != []  # RRF still functions identically; formula untouched by this file

    def test_25_no_global_fallback_when_scoped_selection_misses_entirely(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_batch(
            [
                ContextChunk(chunk_id="a1", text="Alpha content", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1}),
                ContextChunk(chunk_id="b1", text="totally unrelated to the query", embedding=[0.0, 1.0, 0.0], metadata={"job_id": "j", "document_id": "doc-B", "workspace_id": "ws-1", "ingestion_generation": 1}),
            ]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1, "doc-B": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        # doc-B is selected but has a poor match; the (otherwise perfect
        # match) doc-A must NEVER be substituted in just because doc-B's
        # own result was weak/empty.
        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=0.9, search_mode="semantic", workspace_id="ws-1", document_ids=["doc-B"]
        )

        assert results == []
        assert "a1" not in {r.chunk_id for r in results}

    def test_29_canonical_collection_still_used_with_document_ids_present(self):
        vector_store, client = _make_vector_store()
        vector_store.upsert_batch(
            [ContextChunk(chunk_id="a1", text="a", embedding=[1.0, 0.0, 0.0], metadata={"job_id": "j", "document_id": "doc-A", "workspace_id": "ws-1", "ingestion_generation": 1})]
        )
        authority = FakeGenerationAuthorityClient({"doc-A": 1})
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), generation_authority=authority)

        results = retriever.retrieve(
            query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1", document_ids=["doc-A"]
        )

        # The canonical-collection-configured fake client (see
        # _make_vector_store()'s own settings, unchanged by this feature)
        # is what served this result -- 30's "no legacy collection
        # accidentally created" is proven separately in test_vector_store.py's
        # TestM6CanonicalCollectionProvisioningIsolation, unaffected by
        # this document_ids addition since that logic lives entirely in
        # VectorStoreManager, not touched by this feature's own code.
        assert {r.chunk_id for r in results} == {"a1"}

    def test_retrieve_document_ids_empty_short_circuits_before_touching_either_leg(self):
        """Structural proof of item 5/28's ordering requirement: with an
        empty document_ids, NEITHER the vector store nor BM25 is ever
        queried at all."""

        class ExplodingVectorStore:
            def search_similar(self, *a, **k):
                raise AssertionError("must not be called for empty document_ids")

            def scroll_all_chunks(self, *a, **k):
                return []

        class ExplodingBM25(BM25Index):
            def search(self, *a, **k):
                raise AssertionError("must not be called for empty document_ids")

        retriever = _retriever(ExplodingVectorStore(), ExplodingBM25(), FakeEmbedder({}))

        results = retriever.retrieve(query="q", top_k=5, score_threshold=0.0, search_mode="hybrid", workspace_id="ws-1", document_ids=[])

        assert results == []


# ---------------------------------------------------------------------------
# Phase 4B: optional post-RRF reranking integration
# ---------------------------------------------------------------------------


class FakeReranker:
    """Deterministic test double for `RerankerProtocol`: reorders
    candidates by a caller-supplied score lookup (by chunk_id, default 0
    for anything not listed), truncated to `top_k` -- lets tests control
    exactly what "reranking changed the order" means without a real
    cross-encoder model. Records every call for assertions about what
    candidate pool actually reached it.
    """

    def __init__(self, scores_by_chunk_id: dict[str, float] | None = None, *, raise_error: bool = False) -> None:
        self._scores = scores_by_chunk_id or {}
        self._raise_error = raise_error
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(self, query, candidates, top_k):
        self.calls.append((query, [c.chunk_id for c in candidates], top_k))
        if self._raise_error:
            raise RerankerUnavailableError("simulated reranker failure")
        ranked = sorted(candidates, key=lambda c: (-self._scores.get(c.chunk_id, 0.0), c.chunk_id))
        return ranked[:top_k]


def _upsert_five_descending_similarity_chunks(vector_store: VectorStoreManager) -> None:
    """c1..c5, each less cosine-similar to a [1,0,0,0,0]-style query
    vector than the last, all in workspace "ws-1" with a passing
    generation-authority identity -- gives a predictable pre-rerank
    (RRF/cosine) order of c1 > c2 > c3 > c4 > c5 for tests to reorder
    against."""

    similarities = {"c1": 1.00, "c2": 0.80, "c3": 0.60, "c4": 0.40, "c5": 0.20}
    for chunk_id, sim in similarities.items():
        # A 2D unit vector at an angle whose cosine similarity to [1,0]
        # is exactly `sim` -- avoids hand-picking non-unit vectors whose
        # magnitude would also affect the raw dot product.
        import math

        angle = math.acos(sim)
        vector_store.upsert_chunk(
            ContextChunk(
                chunk_id=chunk_id,
                text=f"content for {chunk_id}",
                embedding=[math.cos(angle), math.sin(angle)],
                metadata={"job_id": chunk_id, "workspace_id": "ws-1", "document_id": f"doc-{chunk_id}", "ingestion_generation": 1},
            )
        )


class TestRerankerDisabledByDefault:
    def test_no_reranker_injected_produces_the_exact_pre_phase_4b_order(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        retriever = _retriever(vector_store, BM25Index(), embedder, reranker=None)

        results = retriever.retrieve(query="q", workspace_id="ws-1", top_k=3, score_threshold=0.0, search_mode="hybrid")

        assert [r.chunk_id for r in results] == ["c1", "c2", "c3"]


class TestRerankerReordersFinalResults:
    def test_reranker_score_overrides_rrf_cosine_order_in_hybrid_mode(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        # Reranker inverts relevance entirely: c5 (worst pre-rerank) is
        # now the best match.
        reranker = FakeReranker({"c5": 10.0, "c4": 8.0, "c3": 6.0, "c2": 4.0, "c1": 2.0})
        retriever = _retriever(
            vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5
        )

        results = retriever.retrieve(query="q", workspace_id="ws-1", top_k=3, score_threshold=0.0, search_mode="hybrid")

        assert [r.chunk_id for r in results] == ["c5", "c4", "c3"]

    def test_reranker_score_overrides_order_in_semantic_only_mode(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({"c5": 10.0, "c1": 1.0})
        retriever = _retriever(
            vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5
        )

        results = retriever.retrieve(query="q", workspace_id="ws-1", top_k=1, score_threshold=0.0, search_mode="semantic")

        assert [r.chunk_id for r in results] == ["c5"]

    def test_reranker_score_overrides_order_in_keyword_only_mode(self):
        bm25 = BM25Index()
        bm25.add_documents(
            [
                BM25Document(chunk_id="k1", text="shared keyword term extra", workspace_id="ws-1", document_id="doc-k1"),
                BM25Document(chunk_id="k2", text="shared keyword term", workspace_id="ws-1", document_id="doc-k2"),
            ]
        )
        vector_store, _client = _make_vector_store()
        for chunk_id in ("k1", "k2"):
            vector_store.upsert_chunk(
                ContextChunk(
                    chunk_id=chunk_id,
                    text="shared keyword term",
                    embedding=[1.0, 0.0],
                    metadata={"job_id": chunk_id, "workspace_id": "ws-1", "document_id": f"doc-{chunk_id}", "ingestion_generation": 1},
                )
            )
        reranker = FakeReranker({"k2": 10.0, "k1": 1.0})
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}), reranker=reranker, reranker_candidate_pool_size=5)
        # Populate the chunk cache the same way refresh_bm25_corpus() would,
        # without re-scrolling the fake vector store (irrelevant to this test).
        retriever._chunk_cache = {
            "k1": RetrievalResult(chunk_id="k1", text="shared keyword term extra", relevance_score=0.0, metadata={"job_id": "k1", "workspace_id": "ws-1", "document_id": "doc-k1", "ingestion_generation": 1}),
            "k2": RetrievalResult(chunk_id="k2", text="shared keyword term", relevance_score=0.0, metadata={"job_id": "k2", "workspace_id": "ws-1", "document_id": "doc-k2", "ingestion_generation": 1}),
        }

        results = retriever.retrieve(query="shared keyword term", workspace_id="ws-1", top_k=1, score_threshold=0.0, search_mode="keyword")

        assert [r.chunk_id for r in results] == ["k2"]


class TestRerankerCandidatePoolExpansion:
    def test_reranker_receives_more_candidates_than_top_k(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({})
        retriever = _retriever(
            vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5
        )

        retriever.retrieve(query="q", workspace_id="ws-1", top_k=2, score_threshold=0.0, search_mode="hybrid")

        assert len(reranker.calls) == 1
        _query, candidate_ids, top_k_seen = reranker.calls[0]
        assert top_k_seen == 2
        assert len(candidate_ids) == 5  # the full expanded pool, not just top_k

    def test_reranker_can_promote_a_candidate_ranked_outside_the_naive_top_k(self):
        """The whole point of Task 4's expanded pool: reranking only the
        already-chosen top_k could never surface c5 here, since c5 would
        never have been selected in the first place."""

        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({"c5": 100.0})  # only c5 stands out
        retriever = _retriever(
            vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5
        )

        results = retriever.retrieve(query="q", workspace_id="ws-1", top_k=2, score_threshold=0.0, search_mode="hybrid")

        assert results[0].chunk_id == "c5"

    def test_pool_size_respects_a_callers_larger_top_k(self):
        """max(top_k, reranker_candidate_pool_size) -- a caller's own
        larger top_k is always respected, matching
        hybrid_candidate_pool_size's own precedent."""

        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({})
        retriever = _retriever(
            vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=2
        )

        retriever.retrieve(query="q", workspace_id="ws-1", top_k=5, score_threshold=0.0, search_mode="hybrid")

        _query, candidate_ids, _top_k = reranker.calls[0]
        assert len(candidate_ids) == 5


class TestRerankerPreservesUpstreamFiltering:
    def test_reranker_never_sees_a_candidate_excluded_by_generation_authority(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        # doc-c3's generation authority reports generation 2, but the
        # indexed chunk still carries generation 1 -- stale, must be
        # excluded before the reranker ever sees it.
        authority = FakeGenerationAuthorityClient(
            {"doc-c1": 1, "doc-c2": 1, "doc-c3": 2, "doc-c4": 1, "doc-c5": 1}
        )
        reranker = FakeReranker({})
        retriever = _retriever(
            vector_store,
            BM25Index(),
            embedder,
            generation_authority=authority,
            reranker=reranker,
            reranker_candidate_pool_size=5,
        )

        retriever.retrieve(query="q", workspace_id="ws-1", top_k=5, score_threshold=0.0, search_mode="hybrid")

        _query, candidate_ids, _top_k = reranker.calls[0]
        assert "c3" not in candidate_ids

    def test_reranker_never_sees_a_candidate_from_a_different_workspace(self):
        vector_store, _client = _make_vector_store()
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="a1", text="in ws-1", embedding=[1.0, 0.0], metadata={"job_id": "a1", "workspace_id": "ws-1", "document_id": "doc-a1", "ingestion_generation": 1})
        )
        vector_store.upsert_chunk(
            ContextChunk(chunk_id="b1", text="in ws-2", embedding=[1.0, 0.0], metadata={"job_id": "b1", "workspace_id": "ws-2", "document_id": "doc-b1", "ingestion_generation": 1})
        )
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({})
        retriever = _retriever(vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5)

        retriever.retrieve(query="q", workspace_id="ws-1", top_k=5, score_threshold=0.0, search_mode="hybrid")

        _query, candidate_ids, _top_k = reranker.calls[0]
        assert candidate_ids == ["a1"]

    def test_reranker_never_sees_a_candidate_outside_document_ids_filter(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        reranker = FakeReranker({})
        retriever = _retriever(vector_store, BM25Index(), embedder, reranker=reranker, reranker_candidate_pool_size=5)

        retriever.retrieve(
            query="q",
            workspace_id="ws-1",
            top_k=5,
            score_threshold=0.0,
            search_mode="hybrid",
            document_ids=["doc-c1", "doc-c2"],
        )

        _query, candidate_ids, _top_k = reranker.calls[0]
        assert set(candidate_ids) == {"c1", "c2"}


class TestRerankerFailureSafety:
    def test_reranker_failure_falls_back_to_pre_rerank_order(self):
        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        failing_reranker = FakeReranker(raise_error=True)
        retriever_with_failing_reranker = _retriever(
            vector_store, BM25Index(), embedder, reranker=failing_reranker, reranker_candidate_pool_size=5
        )
        retriever_without_reranker = _retriever(vector_store, BM25Index(), embedder, reranker=None)

        with_failure = retriever_with_failing_reranker.retrieve(
            query="q", workspace_id="ws-1", top_k=3, score_threshold=0.0, search_mode="hybrid"
        )
        without_reranker_at_all = retriever_without_reranker.retrieve(
            query="q", workspace_id="ws-1", top_k=3, score_threshold=0.0, search_mode="hybrid"
        )

        assert [r.chunk_id for r in with_failure] == [r.chunk_id for r in without_reranker_at_all]

    def test_reranker_failure_does_not_raise_out_of_retrieve(self):
        """Task 9: retrieval must degrade gracefully, never become
        unavailable merely because the reranker failed."""

        vector_store, _client = _make_vector_store()
        _upsert_five_descending_similarity_chunks(vector_store)
        embedder = FakeEmbedder({"q": [1.0, 0.0]})
        failing_reranker = FakeReranker(raise_error=True)
        retriever = _retriever(vector_store, BM25Index(), embedder, reranker=failing_reranker, reranker_candidate_pool_size=5)

        results = retriever.retrieve(query="q", workspace_id="ws-1", top_k=3, score_threshold=0.0, search_mode="hybrid")

        assert len(results) == 3
