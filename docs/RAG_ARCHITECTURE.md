# RAG Architecture (Frozen, as of Phase 5K)

This document describes Team4B's **actual, current, frozen** retrieval and
generation architecture, as validated through Phases 5D–5K. It is factual,
not aspirational — anything described here is either true of the running
code today or explicitly marked as investigated-and-rejected.

## Design principle: generalized, not subject-specific

There is no subject list, no per-subject retrieval branch, and no
hardcoded query/answer mapping anywhere in the retrieval or generation
code. The same `HybridRetriever` → `LLMGenerator` pipeline answers
Operating Systems, DBMS, Data Structures, Computer Networks, and any other
subject a workspace's documents cover, using only:

- the query text
- the `workspace_id` (mandatory, enforced pre-fusion)
- optional `document_ids` / `collection_filter` (source-type) narrowing

Every experimental change considered in Phases 5I–5K that would have
introduced language- or subject-specific logic was explicitly rejected on
those grounds (see "Investigated and rejected" below).

## Pipeline

```
query
  |
  v
HybridRetriever.retrieve(query, workspace_id, top_k, score_threshold, search_mode, ...)
  |
  +-- search_mode="semantic": vector leg only
  +-- search_mode="keyword":  BM25 leg only
  +-- search_mode="hybrid" (production default):
  |     semantic leg (Qdrant cosine similarity) -----\
  |     BM25 leg (in-memory rank_bm25, rebuilt          +--> Reciprocal Rank Fusion --> normalize --> threshold --> top_k
  |       per-workspace per query) ------------------/
  |
  v
Generation-authority filter (MongoDB-backed, fail-closed) -- applied to
BOTH legs' candidates BEFORE fusion, never after
  |
  v
LLMGenerator.generate(query, retrieved_results, conversation_history)
  |
  +-- build_prompt(): system instructions + untrusted-context-delimited
  |     evidence blocks + conversation history + current question
  +-- Ollama /api/generate (llama3, single flat-string prompt)
  +-- Phase 5K output-side guard (see SECURITY_ARCHITECTURE.md)
  |
  v
grounded answer (or INSUFFICIENT_CONTEXT_MESSAGE)
```

## Current production configuration

| Setting | Value |
|---|---|
| `top_k` | 5 |
| `score_threshold` | 0.3 |
| `search_mode` (default) | `hybrid` |
| `rrf_k` | 60 |
| `hybrid_candidate_pool_size` | 100 |
| Reranker | **disabled** |
| Embedding model | `all-MiniLM-L6-v2` |
| BM25 tokenizer | ASCII alnum runs + Devanagari runs (script-aware, not language-aware) |
| LLM | Ollama `llama3` (8B, local, CPU inference in this environment) |

None of these defaults were changed anywhere in Phases 5I–5K — every
retrieval-tuning experiment run against them concluded with "do not
change" (see `docs/RAG_VALIDATION.md`).

## Isolation and authority guarantees

- **Workspace isolation**: `workspace_id` is a mandatory, keyword-only
  parameter on both `BM25Index.search()` and
  `VectorStoreManager.search_similar()`. There is no code path that
  retrieves "every workspace." BM25 additionally rebuilds a **fresh,
  workspace-scoped** index per query so a cross-workspace document can
  never influence IDF/ranking statistics, not merely be filtered out
  afterward.
- **Document filtering**: `document_ids=[]` (present but empty) is a
  deliberate, non-widening narrowing to zero results — never treated as
  "no restriction." `document_ids=[...]` narrows both retrieval legs
  before fusion.
- **Generation authority**: every candidate's `document_id` +
  `ingestion_generation` metadata is checked against Team4A's current
  generation for that document (one batched Mongo read per `retrieve()`
  call). A document with no verifiable current generation is excluded —
  fail-closed, never a default-allow.
- **Citations**: built directly from the same `RetrievalResult` metadata
  already used for isolation — never re-derived from the model's own
  output text.

## Multilingual behavior (accurate, not aspirational)

- English retrieval is consistently strong.
- Hindi (Devanagari) retrieval works for many queries but is
  **phrasing-sensitive**: a compound-word spacing difference between the
  query and the source text's own tokenization can cause a complete
  retrieval miss even when the content exists (see
  `docs/KNOWN_LIMITATIONS.md`).
- Hinglish (Romanized Hindi/English mix) retrieval works well for
  same-language content.
- Cross-script retrieval (a Latin-script query against Devanagari-only
  source content, or vice versa) is **measurably weaker** — this is a
  known, documented, unresolved limitation, not a solved problem.

## Source types

- **PDF**: extracted text, chunked, embedded, indexed. Citations include
  document title and page number when available.
- **YouTube**: transcript text, chunked, embedded, indexed. Citations
  include video title and timestamp range when available. Answers are
  grounded in **transcript text only** — there is no visual-frame
  understanding anywhere in this pipeline, and this is never claimed.
- **MP4 upload**: no content with a distinct `mp4` source-type tag was
  found in either the canonical or validation Qdrant collection as of
  Phase 5J/5K's live audits — video acceptance evidence exists only via
  YouTube-derived transcripts.

## Investigated and rejected

These alternatives were forensically evaluated (offline experiments
against real corpora, never applied to production without evidence) and
explicitly **not adopted**. Detail and evidence: `docs/RAG_VALIDATION.md`
and the individual phase reports in `team4b/data/`.

| Alternative | Phase | Why rejected |
|---|---|---|
| Multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`) | 5I-B | Looked like a win in isolated semantic-only testing, but full hybrid+RRF simulation showed no net improvement and a new Hindi→Hindi regression |
| Script-aware (Devanagari→Latin transliteration) BM25 augmentation | 5I-C | Zero net hybrid-level improvement; BM25-only aggregate got measurably worse; the one targeted cross-script miss got a *worse* rank inside RRF; ~3.8–4.9x latency increase; new false-positive risk on common Hindi function words |
| Enabling the reranker in production | 5H, 5I-B | Promising signal but insufficient evidence: fixed some misses, introduced a new regression, added 1.8–2.0s+ latency per query, cannot recover a candidate absent from the initial pool |
| Query threshold / top_k changes | 5I-B | Threshold sweep (0.0–0.7) was completely flat; top_k increases plateau by k=20 without resolving the hardest miss, and larger top_k risks generation-quality regressions never evaluated |
| Multi-query expansion / query transformation (`multi_query_retrieval.py`, `query_transform.py`) | 5A | Built and unit-tested as an investigation; deliberately kept **unwired** from `dependencies.py`/`rag_service.py`, enforced by a structural regression test (`test_phase5a_cross_script_retrieval_evaluation.py`) — not a current part of the retrieval path |
| Ollama native `system` role field (real template-level role separation) instead of flat-string delimiters | 5F | Live adversarial testing showed this was a **net regression**: did not fix the two most serious injection cases, only marginally reduced one, and introduced two new compliance failures the delimiter-only version already resisted |
| A second LLM call / classifier for output validation | 5K | Explicitly out of scope unless forensic evidence proved it necessary — it did not; a deterministic, single-call output guard proved sufficient (see `SECURITY_ARCHITECTURE.md`) |

## What "frozen" means

As of Phase 5K, no further changes to embeddings, BM25, RRF, reranker
state, `top_k`, `score_threshold`, or cross-language retrieval behavior
are planned without new, specific evidence. The one exception already made
is the Phase 5K output-side security guard, which changes generation
post-processing only — it does not touch retrieval at all.
