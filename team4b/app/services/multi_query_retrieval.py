"""Phase 5A -- generic, opt-in multi-query retrieval orchestration.

NOT wired into production. `app/api/dependencies.py` and
`app/services/rag_service.py` are untouched by this phase; this class is
only ever constructed by the Phase 5A evaluation script and its tests.
No existing production file's behavior changes as a result of this
module existing.

ARCHITECTURE (Section 6's requirement): Phase 4D found that shared RRF
can let a large same-script candidate set crowd out a weak cross-script
one. This class avoids that failure mode structurally, not by tuning
weights:

  - INDEPENDENT CANDIDATE POOLS: each query variant (see
    `query_transform.generate_query_variants`) is retrieved via its own,
    separate call to the existing, UNMODIFIED `HybridRetriever.retrieve()`
    -- never merged before RRF. Each variant's own internal semantic/BM25
    candidate pool and RRF fusion happen exactly as they already do for a
    single query; this class only combines the FINAL, already-fused,
    already-normalized results each variant call returns.
  - SOURCE-QUERY PROVENANCE: every returned `RetrievalResult` carries a
    `phase5a_query_variant_sources` list in its metadata, naming every
    variant that produced it -- never silently discarded.
  - CANDIDATE-PRESERVING MERGE: a chunk_id returned by more than one
    variant is deduplicated by keeping its BEST (max) relevance_score,
    never dropped and never double-counted.
  - GENERIC WEIGHTING: none. The merge rule is "highest normalized
    relevance_score wins", a fixed, content-blind rule -- no per-subject
    or per-language weight is introduced or tunable here.

SAFETY: this class introduces no new authorization logic whatsoever. It
calls `HybridRetriever.retrieve()` -- already the sole, tested
enforcement point for workspace_id/document_ids/collection_filter/
generation-authority -- once per variant, with the SAME arguments the
caller gave for every variant. A transformed query can therefore never
have a wider authorization scope than the original request. The
`document_ids == []` short-circuit is checked here too, before any
variant is even generated, so behavior matches `HybridRetriever.retrieve()`
exactly for that case (return `[]` immediately, no retrieval work at all).
"""

from __future__ import annotations

from typing import Callable

from app.models.retrieval import RetrievalResult
from app.services.hybrid_retriever import HybridRetriever, SearchMode
from app.services.query_transform import QueryVariant, generate_query_variants


class MultiQueryRetriever:
    """Wraps an existing `HybridRetriever` instance by composition --
    never subclasses or modifies it. `variant_generator` is injectable
    (defaults to `generate_query_variants`) purely for testability."""

    def __init__(
        self,
        retriever: HybridRetriever,
        variant_generator: Callable[[str], list[QueryVariant]] = generate_query_variants,
    ) -> None:
        self._retriever = retriever
        self._variant_generator = variant_generator

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
        per_variant_pool_size: int | None = None,
    ) -> list[RetrievalResult]:
        if document_ids is not None and len(document_ids) == 0:
            return []

        variants = self._variant_generator(query)
        pool_size = per_variant_pool_size if per_variant_pool_size is not None else top_k

        best_by_chunk_id: dict[str, RetrievalResult] = {}
        provenance_by_chunk_id: dict[str, list[str]] = {}

        for variant in variants:
            variant_results = self._retriever.retrieve(
                variant.text,
                workspace_id=workspace_id,
                top_k=pool_size,
                score_threshold=score_threshold,
                search_mode=search_mode,
                collection_filter=collection_filter,
                document_ids=document_ids,
            )
            for result in variant_results:
                provenance_by_chunk_id.setdefault(result.chunk_id, []).append(variant.source)
                existing = best_by_chunk_id.get(result.chunk_id)
                if existing is None or result.relevance_score > existing.relevance_score:
                    best_by_chunk_id[result.chunk_id] = result

        ranked = sorted(best_by_chunk_id.values(), key=lambda r: (-r.relevance_score, r.chunk_id))[:top_k]

        annotated: list[RetrievalResult] = []
        for result in ranked:
            metadata_with_provenance = dict(result.metadata)
            metadata_with_provenance["phase5a_query_variant_sources"] = provenance_by_chunk_id[result.chunk_id]
            annotated.append(
                RetrievalResult(
                    chunk_id=result.chunk_id,
                    text=result.text,
                    relevance_score=result.relevance_score,
                    metadata=metadata_with_provenance,
                )
            )
        return annotated
