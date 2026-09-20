# M6 Phase 5I-B — Current-Corpus Generalized Retrieval Quality + Cross-Language Improvement

**Status: FORENSIC/EVALUATION COMPLETE. No production code changed. Decision: Category C (no safe generalized improvement found) for embedding migration; Category B (promising, insufficient evidence, not enabled) for the reranker. No production retrieval change implemented.**

---

## 1. Executive Summary

Using ONLY the trustworthy, live-verified 19-entry current-corpus ground truth from Phase 5I-A (never the stale phase2/phase3 files), this phase computed real Recall@k/MRR for semantic-only, BM25-only, and hybrid retrieval, diagnosed all 3 known misses down to the exact pipeline stage and root cause, and evaluated two improvement candidates — a multilingual embedding model and the existing (disabled) cross-encoder reranker — entirely offline, without touching production.

**Baseline (hybrid, production defaults):** Recall@5 = 84.2% (16/19), Recall@10 = 89.5% (17/19), MRR = 0.618. **Hybrid measurably beats semantic-only at every k** (R@5: 0.842 vs 0.632) — BM25 is a genuine, positive contributor on this dataset, not dead weight.

**All 3 misses diagnosed with concrete evidence, not assumption:**
- Miss 1 (English→English): RRF rank 8 — a mild ranking/candidate-pool issue. Both legs found it individually; fusion just didn't surface it into the top-5.
- Miss 2 (Hinglish→Hindi): RRF rank 14 — BM25's raw score for the correct chunk was **literally 0.0** (zero lexical overlap between Latin-script Hinglish tokens and Devanagari-script source text); semantic alone (rank 48) too weak to compensate.
- Miss 3 (English→Hindi): genuinely **absent from the top-100 candidate pool entirely** in every leg (semantic rank 180, BM25 rank 127) — the only miss unrecoverable by any top_k or threshold tuning. A real, severe cross-language embedding weakness.

**Multilingual embedding experiment — the phase's most important methodological result:** tested in isolation (semantic-only), the candidate model (`paraphrase-multilingual-MiniLM-L12-v2`) looked like a clear win — it fixed Miss 3 outright (rank 180 → rank 3) with no English regression. **But simulated through the FULL hybrid+RRF pipeline** (fusing its new semantic rankings with the SAME real BM25 rankings, exactly as production would), that apparent fix **evaporates** (Miss 3 remains unrecovered, rank effectively unchanged in the fused result) and a real new regression appears: Hindi→Hindi recall, which the CURRENT system already handles perfectly (100%), **drops to 66.7%**. Overall hybrid Recall@5 is unchanged (0.842 = 0.842) and Recall@10 is worse (0.842 vs 0.895). **This is a decisive demonstration of exactly the trap the task explicitly warned against** — an isolated single-language improvement that disappears, and produces a new regression, once evaluated as the product actually operates.

**Reranker (offline only, never enabled):** fixes Miss 1 (rank 8→2) and Miss 2 (rank 14→1) but does nothing for Miss 3 (never in the candidate pool to begin with — confirming the previously-documented limitation that reranking cannot recover what retrieval never generated) and introduces a **new regression** on a previously-correct query (rank 4→7). Net Recall@5 improves (0.842→0.895) but at ~1.8–2.0s/query added latency and with a genuine new failure mode, not a clean win.

**Decision: no production change.** Neither candidate reaches the "clear generalized improvement" bar this phase's own framework requires.

---

## 2. Baseline Configuration

- Branch `phase5-cross-script-retrieval`, commit `6f8a93377fdaf7ebca3ef3b8851ff541fb2b14d8`, git status identical to Phase 5I-A's end state.
- Canonical `educopilot_chunks`: 542 points (confirmed unchanged before/after). Validation `educopilot_chunks_product_validation`: 4938 points (confirmed unchanged before/after).
- Production config (re-confirmed): `default_top_k=5`, `default_score_threshold=0.3`, `default_search_mode=hybrid`, `rrf_k=60`, `hybrid_candidate_pool_size=100`, `reranker_enabled=False` (never toggled), `embedding_model_name=all-MiniLM-L6-v2` (never changed).

---

## 3. Current-Corpus Ground-Truth Status

`team4b/data/phase5i_a_current_corpus_ground_truth_candidate.json` (19 entries, Phase 5I-A) used exclusively for all quantitative claims in this report. Status remains `CANDIDATE` for every entry — no human validation occurred this phase either. The stale `phase2_ground_truth_approved.json` / `phase3_generalized_ground_truth_candidate.json` files were **not** used for any metric in this report, consistent with Phase 5I-A's finding that they reference corpus content that no longer exists.

A new, small, explicitly-supplementary file was created this phase: `team4b/data/phase5i_b_generalization_supplement_candidate.json` (2 entries, Data Structures and Computer Networks subjects, against the **validation** collection) — kept deliberately separate from the canonical-scoped file, to test generalization beyond OS/DBMS (Section 14).

---

## 4. Overall Recall@K/MRR

| Mode | R@1 | R@3 | R@5 | R@10 | MRR |
|---|---|---|---|---|---|
| Semantic-only | 0.421 | 0.526 | 0.632 | 0.737 | 0.489 |
| BM25-only | 0.474 | 0.737 | 0.789 | 0.895 | 0.610 |
| **Hybrid (production)** | **0.474** | **0.789** | **0.842** | **0.895** | **0.618** |

**Hybrid outperforms semantic-only at every k tested, and matches-or-beats BM25-only at every k.** BM25 is genuinely useful on this dataset, not a net drag.

---

## 5. Language Matrix

(Hybrid, production defaults, threshold=0.3, k=5)

| Direction | n | R@1 | R@3 | R@5 | R@10 |
|---|---|---|---|---|---|
| English → English | 11 | 0.727 | 0.818 | 0.909 | 1.0 |
| Hinglish → English | 3 | 0.0 | 1.0 | 1.0 | 1.0 |
| Hindi → Hindi | 3 | 0.333 | 1.0 | 1.0 | 1.0 |
| Hinglish → Hindi | 1 | 0.0 | 0.0 | 0.0 | 0.0 |
| English → Hindi | 1 | 0.0 | 0.0 | 0.0 | 0.0 |

**n=1 for the two failing categories is explicitly too small for a general conclusion** — both are reported as single confirmed instances, not statistically established failure rates. Same-language and script-variant retrieval (Hindi-script and Hinglish-script queries against matching-language content) already perform well by k=3–5; the two persistent zero-recall categories are specifically the ones where query language and source language genuinely differ.

---

## 6. Detailed Analysis of All 3 Misses

| Query | Semantic rank | BM25 rank/score | RRF rank | In top-100 pool? | Chunk quality | Classification |
|---|---|---|---|---|---|---|
| `ci_os_process_definition__q_english` | 4 (0.669) | 10 (10.29) | 8 | Yes, both legs | Clean, on-topic English PDF text | **CANDIDATE_POOL / RRF** — mild ranking miss, resolves at top_k≥10 |
| `ci_os_race_condition__q_hinglish` | 48 (0.314) | 36 (**0.0 raw score**) | 14 | Yes, both legs | Clean, on-topic Hindi text (verified not garbled) | **BM25 (cross-script token mismatch)** — zero lexical overlap between Latin-script query and Devanagari source; resolves at top_k≥20 |
| `ci_os_virtual_memory__q_english_over_hindi_source` | 180 | 127 (0.0) | 133 (uncapped) / absent (capped pool=100) | **No** — absent from the production-capped 100-candidate pool in every leg | Clean, on-topic Hindi text (verified not garbled) | **EMBEDDING (cross-language semantic weakness)** — the most severe miss, unrecoverable by top_k or threshold tuning alone |

For misses 2 and 3, chunk quality was directly ruled out as a contributing cause: both target chunks' actual text was read and confirmed clean, readable, on-topic Devanagari Hindi (not the character-spaced/garbled variant documented elsewhere in the same source video in Phase 5I-A). Neither is eliminated by threshold (the 0.0–0.7 sweep showed zero effect on any of the 3 misses — Section 9) or by workspace/document filtering (all three targets are correctly scoped and present in their expected workspace).

---

## 7. Semantic vs. BM25 vs. Hybrid

Already summarized in Section 4's table. Per-miss detail: BM25 is the leg that fails most severely and specifically for cross-script queries (Miss 2's exact-0.0 score) — a direct, mechanical consequence of BM25 being a lexical/token-overlap method with no cross-script matching capability by design. Semantic (embedding) similarity is the leg that fails most severely for genuine cross-language queries (Miss 3), consistent with `all-MiniLM-L6-v2` being a primarily English-trained model. **The two legs fail for different, complementary reasons** — which is exactly why hybrid outperforms either alone overall, but also why hybrid still can't rescue a case where both legs independently fail badly (Miss 3).

---

## 8. Top-k Experiment

(Hybrid, threshold=0.3)

| top_k | Recall | MRR |
|---|---|---|
| 5 | 0.842 | 0.618 |
| 10 | 0.895 | 0.625 |
| 20 | 0.947 | 0.629 |
| 40 | 0.947 | 0.629 |
| 100 | 0.947 | 0.629 |

Recall plateaus at 94.7% from k=20 onward — **Miss 3 never resolves even at k=100**, confirming it is a genuine absence from the candidate pool, not a ranking-depth problem. Increasing production `top_k` would recover Miss 1 (needs ≥10) and Miss 2 (needs ≥20) but at the cost of feeding substantially more (mostly irrelevant, per Phase 5D/5E/5H's repeated findings) context to the LLM — not evaluated for generation-quality impact this phase, flagged as a real, unquantified tradeoff.

---

## 9. Threshold Experiment

(Hybrid, top_k=5)

| threshold | Recall | MRR |
|---|---|---|
| 0.0 | 0.842 | 0.618 |
| 0.2 | 0.842 | 0.618 |
| 0.3 | 0.842 | 0.618 |
| 0.4 | 0.842 | 0.618 |
| 0.5 | 0.842 | 0.618 |
| 0.7 | 0.842 | 0.618 |

**Completely flat across the entire tested range.** None of the 3 misses are threshold-driven; none of the 16 hits are threshold-fragile either. This reconfirms Phase 5D/5E/5H's repeated finding: score alone does not discriminate meaningfully in this system, at least not in the 0.0–0.7 range, for this dataset. No threshold change is supported by this evidence in either direction.

---

## 10. Multilingual Embedding Experiment

Model: `paraphrase-multilingual-MiniLM-L12-v2` (already locally cached from an earlier phase's evaluation — no fresh download this phase). Offline, in-memory only: all 542 canonical chunks and 19 queries re-embedded with both models, compared via direct cosine similarity (semantic-only) AND via a full hybrid-pipeline simulation (new semantic rankings fused with the SAME real captured BM25 rankings via the real, unmodified `reciprocal_rank_fusion()`). No Qdrant writes, no temporary collection needed, no production config touched.

**Load/performance:** embedding dimension 384 (same as current — no dimension-migration complexity). Load time 8.6s vs. current's 6.65s (comparable). Indexing 542 chunks: 11.5s vs. 11.6s (comparable). Query latency: 13.2ms vs. 7.1ms (roughly double, still negligible in absolute terms compared to existing retrieval/generation latency).

**Semantic-only comparison (isolated, NOT representative of production):**

| Direction | n | Current R@5 | Multilingual R@5 |
|---|---|---|---|
| English→English | 11 | 1.0 | 1.0 |
| Hinglish→English | 3 | 0.333 | **1.0** |
| Hindi→Hindi | 3 | 0.0 | 0.0 |
| Hinglish→Hindi | 1 | 0.0 | 0.0 |
| English→Hindi | 1 | 0.0 | **1.0** |

In isolation, this looks like an unambiguous win. **It is not**, once fused with BM25:

**Full hybrid-simulated comparison (production-representative):**

| Direction | n | Current hybrid R@5 | Multilingual-hybrid R@5 (simulated) |
|---|---|---|---|
| English→English | 11 | 0.909 | 1.0 |
| Hinglish→English | 3 | 1.0 | 1.0 |
| **Hindi→Hindi** | 3 | **1.0** | **0.667 (regression)** |
| Hinglish→Hindi | 1 | 0.0 | 0.0 (unchanged) |
| **English→Hindi (Miss 3)** | 1 | **0.0** | **0.0 (still unresolved)** |
| **Overall R@5** | 19 | **0.842** | **0.842 (unchanged)** |
| **Overall R@10** | 19 | **0.895** | **0.842 (worse)** |

Per-query rank detail confirms the mechanism: the multilingual model's own semantic ranking for Miss 3 improved dramatically (rank 180→3), but BM25's independent ranking for the same chunk remained poor (rank 127, unaffected by the embedding model), and RRF's fusion of one strong signal with one weak signal was not enough to overcome the weak leg — the fused rank stayed outside the top-5. Simultaneously, two of the three genuine Hindi→Hindi cases got measurably worse semantic rankings under the new model (one from rank 29→205, another 17 vs (see raw data) — net effect a real regression in a category the current system already handles perfectly.

**Conclusion: Category C — no safe generalized improvement found for this embedding migration**, based on rigorous, full-pipeline-simulated evidence, not the misleading isolated-language signal alone. This directly demonstrates why the task's own explicit warning against concluding from single-language improvement was necessary.

---

## 11. RRF Analysis

Confirmed directly in the miss analysis (Section 6) and the multilingual simulation (Section 10): RRF's equal-weighting of two independently-ranked legs means a genuine improvement in one leg can be substantially or fully neutralized when the other leg still performs poorly for the same case. No alternative RRF weighting or pool-size scheme was implemented (per the task's explicit "do not implement them yet" instruction) — this is documented as an architectural observation and a candidate area for future, carefully-evaluated experimentation, not something evaluated in isolation this phase.

---

## 12. Chunk-Quality Analysis

For both Hindi-source misses, the actual current chunk text was read directly and confirmed clean, readable, on-topic Devanagari Hindi — not the character-spaced/garbled ASR artifact documented elsewhere in the same source video (Phase 5I-A, Section 3). **Chunk/Team4A-extraction quality is explicitly ruled out as a contributing cause for these two specific misses**, based on direct evidence, not assumption. This does not rule out chunk-quality issues elsewhere in the corpus (the garbled-text pattern is real and was independently confirmed to exist in roughly half of that same video's other chunks in Phase 5I-A) — only that it is not the cause of these particular 3 misses.

---

## 13. Reranker Analysis

Offline only (`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`), pool size 20, never attached to any production `HybridRetriever` instance, never enabled.

| k | Recall before rerank | Recall after rerank |
|---|---|---|
| 1 | 0.474 | 0.789 |
| 3 | 0.789 | 0.895 |
| 5 | 0.842 | 0.895 |
| 10 | 0.895 | 0.947 |

Miss 1 fixed (rank 8→2). Miss 2 fixed dramatically (rank 14→1). Miss 3 **unaffected** (rank was `None` before and after — the candidate was never in the top-20 pre-rerank pool, and reranking, by design, cannot promote a candidate it was never given, exactly matching the task's own previously-documented observation). A new regression was introduced: `ci_dbms_conflict_serializability__q_english` moved from rank 4 (a hit at k=5) to rank 7 (a miss at k=5, recovered only at k=10) — a real, concrete instance of reranking hurting a previously-correct case. Average latency: 1.8–2.0s per query at pool=20 — a real, non-trivial addition on top of existing 10–180s generation latency, though far smaller than Phase 5H's pool=100 finding (up to 286s).

**Conclusion: Category B — promising but insufficient evidence.** Net Recall@5/10 improves, but with a real new failure mode introduced, zero help for the most severe miss, and unquantified latency-at-scale/production-load risk. Reranker remains disabled, per instruction, regardless of this result.

---

## 14. Generalization Analysis

The 19-entry canonical ground truth is limited to Operating Systems and DBMS (Section 3, Phase 5I-A) — a genuine corpus limitation, not fabricated or worked around. This phase added `phase5i_b_generalization_supplement_candidate.json` (2 entries, Data Structures and Computer Networks, against the validation collection) to test generalization beyond those two domains. **Both new entries hit at rank 1** in live verification — the pipeline generalizes cleanly to these additional subjects for genuinely in-scope, same-language queries, consistent with the overall pattern already established (strong same-language performance, weak cross-language performance, regardless of subject). This supplement is intentionally small (2 entries) — most sampled Hindi-language content in the other validation workspaces (Mathematics, Machine Learning) showed the same garbled-text quality issue already documented for the canonical OS video, and no clean Hindi samples were found quickly enough this phase to build genuine additional Hindi entries; recorded as an explicit, disclosed limitation rather than invented data.

---

## 15. Latency/Performance

- Baseline retrieval (canonical, 57 query/mode pool captures): fast, well under 1s/query on average (small 542-point corpus).
- Multilingual embedding: comparable load/index time to current model, ~2x query-embedding latency (13ms vs 7ms) — negligible in absolute terms.
- Reranker: 1.8–2.0s/query at pool=20 (real, non-trivial; substantially worse at larger pool sizes per Phase 5H's separate finding of up to 286s at pool=100).
- No change to LLM generation latency — not touched this phase.

---

## 16. English Regression Analysis

**No English regression found in either candidate.** Multilingual embedding: English→English hybrid-simulated R@5 improved slightly (0.909→1.0, within the noise of n=11). Reranker: no English case regressed except the one cross-domain DBMS case noted in Section 13 (English query, English source — technically an English-language case that got worse, which should be weighed alongside the two English-language cases it fixed). Neither candidate shows a clear, unambiguous "English gets worse" pattern, but neither shows a clean, unambiguous "no regressions anywhere" pattern either — the reranker's one new miss is a real, English-language regression that must be counted honestly.

---

## 17. Security/Isolation Impact

Not independently re-tested this phase — no code affecting `HybridRetriever`'s workspace/document filtering, `ConversationManager`, or the Phase 5F/5G injection-defense code was touched. All retrieval this phase was scoped per-entry by the ground truth's own `workspace_id`, using the real, unmodified workspace-filtering path. No new isolation risk was introduced, since no production code changed.

---

## 18. Production-Change Decision

- **Embedding migration (`paraphrase-multilingual-MiniLM-L12-v2`): Category C — NO SAFE IMPROVEMENT FOUND.** Full-pipeline-simulated evidence shows no net Recall@5 gain, a Recall@10 regression, and a real Hindi→Hindi regression in a category the current system already handles perfectly. Not implemented.
- **Reranker (pool=20): Category B — PROMISING BUT INSUFFICIENT EVIDENCE.** Real net Recall gains at this sample size, but a new regression, zero help for the most severe miss, and real added latency not tested at production scale/concurrency. Remains disabled, per instruction, regardless.
- **Threshold change: Category C — NO SAFE IMPROVEMENT FOUND.** Completely flat across 0.0–0.7; no evidence supports any change.
- **Top_k change: Category D — DATA/CORPUS-DEPENDENT TRADEOFF, not evaluated for generation-quality impact.** Would recover 2 of 3 misses at the retrieval-metric level but was not tested for its effect on LLM answer quality (more candidates historically correlates with more irrelevant-context narration risk, per Phase 5D/5E/5H — not re-tested here).

**No production code was changed this phase.**

---

## 19. Exact Recommended Next Step

1. **If the reranker is to be seriously considered**, it needs: (a) a larger ground truth (19 entries is too small to be confident the one new regression isn't representative of a broader pattern), (b) latency testing under realistic concurrent load (this phase only tested sequential, pool=20 calls), and (c) a generation-quality check (does the reranked evidence actually produce better LLM answers, not just better Recall@k — per Phase 5D/5E/5H's repeated finding that retrieval metrics and generation quality don't always move together).
2. **Do not pursue the specific multilingual embedding model tested here further** without first addressing BM25's demonstrated inability to bridge cross-script queries — since this phase showed the embedding side alone cannot overcome a weak BM25 leg in RRF fusion, any future embedding experiment should be evaluated the same rigorous way (full hybrid-simulated, not isolated) from the start.
3. **Investigate whether BM25's script-mismatch failure (Miss 2's exact 0.0 score) could be addressed by a language-agnostic, non-model-migration change** — e.g., transliteration-aware tokenization — as a potentially more targeted fix than a full embedding migration, though this was not evaluated this phase and is flagged only as a direction, not a recommendation.
4. **Expand the ground truth**, particularly its Hindi-source-content diversity (only 5 of 19 entries involve Hindi source content, and only 2 involve genuine cross-language directions) before drawing any further quantitative conclusions about cross-language retrieval quality.

---

## 20. Explicit List of Files Created/Modified

**Created (all new, none committed):**
- `team4b/data/m6_phase5i_b_retrieval_quality_report.md` (this report)
- `team4b/data/m6_phase5i_b_retrieval_quality_report.json`
- `team4b/data/phase5i_b_generalization_supplement_candidate.json`

**Modified:** none. No application code, test file, `.env`, or configuration was changed this phase.

---

## Data Safety Confirmation

`educopilot_chunks`: 542 → 542, confirmed unchanged. `educopilot_chunks_product_validation`: 4938 → 4938, confirmed unchanged. Team4B full test suite: 1302 passed / 3 skipped / 1 known pre-existing failure — identical to every prior phase's baseline, zero regression, known failure neither fixed nor weakened. No commit, no push, no PR.
