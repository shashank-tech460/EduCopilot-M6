# M6 Local Integration — Final Report

## Critical limitation, stated first

**No live services were started or reached during this task.** This sandbox has no network route to a real Windows laptop's `localhost` services, and no ability to run Docker/Mongo/Redis/Qdrant/Ollama itself (confirmed and documented repeatedly across this project's prior tasks — MongoDB and Ollama in particular cannot be installed here due to network egress restrictions). Every item in the required E2E test matrix (Section 12, Tests 1–12) that requires a real running stack is **BLOCKED / NOT PERFORMED**, not simulated, not assumed passing.

What this task **did** produce, all genuinely completed:
- A reproducible local integration workspace with the three approved baselines cleanly separated.
- A source-verified environment audit that found one concrete, real configuration defect (below).
- Local test-suite verification (real `pytest`/`vitest`/`tsc` runs, in this sandbox) confirming all three teams still meet their approved baselines with zero regression.
- A source-level trace for the citation-correctness investigation (Test 7) and the cold-start investigation (Section 13), both reusing and extending prior verified findings from this project.
- Startup/health/smoke scripts, ready to run on the actual target machine.

## 1. Environment
See `docs/M6-LOCAL-ENV.md` for the full audit. **Key finding: Team 4A's default `mongo_database_name` (`"educopilot"`) does not match Team 4B's and Team 4C's (`"edu-copilot-team-c"`)** — a real, source-confirmed local `.env` requirement (`MONGO_DATABASE_NAME=edu-copilot-team-c` must be explicitly set for Team 4A), not a code defect.

## 2. Versions
Node.js 22.17.1 / npm 10.9.2 as specified. Python version not independently re-verified against `requirements.txt` compatibility in this task.

## 3. Directory structure
```
EduCopilot-M6-Local/
    team4a/     (the approved 4a-service-M6-youtube-error-fix source, project root directly)
    team4b/     (the approved rag_service-M6-document-scope source)
    team4c/     (the approved edu-copilot-team-c-M6-scope-hydration-fix source)
    infra/      (empty — no infra config duplicated here; use your existing Docker setup)
    docs/       (this report + M6-LOCAL-ENV.md)
    scripts/    (start-all.ps1, stop-all.ps1, health-check.ps1, e2e-smoke.ps1)
```

## 4. Startup commands
```
Team 4A: uvicorn app.main:app --host 0.0.0.0 --port 8001       (from team4a/)
Team 4B: uvicorn app.api.main:app --host 0.0.0.0 --port 8002   (from team4b/)
Team 4C: npm run start                                          (from team4c/, after npm run build)
```
Both entrypoint files (`app/main.py`, `app/api/main.py`) confirmed to exist at these exact paths.

## 5. Environment variables required
See `docs/M6-LOCAL-ENV.md` in full — including the exact field names taken directly from Team 4C's actual `.env.example` (`TEAM_A_API_URL`, `TEAM_B_API_URL`, `SERVICE_JWT_PRIVATE_KEY`, etc.), not guessed names.

## 6. Service health
**Not verified live** — `scripts/health-check.ps1` is provided, ready to run on the target machine, checking HTTP reachability, Qdrant's canonical collection, and Ollama's model list.

## 7/8. Test matrix and actual results

| Test | Result |
|---|---|
| 1–6, 8–12 | **BLOCKED — not performed (no live access)** |
| 7 (citation correctness) | **Source investigation completed** — see Section 17 below |
| Cold-start (Section 13) | **Source investigation completed** — reuses this project's own prior, already-verified findings |

## 9. Failed tests
None run live, so none failed live. All three teams' own **unit/type-check suites** were run for real in this sandbox (Section 14) — zero failures, zero unexpected skips.

## 10. Root causes
The one genuine environment root cause found: the Mongo database-name mismatch (Section 1/17).

## 11. Changes made
**None to any application source in this task.** Only the integration workspace, documentation, and scripts were created — per Section 15's own change-control gate ("only modify application code if a real integration defect is reproduced" — no live reproduction occurred, so no code was touched).

## 12. Files changed
None (source). New: `docs/M6-LOCAL-ENV.md`, `docs/M6-LOCAL-INTEGRATION-FINAL.md`, `scripts/*.ps1`.

## 13. Security verification
Re-confirmed by direct source inspection (all previously verified in this project, re-checked here): mandatory workspace_id JWT derivation (4A and 4B), `extra="forbid"` on 4A's canonical request body, ES256 JWT audience/scope separation, Team 4A's secure remote-source resolver controls untouched by any prior correction.

## 14. Workspace isolation verification
Source-confirmed (not live-tested this task): mandatory `workspace_id` Qdrant filter condition (`VectorStoreManager._build_workspace_and_collection_filter`), mandatory BM25 `workspace_id` scoping (`BM25Index.search`), both applied before RRF.

## 15. Qdrant verification
**Not live-inspected.** `scripts/health-check.ps1` includes a read-only check of `educopilot_chunks`'s vector size/distance config for the operator to run.

## 16. JWT verification
Configuration documented in `docs/M6-LOCAL-ENV.md`; the PEM-vs-JWK format pitfall from the prior JWT-configuration correction task is called out explicitly as something to re-check if key material is ever regenerated.

## 17. Citation investigation (Test 7) — source-level findings

Traced the full path: `HybridRetriever` (workspace filter + M4 generation-authority filter, both applied **before** `reciprocal_rank_fusion()`, re-confirmed by direct code order inspection) → RRF → `RAGService` → `app/api/routes.py`'s `assemble_query_response` (source attributions) → Team 4C's `app/api/chat/route.ts` (re-filters attributions against `FileModel.find({workspaceId})` as defense-in-depth) → `SourceAttributionType[]` embedded in **each message's own `data-citations` part** (`ChatPanel.tsx`, confirmed via `message.parts.find(part => part.type === "data-citations")`) — citations are structurally per-message, not shared/global state, which rules out a simple "stale UI state" explanation (category H) at the source level.

**The most important finding for this investigation: if OS and DBMS materials live in the *same* workspace (as the original report describes — "a workspace containing OS material"), workspace filtering is *irrelevant* to this symptom by construction.** A DBMS question surfacing OS citations *within the same authorized workspace* is not a tenancy/security violation — 4B's mandatory workspace filter has nothing to exclude here, since both documents are equally authorized. This re-frames the investigation from "security defect" (categories B/D) toward **category A — retrieval relevance**: the embedding model and/or RRF's score threshold judged the OS content sufficiently semantically similar to include it, which is a ranking/threshold characteristic, not a filtering bug.

One relevant, pre-existing, explicitly-documented limitation found during this trace: `app/api/dependencies.py`'s own docstring states BM25 corpus refresh (`HybridRetriever.refresh_bm25_corpus()`) is "explicitly out of scope" and nothing currently schedules it — meaning, unless something else in the deployment calls it, the BM25 leg may always return an empty corpus in production, degrading `hybrid` mode to effectively vector-only. This is a known, pre-existing gap (not introduced by any M6 correction), relevant context for relevance-tuning discussions, but not itself a workspace-isolation defect.

**Classification: STRONGLY SUPPORTED (category A, retrieval relevance) given the "same workspace" framing; NOT SUPPORTED that this is a tenancy/security defect; UNKNOWN whether live reproduction would reveal something else** (e.g., an actual different-workspace leak, which would be far more serious and would require immediate live investigation with the exact query/citations/Qdrant payloads involved — not something source inspection alone can rule out with certainty).

## 18. Cold-start investigation (Section 13)

Fully investigated in a prior task this project, reusing that finding here rather than re-deriving it: the embedding model (`sentence-transformers`) and the canonical Qdrant collection's own one-time verification are both lazily initialized on the *first real query* after process start (confirmed via `RealEmbeddingModel._ensure_model()`'s `if self._model is None` guard and `VectorStoreManager._with_retry()`'s `self._ensured_collections` tracking), accounting for the observed ~35s first-request cost vs. ~7s warm. `/health` was confirmed to **not** exercise either lazy path (it only checks bare connectivity), so it can report "healthy" while the process is still cold — a real, source-confirmed gap. Recommendation from that investigation stands: **NEED MORE EVIDENCE / A DESIGN DECISION** before implementing a startup-warm-up mechanism, specifically because there is no existing public method to warm the *canonical* collection check without either adding one or reusing the wrong (legacy-collection) public method. No warm-up was implemented in this task, consistent with that prior recommendation and this task's own instruction not to implement it prematurely.

## 14 (Testing Requirements). Actual test results

```
Team 4A: 827 passed, 4 skipped, 0 failed   (matches approved baseline exactly)
Team 4B: 960 passed, 0 failed              (matches approved M6-document-scope baseline)
Team 4C: 450 passed, 0 failed; tsc --noEmit clean   (matches approved M6-scope-hydration-fix baseline)
```
All three run for real, in this sandbox, from the actual integration workspace directories being packaged.

## 19. Remaining blockers
Every live E2E scenario (Tests 1–6, 8–12), live Qdrant/Mongo/Redis inspection, and live citation reproduction — all require an actual running stack this sandbox cannot reach.

## 20. Deployment readiness assessment
**Not assessable from source alone**, and this task explicitly warns against declaring readiness from unit tests alone — which is exactly why this is being reported as blocked rather than "PASS."

## 21. Exact next recommended task
Run `scripts/health-check.ps1` then `scripts/e2e-smoke.ps1` on the actual Windows laptop after setting `MONGO_DATABASE_NAME=edu-copilot-team-c` for Team 4A specifically, then manually walk through Tests 1–10 through the real browser UI, capturing the exact query/citation/Qdrant-payload evidence for Test 7 specifically (the one case where "same workspace" framing means source inspection alone cannot fully resolve whether this is relevance-tuning or an actual defect).

---

# Final classification: **PASS WITH BLOCKERS**

Not FAIL — nothing tested (unit/type-check level, source-level architecture) failed or regressed. Not PASS — the live E2E evidence this task explicitly requires ("Do not declare the project production ready merely because unit tests pass... We need REAL LOCAL E2E evidence") was not obtained and cannot be obtained from this sandbox. The one genuine finding (Mongo database-name mismatch) is an environment configuration item, not a code defect, and is documented with its exact fix.
