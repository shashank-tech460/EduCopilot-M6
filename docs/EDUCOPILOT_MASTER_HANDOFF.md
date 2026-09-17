# EduCopilot --- Master Engineering Handoff

## Purpose

Single source of truth for Claude Code and future engineering work on
the EduCopilot MVP.

**Repository root:**
`D:\Major_Project\project\EduCopilot-M6-Local\EduCopilot-M6-Local`

**Current milestone:** M6 stabilization, local E2E, and RAG quality
work.

**Core product goal:** reliable educational RAG over PDFs, YouTube
videos, and MP4/video content, supporting English, Hindi, and Hinglish
queries/content, grounded answers, and correct source
provenance/citations.

------------------------------------------------------------------------

## 1. Engineering Rules

1.  Diagnose root causes before patching.
2.  No question-specific hacks.
3.  Prefer generalizable, deterministic architecture.
4.  Preserve working components unless evidence shows a defect.
5.  Never fabricate tests, metrics, latency, relevance judgments, or
    model comparisons.
6.  Use real content for retrieval-quality evaluation.
7.  Never expose secrets from `.env` or `.env.local`.
8.  Protect canonical production data during experiments.
9.  Make narrowly scoped changes; run focused tests and then regression.
10. M7 features are frozen until the M6/core product loop is strong.
11. Claude Code works against the actual local repository; ZIPs are
    backups/snapshots, not the primary development workflow.
12. Before significant changes: inspect the actual current repository,
    then implement only authorized scope.

------------------------------------------------------------------------

## 2. Repository and Services

``` text
EduCopilot-M6-Local
├── team4a
├── team4b
├── team4c
├── infra
├── docs
└── scripts
```

## Canonical vs. non-canonical directories

Confirmed by direct repository inspection (2026-09-17). Several
sibling/backup directories exist at the repository root alongside the
three team directories. Only the plain, unsuffixed names are canonical:

-   **`team4a`** -- active/canonical Team4A. Non-canonical siblings:
    `team4a-new` (contains a `4a-service` subfolder, a different
    reorganization attempt), `team4a-backup-before-transcript-windowing`,
    `team4a-before-youtube-hindi-fallback` (a pre-fallback snapshot;
    `team4a` itself contains the newer `canonical_extraction.py` and
    `test_youtube_language_fallback.py` that this backup lacks).
-   **`team4b`** -- active/canonical Team4B. Non-canonical sibling:
    `team4b-context-provenance-temp`.
-   **`team4c`** -- active/canonical Team4C (no known non-canonical
    siblings at the time of this correction).

Do not edit any `-new`, `-backup-*`, `-before-*`, or `-*-temp` suffixed
directory expecting it to affect the running system. If a future
session is unsure which copy is live, check file modification times and
cross-reference against the service startup commands in this section,
which always point at the unsuffixed directory names.

Within `team4b` itself, the live tree also contains numerous backup
sibling files next to the active modules they were copied from (e.g.
`vector_store.py.bak`, `llm_generator.py.backup` /
`.m6-backup` / `.m6-before-num-predict`, `config.py.backup`,
`rag_service.py.m6-backup`, `casual_intent.py.before-hinglish-fix`,
`test_ragas_adapter.py.m6-before-ragas-fix`). The file with no suffix
(no `.bak`/`.backup`/`.m6-*`/`.before-*` extension) is always the active
one actually imported by the application.

Local services:

-   Team4C: `http://localhost:3000`
-   Team4A: `http://localhost:8001`
-   Team4B: `http://localhost:8002`
-   MongoDB: `27017`
-   Redis 4A: `6379`
-   Redis 4B: `6380`
-   Qdrant: `6333`
-   Ollama: `11434`

Team4A startup:

``` powershell
cd D:\Major_Project\project\EduCopilot-M6-Local\EduCopilot-M6-Local eam4a
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --log-level debug
```

Team4B startup:

``` powershell
cd D:\Major_Project\project\EduCopilot-M6-Local\EduCopilot-M6-Local eam4b
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8002 --log-level debug
```

Do not overwrite `.env` or `.env.local` blindly. Preserve real secrets
and never print them.

------------------------------------------------------------------------

# 3. Team4A Status

Team4A is substantially implemented and has passed extensive regression
testing.

## Canonical ingestion

Canonical Qdrant collection:

`educopilot_chunks`

Known successful PDF state:

-   115 canonical chunks
-   `all-MiniLM-L6-v2`
-   publication 115/115
-   POST `/v1/ingest` returned 202
-   browser showed OS PDF Ready

Canonical identity metadata includes:

-   `chunk_id`
-   `document_id`
-   `workspace_id`
-   `user_id`
-   `ingestion_generation`

## YouTube

Known test video `H9ICBRHzZLo` had no English transcript but had Hindi
auto-generated transcript.

Hindi fallback is configured for transcript-unavailable cases only. It
must not convert inaccessible-video failures into language fallback.

Current relevant setting:

`youtube_fallback_language = "hi"`

Recent tests:

-   `test_youtube_language_fallback.py`: 10 passed
-   YouTube tests: 114 passed
-   full Team4A: 860 passed, 5 skipped, 0 failed

MP4/YouTube follow the same canonical
extraction/windowing/metadata/publication direction.

**Do not call Team4A literally perfect.** Final system-level acceptance
still requires 4A → 4B → 4C E2E validation.

------------------------------------------------------------------------

# 4. Team4B Core RAG Architecture

Team4B is the primary technical focus of current M6 work.

Production flow:

``` text
Query
  ↓
Casual-intent gate
  ↓
Follow-up enrichment when applicable
  ↓
HybridRetriever
  ├── Qdrant semantic retrieval
  └── BM25 lexical retrieval
          ↓
       RRF fusion
          ↓
Generation-authority filtering
          ↓
LLM generation
          ↓
Metadata-based response/citations
```

Important classes:

-   `RAGService`
-   `HybridRetriever`
-   `BM25Index`
-   `Embedder`
-   `VectorStoreManager`
-   `RealQdrantClient`
-   `GenerationAuthorityClient`
-   `LLMGenerator`
-   response assembly/citation logic

`HybridRetriever.retrieve()`:

``` text
retrieve(
    query: str,
    *,
    workspace_id: str,
    top_k: int,
    score_threshold: float,
    search_mode: SearchMode = "hybrid",
    collection_filter: list[str] | None = None,
    document_ids: list[str] | None = None
)
```

Qdrant architecture:

`VectorStoreManager.search_similar()` → `QdrantClientProtocol.search()`
→ `RealQdrantClient.search()` → raw Qdrant `query_points()`

Installed qdrant-client: `1.19.0`.

Do NOT downgrade it, call an unavailable `.search()`, or bypass the
abstraction.

**Reproducibility note (confirmed 2026-09-17):** `team4b/requirements.txt`
currently lists `qdrant-client` with **no version pin**. The `1.19.0`
version above reflects what is actually installed in the current local
environment, not a guarantee from `requirements.txt` -- a fresh
`pip install -r requirements.txt` could silently resolve a different
qdrant-client version. This handoff does not change `requirements.txt`;
pinning it is flagged as follow-up work, not done here.

------------------------------------------------------------------------

# 5. Team4B Isolation and Authority Guarantees

These are strong and must be preserved.

## Workspace isolation

`workspace_id` filtering is mandatory and applied at candidate retrieval
construction, not as a post-hoc filter.

Both semantic and lexical retrieval are workspace-aware.

## Generation authority

Generation-authority filtering occurs before stale/superseded candidates
reach the LLM.

Identity includes:

-   `document_id`
-   `ingestion_generation`

Lookup failure is fail-closed.

## Document/source filters

Request-level filters are supplied by Team4C and are not derived from
history.

Empty `document_ids` means no documents are allowed.

------------------------------------------------------------------------

# 6. Citation Integrity

Citations are constructed from `RetrievalResult.metadata`, not from
LLM-generated citation text.

This makes citation-record fabrication through generated prose
structurally difficult/impossible.

Video timestamps and PDF/page provenance are carried into generation
context as part of M6 provenance work.

Preserve metadata-driven citation construction.

------------------------------------------------------------------------

# 7. Casual Intent

Casual intent is deterministic and checked before retrieval.

Current English/Hindi/Hinglish examples include:

-   `thank you`
-   `thanks`
-   `hi kaise ho`
-   `hello kaise ho`
-   `kya haal hai`
-   `kaise ho`
-   `kaise chal raha hai`
-   `dhanyavaad`
-   `shukriya`

Normalization:

-   lowercase
-   strip `!?.,`
-   collapse whitespace
-   whole-phrase exact matching

Technical Hinglish must remain RAG.

Do not add fuzzy/LLM classification just to fix individual messages.

------------------------------------------------------------------------

# 8. Ollama Reliability

Current local configuration:

``` text
OLLAMA_NUM_GPU=0
LLM_GENERATION_TIMEOUT_SECONDS=180
OLLAMA_NUM_PREDICT=1024
```

Ollama version: `0.34.0`

Model: `llama3:latest`, approximately 4.7 GB, 8B Q4_0, context 8192.

These reliability settings are currently frozen unless evidence requires
a change.

------------------------------------------------------------------------

# 9. Team4B Testing

Recent known state:

-   BM25 focused tests: 49 passed
-   retrieval-related tests: 125 passed
-   API tests: 127 passed
-   full Team4B: 1067 passed, 0 failed
-   `test_ragas_adapter.py` has a pre-existing dependency gap when its
    dependency is unavailable

Passing unit/integration tests are not the same thing as systematic
retrieval-quality measurement.

------------------------------------------------------------------------

# 10. Phase 1 --- BM25 Multilingual Lexical Support

**STATUS: NOT STARTED**

Corrected 2026-09-17 by direct repository inspection: the production
tokenizer in `team4b/app/services/bm25_index.py` (`default_tokenizer`,
used by `BM25Index()` as constructed in `team4b/app/api/dependencies.py`
with no override) is still:

``` python
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")
```

This is an ASCII-only alphanumeric tokenizer. It contains no Devanagari
Unicode range and no Devanagari-aware tokenization of any kind. Any
Hindi text tokenizes to an empty token list under BM25 today.
`test_bm25_index.py` contains no Devanagari-related test cases.

A previous version of this handoff incorrectly stated this work as
COMPLETE. That was inaccurate and has been corrected here. Devanagari
BM25 lexical support has not yet been designed or implemented in this
repository -- it remains open work, not a regression to protect.

------------------------------------------------------------------------

# 11. Multilingual RAG Problem

Product requirement:

-   English content
-   Hindi content
-   mixed-language content
-   English queries
-   Hindi queries
-   Hinglish queries
-   cross-language retrieval

Current semantic embedding model:

`all-MiniLM-L6-v2`

The model is English-centric and is the primary unresolved semantic
limitation for reliable Hindi/cross-language retrieval.

BM25 does not currently handle Devanagari lexically (see Section 10 --
its tokenizer is ASCII-only). Even once Devanagari tokenization is
implemented, BM25 would still be unable to provide semantic
cross-language bridging.

Production vector score threshold:

`default_score_threshold = 0.3`

Weak cross-language semantic matches can be excluded before RRF.

RRF is not currently identified as the root cause.

Do not replace RRF, Qdrant, workspace filtering, generation authority,
or the DI/protocol architecture without evidence.

------------------------------------------------------------------------

# 12. Phase 2 --- Multilingual Embedding Evaluation

**STATUS: Harness design specified in this document; implementation is
not yet present in the repository.**

Corrected 2026-09-17 by direct repository inspection: a full-repository
search for `phase2_multilingual_embedding_evaluation.py` (and any
`*phase2*` file) found no such file anywhere in the repository. The
design below is a specification for what to build, not a description of
existing, working code. A previous version of this handoff incorrectly
implied the harness already existed in corrected form; that was
inaccurate and has been corrected here.

Current:

`all-MiniLM-L6-v2`

Candidate:

`paraphrase-multilingual-MiniLM-L12-v2`

No migration decision has been made.

The candidate's actual output dimension must be discovered at runtime
rather than assumed.

## Required harness protections (design spec -- not yet implemented)

When this harness is built, it must:

1.  Validate Qdrant/Mongo connectivity.
2.  Confirm canonical `educopilot_chunks` exists and has content.
3.  Discover actual embedding dimensions before constructing
    model-specific evaluation settings/collections.
4.  Create separate temporary collections.
5.  Read canonical chunks without modifying them.
6.  Re-embed copied chunks.
7.  Use the real unmodified `HybridRetriever`.
8.  Use BM25 + vector + RRF.
9.  Test both:
    -   raw threshold `0.0`
    -   actual production threshold read from Settings
10. Measure:

-   Recall@1
-   Recall@3
-   Recall@5
-   MRR
-   bulk re-embedding time
-   per-query retrieval latency

11. Use original canonical `chunk_id` values as ground-truth
    identifiers.
12. Protect canonical `educopilot_chunks` with a runtime write-target
    guard.
13. Leave temporary collections unless cleanup is explicitly enabled.

## Design pitfalls to avoid (identified from prior design iterations, not from an existing implementation)

No implementation of this harness currently exists in the repository, so
there are no "prior bugs" to have fixed in code. These pitfalls were
identified during design review of earlier drafts of this plan and must
be avoided when the harness is actually implemented:

-   Candidate dimension discovery happening too late.
-   `RealQdrantClient` being constructed incorrectly.
-   Qdrant write/read collection names being mismatched.

------------------------------------------------------------------------

# 13. Phase 2 Ground Truth

`GROUND_TRUTH` must contain only real, human-verified relevance
judgments.

Example:

``` python
{
    "query": "...",
    "query_language": "english",
    "source_language": "english",
    "source_type": "pdf",
    "subject": "dbms",
    "workspace_id": "...",
    "relevant_chunk_ids": {"real-chunk-id-1", "real-chunk-id-2"},
}
```

Never invent:

-   chunk IDs
-   queries presented as real-content benchmarks
-   relevance judgments
-   metrics

Desired matrix where real content exists:

-   English → English
-   Hindi → Hindi
-   Hinglish → Hindi
-   English → Hindi
-   Hindi → English
-   Hinglish → English

Across:

-   PDF
-   YouTube
-   MP4

Across multiple real educational subjects.

If a matrix cell is not represented by real content, report it as
unavailable rather than manufacturing data.

------------------------------------------------------------------------

# 14. Phase 2 Decision Rule

Do not migrate embeddings because the candidate sounds better
theoretically.

Run both models on the same real benchmark and compare:

-   Recall@1
-   Recall@3
-   Recall@5
-   MRR
-   same-language performance
-   cross-language performance
-   threshold behavior
-   latency
-   re-embedding cost
-   retrieved chunk quality

Only then make the migration decision.

------------------------------------------------------------------------

# 15. Complete RAG Audit --- Confirmed Strong Areas

Confirmed strong areas:

-   workspace isolation
-   generation-authority filtering
-   metadata-only citation construction
-   deterministic casual gate
-   deterministic follow-up handling
-   error observability
-   RRF
-   production DI/protocol architecture
-   provenance-aware generation context
-   explicit insufficient-context branch
-   source/document filtering
-   fresh-conversation isolation

Preserve these.

------------------------------------------------------------------------

# 16. Confirmed RAG Weaknesses

## Critical

### C1 --- Multilingual semantic retrieval

The current embedding model is the main unresolved product gap.

Action: execute Phase 2 evaluation against real content.

### C2 --- Retrieval-quality evaluation

There is no permanent Recall@k/MRR benchmark in the running Team4B
system.

Action: establish a repeatable real-content benchmark.

------------------------------------------------------------------------

# 17. High-Priority Improvements

## H1 --- BM25 rebuild per query

BM25 currently rebuilds the relevant workspace index per search.

This is acceptable for correctness and smaller corpora but creates scale
risk.

Approximate concerns:

-   \~1K chunks: likely fine
-   \~10K: measure
-   \~100K: meaningful latency risk
-   \~1M: likely requires amortization/caching

Any future caching must preserve workspace isolation and avoid
cross-workspace IDF leakage.

## H2 --- Score threshold validation

Production threshold is currently read as `0.3`.

After embedding evaluation/migration, inspect score distributions and
validate threshold behavior.

Do not blindly tune it.

## H3 --- Reranking

No reranker currently exists.

Future option only if measured retrieval quality remains insufficient.

## H4 --- Query expansion/rewriting

No general query expansion/decomposition exists.

Current follow-up enrichment is intentionally narrow.

------------------------------------------------------------------------

# 18. Medium/Future Improvements

Medium:

-   context overlap redundancy
-   per-stage latency observability
-   confirming practical long-history token bounds

Future:

-   retrieval/query embedding caching
-   answer-language control
-   adaptive top-k
-   adaptive thresholding
-   semantic deduplication
-   reranking
-   query expansion
-   query decomposition
-   multi-hop retrieval
-   high-concurrency optimization
-   advanced tracing

Do not implement these simply to make the architecture more
sophisticated.

------------------------------------------------------------------------

# 19. Grounding

The system prompt requires context-only answering and discourages
fabrication.

Insufficient-context behavior exists.

Known limitation:

The current empty-retrieval branch cannot perfectly distinguish
"retrieved but irrelevant" context from genuinely useful context.

This should be evaluated during grounding work.

------------------------------------------------------------------------

# 20. Security

Current controls include:

-   workspace filtering
-   generation-authority filtering
-   fail-closed authority behavior
-   retrieved-context-as-data prompt instruction
-   no known improper secret logging

Prompt injection remains a residual risk because prompt-only defenses
are not absolute.

Future security work should strengthen structural defenses for malicious
uploaded content.

------------------------------------------------------------------------

# 21. Team4C Status

Team4C scope includes:

-   dashboard
-   chat
-   source attribution
-   video player
-   file manager
-   workspace isolation
-   Zustand application state
-   resilience

A React Strict Mode race in `useActiveConversation.ts` that disabled
chat input was fixed and typecheck passed.

Integrated flow has worked:

Team4C `/api/chat` → Team4B `/api/v1/query` → grounded answer → source
citations

Known remaining product concern:

**persistent chat history** --- chats have previously disappeared after
refresh.

Do not touch ChatPanel/useActiveConversation unless new evidence
identifies a defect.

Do not call Team4C literally perfect; final system acceptance remains.

------------------------------------------------------------------------

# 22. Overall Completion Status

Do not claim 4A + 4B + 4C are 100% complete.

Current:

-   Team4A: substantially implemented; final E2E acceptance remains.
-   Team4B: strong core architecture; multilingual semantic retrieval
    and systematic retrieval evaluation remain.
-   Team4C: component scope strong; persistent history and full system
    acceptance remain.
-   Overall 4A → 4B → 4C integration/E2E/final validation remains.

------------------------------------------------------------------------

# 23. Frozen Architectural Decisions

Do not change without explicit evidence:

1.  `VectorStoreManager` → protocol → `RealQdrantClient`.
2.  Current Qdrant client compatibility approach.
3.  RRF fusion.
4.  Workspace filtering before candidate construction.
5.  Generation-authority filtering before LLM generation.
6.  Metadata-driven citation construction.
7.  Deterministic casual/follow-up gates.
8.  Current Ollama reliability configuration.
9.  M7 feature freeze.

------------------------------------------------------------------------

# 24. M6 Roadmap

### Phase 1

BM25 Unicode/Devanagari support.

**NOT STARTED** (see Section 10)

### Phase 2

Multilingual embedding evaluation.

**NEXT** (harness not yet implemented -- see Section 12)

### Phase 3

Permanent retrieval-quality benchmark.

### Phase 4

Evidence-driven retrieval optimization:

-   threshold
-   top-k
-   RRF tuning
-   deduplication
-   reranking only if justified

### Phase 5

Grounding and answer quality.

### Phase 6

Citation quality/relevance.

### Phase 7

Security hardening.

### Phase 8

Performance/reliability/scalability.

### Phase 9

Final Team4B acceptance.

### Phase 10

Full 4A → 4B → 4C local E2E.

### Phase 11

Production preparation/deployment.

### Phase 12

Production E2E.

### Final

Sellable MVP readiness only after the above.

------------------------------------------------------------------------

# 25. Immediate Next Action

1.  **OUTSTANDING -- not yet done.** Implement the Phase 2 evaluation
    harness (design specified in Section 12) and place it at:

`team4b/scripts/phase2_multilingual_embedding_evaluation.py`

    Confirmed by full-repository search (2026-09-17): this file does
    not currently exist anywhere in the repository.

2.  Inspect actual canonical Qdrant content.
3.  Identify real documents, workspaces, source types, languages,
    subjects, and chunk IDs.
4.  Build human-verified `GROUND_TRUTH`.
5.  Run current-model baseline.
6.  Run candidate-model evaluation.
7.  Compare results.
8.  Decide migration from evidence.

Do not re-embed canonical production vectors until the evaluation
supports migration.

------------------------------------------------------------------------

# 26. Claude Code Protocol

For every engineering task:

1.  Read this handoff.
2.  Inspect the current local repository.
3.  Inspect actual relevant source files.
4.  Never assume an old ZIP matches current state.
5.  Diagnose root cause.
6.  State exact intended file changes.
7.  Modify only authorized scope.
8.  Preserve secrets.
9.  Run focused tests.
10. Run appropriate regression.
11. Report exact files changed.
12. Report exact test results.
13. Never fabricate results.
14. Never silently modify unrelated services.
15. For experiments, isolate temporary resources from canonical
    production resources.
16. Require explicit authorization for destructive operations.

------------------------------------------------------------------------

# 27. Definition of RAG-Complete

Team4B RAG is complete for the MVP only when:

1.  Multilingual embedding evaluation has run against real content.
2.  Embedding migration decision is evidence-backed.
3.  Repeatable Recall@k/MRR benchmark exists.
4.  Future retrieval changes can be measured against it.
5.  BM25 latency is measured at realistic workspace scale.
6.  Any BM25 optimization preserves workspace isolation.
7.  Grounding behavior is validated.
8.  Citation relevance is validated.
9.  English/Hindi/Hinglish behavior is validated.
10. PDF/YouTube/MP4 behavior is validated.
11. Source/document filtering is validated.
12. Existing isolation, authority, citation, casual/follow-up, and
    reliability guarantees remain regression-green.

------------------------------------------------------------------------

# 28. Golden Rule

**Do not optimize for one failed query. Optimize the retrieval system
for the full product requirement and prove improvements with repeatable
measurements.**

The goal is reliable multilingual educational RAG across real PDFs,
YouTube videos, MP4s, subjects, workspaces, and query languages, with
grounded answers and correct provenance.
