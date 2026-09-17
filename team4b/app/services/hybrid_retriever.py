"""Team 4B HybridRetriever (Task 3.2).

Implements Requirement 2 (Hybrid Search): combines Task 3.1's BM25Index
and Embedder + Task 2.1's VectorStoreManager into a single retrieval
component with three search modes (semantic, keyword, hybrid), Reciprocal
Rank Fusion, and score normalization to [0.0, 1.0].

APPROVED ARCHITECTURE:

    Team 4A -> shared production Qdrant -> VectorStoreManager
        -> HybridRetriever -- semantic leg (Embedder + VectorStoreManager)
                            -- keyword leg (BM25Index)
                            -> RRF merge -> normalize -> threshold -> top_k

No republishing/synchronization pipeline. No second Qdrant collection.
Team 4A and Team 4C are not modified.

PHASE 4B ADDITION (optional, off by default -- see app/services/reranker.py):
an OPTIONAL reranking stage sits after threshold filtering and before
final top_k selection, for all three search modes:

    ... -> threshold-filtered, generation-authority-passed candidates
        -> [pool expanded to Settings.reranker_candidate_pool_size
            when a reranker is configured, else unchanged]
        -> _finalize_results() -- reranks (if configured) and truncates to top_k
        -> final Context_Chunks

`reranker=None` (the default, and the only behavior before Phase 4B)
makes `_finalize_results()` a pure `candidates[:top_k]` truncation --
byte-for-byte the pre-Phase-4B code path. This module never constructs
a reranker itself; one is only ever injected by a caller (see
app/api/dependencies.py's `get_reranker()`).

SCOPE NOTE (Task 3.2 only): this module does NOT implement Task 3.3's
property tests (P4-P7), ConversationManager, LLMGenerator, RAGService,
API routes, RAGAS, or health/metrics.

FILES TOUCHED OUTSIDE THIS ONE, AND WHY (flagged explicitly rather than
silently expanding earlier tasks' scope):
  - app/services/vector_store.py (Task 2.1): added `scroll_all_chunks()`
    and the `scroll` method on `QdrantClientProtocol`/`RealQdrantClient`.
    HybridRetriever needs a way to (a) populate its BM25 corpus from the
    shared collection's actual content and (b) hydrate text/metadata for
    chunk_ids BM25 matched that vector search did not independently
    return for a given query -- Task 2.1's approved scope (upsert/
    search/delete) never needed to read "everything". This is the same
    kind of minimal, necessary cross-task addition already made once in
    Task 2.1 itself (`ContextChunk`, nominally a Task 1.2 model).
  - app/core/config.py (Task 1.1): added `hybrid_candidate_pool_size`.
    Neither official document specifies a pre-fusion candidate pool
    size; Properties 5-6 constrain the FUSED/final result, not what each
    leg retrieves beforehand. A concrete, explicit, configurable value
    was required to implement RRF+threshold+top_k correctly at all.

REQUIREMENT 2.1 vs. 2.4/2.5 -- AN INTERPRETATION MADE EXPLICIT: Req 2.1
says "WHEN the Hybrid_Retriever receives a query... execute both a BM25
keyword search and a semantic vector similarity search in parallel",
worded without a search_mode qualifier. Read completely literally, that
could suggest running both legs for every query regardless of mode. But
Req 2.4/2.5 explicitly say semantic mode "bypass[es] BM25" and keyword
mode "bypass[es] vector similarity", and Property 4 explicitly requires
"For any query with search_mode='semantic', only vector similarity
search SHALL be invoked" (and the symmetric statement for keyword). This
implementation follows Property 4's explicit, unambiguous wording:
parallel dual-leg execution happens ONLY in hybrid mode; semantic and
keyword modes invoke exactly one leg and never construct or call the
other. This resolves what would otherwise be a genuine tension between
2.1's wording and 2.4/2.5/Property4 -- flagged here rather than silently
picked.
"""

from __future__ import annotations

import logging
from concurrent.futures import Executor, ThreadPoolExecutor
from typing import Literal, Protocol

from app.core.config import Settings, get_settings
from app.models.retrieval import RetrievalResult
from app.services.bm25_index import BM25Document, BM25Index
from app.services.generation_authority import GenerationAuthorityClient, GenerationAuthorityUnavailableError
from app.services.reranker import RerankerProtocol, RerankerUnavailableError
from app.services.vector_store import VectorStoreManager

logger = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "semantic", "keyword"]
_VALID_SEARCH_MODES: frozenset[str] = frozenset({"hybrid", "semantic", "keyword"})


class InvalidSearchModeError(ValueError):
    """Raised when `retrieve()` is called with a `search_mode` outside
    {"hybrid", "semantic", "keyword"} (Requirement 7.1/Property 16's
    validation concern, exercised here at the retriever boundary since
    the full `RetrievalConfig` model doesn't exist yet -- Task 1.2).
    """


class EmbedderProtocol(Protocol):
    """The minimal interface HybridRetriever needs from a query embedder
    -- matches `app.services.embedder.Embedder`'s own public method,
    without depending on that concrete class. Added while fixing Task
    3.3's mypy findings: Task 3.2 originally typed the constructor
    parameter as the concrete `Embedder` class, which technically
    rejected the injected `FakeEmbedder` test doubles under strict
    structural typing -- silently unnoticed because Task 3.2's own test
    functions lacked return-type annotations, which made mypy skip
    checking their bodies entirely (see Task 3.3's report). This mirrors
    the same injectable-protocol pattern already used for
    `QdrantClientProtocol` (Task 2.1) and `EmbeddingModelProtocol` (Task
    3.1) -- a genuine design consistency fix, not a behavior change.
    """

    def embed_query(self, text: str) -> list[float]: ...


class HybridRetriever:
    """Combines BM25 keyword search with Qdrant vector similarity,
    merging via Reciprocal Rank Fusion per Requirement 2.

    Owns a small ThreadPoolExecutor (2 workers) used only to run the
    semantic and keyword legs concurrently in hybrid mode -- see the
    module-level report's "concurrency implementation" discussion for
    why this is safe. An executor can be injected for tests or to share
    a pool with other components.
    """

    def __init__(
        self,
        vector_store: VectorStoreManager,
        bm25_index: BM25Index,
        embedder: EmbedderProtocol,
        generation_authority: GenerationAuthorityClient,
        settings: Settings | None = None,
        executor: Executor | None = None,
        reranker: RerankerProtocol | None = None,
    ) -> None:
        self._vector_store = vector_store
        self._bm25_index = bm25_index
        self._embedder = embedder
        # MVP M4: REQUIRED, no default -- there is no code path in this
        # class that can retrieve without a generation-authority check
        # being performed. See app/services/generation_authority.py.
        self._generation_authority = generation_authority
        self._settings = settings or get_settings()
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="hybrid-retriever")
        # Phase 4B: OPTIONAL, `None` by default -- preserves every
        # pre-Phase-4B caller's exact existing behavior unless a reranker
        # is explicitly injected. See `_selection_pool_size()` and
        # `_finalize_results()` below for the only two places this field
        # is read.
        self._reranker = reranker
        # chunk_id -> RetrievalResult(text, metadata), populated by
        # refresh_bm25_corpus(). Used to hydrate BM25-only hits (chunks a
        # keyword search matched that a given query's vector search did
        # not itself return) with real text/metadata, since BM25Index
        # only ever stores/returns (chunk_id, score) pairs.
        self._chunk_cache: dict[str, RetrievalResult] = {}

    def shutdown(self) -> None:
        """Release the owned thread pool. No-op if an executor was
        injected (the caller owns its lifecycle in that case). Service
        lifecycle/teardown orchestration belongs to a later task (7.1);
        this method exists so Task 3.2's own tests can clean up.
        """

        if self._owns_executor:
            self._executor.shutdown(wait=True)

    # -- BM25 corpus population (documented Task 3.2 freshness behavior) --

    # -- MVP M4: generation-authority filtering (applied BEFORE RRF) -------

    @staticmethod
    def _candidate_document_id(metadata: dict) -> str | None:
        document_id = metadata.get("document_id")
        return document_id if isinstance(document_id, str) and document_id else None

    @staticmethod
    def _candidate_generation(metadata: dict) -> int | None:
        generation = metadata.get("ingestion_generation")
        # `bool` is a subclass of `int` in Python -- explicitly excluded,
        # matching the identical guard in generation_authority.py.
        return generation if isinstance(generation, int) and not isinstance(generation, bool) else None

    def _fetch_generation_map(self, all_candidate_metadata: list[dict], workspace_id: str) -> dict[str, int]:
        """ONE fresh, batched, workspace-scoped Mongo authority read per
        `retrieve()` call -- collects candidate document_ids from
        whichever leg(s) this mode actually uses, then a single
        `GenerationAuthorityClient.get_current_generations()` call.

        Fail-closed: if the authority lookup fails entirely (Mongo
        unavailable), returns an empty map -- every candidate in this
        batch is then excluded by `_passes_generation_check` below,
        never trusted as a fallback.
        """

        document_ids = {
            document_id
            for metadata in all_candidate_metadata
            if (document_id := self._candidate_document_id(metadata)) is not None
        }
        if not document_ids:
            return {}

        try:
            return self._generation_authority.get_current_generations(document_ids, workspace_id=workspace_id)
        except GenerationAuthorityUnavailableError:
            logger.error(
                "Generation authority unavailable -- excluding every candidate in this batch (fail-closed)",
                extra={"candidate_document_count": len(document_ids)},
            )
            return {}

    def _passes_generation_check(self, metadata: dict, generation_map: dict[str, int]) -> bool:
        """A candidate passes ONLY if its own document_id/ingestion_generation
        metadata is well-formed AND matches the authoritative current
        generation for that document_id. Missing metadata, a document_id
        the authority lookup could not verify at all, or a generation
        mismatch (stale) all return False -- fail-closed, never a
        default-allow path.
        """

        document_id = self._candidate_document_id(metadata)
        generation = self._candidate_generation(metadata)
        if document_id is None or generation is None:
            return False
        current_generation = generation_map.get(document_id)
        return current_generation is not None and generation == current_generation

    def refresh_bm25_corpus(self) -> int:
        """Rebuild the BM25 corpus, and this retriever's chunk cache,
        from the CANONICAL shared collection's current content (MVP M3:
        `Settings.canonical_qdrant_collection_name`, i.e.
        `educopilot_chunks` -- NOT the legacy `qdrant_collection_name`
        collection the rest of this class's docstrings still refer to as
        "the shared production collection"; that legacy collection is
        untouched and no longer read by this method).

        DOCUMENTED, NOT SPECIFIED, FRESHNESS BEHAVIOR: neither official
        document defines when/how often the BM25 corpus should be kept
        in sync with the (Team-4A-populated) Vector_Store -- flagged as
        an unresolved ambiguity in the Phase 1 analysis and carried
        forward, deliberately not silently resolved by inventing a
        synchronization service. The Task 3.2 choice made here: a full,
        synchronous, ON-DEMAND rebuild, triggered only when this method
        is explicitly called. There is no background thread, no polling,
        no scheduler, and HybridRetriever never calls this automatically
        from `retrieve()`. A caller (e.g. a future service startup hook
        or orchestrator, Task 7.1) decides when to call it. This keeps
        freshness entirely externally controlled and simple to reason
        about, at the explicit cost that keyword/hybrid search will not
        see newly-ingested content until this is called again -- a
        trade-off, not an assumption presented as spec-mandated.

        MVP M3: each indexed `BM25Document` is tagged with the
        `workspace_id` from that chunk's own canonical payload metadata
        (present on every canonically-published chunk -- Phase 1's
        identity fields) -- a chunk with no `workspace_id` in its
        metadata is indexed with `workspace_id=None`, which (per
        `BM25Index.search()`'s own contract) can never be returned by any
        real, workspace-scoped search.

        Returns the number of chunks loaded, for a caller to log/verify.
        """

        chunks = self._vector_store.scroll_all_chunks(collection_name=self._settings.canonical_qdrant_collection_name)
        self._chunk_cache = {chunk.chunk_id: chunk for chunk in chunks}
        self._bm25_index.rebuild(
            [
                BM25Document(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    workspace_id=chunk.metadata.get("workspace_id"),
                    document_id=chunk.metadata.get("document_id"),
                    source_type=chunk.metadata.get("source_type"),
                )
                for chunk in chunks
            ]
        )
        logger.info("BM25 corpus refreshed", extra={"chunk_count": len(chunks)})
        return len(chunks)

    # -- Public entry point -------------------------------------------------

    def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int,
        score_threshold: float,
        search_mode: SearchMode = "hybrid",
        collection_filter: list[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Retrieve up to `top_k` Context_Chunks with relevance_score in
        [0.0, 1.0], routed by `search_mode` (Requirement 2, Property 4).

        `workspace_id` is REQUIRED (keyword-only, no default) -- MVP M3's
        mandatory multi-tenant isolation boundary. It is threaded into
        BOTH the vector leg (`VectorStoreManager.search_similar`'s own
        mandatory `workspace_id` parameter) and the BM25 leg
        (`BM25Index.search`'s own mandatory `workspace_id` parameter)
        BEFORE either leg's results are combined -- never applied only
        after Reciprocal Rank Fusion, which would let cross-workspace
        candidates influence fused ranking even if filtered out of the
        final result. There is no default value and no way to search
        "every workspace" through this method.

        `document_ids` (MVP M6, additive): `None` (the default) preserves
        the exact previous, workspace-wide behavior. `[]` (present but
        empty) is a DELIBERATE, non-widening narrowing to zero results --
        this method returns `[]` immediately, before touching either
        retrieval leg, rather than ever treating an empty list as "no
        restriction" (a dangerous silent scope-widening). `[...]`
        threads into BOTH legs' own mandatory scoping, exactly like
        `workspace_id` -- never applied only after fusion.

        `collection_filter` (source-type restriction) is threaded into
        BOTH the vector leg and the BM25 leg for `keyword` and `hybrid`
        modes, exactly like `workspace_id`/`document_ids` -- never
        applied only after Reciprocal Rank Fusion (Phase 4E-F1: prior to
        this fix, the BM25 leg silently ignored this parameter in hybrid
        mode, so a non-selected source type could still enter fused
        results via a lexical match). Its own empty-value contract is
        unchanged and intentionally different from `document_ids`'s:
        `None` or `[]` both mean "no source-type restriction" (matching
        `VectorStoreManager._build_collection_filter()`'s existing
        semantic-leg behavior), not "zero results".
        """

        if search_mode not in _VALID_SEARCH_MODES:
            raise InvalidSearchModeError(
                f"search_mode must be one of {sorted(_VALID_SEARCH_MODES)}, got {search_mode!r}"
            )

        if document_ids is not None and len(document_ids) == 0:
            return []

        if search_mode == "semantic":
            return self._retrieve_semantic_only(
                query, workspace_id, top_k, score_threshold, collection_filter, document_ids
            )
        if search_mode == "keyword":
            return self._retrieve_keyword_only(
                query, workspace_id, top_k, score_threshold, collection_filter, document_ids
            )
        return self._retrieve_hybrid(query, workspace_id, top_k, score_threshold, collection_filter, document_ids)

    # -- Phase 4B: reranking / evidence selection (shared by all 3 modes) ----

    def _selection_pool_size(self, top_k: int) -> int:
        """How many threshold-passed, generation-authority-passed
        candidates to keep before final evidence selection.

        Without a reranker configured, this is just `top_k` -- byte-for-
        byte the pre-Phase-4B behavior. With a reranker configured, a
        larger pool (`Settings.reranker_candidate_pool_size`) is kept so
        the reranker has real headroom to promote a candidate that
        RRF/cosine/BM25 ranked below the final top_k -- reranking only
        the already-chosen top_k could never surface anything ranked
        below it in the first place.
        """

        if self._reranker is None:
            return top_k
        return max(top_k, self._settings.reranker_candidate_pool_size)

    def _finalize_results(self, query: str, candidates: list[RetrievalResult], top_k: int) -> list[RetrievalResult]:
        """The one shared place candidate selection becomes final
        evidence, for all three search modes (Task 7: ranking and
        evidence selection are a separate layer from each mode's own
        candidate-gathering logic above).

        `candidates` must already be threshold-filtered, generation-
        authority-filtered, and sorted best-first by whichever mode
        called this -- this method only ever narrows/reorders further,
        never re-applies those checks and never adds anything.

        No reranker configured: exactly the pre-Phase-4B behavior, take
        the first `top_k`. Reranker configured: ask it to re-score/
        re-order `candidates` and select the final `top_k`. If it raises
        `RerankerUnavailableError` for any reason, this logs the failure
        and falls back to the same pre-Phase-4B behavior rather than
        letting retrieval fail outright (Task 9 -- reranking is a
        quality enhancement, never an availability dependency).
        """

        if self._reranker is None:
            return candidates[:top_k]

        try:
            return self._reranker.rerank(query, candidates, top_k)
        except RerankerUnavailableError as exc:
            logger.warning(
                "Reranker unavailable -- degrading to pre-rerank order",
                extra={"candidate_count": len(candidates), "top_k": top_k, "error": str(exc)},
            )
            return candidates[:top_k]

    # -- Semantic-only mode --------------------------------------------------

    def _semantic_candidates(
        self,
        query: str,
        workspace_id: str,
        pool_size: int,
        collection_filter: list[str] | None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        """Embed the query and run vector similarity search, requesting a
        candidate pool (not the final top_k) at a maximally permissive
        score_threshold (-1.0, the theoretical minimum for cosine
        similarity) so that Requirement 7's real score_threshold can be
        applied AFTER normalization, on the normalized scale, rather than
        being misapplied against raw cosine similarity's [-1,1] scale.

        MVP M3: queries the CANONICAL collection
        (`Settings.canonical_qdrant_collection_name`), with the mandatory
        `workspace_id` filter applied by `VectorStoreManager.search_similar`
        itself.
        """

        query_vector = self._embedder.embed_query(query)
        return self._vector_store.search_similar(
            query_vector=query_vector,
            top_k=pool_size,
            score_threshold=-1.0,
            collection_filter=collection_filter,
            workspace_id=workspace_id,
            collection_name=self._settings.canonical_qdrant_collection_name,
            document_ids=document_ids,
        )

    def _retrieve_semantic_only(
        self,
        query: str,
        workspace_id: str,
        top_k: int,
        score_threshold: float,
        collection_filter: list[str] | None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        selection_size = self._selection_pool_size(top_k)
        pool_size = max(top_k, self._settings.hybrid_candidate_pool_size, selection_size)
        candidates = self._semantic_candidates(query, workspace_id, pool_size, collection_filter, document_ids)

        # MVP M4: generation-authority filtering, BEFORE normalization/
        # threshold/top-k -- a stale candidate must never occupy a slot
        # in the final result even if it would otherwise rank highly.
        generation_map = self._fetch_generation_map([c.metadata for c in candidates], workspace_id)
        candidates = [c for c in candidates if self._passes_generation_check(c.metadata, generation_map)]

        normalized_results = [
            RetrievalResult(
                chunk_id=candidate.chunk_id,
                text=candidate.text,
                relevance_score=_normalize_cosine_similarity(candidate.relevance_score),
                metadata=candidate.metadata,
            )
            for candidate in candidates
        ]
        filtered = [result for result in normalized_results if result.relevance_score >= score_threshold]
        filtered.sort(key=lambda result: (-result.relevance_score, result.chunk_id))
        return self._finalize_results(query, filtered[:selection_size], top_k)

    # -- Keyword-only mode ----------------------------------------------------

    def _retrieve_keyword_only(
        self,
        query: str,
        workspace_id: str,
        top_k: int,
        score_threshold: float,
        collection_filter: list[str] | None = None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        # top_k=None: the full ranked corpus, not a pre-truncated slice --
        # threshold and top_k are applied AFTER normalization, below,
        # exactly like the semantic-only path above and the hybrid path.
        # `workspace_id` is mandatory (MVP M3) -- `BM25Index.search` only
        # ever scores documents belonging to this workspace. `document_ids`
        # (MVP M6) and `collection_filter` (Phase 4E-F1) narrow further,
        # both enforced by BM25Index.search() itself.
        ranked = self._bm25_index.search(
            query, top_k=None, workspace_id=workspace_id, document_ids=document_ids, collection_filter=collection_filter
        )
        if not ranked:
            return []

        # Hydrate every BM25 hit's text/metadata FIRST -- generation
        # filtering (MVP M4) needs the metadata, and must happen BEFORE
        # score normalization/thresholding, so a stale candidate can
        # never occupy a slot in the final result.
        hydrated: list[tuple[str, float, RetrievalResult]] = []
        for chunk_id, raw_score in ranked:
            source = self._chunk_cache.get(chunk_id)
            if source is None:
                # BM25 knows this chunk_id (it was indexed via
                # refresh_bm25_corpus) but this retriever's chunk cache
                # doesn't have it -- can only happen if the injected
                # BM25Index was populated some other way than
                # refresh_bm25_corpus (e.g. directly in a test). Skipping
                # rather than fabricating empty text/metadata.
                logger.warning("BM25 hit has no cached text/metadata; skipping", extra={"chunk_id": chunk_id})
                continue
            hydrated.append((chunk_id, raw_score, source))

        generation_map = self._fetch_generation_map([source.metadata for _, _, source in hydrated], workspace_id)
        hydrated = [
            (chunk_id, raw_score, source)
            for chunk_id, raw_score, source in hydrated
            if self._passes_generation_check(source.metadata, generation_map)
        ]
        if not hydrated:
            return []

        raw_scores = [raw_score for _, raw_score, _ in hydrated]
        min_score, max_score = min(raw_scores), max(raw_scores)

        results: list[RetrievalResult] = []
        for chunk_id, raw_score, source in hydrated:
            normalized_score = _normalize_bm25_score(raw_score, min_score, max_score)
            if normalized_score < score_threshold:
                continue
            results.append(
                RetrievalResult(
                    chunk_id=chunk_id, text=source.text, relevance_score=normalized_score, metadata=source.metadata
                )
            )

        results.sort(key=lambda result: (-result.relevance_score, result.chunk_id))
        selection_size = self._selection_pool_size(top_k)
        return self._finalize_results(query, results[:selection_size], top_k)

    # -- Hybrid mode: parallel legs + Reciprocal Rank Fusion -------------------

    def _retrieve_hybrid(
        self,
        query: str,
        workspace_id: str,
        top_k: int,
        score_threshold: float,
        collection_filter: list[str] | None,
        document_ids: list[str] | None = None,
    ) -> list[RetrievalResult]:
        selection_size = self._selection_pool_size(top_k)
        pool_size = max(top_k, self._settings.hybrid_candidate_pool_size, selection_size)

        # Requirement 2.1: execute both legs in parallel. See this
        # module's docstring and the Task 3.2 report for why running
        # these two independent, read-only operations concurrently on a
        # small thread pool is safe. MVP M3: `workspace_id` is passed
        # into BOTH legs -- `workspace_id` itself is an immutable string
        # captured by each closure below, never a shared mutable object,
        # so concurrent calls to this method (from concurrent FastAPI
        # requests, each with their own `workspace_id`) cannot interfere
        # with each other (see tests/test_bm25_index.py's and
        # tests/test_hybrid_retriever.py's concurrency tests).
        vector_future = self._executor.submit(
            self._semantic_candidates, query, workspace_id, pool_size, collection_filter, document_ids
        )
        # Phase 4E-F1: `collection_filter` is now threaded into the BM25
        # leg too, exactly like `workspace_id`/`document_ids` already
        # were -- a non-selected source type can no longer enter this
        # leg's ranked list at all, so it can never reach RRF fusion
        # either. Previously this leg received no source-type
        # restriction, so a lexical match of an excluded source type
        # could survive into the fused hybrid result even though
        # semantic-only mode correctly excluded it (see
        # tests/test_phase4e_workspace_rag_safety.py's now-superseded
        # KNOWN_GAP test, updated alongside this fix).
        bm25_future = self._executor.submit(
            self._bm25_index.search,
            query,
            None,
            workspace_id=workspace_id,
            document_ids=document_ids,
            collection_filter=collection_filter,
        )

        vector_candidates = vector_future.result()
        bm25_ranked = bm25_future.result()

        # MVP M4: generation-authority filtering, BEFORE reciprocal_rank_fusion
        # is ever called -- a stale candidate must never influence RRF,
        # even transiently. ONE combined, batched authority lookup covers
        # BOTH legs' candidate document_ids.
        bm25_metadata_by_chunk_id: dict[str, dict] = {}
        for chunk_id, _raw_score in bm25_ranked:
            source = self._chunk_cache.get(chunk_id)
            if source is not None:
                bm25_metadata_by_chunk_id[chunk_id] = source.metadata

        all_candidate_metadata = [c.metadata for c in vector_candidates] + list(bm25_metadata_by_chunk_id.values())
        generation_map = self._fetch_generation_map(all_candidate_metadata, workspace_id)

        vector_candidates = [c for c in vector_candidates if self._passes_generation_check(c.metadata, generation_map)]
        bm25_ranked = [
            (chunk_id, raw_score)
            for chunk_id, raw_score in bm25_ranked
            if chunk_id in bm25_metadata_by_chunk_id
            and self._passes_generation_check(bm25_metadata_by_chunk_id[chunk_id], generation_map)
        ]

        fused_scores = reciprocal_rank_fusion(bm25_ranked, vector_candidates, k=self._settings.rrf_k)
        max_possible_score = _max_possible_rrf_score(k=self._settings.rrf_k, num_lists=2)

        vector_by_id = {candidate.chunk_id: candidate for candidate in vector_candidates}

        results: list[RetrievalResult] = []
        for chunk_id, raw_score in fused_scores:
            normalized_score = min(raw_score / max_possible_score, 1.0) if max_possible_score > 0 else 0.0
            if normalized_score < score_threshold:
                continue
            source = vector_by_id.get(chunk_id) or self._chunk_cache.get(chunk_id)
            if source is None:
                logger.warning(
                    "Fused hit has no available text/metadata from either leg; skipping", extra={"chunk_id": chunk_id}
                )
                continue
            results.append(
                RetrievalResult(
                    chunk_id=chunk_id, text=source.text, relevance_score=normalized_score, metadata=source.metadata
                )
            )
            if len(results) >= selection_size:
                break

        return self._finalize_results(query, results, top_k)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (Requirement 2.2, Property 5)
#
# score = sum(1 / (k + rank_i)) for each ranking list a chunk_id appears
# in, rank_i is 1-indexed position within that list. Exactly the formula
# given in the official design document -- no weighted averages, no
# score-value blending, no alternative fusion algorithm.
# ---------------------------------------------------------------------------


def reciprocal_rank_fusion(
    bm25_ranked: list[tuple[str, float]],
    vector_ranked: list[RetrievalResult],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Merge two ranked lists (BM25's (chunk_id, score) pairs and vector
    search's RetrievalResults, both already ranked best-first) via
    Reciprocal Rank Fusion.

    Returns (chunk_id, raw_rrf_score) pairs sorted by score descending.

    DETERMINISM NOTE: Property 5 states the resulting order "SHALL be
    strictly descending by computed score". The RRF formula itself can
    legitimately produce exact ties (e.g. two chunk_ids each appearing
    at the same rank in exactly one list, and absent from the other) --
    this is a property of the formula, not a bug. To keep the overall
    ordering deterministic and reproducible (this function's own
    "Deterministic RRF" requirement) even when scores tie, ties are
    broken by chunk_id ascending. This is an explicit, documented
    determinism decision beyond the property's literal wording about
    score alone -- not a deviation from the RRF formula, which is
    applied exactly as specified.
    """

    scores: dict[str, float] = {}

    for rank, (chunk_id, _bm25_score) in enumerate(bm25_ranked, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)

    for rank, result in enumerate(vector_ranked, start=1):
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1.0 / (k + rank)

    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _max_possible_rrf_score(k: int, num_lists: int) -> float:
    """The theoretical maximum RRF score attainable: a chunk_id ranked
    #1 in every one of `num_lists` ranking lists. Every individual RRF
    term 1/(k+rank) is strictly positive for rank >= 1 and k > 0, so this
    is a safe, always-positive normalization denominator.
    """

    return num_lists * (1.0 / (k + 1))


# ---------------------------------------------------------------------------
# Score normalization to [0.0, 1.0] (Requirement 2.3, Property 7)
#
# Requirement 2.3 says a combined Relevance_Score is assigned "based on
# its position in the fused ranking" -- worded ambiguously between (a)
# normalizing the actual computed RRF score magnitude, or (b) a purely
# positional index-based score (e.g. 1 - (position-1)/(total-1)) that
# discards RRF's own score gaps entirely. This implementation chooses
# (a): dividing by the theoretical maximum RRF score, which preserves
# genuine relevance differences the RRF formula itself computed (a large
# score gap between rank 1 and rank 2 stays visible) rather than
# compressing every result to a fixed step size. This is a documented
# interpretation, not something either official document states outright
# -- flagged rather than silently picked as self-evident.
#
# Property 7 ("For any Context_Chunk returned by the Hybrid_Retriever,
# its Relevance_Score SHALL be a float within [0.0, 1.0]") is worded
# generally, not "only in hybrid mode" -- so semantic-only and
# keyword-only results are normalized too, below, using the same
# monotonic-transform principle (order-preserving, scale-only).
# ---------------------------------------------------------------------------


def _normalize_cosine_similarity(raw_cosine_similarity: float) -> float:
    """Map cosine similarity's theoretical range [-1.0, 1.0] to [0.0, 1.0]
    via (x + 1) / 2 -- the standard linear rescaling, monotonic (changes
    no ranking, only the numeric scale), with a defensive clip for
    floating-point edge cases just outside the theoretical bounds.
    """

    return min(max((raw_cosine_similarity + 1.0) / 2.0, 0.0), 1.0)


def _normalize_bm25_score(raw_score: float, min_score: float, max_score: float) -> float:
    """Min-max normalize a raw (unbounded, possibly negative -- see Task
    3.1's documented small-corpus IDF behavior) BM25 score into [0.0,
    1.0] relative to the current candidate set. Monotonic -- preserves
    BM25's own ranking exactly.

    When every candidate in the set ties (`max_score == min_score`), all
    are assigned 1.0 rather than an arbitrary midpoint: a genuine tie
    means they are equally, maximally relevant relative to each other
    within this result set, and assigning anything less than "fully
    relevant" would impose a relevance judgment BM25 itself never made.
    """

    if max_score == min_score:
        return 1.0
    return (raw_score - min_score) / (max_score - min_score)
