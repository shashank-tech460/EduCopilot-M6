"""Phase 4E-F1 -- regression suite for the BM25 source-filter enforcement fix.

Background: Phase 4E's safety harness found that `collection_filter`
(source-type restriction) was enforced on the semantic retrieval leg but
NOT on the BM25 leg in hybrid mode, so a non-selected source type could
leak into fused results via a lexical-only match
(`tests/test_phase4e_workspace_rag_safety.py`'s former
`test_KNOWN_GAP_...`, now `test_PHASE4E_F1_FIXED_...`). This file is the
dedicated, focused regression suite for the fix itself:

  - `BM25Document` gained a `source_type` field (mirroring
    `workspace_id`/`document_id`'s existing precedent).
  - `BM25Index.search()` gained a `collection_filter` parameter, using
    the SAME "falsy means no restriction" contract the semantic leg's
    `VectorStoreManager._build_collection_filter()` already has (NOT
    `document_ids`'s "empty list means zero results" contract -- the two
    parameters have always had different empty-value semantics).
  - `HybridRetriever` threads `collection_filter` into the BM25 leg for
    both `keyword` and `hybrid` search modes.

GENERALITY: these tests deliberately use arbitrary, made-up source-type
labels ("type-alpha"/"type-beta"/"type-gamma") for most cases, proving
the mechanism has no dependency on the real "document"/"video"
vocabulary -- source type is plain metadata to this code, not domain
logic. One test (`test_real_normalized_vocabulary_end_to_end`) uses the
actual production "document"/"video" values for an end-to-end sanity
check through the real semantic+BM25 pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.bm25_index import BM25Document, BM25Index
from app.services.hybrid_retriever import HybridRetriever
from app.services.reranker import RerankerUnavailableError
from app.services.vector_store import ContextChunk, VectorStoreManager
from tests.fakes import InMemoryQdrantClient


def _settings(**overrides: Any) -> Settings:
    collection_name = overrides.pop("qdrant_collection_name", "phase4e_f1_test_collection")
    canonical = overrides.pop("canonical_qdrant_collection_name", collection_name)
    return Settings(_env_file=None, qdrant_collection_name=collection_name, canonical_qdrant_collection_name=canonical, **overrides)  # type: ignore[call-arg]


def _make_vector_store(**settings_overrides: Any) -> tuple[VectorStoreManager, InMemoryQdrantClient]:
    client = InMemoryQdrantClient()
    settings = _settings(vector_store_initial_backoff_seconds=0.001, **settings_overrides)
    manager = VectorStoreManager(settings=settings, qdrant_client=client, sleep_fn=lambda _s: None)
    manager.ensure_collection()
    return manager, client


class _FakeEmbedder:
    def __init__(self, vectors_by_query: dict[str, list[float]]) -> None:
        self._vectors = vectors_by_query

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get(text, [0.0, 0.0])


class _PermissiveGenerationAuthority:
    """Every document_id passed in is reported as currently authorized --
    this file is testing SOURCE-TYPE filtering specifically, not
    generation-authority enforcement (already covered exhaustively in
    tests/test_phase4e_workspace_rag_safety.py's TestGenerationAuthority)."""

    def get_current_generations(self, document_ids: set[str], *, workspace_id: str) -> dict[str, int]:
        return {doc_id: 1 for doc_id in document_ids}


class _RecordingReranker:
    def __init__(self, favor_chunk_id: str | None = None, *, raise_error: bool = False) -> None:
        self._favor = favor_chunk_id
        self._raise_error = raise_error
        self.received_candidates: list[list[RetrievalResult]] = []

    def rerank(self, query: str, candidates, top_k: int) -> list[RetrievalResult]:
        self.received_candidates.append(list(candidates))
        if self._raise_error:
            raise RerankerUnavailableError("simulated reranker failure")
        ranked = sorted(candidates, key=lambda c: (c.chunk_id != self._favor, c.chunk_id))
        return ranked[:top_k]


@dataclass
class _Chunk:
    chunk_id: str
    document_id: str
    workspace_id: str
    source_type: str
    text: str
    embedding: list[float]
    ingestion_generation: int = 1

    def to_context_chunk(self) -> ContextChunk:
        return ContextChunk(
            chunk_id=self.chunk_id,
            text=self.text,
            embedding=self.embedding,
            metadata={
                "job_id": self.chunk_id,
                "workspace_id": self.workspace_id,
                "document_id": self.document_id,
                "ingestion_generation": self.ingestion_generation,
                "source_type": self.source_type,
            },
        )

    def to_bm25_document(self) -> BM25Document:
        return BM25Document(
            chunk_id=self.chunk_id, text=self.text, workspace_id=self.workspace_id, document_id=self.document_id, source_type=self.source_type
        )


def _index(vector_store: VectorStoreManager, bm25_index: BM25Index, chunks: list[_Chunk]) -> dict[str, RetrievalResult]:
    vector_store.upsert_batch([c.to_context_chunk() for c in chunks])
    bm25_index.add_documents([c.to_bm25_document() for c in chunks])
    return {c.chunk_id: RetrievalResult(chunk_id=c.chunk_id, text=c.text, relevance_score=0.0, metadata=c.to_context_chunk().metadata) for c in chunks}


def _retriever(vector_store, bm25_index, embedder, reranker=None, **settings_overrides) -> HybridRetriever:
    settings = _settings(**settings_overrides)
    return HybridRetriever(
        vector_store=vector_store,
        bm25_index=bm25_index,
        embedder=embedder,
        generation_authority=_PermissiveGenerationAuthority(),
        settings=settings,
        reranker=reranker,
    )


WS = "ws-phase4e-f1"


def _three_type_universe() -> tuple[VectorStoreManager, BM25Index, dict[str, RetrievalResult], _FakeEmbedder]:
    """Three chunks, three distinct source types, all lexically matching
    the same query -- pure keyword/BM25 relevance, no vector-search
    contribution needed (embeddings are all identical/irrelevant)."""

    vector_store, _client = _make_vector_store()
    bm25_index = BM25Index()
    chunks = [
        _Chunk("c-alpha", "doc-alpha", WS, "type-alpha", "shared keyword content alpha", [0.0, 0.0]),
        _Chunk("c-beta", "doc-beta", WS, "type-beta", "shared keyword content beta", [0.0, 0.0]),
        _Chunk("c-gamma", "doc-gamma", WS, "type-gamma", "shared keyword content gamma", [0.0, 0.0]),
    ]
    chunk_cache = _index(vector_store, bm25_index, chunks)
    embedder = _FakeEmbedder({"shared keyword content": [0.0, 0.0]})
    return vector_store, bm25_index, chunk_cache, embedder


class TestBM25LegSourceFiltering:
    """Tests A, B, C, D, E, F -- pure keyword-mode BM25 filtering."""

    def test_A_filter_type_alpha_excludes_type_beta(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=["type-alpha"])

        returned = {r.chunk_id for r in results}
        assert returned == {"c-alpha"}
        assert "c-beta" not in returned

    def test_B_filter_type_beta_excludes_type_alpha(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=["type-beta"])

        returned = {r.chunk_id for r in results}
        assert returned == {"c-beta"}
        assert "c-alpha" not in returned

    def test_C_filter_type_gamma_excludes_both_others(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=["type-gamma"])

        returned = {r.chunk_id for r in results}
        assert returned == {"c-gamma"}
        assert returned.isdisjoint({"c-alpha", "c-beta"})

    def test_D_multiple_filters_include_exactly_those_types(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=["type-alpha", "type-beta"])

        returned = {r.chunk_id for r in results}
        assert returned == {"c-alpha", "c-beta"}
        assert "c-gamma" not in returned

    def test_E_no_collection_filter_preserves_existing_behavior(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=None)

        assert {r.chunk_id for r in results} == {"c-alpha", "c-beta", "c-gamma"}

    def test_F_empty_collection_filter_behaves_like_no_restriction(self):
        """Matches the EXISTING contract `VectorStoreManager.
        _build_collection_filter()` already has for the semantic leg
        (`if not collection_filter: return None`) -- an empty list is
        NOT the same convention as `document_ids=[]` (which narrows to
        zero); this test locks in that this fix did not accidentally
        change collection_filter's own long-established empty-value
        contract."""

        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results_empty = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=[])
        results_none = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", collection_filter=None)

        assert {r.chunk_id for r in results_empty} == {r.chunk_id for r in results_none} == {"c-alpha", "c-beta", "c-gamma"}

    def test_bm25_index_search_directly_excludes_non_matching_source_type(self):
        """Unit-level proof at the BM25Index layer itself, independent
        of HybridRetriever -- an excluded source type's text never even
        enters the per-query BM25Okapi corpus (not merely filtered from
        the final list)."""

        index = BM25Index()
        index.add_documents([
            BM25Document(chunk_id="a", text="distinctive term", workspace_id=WS, document_id="doc-a", source_type="type-alpha"),
            BM25Document(chunk_id="b", text="distinctive term", workspace_id=WS, document_id="doc-b", source_type="type-beta"),
        ])

        results = index.search("distinctive term", workspace_id=WS, collection_filter=["type-alpha"])

        assert [chunk_id for chunk_id, _score in results] == ["a"]


class TestHybridModeSourceFiltering:
    """Tests C (hybrid variant), G, H, I -- source filtering through RRF
    and the reranker."""

    def test_C_source_filtering_holds_in_hybrid_mode_not_just_keyword_mode(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["type-alpha"])

        returned = {r.chunk_id for r in results}
        assert returned == {"c-alpha"}
        assert "c-beta" not in returned and "c-gamma" not in returned

    def test_G_source_filtering_correct_after_rrf_even_when_excluded_type_would_rank_first_on_bm25_alone(self):
        """The excluded-type chunk is the STRONGEST lexical match (exact,
        repeated term) -- if RRF ever received it, it would likely rank
        at or near the top. Proves exclusion happens before RRF fusion,
        not as a post-hoc trim of the fused list."""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunks = [
            _Chunk("c-included", "doc-included", WS, "type-alpha", "topic term", [1.0, 0.0]),
            _Chunk("c-excluded", "doc-excluded", WS, "type-beta", "topic term topic term topic term", [1.0, 0.0]),
        ]
        chunk_cache = _index(vector_store, bm25_index, chunks)
        embedder = _FakeEmbedder({"topic term": [1.0, 0.0]})
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("topic term", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["type-alpha"])

        assert [r.chunk_id for r in results] == ["c-included"]

    def test_H_source_filtering_correct_with_reranker_enabled(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        reranker = _RecordingReranker(favor_chunk_id="c-beta")  # would promote the excluded chunk, if it ever saw it
        retriever = _retriever(vector_store, bm25_index, embedder, reranker=reranker, reranker_candidate_pool_size=10)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["type-alpha"])

        assert [r.chunk_id for r in results] == ["c-alpha"]
        for candidates in reranker.received_candidates:
            assert all(c.chunk_id != "c-beta" for c in candidates)

    def test_I_source_filtering_correct_when_reranker_fails_and_falls_back(self):
        vector_store, bm25_index, chunk_cache, embedder = _three_type_universe()
        failing_reranker = _RecordingReranker(raise_error=True)
        retriever = _retriever(vector_store, bm25_index, embedder, reranker=failing_reranker, reranker_candidate_pool_size=10)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["type-alpha"])

        assert [r.chunk_id for r in results] == ["c-alpha"]


class TestSourceFilteringCombinedWithOtherScoping:
    """Tests J, K -- source filtering composed with workspace and
    document scoping, proving neither invariant weakens the other."""

    def test_J_workspace_isolation_intact_simultaneously_with_source_filtering(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunks = [
            _Chunk("c-ws1-alpha", "doc-1", "ws-1", "type-alpha", "shared keyword content", [0.0, 0.0]),
            _Chunk("c-ws1-beta", "doc-2", "ws-1", "type-beta", "shared keyword content", [0.0, 0.0]),
            _Chunk("c-ws2-alpha", "doc-3", "ws-2", "type-alpha", "shared keyword content", [0.0, 0.0]),
        ]
        chunk_cache = _index(vector_store, bm25_index, chunks)
        embedder = _FakeEmbedder({"shared keyword content": [0.0, 0.0]})
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared keyword content", workspace_id="ws-1", top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["type-alpha"])

        assert [r.chunk_id for r in results] == ["c-ws1-alpha"]

    def test_K_document_filtering_and_source_filtering_together(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunks = [
            _Chunk("c-doc1-alpha", "doc-1", WS, "type-alpha", "shared keyword content", [0.0, 0.0]),
            _Chunk("c-doc1-beta", "doc-1", WS, "type-beta", "shared keyword content", [0.0, 0.0]),
            _Chunk("c-doc2-alpha", "doc-2", WS, "type-alpha", "shared keyword content", [0.0, 0.0]),
        ]
        chunk_cache = _index(vector_store, bm25_index, chunks)
        embedder = _FakeEmbedder({"shared keyword content": [0.0, 0.0]})
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve(
            "shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid",
            collection_filter=["type-alpha"], document_ids=["doc-1"],
        )

        assert [r.chunk_id for r in results] == ["c-doc1-alpha"]


class TestRealNormalizedVocabularyEndToEnd:
    def test_real_normalized_vocabulary_end_to_end(self):
        """Sanity check with the ACTUAL production vocabulary
        ("document"/"video", see vector_store.normalize_source_type) run
        through the full semantic+BM25+RRF pipeline, not just synthetic
        labels."""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunks = [
            _Chunk("c-pdf", "doc-pdf", WS, "document", "shared keyword content", [1.0, 0.0]),
            _Chunk("c-video", "doc-video", WS, "video", "shared keyword content", [1.0, 0.0]),
        ]
        chunk_cache = _index(vector_store, bm25_index, chunks)
        embedder = _FakeEmbedder({"shared keyword content": [1.0, 0.0]})
        retriever = _retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        document_only = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["document"])
        video_only = retriever.retrieve("shared keyword content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["video"])

        assert [r.chunk_id for r in document_only] == ["c-pdf"]
        assert [r.chunk_id for r in video_only] == ["c-video"]
