"""Team 4B response assembly (Task 7.2).

Transforms Task 7.1's internal `RAGServiceResult` into the official
`QueryResponse` contract (Requirement 6: Source Attribution): converts
each raw `RetrievalResult` into a `SourceAttribution`, sorts by
relevance_score descending, and deduplicates by (document_id,
page_number, start_timestamp, end_timestamp).

APPROVED ARCHITECTURE:

    FastAPI/API layer (future Task 8.1)
            |
            v
        RAGService (Task 7.1, unmodified)
            |
            v
    response assembly (this module)
            |
            v
        QueryResponse

SCOPE NOTE (Task 7.2 only): this module does NOT implement Task 8.1's
API routes, does not call Ollama/Qdrant/Redis, does not perform another
retrieval or generation pass, and does not modify `RAGService`,
`HybridRetriever`, `ConversationManager`, `LLMGenerator`, or any Task 1.2
model.

REUSED, NOT REIMPLEMENTED, ADAPTER: the Team 4A -> Team 4B metadata
mapping (pdf/mp4/youtube -> document/video, document_id := job_id,
document_title, section_heading, and the YouTube end_timestamp fallback)
is NOT reimplemented here. It already runs inside
`VectorStoreManager.search_similar()` (Task 2.1/3.2's
`normalize_payload()` and its helpers), so every `RetrievalResult` this
module ever receives already carries `document_id`, `document_title`,
`section_heading`, and `end_timestamp` as computed metadata keys, plus
passthrough raw fields (`page_number`, `start_timestamp`) that are only
ever present for the source types that actually have them -- confirmed
by direct inspection of real `VectorStoreManager` output for both a PDF
chunk and a YouTube chunk (see this task's report), not assumed. This
module's `to_source_attribution()` is a plain, direct reader of that
already-computed metadata dict; it contains no pdf/mp4/youtube-specific
branching of its own.

DEDUPLICATION KEY DESIGN: `(document_id, page_number, start_timestamp,
end_timestamp)`. This single 4-tuple key correctly implements both
halves of Requirement 6.5 without needing a separate document/video type
flag (`SourceAttribution` itself has no such field, by the official
contract): a document-type attribution's `start_timestamp`/
`end_timestamp` are always both `None` and a video-type attribution's
`page_number` is always `None` (confirmed by direct inspection -- raw
PDF/MP4 payloads never carry YouTube-only fields and vice versa), so two
document attributions collide only when `document_id` AND `page_number`
match, and two video attributions collide only when `document_id` AND
both timestamps match -- exactly Requirement 6.5's stated behavior, with
no possibility of a document-type and a video-type attribution ever
colliding with each other. When a collision occurs, the FIRST (highest-
relevance, since input is sorted before deduplication) attribution for
that key is kept.

ORDERING DESIGN: `HybridRetriever` (Task 3.2) already returns results
sorted by `(-relevance_score, chunk_id)` in every search mode -- verified
by inspection of `_retrieve_semantic_only`/`_retrieve_keyword_only`/
`_retrieve_hybrid`, all of which end with exactly that sort key. This
module RE-SORTS anyway with the same `(-relevance_score, chunk_id)` key
rather than trusting that upstream invariant implicitly: Requirement 6's
ordering guarantee is a property of the FINAL response this module
produces, and this is the layer that should own and guarantee it
directly, independent of whether some future change to `HybridRetriever`
altered its own output order. This is a deliberate, minimal,
non-duplicative choice (a single `list.sort()` call, not a
reimplementation of RRF or any retrieval logic) -- flagged for
visibility, not because it's expected to ever actually reorder anything
given the current `HybridRetriever` implementation.

RETRIEVAL_METADATA: passed through from `RAGServiceResult.retrieval_metadata`
completely unmodified -- no new fields added, no existing fields renamed
or removed, per the explicit instruction not to invent an expanded
schema.
"""

from __future__ import annotations

from app.models.query import QueryResponse, SourceAttribution
from app.models.retrieval import RetrievalResult
from app.services.rag_service import RAGServiceResult


def to_source_attribution(result: RetrievalResult) -> SourceAttribution:
    """Convert one `RetrievalResult` into a `SourceAttribution`,
    reading exclusively from its already-normalized `metadata` dict
    (see module docstring) -- no mapping logic of this module's own.

    Raises `ValueError` if `document_id`/`document_title` are
    missing or not strings in the supplied metadata (which should not
    happen given the upstream adapter's guarantees) -- per the explicit
    instruction to fail clearly rather than fabricate a placeholder
    value for genuinely invalid internal data. This also gives mypy a
    concrete `str` type to narrow to before constructing
    `SourceAttribution`, whose fields are typed `str`, not `str | None`.
    """

    metadata = result.metadata
    document_id = metadata.get("document_id")
    document_title = metadata.get("document_title")
    if not isinstance(document_id, str) or not isinstance(document_title, str):
        raise ValueError(
            f"RetrievalResult {result.chunk_id!r} is missing valid document_id/document_title "
            f"metadata (both required by SourceAttribution): {metadata!r}"
        )

    return SourceAttribution(
        document_id=document_id,
        document_title=document_title,
        chunk_id=result.chunk_id,
        relevance_score=result.relevance_score,
        page_number=metadata.get("page_number"),
        section_heading=metadata.get("section_heading"),
        start_timestamp=metadata.get("start_timestamp"),
        end_timestamp=metadata.get("end_timestamp"),
    )


def _deduplication_key(attribution: SourceAttribution) -> tuple[str, int | None, float | None, float | None]:
    """See module docstring's "Deduplication key design"."""

    return (attribution.document_id, attribution.page_number, attribution.start_timestamp, attribution.end_timestamp)


def _sort_and_deduplicate(attributions: list[SourceAttribution]) -> list[SourceAttribution]:
    ordered = sorted(attributions, key=lambda attribution: (-attribution.relevance_score, attribution.chunk_id))

    seen: set[tuple[str, int | None, float | None, float | None]] = set()
    deduplicated: list[SourceAttribution] = []
    for attribution in ordered:
        key = _deduplication_key(attribution)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(attribution)

    return deduplicated


def assemble_query_response(rag_result: RAGServiceResult) -> QueryResponse:
    """Transform Task 7.1's internal `RAGServiceResult` into the
    official `QueryResponse` contract: converts every retrieval result
    into a `SourceAttribution`, sorts by relevance_score descending
    (chunk_id ascending tie-break), deduplicates by (document_id,
    page_number, start_timestamp, end_timestamp), and passes `answer`,
    `session_id`, and `retrieval_metadata` straight through unmodified.
    """

    attributions = [to_source_attribution(result) for result in rag_result.retrieval_results]
    final_attributions = _sort_and_deduplicate(attributions)

    return QueryResponse(
        answer=rag_result.answer,
        session_id=rag_result.session_id,
        source_attributions=final_attributions,
        retrieval_metadata=rag_result.retrieval_metadata,
    )
