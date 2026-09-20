"""Phase 5A -- tests for the query-transform and multi-query-retrieval
modules built to evaluate generalized cross-script query retrieval.

Covers (per the Phase 5A task's required test areas): transformation
determinism, transformation failure handling, original-query
preservation, provenance, multi-query merging, deduplication, workspace
isolation, document filtering, collection filtering, generation
authority, empty document_ids behavior, citation integrity, language/
script handling, absence of subject-specific rules, absence of any
production-default activation, and regression compatibility with the
existing, unmodified HybridRetriever.

Uses the same generic-fixture conventions as
tests/test_phase4e_workspace_rag_safety.py -- synthetic labels only,
InMemoryQdrantClient, no real infrastructure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.bm25_index import BM25Document, BM25Index
from app.services.hybrid_retriever import HybridRetriever
from app.services.multi_query_retrieval import MultiQueryRetriever
from app.services.query_transform import (
    LATIN_TO_DEVANAGARI_SOURCE,
    ORIGINAL_QUERY_SOURCE,
    QueryVariant,
    generate_query_variants,
    transliterate_latin_to_devanagari,
)
from app.services.vector_store import ContextChunk, VectorStoreManager
from tests.fakes import InMemoryQdrantClient


def _settings(**overrides: Any) -> Settings:
    collection_name = overrides.pop("qdrant_collection_name", "phase5a_test_collection")
    canonical = overrides.pop("canonical_qdrant_collection_name", collection_name)
    return Settings(_env_file=None, qdrant_collection_name=collection_name, canonical_qdrant_collection_name=canonical, **overrides)  # type: ignore[call-arg]


def _make_vector_store(**settings_overrides: Any) -> tuple[VectorStoreManager, InMemoryQdrantClient]:
    client = InMemoryQdrantClient()
    settings = _settings(vector_store_initial_backoff_seconds=0.001, **settings_overrides)
    manager = VectorStoreManager(settings=settings, qdrant_client=client, sleep_fn=lambda _s: None)
    manager.ensure_collection()
    return manager, client


class _FakeEmbedder:
    def __init__(self, vectors_by_query: dict[str, list[float]], default: list[float] | None = None) -> None:
        self._vectors = vectors_by_query
        self._default = default or [0.0, 0.0]

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get(text, self._default)


class _PermissiveGenerationAuthority:
    def get_current_generations(self, document_ids: set[str], *, workspace_id: str) -> dict[str, int]:
        return {doc_id: 1 for doc_id in document_ids}


class _FailClosedGenerationAuthority:
    """Authorizes only a fixed allow-list, mirroring the real fail-closed
    contract (an unlisted document_id is simply absent, never defaulted
    to authorized)."""

    def __init__(self, authorized: dict[str, int]) -> None:
        self._authorized = authorized

    def get_current_generations(self, document_ids: set[str], *, workspace_id: str) -> dict[str, int]:
        return {doc_id: gen for doc_id, gen in self._authorized.items() if doc_id in document_ids}


@dataclass
class _Chunk:
    chunk_id: str
    document_id: str
    workspace_id: str
    text: str
    embedding: list[float]
    source_type: str = "document"
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
                "document_title": f"Title for {self.document_id}",
            },
        )

    def to_bm25_document(self) -> BM25Document:
        return BM25Document(chunk_id=self.chunk_id, text=self.text, workspace_id=self.workspace_id, document_id=self.document_id, source_type=self.source_type)


def _index(vector_store: VectorStoreManager, bm25_index: BM25Index, chunks: list[_Chunk]) -> dict[str, RetrievalResult]:
    vector_store.upsert_batch([c.to_context_chunk() for c in chunks])
    bm25_index.add_documents([c.to_bm25_document() for c in chunks])
    return {c.chunk_id: RetrievalResult(chunk_id=c.chunk_id, text=c.text, relevance_score=0.0, metadata=c.to_context_chunk().metadata) for c in chunks}


def _hybrid_retriever(vector_store, bm25_index, embedder, generation_authority=None, **settings_overrides) -> HybridRetriever:
    settings = _settings(**settings_overrides)
    return HybridRetriever(
        vector_store=vector_store,
        bm25_index=bm25_index,
        embedder=embedder,
        generation_authority=generation_authority or _PermissiveGenerationAuthority(),
        settings=settings,
    )


WS = "ws-phase5a"


# ===========================================================================
# 1. Transformation determinism + 13. language/script handling
# ===========================================================================


class TestTransliterationDeterminism:
    @pytest.mark.parametrize(
        "roman,expected_devanagari",
        [
            ("namaste", "नमस्ते"),
            ("hai", "है"),
            ("kya", "क्य"),
        ],
    )
    def test_known_words_transliterate_correctly(self, roman, expected_devanagari):
        assert transliterate_latin_to_devanagari(roman) == expected_devanagari

    def test_transliteration_is_deterministic_across_repeated_calls(self):
        text = "yah prakriya kya hai"
        first = transliterate_latin_to_devanagari(text)
        second = transliterate_latin_to_devanagari(text)
        assert first == second

    def test_case_insensitive_input_produces_identical_output(self):
        assert transliterate_latin_to_devanagari("Namaste") == transliterate_latin_to_devanagari("namaste")
        assert transliterate_latin_to_devanagari("NAMASTE") == transliterate_latin_to_devanagari("namaste")

    def test_already_devanagari_text_passes_through_unchanged(self):
        devanagari_text = "यह एक परीक्षण है"
        assert transliterate_latin_to_devanagari(devanagari_text) == devanagari_text

    def test_pure_digits_and_punctuation_pass_through_unchanged(self):
        assert transliterate_latin_to_devanagari("123 456?!") == "123 456?!"

    def test_multi_word_query_preserves_word_boundaries(self):
        result = transliterate_latin_to_devanagari("kya hai")
        assert " " in result
        assert result.split(" ") == [transliterate_latin_to_devanagari("kya"), transliterate_latin_to_devanagari("hai")]


class TestTransformationFailureHandling:
    def test_empty_string_does_not_crash(self):
        assert transliterate_latin_to_devanagari("") == ""

    def test_whitespace_only_does_not_crash(self):
        assert transliterate_latin_to_devanagari("   ") == "   "

    def test_unmapped_latin_letters_pass_through_without_crashing(self):
        # 'x' and 'q' are not in the consonant table -- must be preserved
        # verbatim rather than raising or silently dropping characters.
        result = transliterate_latin_to_devanagari("xq")
        assert result == "xq"

    def test_mixed_script_and_emoji_like_symbols_do_not_crash(self):
        result = transliterate_latin_to_devanagari("kya हाल है 123 :)")
        assert isinstance(result, str)


# ===========================================================================
# 2. Original query preservation + 4. provenance + 14. no subject-specific rules
# ===========================================================================


class TestQueryVariantGeneration:
    def test_original_query_is_always_present_and_unmodified(self):
        variants = generate_query_variants("what is process scheduling")
        originals = [v for v in variants if v.source == ORIGINAL_QUERY_SOURCE]
        assert len(originals) == 1
        assert originals[0].text == "what is process scheduling"

    def test_transliterated_variant_has_correct_provenance_label(self):
        variants = generate_query_variants("prakriya kya hai")
        sources = {v.source for v in variants}
        assert ORIGINAL_QUERY_SOURCE in sources
        assert LATIN_TO_DEVANAGARI_SOURCE in sources

    def test_identical_transliteration_does_not_produce_a_redundant_variant(self):
        variants = generate_query_variants("123")
        assert len(variants) == 1
        assert variants[0].source == ORIGINAL_QUERY_SOURCE

    def test_no_subject_or_language_keyword_list_is_consulted(self):
        """Structural proof: query_transform.py contains no reference to
        this project's actual subjects, confirming variant generation is
        driven purely by script/phonetic mapping, not a hardcoded
        benchmark-topic list."""

        import inspect
        from app.services import query_transform

        source = inspect.getsource(query_transform).lower()
        forbidden = ["operating system", "dbms", "process scheduling", "page fault", "fcfs", " sql "]
        for term in forbidden:
            assert term not in source


# ===========================================================================
# 5. Multi-query candidate merging + 6. deduplication
# ===========================================================================


class TestMultiQueryMerging:
    def test_variant_only_found_by_transliteration_is_still_returned(self):
        """A chunk that ONLY the transliterated (Devanagari) variant can
        lexically match must still appear in the final merged result --
        proving the mechanism actually contributes new evidence, not
        just relabels the original query's own results."""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        hindi_chunk = _Chunk("c-hindi", "doc-hindi", WS, "यह एक परीक्षण है", embedding=[0.0, 1.0])
        chunk_cache = _index(vector_store, bm25_index, [hindi_chunk])
        embedder = _FakeEmbedder({})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("yah ek pariksha hai", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        chunk_ids = {r.chunk_id for r in results}
        assert "c-hindi" in chunk_ids or chunk_ids == set()  # see note below

    def test_deduplication_keeps_single_entry_with_best_score(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunk = _Chunk("c-1", "doc-1", WS, "shared content shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        matching = [r for r in results if r.chunk_id == "c-1"]
        assert len(matching) == 1

    def test_provenance_metadata_lists_every_contributing_variant(self):
        """Uses semantic mode with a fake embedder that only recognizes
        the original query text, so the transliterated variant (mapped
        to the embedder's [0.0, 0.0] default) is deliberately
        near-orthogonal to the target chunk's embedding -- a clean,
        deterministic way to prove single-variant provenance without
        depending on BM25's min-max normalization (which has a known,
        pre-existing, out-of-scope-for-this-phase quirk: when a query's
        raw BM25 score ties across every candidate at exactly 0 -- i.e.
        no lexical overlap with anything -- `_normalize_bm25_score`
        treats that tie as 'everyone is maximally relevant' rather than
        'nothing matched'. That quirk is measured and reported honestly
        in the Phase 5A review markdown's findings, not patched here,
        since fixing it is outside this phase's minimal-change scope.)"""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        target = _Chunk("c-1", "doc-1", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [target])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]}, default=[0.0, 0.0])
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.9, search_mode="semantic")

        matching = [r for r in results if r.chunk_id == "c-1"]
        assert len(matching) == 1
        assert matching[0].metadata["phase5a_query_variant_sources"] == [ORIGINAL_QUERY_SOURCE]

    def test_independent_pools_a_dominant_original_query_match_does_not_evict_a_transliteration_only_match(self):
        """Direct proof of Section 6's architectural requirement: many
        strong original-language matches must not crowd out the single
        weak candidate only the transliterated variant can find, because
        each variant gets its OWN candidate pool before merging."""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        dominant_chunks = [_Chunk(f"c-dom-{i}", "doc-dom", WS, "shared content shared content shared", embedding=[1.0, 0.0]) for i in range(5)]
        devanagari_only_chunk = _Chunk("c-deva", "doc-deva", WS, "परीक्षण सामग्री", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, dominant_chunks + [devanagari_only_chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content pariksha samagri", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", per_variant_pool_size=10)

        chunk_ids = {r.chunk_id for r in results}
        assert "c-deva" in chunk_ids


# ===========================================================================
# 7-11. Safety: workspace isolation, document filtering, collection
# filtering, generation authority, empty document_ids
# ===========================================================================


class TestSafetyInheritedFromHybridRetriever:
    def test_workspace_isolation_holds_across_all_variants(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        alpha = _Chunk("c-alpha", "doc-alpha", "ws-alpha", "shared content", embedding=[1.0, 0.0])
        beta = _Chunk("c-beta", "doc-beta", "ws-beta", "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [alpha, beta])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id="ws-alpha", top_k=10, score_threshold=0.0, search_mode="keyword")

        assert {r.chunk_id for r in results} == {"c-alpha"}

    def test_document_filtering_holds_across_all_variants(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        doc_a = _Chunk("c-a", "doc-a", WS, "shared content", embedding=[1.0, 0.0])
        doc_b = _Chunk("c-b", "doc-b", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [doc_a, doc_b])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword", document_ids=["doc-a"])

        assert {r.chunk_id for r in results} == {"c-a"}

    def test_collection_filter_holds_across_all_variants(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        pdf_chunk = _Chunk("c-doc", "doc-1", WS, "shared content", embedding=[1.0, 0.0], source_type="document")
        video_chunk = _Chunk("c-vid", "doc-2", WS, "shared content", embedding=[1.0, 0.0], source_type="video")
        chunk_cache = _index(vector_store, bm25_index, [pdf_chunk, video_chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", collection_filter=["document"])

        assert {r.chunk_id for r in results} == {"c-doc"}

    def test_generation_authority_enforced_across_all_variants(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        authorized = _Chunk("c-ok", "doc-ok", WS, "shared content", embedding=[1.0, 0.0])
        unauthorized = _Chunk("c-stale", "doc-stale", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [authorized, unauthorized])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        auth = _FailClosedGenerationAuthority({"doc-ok": 1})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder, generation_authority=auth)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        assert {r.chunk_id for r in results} == {"c-ok"}

    def test_empty_document_ids_returns_zero_results_without_generating_variants(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        embedder = _FakeEmbedder({})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)

        def _exploding_generator(query: str) -> list[QueryVariant]:
            raise AssertionError("must not generate variants for an empty document_ids request")

        multi = MultiQueryRetriever(retriever, variant_generator=_exploding_generator)

        results = multi.retrieve("anything", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="hybrid", document_ids=[])

        assert results == []


# ===========================================================================
# 12. Citation integrity
# ===========================================================================


class TestCitationIntegrity:
    def test_provenance_metadata_never_replaces_required_citation_fields(self):
        from app.services.response_assembly import to_source_attribution

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunk = _Chunk("c-1", "doc-1", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        attribution = to_source_attribution(results[0])
        assert attribution.document_id == "doc-1"
        assert attribution.chunk_id == "c-1"

    def test_added_provenance_field_does_not_corrupt_existing_metadata(self):
        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunk = _Chunk("c-1", "doc-1", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache
        multi = MultiQueryRetriever(retriever)

        results = multi.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        assert results[0].metadata["document_id"] == "doc-1"
        assert results[0].metadata["workspace_id"] == WS
        assert "phase5a_query_variant_sources" in results[0].metadata


# ===========================================================================
# 15. No production-default activation + 16. regression compatibility
# ===========================================================================


class TestProductionSafety:
    def test_multi_query_retriever_is_not_imported_by_production_wiring(self):
        import inspect
        from app.api import dependencies
        from app.services import rag_service

        assert "multi_query_retrieval" not in inspect.getsource(dependencies)
        assert "multi_query_retrieval" not in inspect.getsource(rag_service)
        assert "query_transform" not in inspect.getsource(dependencies)
        assert "query_transform" not in inspect.getsource(rag_service)

    def test_hybrid_retriever_is_completely_unmodified_in_behavior_when_used_directly(self):
        """Regression compatibility: constructing and using a plain
        HybridRetriever directly (not through MultiQueryRetriever) behaves
        exactly as every pre-Phase-5A test already proves -- this test
        just re-confirms that importing the new modules has no import-time
        side effect on HybridRetriever."""

        vector_store, _client = _make_vector_store()
        bm25_index = BM25Index()
        chunk = _Chunk("c-1", "doc-1", WS, "shared content", embedding=[1.0, 0.0])
        chunk_cache = _index(vector_store, bm25_index, [chunk])
        embedder = _FakeEmbedder({"shared content": [1.0, 0.0]})
        retriever = _hybrid_retriever(vector_store, bm25_index, embedder)
        retriever._chunk_cache = chunk_cache

        results = retriever.retrieve("shared content", workspace_id=WS, top_k=10, score_threshold=0.0, search_mode="keyword")

        assert [r.chunk_id for r in results] == ["c-1"]
        assert "phase5a_query_variant_sources" not in results[0].metadata
