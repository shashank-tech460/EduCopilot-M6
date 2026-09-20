# M6 Phase 5C — Controlled Retrieval Fix Implementation

**Date:** 2026-09-20
**Scope:** Implemented ONLY the two fixes explicitly authorized — Phase 5C-1 (safe first-message fallback) and Phase 5C-2 (BM25 startup lifecycle wiring). No embedding, threshold, RRF, `top_k`, or reranker change. No subject-specific logic. No canonical data modified. **No commit. No push.**
**Full machine-readable results:** `team4b/data/m6_phase5c_retrieval_fix_report.json`

---

## 1. Exact files changed

| File | Change |
|---|---|
| `team4b/app/services/rag_service.py` | Removed the "no previous turn → skip retrieval entirely" early-return branch. `build_enriched_retrieval_query()` is now called unconditionally when `is_elliptical_query(query)` is `True` — it already returns the query unchanged when there's no previous turn, so retrieval now always runs. |
| `team4b/tests/test_rag_service.py` | One test rewritten to assert the new, correct behavior (retrieval is attempted, not skipped). |
| `team4b/tests/test_api.py` | One route-level test rewritten analogously. |
| `team4b/app/api/main.py` | Added a `lifespan` handler that calls the existing `get_hybrid_retriever().refresh_bm25_corpus()` once at startup (non-fatal on failure). Added `logging.basicConfig(level=logging.INFO)` — required because no logging configuration existed anywhere in the app, silently dropping all INFO-level logs including the new startup line and the pre-existing `refresh_bm25_corpus()` log line itself. |
| `team4b/app/api/dependencies.py` | Docstring-only update reflecting that BM25 population is no longer entirely unwired. |

**5 files changed, 154 insertions, 45 deletions.** No other file touched.

---

## 2. Before/after retrieval flow

**Before:**
```
is_elliptical_query(query) == True AND no previous turn
  → HybridRetriever.retrieve() never called
  → retrieval_results = []
  → LLMGenerator.generate_conversational() (same path as "Hi")
  → scripted clarifying-question reply
```

**After:**
```
is_elliptical_query(query) == True AND no previous turn
  → build_enriched_retrieval_query(query, None) returns query unchanged
  → HybridRetriever.retrieve() called normally, on the original query
  → evidence found  → LLMGenerator.generate() → grounded, cited answer
  → no evidence found → LLMGenerator.generate() → INSUFFICIENT_CONTEXT_MESSAGE
                          (pre-existing, already-tested behavior; no LLM call, no fabrication)
```

Genuine follow-ups (a real previous turn exists) and casual greetings (`is_casual_message()`, a separate, untouched gate) are completely unaffected by this change.

---

## 3. Follow-up regression results

- `test_followup_context.py` + `test_rag_service.py`: **71 passed** (same count as the pre-change baseline).
- `test_api.py`: **127 passed**.
- Genuine follow-up enrichment tests (`test_elliptical_followup_enriches_retrieval_with_previous_user_turn`, `test_topic_switch_then_elliptical_followup_uses_the_new_topic`, and others) pass **unchanged** — enrichment with a real previous turn was not touched.
- Full Team4B suite: **1302 passed, 3 skipped, 1 failed — identical to the pre-change baseline.** The one failure is the same, pre-existing, already-documented `TestRelevantChunkIdsExistInCanonicalCorpus` (stale ground-truth chunk-ID mismatch from the post-Docker-incident rebuild). Not modified. **No new failures anywhere.**

---

## 4. 19-case targeted results

All 19 previously-confirmed-failing queries (10 from round-2's clean corpus, 9 from round-1) were re-run against the isolated validation environment with the fix live.

**Result: 19/19 (100%) now return non-zero citations and a grounded answer**, up from 0/19 before.

| Test | Citations | Latency | Notes |
|---|---|---|---|
| DS-10, DB-01, DB-02, DB-08, MA-08, MA-10, CN-06, EN-01, EN-05, MC-01, MC-02, MD-02, XS-03, XS-04, NS-01 | 5 each | 47.9s–179.8s | Manually spot-checked full answer text: genuinely correct, well-grounded, correctly-cited — matching exactly the content independently confirmed retrievable in Phase 5B's diagnostic trace (e.g. DB-01's citation pages `[1,6,1,5,12]` match Phase 5B's own trace exactly). |
| CN-11 | 4 | 153.1s | Correct and grounded; one candidate fell just below the (unchanged) threshold, immaterial to correctness. |
| OS-01, OS-04 | 5 each | 84.6s / 87.9s | Citations come from this workspace's own weak/ML-adjacent video content (a corpus-composition issue, not a code defect — see Phase 5B). The model **honestly declines** rather than fabricating an OS answer — exactly the desired "insufficient evidence, not a fabricated topic" outcome. |
| SEC-DOC-01 | 1 | 11.5s | Correct, grounded answer from the single-document Security Test workspace. |

---

## 5. BM25 startup verification

Live log from the restarted validation Team4B process:

```
2026-09-20 14:13:18,950 INFO app.services.hybrid_retriever: BM25 corpus refreshed
2026-09-20 14:13:18,951 INFO app.api.main: Startup BM25 corpus refresh succeeded
```

- **4938 chunks indexed** (the full validation collection).
- **1.23 seconds** total startup refresh time (would be proportionally faster against the 542-point canonical collection).
- Confirmed the log line was previously invisible not because the refresh wasn't running, but because **no logging configuration existed anywhere in the application** — `logging.basicConfig()` was required as a minimal, additive fix so INFO-level logs (this new line and the pre-existing one inside `refresh_bm25_corpus()` itself) are actually shown, without changing what is logged.

---

## 6. Semantic / BM25 / RRF evidence

**Direct, empirical before/after comparison** of citation `relevanceScore`s for the same representative query ("What are the layers of the OSI model?", Computer Networks workspace):

| | Before (BM25 always empty) | After (BM25 populated) |
|---|---|---|
| Rank 1 | 0.5000 | **1.0000** |
| Rank 2 | 0.4919 | 0.9685 |
| Rank 3 | 0.4841 | 0.9541 |
| Rank 4 | 0.4766 | 0.9318 |
| Rank 5 | 0.4692 | 0.9042 |

Scores are no longer capped near 0.5 — direct confirmation that BM25 is now genuinely contributing a second ranked list to Reciprocal Rank Fusion, exactly as the formula was always designed to combine, instead of RRF silently normalizing against a two-list denominator with only one list ever contributing.

**Workspace/document filtering in both legs**: re-confirmed intact by direct code reading of `_retrieve_hybrid()` (unchanged by this phase's edits) — `collection_filter`, `workspace_id`, and `document_ids` are still threaded into both the vector and BM25 futures before fusion.

---

## 7. B-tree case — before/after ranking

**Query:** *"What is a B-tree and how does node splitting work during insertion?"* | **Target:** page 128, `Data Structures Full Notes.pdf`

| | Semantic rank | BM25 rank | Fused rank | Normalized score | Final top-5? | Reaches LLM? |
|---|---|---|---|---|---|---|
| **Before (BM25 always empty)** | 29 / 100 (raw cosine 0.4612) | n/a — leg always empty | 29 | 0.3427 | No | No |
| **After (BM25 populated)** | 29 / 100 (unchanged) | **1 / 746** (raw score 37.84) | **9** | 0.8427 | No | No |

BM25 alone ranks the target chunk **#1 of 746** — an exact lexical match on "B-tree," "node," "splitting," "insertion." Fusing it with the semantic leg improves the overall rank from **29th to 9th** (a ~3x improvement) and the normalized score from 0.343 to 0.843 — both now far above the unchanged 0.3 threshold. **It still does not crack the top-5 cutoff**: 8 other chunks from the same 129-chunk, heavily tree/BST-themed PDF also score well on both legs.

**Live end-to-end confirmation**: re-ran the exact query against the real, fixed, BM25-populated validation environment via the actual chat API. The final answer's 5 citations are pages `[119, 98, 127, 99, 120]` — page 128 is confirmed absent. The model correctly stated it could not find specific information on B-tree node splitting rather than fabricating an answer.

**Per instruction, `top_k` was NOT changed**, even though it is the direct lever that would rescue this specific case. This is documented as a remaining, known limitation for a future phase.

---

## 8. Latency impact

- **Startup**: +1.23s one-time cost (measured, 4938 chunks; would be proportionally faster against the 542-point production collection).
- **Per-query**: no structural change. BM25 search itself is fast (in-memory, workspace-scoped, historically ~0.137s per query per the Phase 4C report) and runs in parallel with the semantic leg via the pre-existing thread pool, unchanged. Query latency across the 19 retested cases (11.5s–179.8s) remained dominated by CPU-only Ollama generation, consistent with every prior validation round — not attributable to this phase's changes.

---

## 9. Workspace/document isolation verification

Re-ran WI-01..04 (each asks one workspace about content exclusive to a different workspace) against the fixed environment:

| Test | Workspace asked | Content asked about | Cross-workspace citation? |
|---|---|---|---|
| WI-01 | Data Structures | DBMS normalization | **No** — all 5 citations from the DS PDF |
| WI-02 | DBMS | Trigonometric identity | **No** — all 5 citations from the DBMS PDF |
| WI-03 | Machine Learning | OSI model layers | **No** — all 5 citations from the ML video |
| WI-04 | Operating Systems | Linked list | **No** — all 5 citations from the OS workspace's own video |

**0/4 showed any cross-workspace leakage — isolation fully intact after the fix.**

---

## 10. Canonical 542-point verification

| | Before | After | Match |
|---|---|---|---|
| `educopilot_chunks` (protected canonical) | 542 | 542 | Yes |
| `educopilot_chunks_product_validation` | 4938 | 4938 | Yes |

---

## 11. Remaining known limitations (not addressed in this phase)

1. **DS-11 (B-tree case)**: BM25 improves the fused rank from 29th to 9th but doesn't crack the top-5 cutoff. Whether to increase `top_k`, enable the reranker, or pursue another ranking change is a decision for a future, explicitly-scoped phase — not decided here.
2. **OS-01/OS-04**: retrieval now runs correctly, but this workspace's own candidate pool is independently weak (a corpus-composition characteristic documented in Phase 5B, not a code defect). The model now gives an honest "insufficient evidence" answer instead of a scripted clarification — correct, but still not a *good* answer.
3. **F3 (hallucinated prior-conversation context)** — not investigated or fixed; out of this phase's explicit scope, and no related regression was exposed by this phase's own changes.
4. **F4 (casual-intent classifier's narrow phrase list)** — a separate, untouched classifier; not investigated or fixed here.
5. **F2 (cross-language retrieval)** — unrelated to either mechanism fixed in this phase; not investigated or fixed here.
6. **BM25 freshness** remains startup-only (a one-time refresh, no ongoing sync after new ingestion) — an already-documented, pre-existing trade-off in `refresh_bm25_corpus()`'s own docstring, unchanged by this phase.

---

## 12. Whether another retrieval change is justified

**Not decided in this phase — correctly out of scope.** The B-tree case's before/after ranking (29 → 9) demonstrates BM25 population provides a real, substantial ranking-quality improvement, but is not sufficient on its own to guarantee every precision-relevant chunk reaches the final top-5 in a densely-related-content workspace. Whether `top_k`, the reranker, or another mechanism should be the next lever is a decision for a future, explicitly-scoped phase — this report documents the evidence for that decision; it does not make it.

**Do not claim the RAG problem is solved.** The primary defect (query-transformation false positives skipping retrieval) is fixed and verified across 19/19 confirmed cases plus a clean isolation re-check and a full regression pass with zero new failures. The independent BM25 lifecycle gap is fixed and verified via live logs, score-distribution evidence, and the B-tree forensic case. Several other, separately-diagnosed issues (F2, F3, F4, and DS-11's residual ranking gap) remain open and were deliberately not touched in this phase.

---

## Safety confirmation

| Check | Result |
|---|---|
| Canonical data modified | No |
| Embedding changed | No |
| `score_threshold` changed | No |
| Reranker enabled | No |
| RRF constants/formula changed | No |
| `top_k` changed | No |
| Subject-specific logic added | No |
| Document-specific exceptions added | No |
| `.env`/`.env.local` modified | No |
| Qdrant reset/recreated | No |
| Full 123-question battery rerun | No (by design — targeted 19-case + isolation + regression suite only) |
| Committed | No |
| Pushed | No |

**Report files:**
- `team4b/data/m6_phase5c_retrieval_fix_report.json`
- `team4b/data/m6_phase5c_retrieval_fix_report.md`
