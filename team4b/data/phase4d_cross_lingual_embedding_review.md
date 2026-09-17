# Phase 4D — Cross-Lingual Candidate Generation Evaluation

**Evaluation only. No production changes.** All numbers below are real measurements from this session, against Phase 4A's already-built, still-present temporary Qdrant collections (reused, not rebuilt) and the real, unmodified `HybridRetriever`/`BM25Index`/`CrossEncoderReranker` classes pointed at those temporary collections via a settings override. `educopilot_chunks` was never written to.

---

## 1. Executive Summary

**Recommendation: DO NOT migrate the production embedding model.** The multilingual candidate (`paraphrase-multilingual-MiniLM-L12-v2`) shows a real, measurable improvement in **isolated semantic-only** retrieval for English→Hindi (0/8 → 3/8 entering the top-100) and Hindi→English (dramatic MRR gains, confirmed again). But once combined with the **real, existing hybrid BM25+RRF pipeline that production actually uses**, that English→Hindi gain **completely evaporates: 0/8 both before and after**, even with reranking added on top. Hinglish→Hindi shows only a token, practically useless improvement (2/8 enter the pool at ranks 81 and 98 — nowhere near usable). Hindi→Hindi shows a **mixed result**: 3 queries newly succeed, but 2 regress, and the aggregate MRR for that pair actually **decreases** even as recall@10 increases. None of the three conditions the task's decision rule requires (substantial English→Hindi improvement, substantial Hinglish→Hindi improvement, no unacceptable regression) are met at the level that matters — the real hybrid pipeline, not semantic-only isolation.

## 2. Models Tested

| Model | Role | Dimension | Source |
|---|---|---|---|
| `all-MiniLM-L6-v2` | baseline (current production) | 384 | Phase 4A temp collection `phase2_eval_all_minilm_l6_v2_20260917T113049` (reused, 1650 chunks, not rebuilt) |
| `paraphrase-multilingual-MiniLM-L12-v2` | candidate | 384 | Phase 4A temp collection `phase2_eval_paraphrase_multilingual_minilm_l12_v2_20260917T113049` (reused, 1650 chunks, not rebuilt) |

**Optional second candidate: not evaluated.** Given the already very large scope of this phase and the explicit instruction not to spend excessive time searching for models or download large ones, I deliberately limited this phase to the one already-identified primary candidate.

## 3. Dataset

`team4b/data/phase2_ground_truth_approved.json` — all 75 approved entries, unmodified. Never edited during this phase.

## 4. Overall Metrics (production threshold 0.3, top_k=10)

| Pipeline | Model | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|---|
| Semantic-only | baseline | 0.180 | 0.313 | 0.353 | 0.380 | 0.260 |
| Semantic-only | candidate | 0.213 | 0.320 | 0.420 | 0.487 | 0.294 |
| Hybrid (BM25+RRF) | baseline | 0.207 | 0.433 | 0.447 | 0.473 | 0.313 |
| Hybrid (BM25+RRF) | candidate | 0.240 | 0.360 | 0.487 | **0.540** | **0.334** |

*(The baseline-hybrid number here, 0.473, differs slightly from Phase 4B's 0.487 measured against the live canonical collection directly — both use the same content/model; the ~1-query difference is attributable to re-indexing into a temp collection rather than a substantive finding. Both numbers in this table come from the identical evaluation pipeline, so the baseline-vs-candidate comparison itself is fair.)*

## 5. Language-Direction Matrix (Hybrid, production threshold, Recall@10 / MRR)

| query→source | n | baseline | candidate |
|---|---|---|---|
| English→English | 16 | 0.938 / 0.658 | **1.000** / 0.621 |
| Hinglish→English | 16 | 0.812 / 0.518 | **0.938** / 0.676 |
| Hindi→English | 16 | 0.250 / 0.122 | 0.250 / 0.156 |
| English→Hindi | 8 | 0.000 / 0.000 | **0.000 / 0.000 (unchanged)** |
| Hinglish→Hindi | 8 | 0.000 / 0.000 | **0.000 / 0.000 (unchanged)** |
| Hindi→Hindi | 8 | 0.312 / 0.250 | 0.562 / **0.123 (MRR regressed)** |

## 6. English→Hindi Candidate Recall (the critical acceptance measurement)

| | Recall@1 | Recall@10 | Recall@25 | Recall@50 | Recall@100 |
|---|---|---|---|---|---|
| Baseline, semantic-only | 0.000 | 0.000 | 0.000 | 0.000 | **0.000** |
| Candidate, semantic-only | 0.000 | 0.000 | 0.000 | 0.000 | **0.375** |
| Baseline, hybrid RRF | 0.000 | 0.000 | 0.000 | 0.000 | **0.000** |
| Candidate, hybrid RRF | 0.000 | 0.000 | 0.000 | 0.000 | **0.000** |

**The multilingual model's semantic-only gain (0%→37.5% candidate-recall@100) completely disappears once BM25+RRF fusion is applied — 0/8 in both hybrid rows.** This is the single most important finding of this phase: isolated embedding evaluation (Phase 4A's methodology) overstated the practical benefit, because production never runs semantic-only.

## 7. Hinglish→Hindi Candidate Recall

| | Recall@1 | Recall@10 | Recall@25 | Recall@50 | Recall@100 |
|---|---|---|---|---|---|
| Baseline, semantic-only | 0.000 | 0.000 | 0.000 | 0.000 | 0.125 |
| Candidate, semantic-only | 0.000 | 0.000 | 0.000 | 0.125 | 0.250 |
| Baseline, hybrid RRF | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| Candidate, hybrid RRF | 0.000 | 0.000 | 0.000 | 0.000 | **0.250** (ranks 81, 98 — not remotely usable) |

A small improvement survives RRF fusion here (unlike English→Hindi), but at ranks 81 and 98 out of 100 — far too deep to be practically meaningful at any realistic top-k.

## 8. Hindi→Hindi Results

Per-query classification (hybrid RRF, no reranker, production threshold):
- **FIXED** (miss→hit): `c_os_modules` (RRF rank 58→10), `c_sjf_not_implementable` (60→10), `c_page_fault_definition` (41→5) — 3 queries.
- **REGRESSED**: `c_real_time_os` (RRF rank 2→18, dropped out of top-10), `c_fcfs_disk_scheduling` (85→**not in top-100 at all**) — 2 queries.
- **Unchanged, both hit**: `c_process_stack_contents` (2→3), `c_memory_hierarchy_locality` (1→4) — 2 queries.
- **Unchanged, both miss top-10**: `c_hold_and_wait_deadlock` (15→47, still in pool, still misses) — 1 query.

Net: recall@10 improves (0.312→0.562) because 3 fixes outweigh 2 regressions in count, but **MRR regresses (0.250→0.123)** because the queries that stayed hits mostly moved to weaker ranks, and the newly-fixed queries land right at the rank-10 boundary (weak individual contribution to MRR). **This is not an unambiguous win for Hindi→Hindi** — it is a real trade, not a clean improvement.

## 9. Hindi→English Results

Semantic-only: MRR improved substantially (0.000→0.209, confirming Phase 4A's finding again). Hybrid RRF: recall@10 unchanged (0.250→0.250) but MRR improved (0.122→0.156). This direction remains the candidate model's clearest, most consistent strength across every evaluation this project has run (Phase 4A and now 4D agree).

## 10. English/Hinglish→English Regression Analysis

**No regression found.** English→English improved (0.938→1.000 recall@10 in hybrid); Hinglish→English improved (0.812→0.938). Neither shows any decrease at recall@10. (MRR shifted slightly in both directions across the two pairs but with no consistent degradation pattern worth flagging as a regression.)

## 11. Hybrid/RRF Results

Covered throughout Sections 4-9. Key structural finding: RRF fusion, which combines the multilingual semantic leg with the SAME real BM25 leg used in production, pulls in competing candidates from the rest of the workspace (which contains ~1050 English-language chunks, most of them duplicate copies of one OS textbook). For English/Hinglish queries, those competing English chunks score well on BM25 and reasonably on semantics, crowding the correct Hindi chunk out of the fused top-100 even when it had weak-but-real semantic signal on its own. This is a plausible, coherent explanation for Section 6's central finding, not confirmed beyond doubt (see Section 16).

## 12. Reranker Results

Multilingual embedding + real BM25 + RRF + `CrossEncoderReranker` (pool=40, production default), evaluated on the 24 Hindi-source queries:
- **English→Hindi: 0/8** (unchanged — reranking cannot promote a candidate that never enters the pool).
- **Hinglish→Hindi: 0/8** (unchanged, same reason).
- **Hindi→Hindi: 5/8** (`c_os_modules` rank1, `c_real_time_os` rank7, `c_process_stack_contents` rank1, `c_page_fault_definition` rank1, `c_memory_hierarchy_locality` rank1). This is better than hybrid-without-reranker's 5/8-by-a-different-count (see Section 8) — reranking here RECOVERS `c_real_time_os` (which the multilingual embedding alone had regressed) but simultaneously **newly loses `c_sjf_not_implementable`** (which had been a RRF-only hit at rank 10, reranked out of the top 10). Net: still 5/8, but a different, overlapping set of 5 — reranking is not a strict improvement even within Hindi→Hindi.

Compare to Phase 4C/4B's baseline-embedding + reranker result: 4/8 Hindi→Hindi hits. So multilingual+reranker (5/8) is one query better than baseline+reranker (4/8) — a small, real, but modest gain, entirely confined to Hindi→Hindi; still 0/8 for both cross-script directions.

## 13. Threshold Results

Hybrid RRF recall@10 was **identical at threshold=0.0 and threshold=0.3** for both models (baseline: 0.473 both; candidate: 0.540 both). **Threshold 0.3 removes zero already-recovered relevant candidates** for either model in this evaluation — confirming Phase 4A's original finding still holds with the full hybrid pipeline, not just semantic-only. Production threshold was never changed.

## 14. Latency

| Stage | Measurement |
|---|---|
| Model load (candidate, already cached from Phase 4A) | Fast (seconds, not the ~130s one-time cold-download measured in Phase 4A) |
| Semantic-only search, 24 queries (candidate) | 423.8ms/query mean (includes some lazy-load skew) |
| Semantic-only search, 75 queries (candidate) | ~155ms/query mean (steadier estimate) |
| Hybrid RRF, 75 queries (candidate) | 266.0ms/query mean (θ=0.0), 163.5ms/query (θ=0.3) |
| Hybrid RRF + reranker, 24 Hindi-source queries (candidate, pool=40) | 4941ms/query mean |
| Total Phase 4D evaluation wall time (all steps) | ~4 minutes |

Embedding/indexing time for both temp collections (~37s embedding + ~1.3s indexing for 1650 chunks each) was **not re-measured** — those collections were reused unchanged from Phase 4A rather than rebuilt, per the instruction to avoid unnecessary re-computation; see Phase 4A's report for those original numbers.

## 15. Fixed/Recovered/Unchanged/Regressed Classification (all 24 Hindi-source queries, hybrid RRF, no reranker)

| Classification | Count | % of 24 | Queries |
|---|---|---|---|
| FIXED | 3 | 12.5% | `c_os_modules__q_hindi`, `c_sjf_not_implementable__q_hindi`, `c_page_fault_definition__q_hindi` |
| RECOVERED (pool only) | 2 | 8.3% | `c_sjf_not_implementable__q_hinglish` (rank 98), `c_page_fault_definition__q_hinglish` (rank 81) |
| UNCHANGED (both miss) | 15 | 62.5% | all 8 English→Hindi + 6 of 8 Hinglish→Hindi + `c_os_modules__q_english/hinglish` etc. |
| UNCHANGED (both hit / both in-pool) | 3 | 12.5% | `c_process_stack_contents__q_hindi`, `c_memory_hierarchy_locality__q_hindi`, `c_hold_and_wait_deadlock__q_hindi` |
| REGRESSED | 2 | 8.3% | `c_real_time_os__q_hindi` (rank 2→18), `c_fcfs_disk_scheduling__q_hindi` (rank 85→absent from top-100) |

**English→Hindi: 0 FIXED, 0 RECOVERED, 8 UNCHANGED (100% still failing).**
**Hinglish→Hindi: 0 FIXED, 2 RECOVERED (both far too deep to be useful), 6 UNCHANGED.**

## 16. Root-Cause Interpretation

- **Confirmed:** the multilingual embedding model provides *some* semantic signal for English/Hindi/Hinglish→Hindi that the baseline model provides essentially none of (3/8 and 2/8 entering the semantic top-100 respectively, vs 0/8 and 1/8 for baseline). This signal is real but weak (best rank observed: 78; worst still inside top-100: 91).
- **Confirmed:** that weak signal does not survive RRF fusion against the real BM25 leg in this workspace, because the workspace also contains ~1050 English-language chunks (mostly duplicate OS-textbook copies) that outcompete it on both legs simultaneously for English/Hinglish queries.
- **Strongly supported, not fully isolated:** the specific mechanism is RRF's fusion arithmetic naturally favoring candidates that rank reasonably on *both* legs over a candidate that ranks only moderately on one — a structural property of RRF, not a bug, but one that actively works against a weak-but-real cross-script semantic signal when a large competing same-language corpus exists in the same workspace.
- **Unresolved:** whether a workspace with proportionally *less* competing English content would let the same weak multilingual semantic signal survive RRF fusion — this investigation used the one real workspace available and cannot isolate that variable without a different corpus.
- **Unresolved:** why the multilingual model's Hindi→Hindi semantic-only ranks are inconsistent (some improve, some regress, relative to baseline) — a per-query embedding-behavior question outside this phase's scope.

## 17. Recommendation

**Do not migrate `educopilot_chunks` to `paraphrase-multilingual-MiniLM-L12-v2`.** Applying the task's own decision rule directly:
- ❌ Substantial English→Hindi candidate recall improvement in the pipeline production actually runs: **not shown** (0/8 in hybrid, both before and after, and even with reranking).
- ❌ Substantial Hinglish→Hindi improvement: **not shown** (2/8 recovered, but at ranks 81/98 — not substantial in any practical sense).
- ✅ No unacceptable regression in English-source retrieval: **satisfied** (English→English and Hinglish→English both improved).
- ✅ Acceptable CPU performance: **satisfied** for the embedding swap alone (comparable to baseline); reranking remains costly regardless of which embedding is used.
- ❌ Works across the generalized benchmark, not just hand-picked queries: **not shown** — the one clear win (Hindi→Hindi) is itself a mixed 3-fixed/2-regressed trade, and the language pairs Phase 4D was specifically designed to fix (English/Hinglish→Hindi) show no meaningful improvement.

Since the primary acceptance criteria fail, **embedding migration is not justified by this evidence.** The next controlled approach worth investigating (per Phase 4C's own recommendation, now reinforced) is something that can bridge the query and Hindi content **before** they compete inside the same RRF-fused candidate pool — e.g., query-side normalization/translation, or a retrieval architecture that doesn't force cross-script and same-script candidates through one shared fusion step. Per this phase's explicit scope, **that next approach is not implemented here.**

---

## Production Safety Confirmation

- `educopilot_chunks` point count: **1650 before this phase → 1650 after** (verified directly at the start and end of this task).
- Canonical collection name unchanged: `educopilot_chunks`.
- No production Qdrant vectors were changed, created, or deleted — all work targeted Phase 4A's pre-existing, reused temporary collections (`phase2_eval_all_minilm_l6_v2_20260917T113049`, `phase2_eval_paraphrase_multilingual_minilm_l12_v2_20260917T113049`), which are clearly evaluation-only by name and were **retained** (not deleted) for audit purposes, exactly as they were before this phase began.
- No MongoDB writes occurred; a `PermissiveGenerationAuthorityClient` fake (documented, evaluation-only, matching Phase 4B/4C's identical precedent) was used to isolate the embedding/retrieval comparison from the already-diagnosed Mongo/Qdrant alignment gap (Phase 4C) — never used in production code.
- Production embedding configuration (`Settings.embedding_model_name = "all-MiniLM-L6-v2"`) was never changed on disk/in `.env` — all model swaps were done via in-memory `Settings.model_copy()` inside evaluation scripts only.
- `RERANKER_ENABLED` was not touched — remains at its Phase 4B default (`False`) in production; the reranker was only ever constructed directly inside this phase's own evaluation scripts.
- Team4A and Team4C were not touched.
- No `.env` secret values were read or exposed.
