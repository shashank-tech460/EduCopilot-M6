"""Task 3.3 -- official HybridRetriever correctness properties P4-P7.

    Property 4: Search mode routing correctness
    Property 5: Reciprocal Rank Fusion determinism
    Property 6: Retrieval result bounds (threshold + top-k)
    Property 7: Relevance_Score range invariant

These test BEHAVIOR through HybridRetriever's public API (`retrieve()`)
and the standalone `reciprocal_rank_fusion()` function, using
independently-written reference computations and Hypothesis-generated
adversarial inputs -- not by re-asserting private implementation details
against themselves. Task 3.2's own test suite (`test_hybrid_retriever.py`)
remains the focused unit/integration/error-path coverage for that task;
this file is specifically the four official properties.

NORMALIZATION AND CANDIDATE-POOL-SIZE STANCE (per this task's explicit
instructions): Task 3.2's three different normalization strategies
(semantic: (cosine+1)/2; keyword: min-max within result set; hybrid:
raw RRF / theoretical max) are NOT rewritten here. This file tests
whether they satisfy P7 as originally implemented, and reports rather
than silently fixes anything they don't. Likewise, `hybrid_candidate_pool_size`
(default 100) is treated as an implementation detail, not an official
value -- properties are exercised with small, explicit pool sizes so
their correctness is shown to hold independently of that default, and a
recall limitation this trivially exposes is reported (see
`TestCandidatePoolRecallLimitation`), not hidden or "fixed" by
redesigning Task 3.2's pooling strategy (out of this task's scope).
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.bm25_index import BM25Document, BM25Index
from app.services.hybrid_retriever import HybridRetriever, reciprocal_rank_fusion
from app.services.vector_store import ContextChunk, VectorStoreManager
from tests.test_hybrid_retriever import FakeEmbedder, FakeGenerationAuthorityClient, _make_vector_store, _retriever, _settings

_HYP = hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

_chunk_id = st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8)


def _unique_chunk_ids(n_min: int, n_max: int) -> st.SearchStrategy[list[str]]:
    return st.lists(_chunk_id, min_size=n_min, max_size=n_max, unique=True)


_embedding_component = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_embedding = st.lists(_embedding_component, min_size=3, max_size=3)


# ===========================================================================
# Property 4: Search mode routing correctness
#
# "For any query with search_mode='semantic', only vector similarity
#  search SHALL be invoked; for any query with search_mode='keyword',
#  only BM25 search SHALL be invoked; for any query with
#  search_mode='hybrid', both SHALL be invoked."
# (Validates Requirements 2.4, 2.5)
# ===========================================================================


class _RaisingBM25(BM25Index):
    """A BM25Index that raises if search() is ever called -- proves the
    caller genuinely never invoked it, rather than invoking it and
    happening to discard the result."""

    def search(self, query: str, top_k: int | None = None, *, workspace_id: str, document_ids: list[str] | None = None, collection_filter: list[str] | None = None) -> list[tuple[str, float]]:
        raise AssertionError("BM25 leg must not be invoked for this search_mode")


class _RaisingEmbedder:
    """An Embedder stand-in that raises if embed_query() is ever
    called -- proves the semantic leg (which always embeds first) was
    genuinely never invoked."""

    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("Embedder/semantic leg must not be invoked for this search_mode")


class _CountingBM25(BM25Index):
    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    def search(self, query: str, top_k: int | None = None, *, workspace_id: str, document_ids: list[str] | None = None, collection_filter: list[str] | None = None) -> list[tuple[str, float]]:
        self.call_count += 1
        return super().search(query, top_k, workspace_id=workspace_id, document_ids=document_ids, collection_filter=collection_filter)


class _CountingEmbedder:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector
        self.call_count = 0

    def embed_query(self, text: str) -> list[float]:
        self.call_count += 1
        return self._vector


def _populate_vector_store(
    vector_store: VectorStoreManager, chunk_ids: list[str], embeddings: list[list[float]]
) -> None:
    if not chunk_ids:
        return
    vector_store.upsert_batch(
        [
            ContextChunk(chunk_id=cid, text=f"text for {cid}", embedding=vec, metadata={"job_id": "job", "document_id": f"doc-{cid}", "workspace_id": "ws-1", "ingestion_generation": 1})
            for cid, vec in zip(chunk_ids, embeddings)
        ]
    )


class TestPropertyFourSearchModeRouting:
    @_HYP
    @given(
        vector_chunk_ids=_unique_chunk_ids(0, 4),
        query_vector=_embedding,
    )
    def test_semantic_mode_never_invokes_bm25(self, vector_chunk_ids: list[str], query_vector: list[float]) -> None:
        vector_store, _client = _make_vector_store()
        embeddings = [query_vector for _ in vector_chunk_ids]  # exact-match embeddings; content irrelevant here
        _populate_vector_store(vector_store, vector_chunk_ids, embeddings)

        raising_bm25 = _RaisingBM25()
        retriever = _retriever(vector_store, raising_bm25, FakeEmbedder({"q": query_vector}))

        results = retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == len(vector_chunk_ids)  # semantic leg did run and found everything

    @_HYP
    @given(bm25_texts=st.lists(st.text(min_size=1, max_size=20), min_size=0, max_size=4))
    def test_keyword_mode_never_invokes_embedder_or_vector_store(self, bm25_texts: list[str]) -> None:
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        chunk_ids = [f"c{i}" for i in range(len(bm25_texts))]
        bm25.add_documents([BM25Document(chunk_id=cid, text=text, workspace_id="ws-1") for cid, text in zip(chunk_ids, bm25_texts)])

        retriever = _retriever(vector_store, bm25, _RaisingEmbedder())
        for cid, text in zip(chunk_ids, bm25_texts):
            retriever._chunk_cache[cid] = RetrievalResult(chunk_id=cid, text=text, relevance_score=0.0, metadata={"document_id": f"doc-{cid}", "ingestion_generation": 1})

        # Must not raise -- proves the embedder (and therefore the
        # vector-search leg, which cannot run without an embedding) was
        # never invoked.
        retriever.retrieve(query="anything", top_k=10, score_threshold=-1.0, search_mode="keyword", workspace_id="ws-1")

    def test_hybrid_mode_invokes_both_legs_at_least_once(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["v1"], [[1.0, 0.0, 0.0]])
        counting_bm25 = _CountingBM25()
        counting_bm25.add_documents([BM25Document(chunk_id="k1", text="keyword content", workspace_id="ws-1")])
        counting_embedder = _CountingEmbedder([1.0, 0.0, 0.0])
        retriever = _retriever(vector_store, counting_bm25, counting_embedder)
        retriever._chunk_cache["k1"] = RetrievalResult(
            chunk_id="k1", text="keyword content", relevance_score=0.0, metadata={"document_id": f"doc-{"k1"}", "ingestion_generation": 1}
        )

        retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert counting_bm25.call_count == 1
        assert counting_embedder.call_count == 1

    def test_semantic_mode_result_never_contains_a_bm25_only_chunk(self) -> None:
        """Direct behavioral proof, not just non-invocation: a chunk that
        ONLY exists in the BM25 corpus (never in the vector store) must
        never appear in semantic-mode results, because semantic mode
        cannot have retrieved it at all.
        """

        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["v1"], [[1.0, 0.0, 0.0]])
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="bm25_only", text="only in keyword index", workspace_id="ws-1")])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}))
        retriever._chunk_cache["bm25_only"] = RetrievalResult(
            chunk_id="bm25_only", text="only in keyword index", relevance_score=0.0, metadata={"document_id": f"doc-{"bm25_only"}", "ingestion_generation": 1}
        )

        results = retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert "bm25_only" not in {r.chunk_id for r in results}

    def test_keyword_mode_result_never_contains_a_vector_only_chunk(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["vector_only"], [[1.0, 0.0, 0.0]])
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="k1", text="keyword content", workspace_id="ws-1")])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}))
        retriever._chunk_cache["k1"] = RetrievalResult(
            chunk_id="k1", text="keyword content", relevance_score=0.0, metadata={"document_id": f"doc-{"k1"}", "ingestion_generation": 1}
        )

        results = retriever.retrieve(query="q", top_k=10, score_threshold=-1.0, search_mode="keyword", workspace_id="ws-1")

        assert "vector_only" not in {r.chunk_id for r in results}


# ===========================================================================
# Property 5: Reciprocal Rank Fusion determinism
#
# "For any two ranked lists of chunk_ids, the RRF merge SHALL produce
#  scores that equal Sum 1/(k + rank_i) for each chunk across both lists,
#  and the resulting order SHALL be strictly descending by computed
#  score." (Validates Requirement 2.2)
# ===========================================================================


def _reference_rrf(bm25_ranked_ids: list[str], vector_ranked_ids: list[str], k: int) -> dict[str, float]:
    """Independently-written reference RRF calculation (not a call into
    `reciprocal_rank_fusion` or any shared helper) -- computes
    Sum 1/(k+rank) per chunk_id across both lists via a single combined
    loop over both lists in turn, deliberately structured differently
    from the implementation's two separate loops, so this is a genuine
    independent check of the formula rather than a restatement of the
    same code path.
    """

    combined_scored: dict[str, float] = {}
    for source_list in (bm25_ranked_ids, vector_ranked_ids):
        for index, chunk_id in enumerate(source_list):
            rank = index + 1  # 1-indexed
            contribution = 1.0 / (k + rank)
            combined_scored[chunk_id] = combined_scored.get(chunk_id, 0.0) + contribution
    return combined_scored


def _to_vector_results(chunk_ids: list[str]) -> list[RetrievalResult]:
    return [RetrievalResult(chunk_id=cid, text="t", relevance_score=1.0, metadata={"document_id": f"doc-{cid}", "ingestion_generation": 1}) for cid in chunk_ids]


def _to_bm25_ranked(chunk_ids: list[str]) -> list[tuple[str, float]]:
    # The score value here is deliberately arbitrary/irrelevant -- RRF
    # operates purely on rank position, never on the underlying score
    # magnitude (asserted directly in a dedicated test below).
    return [(cid, float(len(chunk_ids) - i)) for i, cid in enumerate(chunk_ids)]


class TestPropertyFiveRRFDeterminism:
    @_HYP
    @given(bm25_ids=_unique_chunk_ids(0, 8), vector_ids=_unique_chunk_ids(0, 8))
    def test_exact_formula_matches_independent_reference(self, bm25_ids: list[str], vector_ids: list[str]) -> None:
        k = 60
        fused = dict(reciprocal_rank_fusion(_to_bm25_ranked(bm25_ids), _to_vector_results(vector_ids), k=k))
        expected = _reference_rrf(bm25_ids, vector_ids, k=k)

        assert fused.keys() == expected.keys()
        for chunk_id in expected:
            assert fused[chunk_id] == pytest.approx(expected[chunk_id])

    @_HYP
    @given(bm25_ids=_unique_chunk_ids(1, 8), vector_ids=_unique_chunk_ids(1, 8))
    def test_repeated_identical_input_produces_identical_output(
        self, bm25_ids: list[str], vector_ids: list[str]
    ) -> None:
        bm25_ranked = _to_bm25_ranked(bm25_ids)
        vector_ranked = _to_vector_results(vector_ids)

        first = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)
        second = reciprocal_rank_fusion(bm25_ranked, vector_ranked, k=60)

        assert first == second

    @_HYP
    @given(bm25_ids=_unique_chunk_ids(2, 10), vector_ids=_unique_chunk_ids(0, 10))
    def test_result_order_is_non_increasing_by_score(self, bm25_ids: list[str], vector_ids: list[str]) -> None:
        fused = reciprocal_rank_fusion(_to_bm25_ranked(bm25_ids), _to_vector_results(vector_ids), k=60)

        scores = [score for _cid, score in fused]
        assert scores == sorted(scores, reverse=True)

    @_HYP
    @given(bm25_ids=_unique_chunk_ids(2, 10), vector_ids=_unique_chunk_ids(0, 10))
    def test_ties_are_broken_deterministically_by_chunk_id_without_altering_scores(
        self, bm25_ids: list[str], vector_ids: list[str]
    ) -> None:
        """Verifies the instruction explicitly: the chunk_id tie-break
        changes ORDER among tied entries, never the mathematically
        computed RRF score itself."""

        k = 60
        fused = reciprocal_rank_fusion(_to_bm25_ranked(bm25_ids), _to_vector_results(vector_ids), k=k)
        expected = _reference_rrf(bm25_ids, vector_ids, k=k)

        for chunk_id, score in fused:
            assert score == pytest.approx(expected[chunk_id])

        for (cid_a, score_a), (cid_b, score_b) in zip(fused, fused[1:]):
            if score_a == pytest.approx(score_b):
                assert cid_a <= cid_b

    def test_overlapping_chunks_sum_contributions_from_both_lists(self) -> None:
        k = 60
        fused = dict(
            reciprocal_rank_fusion(_to_bm25_ranked(["shared", "a"]), _to_vector_results(["b", "shared"]), k=k)
        )

        # "shared" is rank 1 in bm25_ranked and rank 2 in vector_ranked.
        assert fused["shared"] == pytest.approx(1.0 / (k + 1) + 1.0 / (k + 2))

    def test_disjoint_chunks_each_get_only_their_own_list_contribution(self) -> None:
        k = 60
        fused = dict(reciprocal_rank_fusion(_to_bm25_ranked(["a"]), _to_vector_results(["b"]), k=k))

        assert fused["a"] == pytest.approx(1.0 / (k + 1))
        assert fused["b"] == pytest.approx(1.0 / (k + 1))

    def test_default_k_is_60_end_to_end(self) -> None:
        assert Settings(_env_file=None).rrf_k == 60  # type: ignore[call-arg]

    @_HYP
    @given(bm25_ids=_unique_chunk_ids(1, 6), vector_ids=_unique_chunk_ids(1, 6))
    def test_rrf_score_is_independent_of_underlying_raw_score_magnitude(
        self, bm25_ids: list[str], vector_ids: list[str]
    ) -> None:
        """RRF is purely rank-based. Changing the raw BM25 scores (while
        preserving rank order) must not change the fused score at all --
        this is what makes RRF immune to incompatible/incomparable raw
        score scales (e.g. negative BM25 vs. cosine similarity).
        """

        low_magnitude_scores = [(cid, 0.001 * (len(bm25_ids) - i)) for i, cid in enumerate(bm25_ids)]
        high_magnitude_scores = [(cid, 10_000.0 * (len(bm25_ids) - i)) for i, cid in enumerate(bm25_ids)]

        vector_ranked = _to_vector_results(vector_ids)
        fused_low = reciprocal_rank_fusion(low_magnitude_scores, vector_ranked, k=60)
        fused_high = reciprocal_rank_fusion(high_magnitude_scores, vector_ranked, k=60)

        assert fused_low == fused_high


# ===========================================================================
# Property 6: Retrieval result bounds (threshold + top-k)
#
# "For any retrieval query, all returned Context_Chunks SHALL have a
#  Relevance_Score >= the configured score_threshold AND the total
#  number of results SHALL be <= the configured top_k."
# (Validates Requirements 2.6, 2.7)
# ===========================================================================


class TestPropertySixThresholdAndTopKBounds:
    @_HYP
    @given(
        num_chunks=st.integers(min_value=0, max_value=15),
        top_k=st.integers(min_value=1, max_value=50),
        score_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        search_mode=st.sampled_from(["semantic", "keyword", "hybrid"]),
    )
    def test_result_count_never_exceeds_top_k_and_every_score_meets_threshold(
        self, num_chunks: int, top_k: int, score_threshold: float, search_mode: str
    ) -> None:
        vector_store, _client = _make_vector_store()
        chunk_ids = [f"c{i}" for i in range(num_chunks)]
        embeddings = [[float((i % 3) - 1), float(((i + 1) % 3) - 1), 0.5] for i in range(num_chunks)]
        _populate_vector_store(vector_store, chunk_ids, embeddings)

        bm25 = BM25Index()
        bm25.add_documents(
            [BM25Document(chunk_id=cid, text=f"content number {i} keyword", workspace_id="ws-1") for i, cid in enumerate(chunk_ids)]
        )

        embedder = FakeEmbedder({"q": [1.0, 0.0, 0.5]})
        retriever = _retriever(vector_store, bm25, embedder, hybrid_candidate_pool_size=5)
        retriever._chunk_cache = {
            cid: RetrievalResult(chunk_id=cid, text=f"content number {i} keyword", relevance_score=0.0, metadata={})
            for i, cid in enumerate(chunk_ids)
        }

        results = retriever.retrieve(
            query="q", top_k=top_k, score_threshold=score_threshold, search_mode=search_mode  # type: ignore[arg-type]
        , workspace_id="ws-1")
        retriever.shutdown()

        assert len(results) <= top_k
        for result in results:
            assert result.relevance_score >= score_threshold - 1e-9  # tolerate float rounding at the exact boundary

    def test_boundary_top_k_equals_one(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["a", "b", "c"], [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 1.0, 0.0]])
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=1, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert results[0].chunk_id == "a"  # closest match

    def test_boundary_top_k_equals_fifty_with_fewer_available_chunks(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["a", "b"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=50, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 2  # never fabricates extra results to reach top_k

    def test_boundary_threshold_zero_admits_everything(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["a", "b"], [[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]])
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=10, score_threshold=0.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 2  # normalized scores are 1.0 and 0.0 -- both >= 0.0

    def test_boundary_threshold_one_admits_only_perfect_matches(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["perfect", "close"], [[1.0, 0.0, 0.0], [0.99, 0.01, 0.0]])
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=10, score_threshold=1.0, search_mode="semantic", workspace_id="ws-1")

        assert {r.chunk_id for r in results} == {"perfect"}

    def test_empty_corpus_returns_empty_regardless_of_top_k_or_threshold(self) -> None:
        vector_store, _client = _make_vector_store()
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        for mode in ("semantic", "keyword", "hybrid"):
            results = retriever.retrieve(query="q", top_k=50, score_threshold=0.0, search_mode=mode, workspace_id="ws-1")  # type: ignore[arg-type]
            assert results == []
        retriever.shutdown()

    def test_per_call_overrides_do_not_mutate_shared_settings_defaults(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["a", "b", "c"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        shared_settings = _settings()
        original_default_top_k = shared_settings.default_top_k
        original_default_threshold = shared_settings.default_score_threshold

        retriever = HybridRetriever(
            vector_store=vector_store,
            bm25_index=BM25Index(),
            embedder=FakeEmbedder({"q": [1.0, 0.0, 0.0]}),
            generation_authority=FakeGenerationAuthorityClient(),
            settings=shared_settings,
        )

        retriever.retrieve(query="q", top_k=1, score_threshold=0.99, search_mode="semantic", workspace_id="ws-1")
        retriever.retrieve(query="q", top_k=50, score_threshold=0.0, search_mode="semantic", workspace_id="ws-1")
        retriever.retrieve(query="q", top_k=17, score_threshold=0.5, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert shared_settings.default_top_k == original_default_top_k
        assert shared_settings.default_score_threshold == original_default_threshold


# ===========================================================================
# Property 7: Relevance_Score range invariant
#
# "For any Context_Chunk returned by the Hybrid_Retriever, its
#  Relevance_Score SHALL be a float within the closed interval
#  [0.0, 1.0]." (Validates Requirement 2.3)
# ===========================================================================


class TestPropertySevenScoreRangeInvariant:
    @_HYP
    @given(embeddings=st.lists(_embedding, min_size=0, max_size=10), query_vector=_embedding)
    def test_semantic_mode_scores_always_in_bounds(
        self, embeddings: list[list[float]], query_vector: list[float]
    ) -> None:
        vector_store, _client = _make_vector_store()
        chunk_ids = [f"c{i}" for i in range(len(embeddings))]
        _populate_vector_store(vector_store, chunk_ids, embeddings)
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": query_vector}))

        results = retriever.retrieve(query="q", top_k=50, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    @_HYP
    @given(texts=st.lists(st.text(min_size=0, max_size=30), min_size=0, max_size=8))
    def test_keyword_mode_scores_always_in_bounds_including_negative_bm25(self, texts: list[str]) -> None:
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        chunk_ids = [f"c{i}" for i in range(len(texts))]
        bm25.add_documents([BM25Document(chunk_id=cid, text=text, workspace_id="ws-1") for cid, text in zip(chunk_ids, texts)])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}))
        for cid, text in zip(chunk_ids, texts):
            retriever._chunk_cache[cid] = RetrievalResult(chunk_id=cid, text=text, relevance_score=0.0, metadata={"document_id": f"doc-{cid}", "ingestion_generation": 1})

        results = retriever.retrieve(
            query="keyword search terms", top_k=50, score_threshold=-1.0, search_mode="keyword"
        , workspace_id="ws-1")

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    @_HYP
    @given(
        vector_embeddings=st.lists(_embedding, min_size=0, max_size=6),
        bm25_texts=st.lists(st.text(min_size=0, max_size=30), min_size=0, max_size=6),
        query_vector=_embedding,
    )
    def test_hybrid_mode_scores_always_in_bounds(
        self, vector_embeddings: list[list[float]], bm25_texts: list[str], query_vector: list[float]
    ) -> None:
        vector_store, _client = _make_vector_store()
        vector_chunk_ids = [f"v{i}" for i in range(len(vector_embeddings))]
        _populate_vector_store(vector_store, vector_chunk_ids, vector_embeddings)

        bm25 = BM25Index()
        bm25_chunk_ids = [f"k{i}" for i in range(len(bm25_texts))]
        bm25.add_documents([BM25Document(chunk_id=cid, text=text, workspace_id="ws-1") for cid, text in zip(bm25_chunk_ids, bm25_texts)])

        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": query_vector}))
        for i, cid in enumerate(bm25_chunk_ids):
            retriever._chunk_cache[cid] = RetrievalResult(
                chunk_id=cid, text=bm25_texts[i], relevance_score=0.0, metadata={"document_id": f"doc-{cid}", "ingestion_generation": 1}
            )

        results = retriever.retrieve(query="q", top_k=50, score_threshold=-1.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    def test_edge_case_negative_bm25_score_normalizes_in_bounds(self) -> None:
        # A single-document corpus produces a negative raw BM25 score
        # for an exact match (documented in Task 3.1's own tests).
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="only", text="reciprocal rank fusion", workspace_id="ws-1")])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}))
        retriever._chunk_cache["only"] = RetrievalResult(
            chunk_id="only", text="reciprocal rank fusion", relevance_score=0.0, metadata={"document_id": f"doc-{"only"}", "ingestion_generation": 1}
        )

        results = retriever.retrieve(
            query="reciprocal rank fusion", top_k=5, score_threshold=-1.0, search_mode="keyword"
        , workspace_id="ws-1")

        assert len(results) == 1
        assert 0.0 <= results[0].relevance_score <= 1.0

    def test_edge_case_all_equal_bm25_scores(self) -> None:
        vector_store, _client = _make_vector_store()
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id=f"c{i}", text="identical shared content", workspace_id="ws-1") for i in range(4)])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({}))
        for i in range(4):
            retriever._chunk_cache[f"c{i}"] = RetrievalResult(
                chunk_id=f"c{i}", text="identical shared content", relevance_score=0.0, metadata={"document_id": f"doc-{f"c{i}"}", "ingestion_generation": 1}
            )

        results = retriever.retrieve(
            query="identical shared content", top_k=10, score_threshold=-1.0, search_mode="keyword"
        , workspace_id="ws-1")

        assert len(results) == 4
        for result in results:
            assert result.relevance_score == pytest.approx(1.0)  # documented all-tied convention

    def test_edge_case_one_result(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["only"], [[1.0, 0.0, 0.0]])
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) == 1
        assert 0.0 <= results[0].relevance_score <= 1.0

    def test_edge_case_empty_results(self) -> None:
        vector_store, _client = _make_vector_store()
        retriever = _retriever(vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}))

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        assert results == []  # vacuously satisfies the bound -- nothing violates it

    def test_edge_case_tied_rrf_scores_stay_in_bounds(self) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(vector_store, ["a", "b"], [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        bm25 = BM25Index()
        bm25.add_documents([BM25Document(chunk_id="a", text="alpha", workspace_id="ws-1"), BM25Document(chunk_id="b", text="beta", workspace_id="ws-1")])
        retriever = _retriever(vector_store, bm25, FakeEmbedder({"q": [1.0, 0.0, 0.0]}))
        retriever._chunk_cache["a"] = RetrievalResult(chunk_id="a", text="alpha", relevance_score=0.0, metadata={"document_id": f"doc-{"a"}", "ingestion_generation": 1})
        retriever._chunk_cache["b"] = RetrievalResult(chunk_id="b", text="beta", relevance_score=0.0, metadata={"document_id": f"doc-{"b"}", "ingestion_generation": 1})

        results = retriever.retrieve(query="q", top_k=5, score_threshold=-1.0, search_mode="hybrid", workspace_id="ws-1")
        retriever.shutdown()

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0

    @pytest.mark.parametrize("cosine_value", [1.0, -1.0, 0.0, 0.999999, -0.999999, 1e-9, -1e-9])
    def test_edge_case_cosine_values_at_or_near_boundaries(self, cosine_value: float) -> None:
        from app.services.hybrid_retriever import _normalize_cosine_similarity

        normalized = _normalize_cosine_similarity(cosine_value)
        assert 0.0 <= normalized <= 1.0


# ===========================================================================
# Candidate-pool-size independence + reported recall limitation
#
# Per this task's explicit instructions: properties must hold
# independently of hybrid_candidate_pool_size, and any recall problem the
# pool size causes must be reported, not hidden or silently "fixed" here.
# ===========================================================================


class TestCandidatePoolIndependence:
    @pytest.mark.parametrize("pool_size", [1, 2, 5, 100])
    def test_p6_and_p7_hold_regardless_of_candidate_pool_size(self, pool_size: int) -> None:
        vector_store, _client = _make_vector_store()
        _populate_vector_store(
            vector_store,
            [f"c{i}" for i in range(10)],
            [[float((i % 3) - 1), 0.5, 0.0] for i in range(10)],
        )
        retriever = _retriever(
            vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.5, 0.0]}), hybrid_candidate_pool_size=pool_size
        )

        results = retriever.retrieve(query="q", top_k=5, score_threshold=0.0, search_mode="semantic", workspace_id="ws-1")

        assert len(results) <= 5  # P6 holds
        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0  # P7 holds


class TestCandidatePoolRecallLimitation:
    def test_configured_pool_size_directly_bounds_vector_candidates_considered(self) -> None:
        """REPORTED LIMITATION (per this task's explicit instructions,
        not silently hidden and not "fixed" here -- fixing would mean
        redesigning Task 3.2's pooling strategy, which is out of Task
        3.3's scope):

        `_retrieve_hybrid`/`_retrieve_semantic_only` request
        `max(top_k, hybrid_candidate_pool_size)` vector candidates before
        fusion/thresholding. Because of that `max(...)`, a *small*
        configured `hybrid_candidate_pool_size` (below `top_k`) has NO
        effect at all -- the pool is never smaller than `top_k`. An
        earlier version of this test tried to demonstrate a top_k-level
        recall difference this way and incorrectly failed to find one --
        which is itself worth recording: the clamp fully protects
        `top_k`-sized requests from being under-filled by a too-small
        configured pool.

        The GENUINE limitation is one level down: whenever the total
        corpus is larger than the *effective* pool
        (`max(top_k, hybrid_candidate_pool_size)`), any chunk ranked
        below that pool size by cosine similarity ALONE never gets a
        chance to contribute its vector-leg RRF term at all -- even if a
        strong BM25 match would otherwise have boosted it into the final
        top_k once fused. This test verifies that mechanism directly
        (the vector leg's own candidate count), since reliably forcing
        that mechanism to visibly change the FINAL fused ranking through
        the public API requires precisely tuned scores across both legs
        rather than a robust, generally-true example -- documented here
        as a real, reportable correctness/recall boundary of Task 3.2's
        chosen design, not swept under the rug.
        """

        vector_store, _client = _make_vector_store()
        embeddings = [[1.0 - 0.05 * i, 0.05 * i, 0.0] for i in range(10)]  # 10 distinct chunks
        _populate_vector_store(vector_store, [f"c{i}" for i in range(10)], embeddings)

        small_pool_retriever = _retriever(
            vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), hybrid_candidate_pool_size=3
        )
        large_pool_retriever = _retriever(
            vector_store, BM25Index(), FakeEmbedder({"q": [1.0, 0.0, 0.0]}), hybrid_candidate_pool_size=100
        )

        # top_k deliberately SMALLER than both configured pool sizes, so
        # the max(top_k, pool_size) clamp does not mask the difference
        # between them.
        small_pool_candidates = small_pool_retriever._semantic_candidates(
            "q", "ws-1", max(1, small_pool_retriever._settings.hybrid_candidate_pool_size), collection_filter=None
        )
        large_pool_candidates = large_pool_retriever._semantic_candidates(
            "q", "ws-1", max(1, large_pool_retriever._settings.hybrid_candidate_pool_size), collection_filter=None
        )
        small_pool_retriever.shutdown()
        large_pool_retriever.shutdown()

        assert len(small_pool_candidates) == 3
        assert len(large_pool_candidates) == 10
        # Every chunk in the small pool is also in the large pool (the
        # small pool is a strict prefix by rank), but not vice versa --
        # the large pool sees 7 chunks the small pool's vector leg never
        # even considers.
        small_ids = {c.chunk_id for c in small_pool_candidates}
        large_ids = {c.chunk_id for c in large_pool_candidates}
        assert small_ids.issubset(large_ids)
        assert len(large_ids - small_ids) == 7
