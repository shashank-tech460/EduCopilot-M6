# Approved Team 4A ↔ Team 4B Contract Decisions

Recorded here (not re-litigated) so every later task implements the same,
already-approved contract. Source: the Final Architecture/Contract
Checkpoint, approved before Task 1.1 began. No Team 4A or Team 4C code is
modified by any of this.

## 1. Document identity

`document_id := Team 4A's job_id`.

> "`document_id` is currently mapped from Team 4A `job_id` because Team 4A
> does not expose a stable logical document identifier. This identifies
> an ingestion event rather than a persistent document across
> re-ingestion."

This exact wording must appear wherever `document_id` is documented in
code (Task 2.1) and in the requirement-traceability entries for
Requirement 1.6 and Property 2.

> **SUPERSEDED (MVP M3 identity correction).** The premise above --
> "Team 4A does not expose a stable logical document identifier" -- is no
> longer true. Team 4A's Phase 1/2C canonical ingestion path publishes a
> real, permanent `document_id` (Team 4C's own `File._id`) directly in
> every canonical chunk's payload, distinct from `job_id` (still one
> ingestion attempt, unchanged). `app/services/vector_store.py`'s
> `normalize_payload()` no longer remaps `document_id := job_id` -- it
> preserves whatever `document_id` is actually present in the payload
> (canonical chunks: the real File._id; any payload genuinely missing
> the field: absent/`None`, never silently backfilled from `job_id`).
> `job_id` itself is completely unaffected by this correction. The
> original text above is left in place, not deleted, as the historical
> record this file's own header says is "recorded here, not
> re-litigated" -- this note documents that the decision has since been
> revisited and corrected, not that it never existed.

## 2. Qdrant data flow

```
Team 4A ingestion → shared production Qdrant collection → Team 4B VectorStore/retrieval → RAG → Team 4C
```

Team 4B reads Team 4A's records **directly** from the shared production
collection. No republishing pipeline, no synchronization service, no new
API between 4A and 4B.

## 3. Shared collection ownership

Team 4B owns/provisions the shared production collection
(`Settings.qdrant_collection_name`, default
`team4b_shared_production_chunks` — see `app/core/config.py`). Team 4A's
local/demo collection (`team4a_ingested_chunks`) is separate and is never
read from or written to by Team 4B.

## 4. Vector configuration

384 dimensions, Cosine distance, `all-MiniLM-L6-v2` — matches Team 4A's
verified actual output. Configurable via `Settings.embedding_dimensions`
/ `Settings.embedding_distance` / `Settings.embedding_model_name`, not
hard-coded.

## 5. Read-side normalization adapter (to be implemented in Task 2.1, not here)

Lives entirely in Team 4B's read/query path (`VectorStoreManager.search_similar`
or an adjacent pure function it calls). Never an upsert-time transform.

- **source_type:** `pdf → document`, `mp4 → video`, `youtube → video`.
- **document_title:** `filename` for PDF/MP4; `video_title` (fallback to
  `filename` if absent) for YouTube.
- **section_heading:** text of the `Heading` with the lowest `level` in
  the chunk's `headings` list (first in list order if tied); `None` if
  the list is empty or absent.
- **YouTube end_timestamp fallback** (test for `None`/missing, never
  truthiness — `0.0` is a valid timestamp):
  ```python
  if source_type == "youtube" and end_timestamp is None:
      end_timestamp = start_timestamp + duration
  ```
  `duration` here is the per-segment `ChunkMetadata.duration` (sourced
  from `YouTubeSegment.duration`), not `YouTubeMetadata.duration_seconds`
  (whole-video duration) — confirmed from Team 4A's actual `schemas.py`.

## 6. Explicitly out of scope for Team 4B at this time

- No streaming API support (Team 4C's `useChat`/streaming expectation is
  a recorded future integration issue, not something to build
  speculatively now).
- No content-hash/filename-hash or other synthetic document identity.
- No multiple physical Qdrant collections (partitioning is satisfied via
  payload-field filtering on `source_type` / `document_id` within the one
  shared collection).

## 7. Corrective Task 1.2 note: two `SearchMode` representations coexist

`app/services/hybrid_retriever.py` already had its own
`SearchMode = Literal["hybrid", "semantic", "keyword"]` type alias
(Task 3.2) before the official `app.models.query.SearchMode` enum was
added (Corrective Task 1.2). Per that corrective task's explicit
instruction not to modify service implementations unless required,
`hybrid_retriever.py` was left untouched -- the two independently
express the same three values in different but compatible forms. A
future task that wires `RetrievalConfig`/`QueryRequest` into
`HybridRetriever.retrieve()` will need to convert between them (e.g.
`SearchMode.HYBRID.value` -> the `Literal`), which is a trivial,
values-preserving conversion, not a contract conflict.
