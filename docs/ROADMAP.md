# Roadmap

## M6 — completed

- Three-service architecture: ingestion (Team4A), RAG/generation
  (Team4B), product/frontend (Team4C).
- PDF and YouTube ingestion with a generation/authority mechanism for
  safe re-ingestion.
- Hybrid (semantic + BM25 + RRF) retrieval, workspace/document-isolated,
  validated through a multi-phase forensic testing arc.
- Grounded generation with citations and a two-layer prompt-injection
  defense (one pattern fixed and validated; one residual tracked, not
  hidden).
- Full product integration: real auth, workspace/material management, a
  streaming AI Tutor UI, citations independently re-verified against
  workspace ownership.
- A premium, accessible, responsive UI — verified at 375/390/768/1024/
  1280/1440px on every major page, WCAG 2A/2AA checked via automated
  testing (a real contrast bug and, separately, a real CSS `mask-image`
  bug affecting text readability were both found and fixed this way, not
  just claimed).
- A full automated test suite: Team4B's pytest suite (1302 passed / 3
  skipped / 1 known, explained pre-existing failure), Team4C's Vitest
  (469 tests), Playwright E2E (12 specs, including real ingestion →
  retrieval → grounded-answer → citation flows against the live backend),
  and axe-core accessibility checks.
- A consolidated, maintained documentation set (this document's siblings)
  replacing a large number of temporary development-session reports.

## M6 — deferred (explicitly out of scope for this milestone)

- Production deployment (cloud infrastructure, managed databases, a
  real secret-management system).
- GPU-backed or hosted LLM inference (current generation is CPU-bound
  and slow — see [LIMITATIONS.md](LIMITATIONS.md)).
- Load/scale testing beyond a single local development machine.
- A decision on the open `REPRO-SPOOF-5` prompt-injection residual
  (accept as documented, or commission a separately-scoped fix) — a
  product/architecture decision, not something to resolve silently.
- A decision on the ingestion-trust-model question (who can get content
  indexed, and what that implies for injection risk) — deferred to the
  architecture authority in the original RAG validation arc, still open.
- Further Hindi/cross-script retrieval improvement — several approaches
  were evaluated and rejected on real evidence; no further attempt is
  currently planned without new evidence.

## Future (M7+) — potential directions

Listed here only because they are genuinely plausible next steps, not
because any of them is planned or committed:

- **Cloud/hosted LLM option** — an alternative `LLMGenerator` backend
  behind the same interface, for deployments where local Ollama/GPU
  hardware isn't available.
- **Real object storage** — replace the local-storage development mock
  with S3-compatible or equivalent storage for uploaded PDFs/videos.
- **Horizontally scalable ingestion workers** — Team4A's Celery worker
  count is already configurable; a real deployment would run multiple
  worker processes/machines against a shared Redis broker.
- **Observability** — centralized structured-log aggregation, request
  tracing across the three services, and alerting.
- **Rate limiting** — per-account/per-IP limits on ingestion and query
  endpoints, currently absent.
- **Additional file formats** — e.g., DOCX, PPTX, plain-text notes —
  would extend Team4A's extraction stage; not started.
- **Richer learning tools** — e.g., auto-generated practice questions or
  spaced-repetition prompts derived from a workspace's material, built on
  top of the existing grounded-generation pipeline rather than
  replacing it.
- **Multi-tenant production hardening** — stricter resource quotas per
  account, audit logging, and a formal incident-response process.

Nothing in this section should be read as promised or scheduled — it is
a list of directions consistent with the current architecture, for
whoever picks this project up next.
