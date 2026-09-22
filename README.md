# EduCopilot

**An educational RAG copilot** — students upload their own course PDFs and
lecture videos, organize them into workspaces, and ask an AI Tutor
questions. Every answer is grounded in that student's own material, with
a citation back to the exact page or timestamp — never a guess from the
model's general training data.

## Overview

EduCopilot is built as three independent services:

- **Team4A** — ingests PDFs and YouTube videos: extracts text, chunks it,
  generates embeddings, and publishes to a vector store.
- **Team4B** — the RAG (Retrieval-Augmented Generation) engine: hybrid
  semantic + keyword retrieval, workspace/document isolation, and grounded
  answer generation with citations.
- **Team4C** — the Next.js product: authentication, workspaces, material
  management, and the AI Tutor chat UI.

Full architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Problem statement

Students have course PDFs and recorded lectures but no fast way to ask
"what does my own material say about X?" and get a trustworthy, cited
answer — one that honestly says "I don't know" when the material doesn't
cover the question, rather than guessing.

## Key features

- **Workspace-isolated organization** — course material is grouped into
  workspaces; a workspace's content is never visible to another user, and
  never cross-cited into another workspace's answers.
- **PDF and YouTube ingestion**, with per-document status
  (uploading/processing/ready/failed) reflected live in the UI.
- **AI Tutor** — a streaming chat interface. Answers adapt their structure
  to the question (short prose for a simple definition, numbered steps
  for a procedure, bullet points for a list of concepts) because the
  underlying LLM does, not because the frontend forces a template.
- **Grounded, cited answers** — every citation is built from real
  retrieval metadata, re-verified against the caller's own workspace
  before being rendered, and traceable to a specific PDF page or video
  timestamp.
- **Hybrid retrieval** — semantic (vector) search + BM25 keyword search,
  merged with Reciprocal Rank Fusion, so both conceptual and exact-terminology
  questions are covered.
- **Source-grounded, not hallucination-prone by design** — the LLM is
  instructed to answer only from retrieved evidence, with a documented,
  measured (not just claimed) mitigation for prompt injection. See
  [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md).

## Architecture overview

```
Student (browser)
    |
    v
Team4C — Next.js UI + API routes (auth, workspaces, materials, chat)
    |  (internal service JWT)
    v
Team4B — RAGService
    +-- HybridRetriever (semantic via Qdrant + BM25, fused via RRF)
    +-- Generation-authority filter (MongoDB, fail-closed)
    +-- LLMGenerator -> Ollama (llama3) -> grounded answer + citations
    ^
    |  (internal service JWT)
    |
Team4A — ingestion: extract -> chunk -> embed -> publish to Qdrant
                     writes ingestion-generation record to MongoDB
```

Full detail, including request/ingestion/query lifecycles:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/INTEGRATION.md](docs/INTEGRATION.md).

### Team responsibilities

| Team | Responsibility |
|---|---|
| **Team4A** | PDF/YouTube ingestion, extraction, chunking, embedding, Qdrant publishing, the ingestion-generation/authority record |
| **Team4B** | Hybrid retrieval, generation-authority checks, LLM generation, citations, prompt-injection defenses — **RAG-accepted and frozen** (see [docs/M6_STATUS.md](docs/M6_STATUS.md)) |
| **Team4C** | Next.js frontend, auth, workspace/material CRUD, the AI Tutor UI, and the MongoDB product schema — full product integration completed and tested |

## Technology stack

Next.js 16 / React 19 / TypeScript (Team4C) · FastAPI / Python 3.12
(Team4A, Team4B) · MongoDB · Qdrant · Redis · Ollama (`llama3`). Full
detail per service: [docs/TEAM4A.md](docs/TEAM4A.md),
[docs/TEAM4B.md](docs/TEAM4B.md), [docs/TEAM4C.md](docs/TEAM4C.md).

## Prerequisites

Node.js 20+ (this project developed against 22.17.1), Python 3.12, Docker
Desktop, MongoDB, Ollama (with the `llama3` model pulled). Full list with
exact versions: [docs/SETUP.md](docs/SETUP.md).

## Ports (local development)

| Service | Port |
|---|---|
| Team4C | 3000 |
| Team4A | 8001 |
| Team4B | 8002 |
| Qdrant | 6333 |
| MongoDB | 27017 |
| Redis (Team4A) | 6379 |
| Redis (Team4B) | 6380 |
| Ollama | 11434 |

## Quick setup

```powershell
# 1. Install
cd team4c && npm install && cd ..
cd team4a && pip install -r requirements.txt && cd ..
cd team4b && pip install -r requirements.txt && cd ..

# 2. Configure environment (see docs/SETUP.md for exact values)
cd team4c && Copy-Item .env.example .env.local && cd ..
cd team4b && Copy-Item .env.example .env && cd ..
# create team4a\.env by hand — see docs/SETUP.md

# 3. Start infrastructure, then each service (separate terminals)
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest
docker run -d --name team4a-redis -p 6379:6379 redis:7-alpine
docker run -d --name team4b-redis -p 6380:6379 redis:7-alpine
# MongoDB + Ollama running natively or via their own containers

cd team4a && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
cd team4a && celery -A app.celery_app worker --loglevel=info   # second terminal
cd team4b && uvicorn app.api.main:app --host 0.0.0.0 --port 8002
cd team4c && npm run dev
```

Full, exact walkthrough (including generating the auth/JWT secrets):
[docs/SETUP.md](docs/SETUP.md).

## Startup order

Infrastructure (MongoDB, Redis ×2, Qdrant, Ollama) → Team4A → Team4B →
Team4C. Why: [docs/INTEGRATION.md](docs/INTEGRATION.md#startup-order).

## Health checks

```powershell
curl http://localhost:3000
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:6333/collections
```

## Testing

```powershell
# Team4B (the service covered by the Phase 5 RAG validation arc)
cd team4b && python -m pytest -q
# Expected: 1302 passed, 3 skipped, 1 known pre-existing failure (explained, not silenced — see docs/TESTING.md)

# Team4A
cd team4a && python -m pytest -q

# Team4C
cd team4c
npx tsc --noEmit && npx eslint . && npx vitest run && npx playwright test
# Expected: 0 type errors, 469 Vitest tests passing, 13/13 Playwright tests passing,
# 5/5 pages passing WCAG 2A/2AA accessibility checks
```

Full detail, including how to distinguish a pre-existing issue from a
regression: [docs/TESTING.md](docs/TESTING.md).

## Production build

```powershell
cd team4c && npm run build
```

## Documentation

| Document | Covers |
|---|---|
| [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) | Problem, solution, features, and scope explained professionally |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System-level design, data flow, isolation model |
| [docs/TEAM4A.md](docs/TEAM4A.md) | Ingestion service in full |
| [docs/TEAM4B.md](docs/TEAM4B.md) | RAG/query service in full |
| [docs/TEAM4C.md](docs/TEAM4C.md) | Frontend/product in full |
| [docs/INTEGRATION.md](docs/INTEGRATION.md) | Exact service-to-service contracts, ingestion/query lifecycles |
| [docs/SETUP.md](docs/SETUP.md) | Fresh-machine installation walkthrough, quick start to full setup |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Every environment variable, what it does, safe example values |
| [docs/TESTING.md](docs/TESTING.md) | Test suites, expected baselines, what each category validates |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Common problems, safe diagnostics, safe fixes |
| [docs/PROJECT_QA.md](docs/PROJECT_QA.md) | Full Q&A reference — architecture, RAG, security, deployment, interview-length explanations, an honest engineering evaluation |
| [docs/DEVELOPER_HANDOFF.md](docs/DEVELOPER_HANDOFF.md) | What to read first, where code lives, what not to modify casually |
| [docs/SECURITY.md](docs/SECURITY.md) | Product-wide security reference (auth, isolation, JWT, secrets) |
| [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md) | Team4B's frozen retrieval/generation pipeline, including every alternative investigated and rejected |
| [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md) | Team4B's prompt-injection threat model and defenses, stated plainly (fixed vs. mitigated vs. open) |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | Current limitations, test/dev-only limitations, and future improvements — kept separate |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Team4B's real, evidence-backed retrieval/generation limitations |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Completed vs. deferred vs. genuinely future work |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | High-level milestones |
| [docs/M6_STATUS.md](docs/M6_STATUS.md) | Current, authoritative project status |

## Security notes

- **Never commit** a real `.env`, `.env.local`, or `*.pem` file — all are
  git-ignored. See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).
- Service-to-service calls are authenticated with short-lived signed
  internal JWTs, never long-lived shared API keys.
- Prompt injection is **mitigated, not eliminated** — a specific
  forced-fixed-output attack pattern is fixed and validated (0/32 live
  cases after the fix); one lower-severity residual (prompt-scaffold
  disclosure, no real secret exists to leak) remains open and is tracked,
  not hidden. See [docs/SECURITY_ARCHITECTURE.md](docs/SECURITY_ARCHITECTURE.md).

## Known limitations

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) for the full,
evidence-backed list. Headline items: Hindi/cross-script retrieval is
weaker than same-language retrieval and not claimed to be solved; the LLM
occasionally misapplies in-scope content from the wrong subject area
instead of declining; local LLM generation is CPU-bound and can take
30–140+ seconds per answer in this environment; no cloud deployment or
load testing has been performed.

## Current status

See [docs/M6_STATUS.md](docs/M6_STATUS.md) for the authoritative,
up-to-date breakdown. In short: **Team4B's generalized RAG is validated
and frozen**; **Team4C's product integration is complete and tested**
(auth, workspaces, materials, AI Tutor, a full automated test suite, and
a dedicated visual-polish/accessibility pass).

## Project structure

```
.
├── team4a/           Ingestion service (FastAPI, Python)
├── team4b/           RAG/retrieval service (FastAPI, Python)
│   ├── app/          application source
│   ├── tests/        pytest suite
│   ├── scripts/      reproducible evaluation harnesses
│   ├── data/         phase evaluation reports and evidence
│   └── docs/         service-level decision records
├── team4c/           Next.js frontend/API
│   ├── app/          routes, API handlers
│   ├── components/   UI components
│   ├── lib/, models/, services/, hooks/, store/
│   ├── tests/        unit/, component/, e2e/
│   └── docs/         Team4C's own decision records
├── docs/             project-level documentation (this file's companions)
├── infra/            infra placeholder (intentionally minimal)
└── scripts/          top-level orchestration (start-all/stop-all/health-check/e2e-smoke)
```

A small number of gitignored backup/duplicate directories
(`team4a-backup-before-transcript-windowing/`,
`team4a-before-youtube-hindi-fallback/`, `team4b-context-provenance-temp/`,
`team4c-validation/`) exist locally for rollback reference from earlier
development but are intentionally excluded from version control and from
any ZIP/GitHub distribution — see
[docs/REPOSITORY_CLEANUP_REPORT.md](docs/REPOSITORY_CLEANUP_REPORT.md).
