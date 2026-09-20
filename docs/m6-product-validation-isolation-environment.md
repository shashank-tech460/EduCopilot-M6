# M6 Product-Level Validation — Isolated Environment Design

**Date:** 2026-09-18
**Purpose:** Protect the rebuilt, backed-up 542-point baseline (`educopilot_chunks`) while running the full product-level RAG validation (6 PDFs, 7 YouTube URLs, 26 test dimensions) against the real application.

---

## Architecture chosen: separate Qdrant collection + a fully parallel, disposable instance of the real Team4A/4B/4C services

This is the user's first-preference option ("separate Qdrant collection"). No new Docker containers, volumes, or Qdrant instance were created — the existing, already-running, healthy Qdrant server (`team4a-qdrant-1`, port 6333, backed by the protected `4a-service_qdrant_storage` volume) now hosts a second, physically independent collection alongside the protected one. Qdrant collections are independent on-disk namespaces; creating/writing to one never touches another.

### What was created

| Component | Production (protected) | Validation (disposable) |
|---|---|---|
| Qdrant collection | `educopilot_chunks` (542 points) | `educopilot_chunks_product_validation` (0 points, created via Team4B's own sanctioned `VectorStoreManager.ensure_collection()` — same method used for the earlier rebuild, no app code changed) |
| Team4A (ingestion) | port 8001 (unchanged, already running) | port 8011, new process, `CANONICAL_QDRANT_COLLECTION_NAME=educopilot_chunks_product_validation`, otherwise identical config (same Mongo, same Redis, same JWT keys) |
| Team4B (query/RAG) | port 8002 (unchanged, already running) | port 8012, new process, same collection override, `REDIS_URL=redis://localhost:6380/1` (separate cache DB index from production's db 0, to avoid any query-cache cross-talk) |
| Team4C (UI) | port 3000 (unchanged, already running), directory `team4c/` | port 3010, new process, directory `team4c-validation/` (a full source copy — Next.js refuses two dev servers from the same source directory even on different ports), `TEAM_A_API_URL=http://localhost:8011`, `TEAM_B_API_URL=http://localhost:8012`, `AUTH_URL=http://localhost:3010` |
| MongoDB | same instance, same database (`edu-copilot-team-c`) | **intentionally shared** — this matches the real product's architecture (a single Mongo backs all workspaces/accounts) and is the same isolation model (`workspace_id`/`userId`) already validated by the existing test suite. New validation accounts/workspaces are simply new documents; nothing about the existing OS/DBMS workspace documents is touched. |
| Embedding model, reranker, Phase5A | unchanged, unchanged, unchanged (unwired) | unchanged, unchanged, unchanged (unwired) — no `.env` in either environment touches these settings |

### Why this satisfies the isolation requirement

- **Qdrant-level**: the validation corpus can only ever be written to `educopilot_chunks_product_validation`. The validation Team4A/4B processes never hold a reference to the collection name `educopilot_chunks` at all (it is not present anywhere in their process environment).
- **No shared application code path can cross-write**: this is the same, unmodified production code for both stacks — only the `CANONICAL_QDRANT_COLLECTION_NAME` env var differs per process.
- **No Docker/volume risk**: no new containers, no new volumes, no compose changes, no restarts of the existing `team4a-qdrant-1`/`team4a-redis-1`/`m6-validation-team4b-redis` containers. The protected volume was never touched.
- **Mongo isolation** relies on the same `workspace_id`/`userId` scoping the application already enforces and already has dedicated regression tests for (Team4B's workspace-isolation suite) — this is treated as "the application's existing model," per your instruction to use real accounts/workspaces the normal way, not as a gap in the Qdrant-focused isolation you asked for.

### Verified before any ingestion

```
Production Team4A  (8001) -> healthy
Production Team4B  (8002) -> healthy
Production Team4C  (3000) -> HTTP 200
Validation Team4A  (8011) -> healthy
Validation Team4B  (8012) -> healthy
Validation Team4C  (3010) -> HTTP 200

educopilot_chunks                     -> 542 points  (protected baseline, unchanged)
educopilot_chunks_product_validation  -> 0 points    (empty, ready for validation ingestion)
```

**Protected baseline recorded at start of product-level validation: 542.**

### Known limitation

Team4C's `.local-uploads` directory (used for PDF storage in this local dev setup) is shared between the two Team4C instances (both point at the same `team4c/.local-uploads` path in the copied source's config, since `team4c-validation` was copied from `team4c` before any upload-path override was made — file *records* are still correctly isolated by `workspace_id`/`documentId` in Mongo either way, this only affects where raw uploaded bytes are stored on disk, not RAG data). This does not affect Qdrant isolation and is noted for completeness only.

### Cleanup (not yet performed)

When validation is complete, the disposable pieces (`team4c-validation/` directory, the two validation uvicorn processes, the `educopilot_chunks_product_validation` Qdrant collection) can be removed without touching anything protected. Not done automatically — left in place per your "do not delete anything" convention from the prior investigation, pending your review of the final report.
