# EduCopilot — M6

EduCopilot is an educational Retrieval-Augmented-Generation (RAG) product
that lets students ask questions about their own course material (PDFs and
lecture videos) and get answers grounded in that material, with citations
back to the source.

**M6 milestone scope:** a generalized, workspace-isolated RAG backend
(Team4B) fed by an ingestion/extraction pipeline (Team4A), with a Next.js
frontend (Team4C). This README describes the current, actual state of the
system — not an aspirational one. See [Known limitations](#known-limitations)
and [Current M6 status](#current-m6-status) for what is and isn't done.

## Problem statement

Students have course PDFs and recorded lecture videos but no fast way to ask
"what does my own material say about X?" and get a trustworthy, cited
answer — one that says "I don't know" when the material doesn't cover the
question, rather than guessing.

## Major capabilities

- **Generalized RAG**: no subject-specific retrieval logic. The same
  architecture answers Operating Systems, DBMS, Data Structures, Computer
  Networks, and other subjects without per-subject code.
- **Hybrid retrieval**: semantic (Qdrant vector search) + BM25 keyword
  search, merged via Reciprocal Rank Fusion (RRF).
- **Multilingual support (with documented limits)**: English, Hindi
  (Devanagari), and Hinglish queries are all handled by the same pipeline.
  English retrieval is strong and reliable. Hindi and cross-script
  (Hinglish/English↔Hindi) retrieval work in many cases but are measurably
  weaker and phrasing-sensitive — see
  [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md). This is **not**
  claimed to be solved.
- **Supported source types**: PDF documents and YouTube-derived video
  transcripts. Answers from video sources are grounded in the
  **transcript text**, not visual frame content — no visual-video
  understanding exists in this pipeline.
- **Workspace and document isolation**: every retrieval call is scoped to a
  `workspace_id`, enforced before fusion, not after. Optional
  `document_ids`/source-type filtering narrows further, with the same
  isolation guarantee.
- **Generation authority**: a fail-closed check against the ingestion
  system's current-generation record for each document, so a
  since-superseded chunk can never appear in an answer.
- **Grounded generation with citations**: the LLM is instructed to answer
  only from retrieved context and to say so honestly when the context is
  insufficient, rather than fabricating.
- **Prompt-injection defenses**: untrusted-context delimiters + neutralization
  (Phase 5F) plus an output-side guard against forced-fixed-output attacks
  (Phase 5K). See [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md)
  for what is fixed and what residual risk remains.

## Architecture overview

```
User Query
    |
    v
Team4C (Next.js UI + API routes)
    |
    v
Team4B RAGService
    +-- ConversationManager (Redis-backed session history)
    +-- HybridRetriever
    |     +-- Semantic leg  -> Qdrant (educopilot_chunks)
    |     +-- BM25 leg      -> in-memory index, rebuilt from Qdrant
    |     +-- Reciprocal Rank Fusion -> normalized, thresholded, top_k
    +-- GenerationAuthorityClient (MongoDB-backed, fail-closed)
    +-- LLMGenerator -> Ollama (llama3) -> grounded answer + citations
    |
    v
Team4A (ingestion, extraction, chunking, embedding, Qdrant publishing)
```

Full detail: [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md).

### Team responsibilities

| Team | Responsibility | Status |
|---|---|---|
| **Team4A** | PDF/YouTube ingestion, text extraction, chunking, metadata, embedding, publishing to the canonical Qdrant collection | Stable; untouched by the Phase 5 RAG validation arc |
| **Team4B** | Query API, session/history, hybrid retrieval, generation authority, LLM generation, citations, security boundary | **RAG-accepted / frozen** as of Phase 5K — see [docs/M6_STATUS.md](docs/M6_STATUS.md) |
| **Team4C** | Next.js frontend, product integration, auth, UI | Exists and runs; **not** the subject of the Phase 5 RAG validation arc — see [docs/M6_STATUS.md](docs/M6_STATUS.md) for exactly what is and isn't verified |

## Services and ports (local development)

| Service | Default port (docker-compose) | Port actually used in this project's local multi-service runs |
|---|---|---|
| Team4A (ingestion API) | 8000 | 8001 |
| Team4B (RAG API) | 8000 (override via `TEAM4B_HOST_PORT`) | 8002 |
| Team4C (Next.js) | 3000 | 3000 |
| Qdrant | 6333 | 6333 |
| MongoDB | 27017 (standard) | 27017 |
| Redis | 6379 | 6379 |
| Ollama | 11434 | 11434 |

A disposable, fully isolated second stack (ports 8011/8012/3010, its own
Qdrant collection `educopilot_chunks_product_validation`) has been used for
product-level RAG validation without risking the protected corpus — see
[docs/m6-product-validation-isolation-environment.md](docs/m6-product-validation-isolation-environment.md).
It is not part of the deployed product.

## Local setup

Each service has its own detailed setup instructions — this is a pointer,
not a duplicate:

- **Team4A**: `team4a/requirements.txt`, `team4a/Dockerfile`, `team4a/docker-compose.yml`. Copy `team4a/.env` from your own values (no example file is currently committed for Team4A — coordinate with the ingestion owner for required variables).
- **Team4B**: see [team4b/README.md](team4b/README.md) for the full Docker deployment guide (prerequisites, build, startup, environment variables, health checks, troubleshooting). Copy `team4b/.env.example` (or `.env.docker.example` for the containerized variant) to `.env` and fill in real values.
- **Team4C**: see [team4c/README.md](team4c/README.md). Copy `team4c/.env.example` to `.env.local` and fill in real values.

**Never commit a real `.env` file, a `*.pem` key, or any file containing a
real credential.** See [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md#secrets-handling).

## Running each service

```bash
# Team4A
cd team4a && docker compose up --build

# Team4B
cd team4b && docker compose up --build
# or locally: uvicorn app.api.main:app --reload

# Team4C
cd team4c && npm install && npm run dev
```

Top-level orchestration helpers exist in [scripts/](scripts/):
`start-all.ps1`, `stop-all.ps1`, `health-check.ps1`, `e2e-smoke.ps1`.

## Testing

```bash
# Team4B (the service covered by the Phase 5 RAG validation arc)
cd team4b && python -m pytest -q
```

Expected baseline: **1302 passed, 3 skipped, 1 known pre-existing failure**
(a stale-ground-truth test — explained, not silenced, in
[docs/TESTING.md](docs/TESTING.md)). If this baseline changes, treat it as
a regression to investigate, not a test to delete.

Team4A and Team4C each have their own test suites (`team4a/tests/`,
`team4c/tests/`) — not modified or re-baselined by this documentation pass.

## Security

- Workspace and document isolation, generation authority, and the Phase
  5F/5K prompt-injection defenses are documented in
  [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md).
- Prompt injection is **mitigated, not eliminated**: a narrow
  forced-fixed-output attack pattern is fixed (validated at 0/32 live
  cases after the Phase 5K fix); one lower-severity residual (prompt-scaffold
  disclosure, no real secrets) remains open. Do not claim prompt injection
  is impossible.
- Secrets (`.env*`, `*.pem`) are gitignored at both the root and per-service
  level and were audited as part of Phase 5L — see
  [docs/REPOSITORY_CLEANUP_REPORT.md](docs/REPOSITORY_CLEANUP_REPORT.md).

## Current M6 status

See [docs/M6_STATUS.md](docs/M6_STATUS.md) for the authoritative,
up-to-date breakdown of what's COMPLETED, IN PROGRESS, and PENDING. In
short: **Team4B's generalized RAG is validated and frozen** (Phases 5D–5K);
**Team4C product integration is not yet the subject of this validation
arc**. Do not read this repository as "M6 complete" — it is not.

## Known limitations

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the full,
evidence-backed list. Headline items: Hindi retrieval is phrasing-sensitive;
cross-script (Hinglish/English↔Hindi) retrieval is weaker than same-language
retrieval; the LLM occasionally narrates lexically-adjacent-but-wrong-domain
content instead of declining; local LLM generation is CPU-bound and slow
(tens of seconds per request in this environment); one lower-severity
prompt-injection residual remains open.

## Project structure

```
.
├── team4a/           Ingestion service (FastAPI, Python)
├── team4b/           RAG/retrieval service (FastAPI, Python) — the focus of the Phase 5 validation arc
│   ├── app/          application source
│   ├── tests/        pytest suite (1302 passed / 3 skipped / 1 known failure baseline)
│   ├── scripts/       reproducible evaluation harnesses (not one-off scripts)
│   ├── data/          phase evaluation reports and evidence (kept — see docs/RAG_VALIDATION.md)
│   └── docs/          service-level decision records
├── team4c/           Next.js frontend/API
├── docs/             project-level documentation (this file's companions)
├── infra/            infra placeholder (intentionally minimal — see infra/README.md)
└── scripts/          top-level orchestration (start-all/stop-all/health-check/e2e-smoke)
```

`team4c-validation/` (a disposable, gitignored copy of `team4c/` used for
isolated product-level validation) and four gitignored historical
backup/snapshot directories from earlier `team4a`/`team4b` development are
retained locally for rollback reference but are intentionally excluded from
version control — see
[docs/REPOSITORY_CLEANUP_REPORT.md](docs/REPOSITORY_CLEANUP_REPORT.md) for
the full inventory and reasoning.
