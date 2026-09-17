# Phase 4C — Hindi/Hinglish Source Retrieval Recall + Mongo/Qdrant Alignment Investigation

**Investigation only. Nothing in production was changed.** All numbers below are from direct, read-only measurement against the real canonical `educopilot_chunks` collection (1650 points, unchanged before/after — confirmed at the end of this document) and real MongoDB `files` collection (read-only).

---

## 1. Executive Summary

Two distinct, separately-confirmed root causes were found:

1. **A Mongo/Qdrant data-alignment gap, unrelated to embeddings or reranking.** 6 of the 10 real document_ids in `educopilot_chunks` (587 of 1650 chunks, 35.6%) have **no matching MongoDB `files` record**. Production's real, fail-closed `GenerationAuthorityClient` would exclude every chunk from those 6 documents from every query, regardless of retrieval quality. **21 of the 75 approved benchmark entries (28%)** reference a chunk from one of these orphaned documents — meaning nearly a third of the benchmark has been silently measuring retrieval quality for content that real production would never actually be able to return. 4 of the 6 orphaned documents are duplicate ingestions of the *same* OS textbook that already has one valid Mongo-backed copy; the other 2 (an admissions-list PDF and a 1-chunk stray mp4) are unrelated orphaned artifacts.

2. **A confirmed, structural candidate-generation failure for English→Hindi and Hinglish→Hindi queries, fully independent of the above.** For all 8 English→Hindi and 7 of 8 Hinglish→Hindi benchmark queries, the correct chunk is **not present anywhere in the top 100** of *either* the semantic leg or the BM25 leg, individually or after RRF fusion — confirmed by direct measurement, not inferred. No amount of reranking or pool-size increase up to 100 can fix this, because reranking can only reorder what retrieval already found. This is a **candidate-generation** problem, not a ranking problem. Hindi→Hindi is meaningfully different and much healthier: BM25 (Devanagari-aware since Phase 1) finds the correct chunk in the top 100 for 7 of 8 queries, and the fused RRF list finds it for all 8 of 8 — the remaining gap there is a pool-size/ranking issue (fixable by pool size + reranking), not a candidate-generation issue.

---

## 2. Mongo/Qdrant Alignment Table

| document_id | Qdrant chunks | Mongo record? | workspace_id | user_id | source_type | source_language (inferred) | Mongo `currentIngestionGeneration` | Qdrant `ingestion_generation` | Would real GenerationAuthorityClient allow it? |
|---|---|---|---|---|---|---|---|---|---|
| `6aa90e314ac03b89c7624ccb` | 115 | ✅ Yes | `6a912a1883f46878932e0eec` | `6a8898b42a813283b77345ab` | pdf | english | 1 | 1 | ✅ **Yes** |
| `6aa8457c8a7bd709c53a5f46` | 250 | ✅ Yes | `6a8de2d7e43679cbe2ee243d` | `6a8898b42a813283b77345ab` | pdf | english | 1 | 1 | ✅ **Yes** |
| `6aaa4cd56eee7990194e5168` | 527 | ✅ Yes | `6a912a1883f46878932e0eec` | `6a8898b42a813283b77345ab` | youtube | english | 1 | 1 | ✅ **Yes** |
| `6aaa7e8c81e2b76728b76bb6` | 177 | ✅ Yes | `6a912a1883f46878932e0eec` | `6a8898b42a813283b77345ab` | youtube | **hindi** | 1 | 1 | ✅ **Yes** |
| `6aa72e4416cbab6b27d5f50b` | 115 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | pdf | english | — | 1 | ❌ **No — fail-closed** |
| `6aa846698a7bd709c53a5f4e` | 115 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | pdf | english | — | 1 | ❌ **No — fail-closed** |
| `6aa72dae16cbab6b27d5f508` | 115 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | pdf | english | — | 1 | ❌ **No — fail-closed** |
| `6aa90d9f4ac03b89c7624cc8` | 115 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | pdf | english | — | 1 | ❌ **No — fail-closed** |
| `6aa72df916cbab6b27d5f50a` | 120 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | pdf | english | — | 1 | ❌ **No — fail-closed** |
| `6aa90eb64ac03b89c7624cce` | 1 | ❌ No | `6a912a1883f46878932e0eec` (Qdrant only) | — | mp4 | english | — | 1 | ❌ **No — fail-closed** |

**Total:** 1650 Qdrant chunks across 10 documents; **1069 chunks (64.8%) are production-reachable**, **581 chunks (35.2%) are permanently unreachable** under the real generation-authority check as it stands today.

**Workspace-id cross-check:** for all 4 documents that do have a Mongo record, the Mongo `workspaceId` and the Qdrant chunk's own `workspace_id` payload field match exactly — no workspace-isolation inconsistency found.

### Explaining the 6 missing records
- `6aa72e4416cbab6b27d5f50b`, `6aa846698a7bd709c53a5f4e`, `6aa72dae16cbab6b27d5f508`, `6aa90d9f4ac03b89c7624cc8` — **duplicate ingestion artifacts**. Direct text comparison (done in Phase 3) already proved these 4 are byte-for-byte the same underlying OS textbook as `6aa90e314ac03b89c7624ccb` (which *does* have a valid Mongo record). These are not "genuinely missing" documents — they are extra Qdrant-only copies of one document that was properly ingested once.
- `6aa72df916cbab6b27d5f50a` (Maharashtra CET admissions list) and `6aa90eb64ac03b89c7624cce` (1-chunk stray mp4, text = "you") — **genuinely orphaned/stale Qdrant data** with no plausible corresponding Mongo record under any other identifier checked. Not educational content in the first place (already flagged unusable in Phase 3).

No record was found "under another identifier" — the 6 missing `_id` values simply don't exist in the `files` collection at all.

---

## 3. Hindi-Source Retrieval Diagnosis (Parts B/C combined)

24 queries were diagnosed in full (8 concepts × 3 query languages), each traced through: semantic top-100, BM25 (full workspace ranking), RRF-fused top-100 at threshold 0.0, RRF at production threshold 0.3, final top-10 with no reranker, final top-10 with reranker (pool=40, production default), and a diagnostic reranked pool=100 pass (evaluation-only, not a production change).

### Aggregate stage recall (count of 8 queries per row where the correct chunk was found)

| query→source | Semantic top-100 | BM25 top-100 | RRF top-100 (θ=0.0) | Final top-10, no rerank | Final top-10, rerank (pool=40) | Found if pool=100 |
|---|---|---|---|---|---|---|
| English→Hindi (n=8) | **0/8** | **0/8** | **0/8** | 0/8 | 0/8 | **0/8** |
| Hinglish→Hindi (n=8) | 1/8 | 0/8 | 1/8 | 0/8 | 0/8 | 1/8 |
| Hindi→Hindi (n=8) | 5/8 | 7/8 | **8/8** | 3/8 | 4/8 | **8/8** |

---

## 4. English→Hindi Analysis

**Confirmed root cause: candidate generation failure, not ranking.** For all 8 queries, `semantic_top100_rank = None` — the correct chunk is not among the 100 most semantically similar chunks (out of ~1400+ in the workspace) under the production `all-MiniLM-L6-v2` embedding model. BM25 ranks are 917–1375 (bottom of the corpus) for all 8, confirming BM25 provides no rescue either. This BM25 result is **structurally certain, not merely observed**: Phase 1's tokenizer matches ASCII and Devanagari via two entirely separate regex alternatives (`[A-Za-z0-9]+` vs. the Devanagari block) — an English query can never produce a token that lexically equals a Devanagari chunk token, so BM25 cannot contribute a lexical match across this script boundary by construction, for any query, not just these 8.

Reranking cannot help because there is nothing to promote: even the diagnostic pool=100 rerank pass found no relevant chunk for any of the 8 queries.

## 5. Hinglish→Hindi Analysis

Same near-total failure as English→Hindi, with one partial exception: `c_process_stack_contents__q_hinglish` reached semantic rank 84 and RRF rank 98 (just inside the top-100), and reranking at pool=100 moved it to rank 70 — a real but practically useless improvement (nowhere close to a top-10 cut). The other 7 of 8 Hinglish→Hindi queries show the identical complete-failure pattern as English→Hindi (BM25 ranks 614–1341; semantic ranks all `None`). Hinglish queries here are written in Latin script, so they share BM25's structural cross-script blindness with English queries; the one exception suggests the embedding model occasionally captures *some* latent cross-script signal, but not reliably.

## 6. Hindi→Hindi Analysis

Meaningfully healthier, and the clearest evidence that **Phase 1's BM25 Devanagari work matters**: for 3 of 8 queries (`c_os_modules`, `c_sjf_not_implementable`, `c_page_fault_definition`), semantic search alone found *nothing* in the top 100 (`None`), but **BM25 found the correct chunk at rank 1, rank 7, and rank 1 respectively** — pure lexical Devanagari matching succeeding where the embedding model failed outright. RRF fusion combining both legs finds the correct chunk in the top 100 for **all 8 of 8** queries (compare: BM25 alone only found 7/8, semantic alone only found 5/8 — fusion's union coverage is strictly better than either leg).

The remaining gap: 4 of 8 have an RRF-fused rank between 46 and 62 — just outside the production default pool size of 40, so they miss the final top-10 today. Enlarging the diagnostic pool to 100 and reranking recovers 3 of these 4 to rank 1, rank 9, and rank 1; the 4th (`c_fcfs_disk_scheduling`) improves from rank 60 to rank 14 — better, but still would not make a top-10 cut even with a 100-candidate pool. One query (`c_hold_and_wait_deadlock`) already succeeds with the existing production pool=40 once reranking is applied (RRF rank 15 → reranked into the top 10).

---

## 7. Stage-by-Stage Recall (all 24 queries)

See Section 3's table above for the aggregate, and `phase4c_candidate_recall_diagnosis.json`'s `part_bcd_stage_by_stage.per_query` array for the exact per-query rank at every stage (semantic, BM25, RRF@0.0, RRF@0.3, final with/without reranker, pool=100 diagnostic).

## 8. Candidate Pool Findings (Part E — evidence reported, no default changed)

Enlarging the reranking candidate pool from the production default of 40 to a diagnostic 100 **materially helps Hindi→Hindi (all 8 of 8 become findable) but has zero effect on English→Hindi (0/8) and almost no effect on Hinglish→Hindi (still 1/8, and that 1 remains far from a usable rank).** This is reported as evidence only — **the production default of 40 was not changed**, both because Part E explicitly instructs against a blind pool-size fix and because the data itself shows pool size is *not* the bottleneck for the two language pairs that most need help (English/Hinglish→Hindi); it only helps the one pair (Hindi→Hindi) that already has a partially-working candidate-generation stage. Blindly enlarging the pool would add real latency (see Section 11) for zero benefit on the actual hard cases.

## 9. Chunk-Quality Findings (Part D)

All 8 underlying Hindi-source chunks used in this diagnosis were inspected directly (full text, not excerpts):
- 5 of 8 chunks (`os_modules`, `sjf_not_implementable`, `page_fault_definition`, `fcfs_disk_scheduling`, and previously `memory_hierarchy_locality`'s first half) begin with a **short garbled, letter-spaced ASR artifact** (e.g. `"नम े ं ट ऑफ इ ं ड ि य ा"`) for roughly their first 10–15 words, before transitioning to clean, well-formed Devanagari for the rest of the chunk (~130–150 words total). This looks like a transcription-boundary echo effect, not random noise.
- 1 concept (`c_memory_hierarchy_locality`) is confirmed to **genuinely span two chunks** (already identified and fixed by adding the second chunk to ground truth in Phase 3.1) — its explanation is incomplete in either chunk alone.
- The other 3 chunks (`real_time_os`, `process_stack_contents`, `hold_and_wait_deadlock`) show no ASR artifact and are self-contained.
- **None of these chunk-quality issues explain the English/Hindi→Hindi candidate-generation failure directly** — the chunks that succeed for Hindi→Hindi BM25 (rank 1, 1, 7) are the *same* chunks that completely fail for English→Hindi semantic search, so the failure tracks the query language, not chunk cleanliness. Chunk-quality issues are a real, secondary concern (likely a partial contributor to the weaker semantic embedding signal even for Hindi→Hindi) but are not the primary explanation for the cross-script failure.

## 10. Filtering/Generation-Authority Findings

The Hindi-source document (`6aaa7e8c81e2b76728b76bb6`) **has a valid Mongo record** and passes the real, unmodified `GenerationAuthorityClient` (confirmed by a live call: `get_current_generations` returned `{'6aaa7e8c81e2b76728b76bb6': 1}`, matching the chunks' own `ingestion_generation=1`). This diagnosis used the **real** production authority client throughout Parts B/C (no fake/bypass needed here, unlike Phase 4B's broader benchmark) — so none of Section 3–6's findings are an artifact of relaxed authority checking. Workspace filtering was likewise the real, unmodified `workspace_id` scoping throughout. No candidate was ever excluded by document_id filtering in this diagnosis (none was applied).

## 11. Latency Measurements

| Stage | Mean latency (24 queries) |
|---|---|
| Semantic search | 847ms* |
| BM25 search | 137ms |
| RRF (both legs, parallel) | 129ms |
| Reranking, pool=40 (production default) | 3.35s |
| Reranking, pool=100 (diagnostic only) | 6.09s |

*\*The semantic mean is inflated by one-time model lazy-loading on the very first call inside the loop; BM25/RRF's much lower, more consistent numbers are more representative of true steady-state per-query cost for those stages.* Reranking cost scales roughly linearly with pool size (2.5× the pool → ~1.8× the latency here), reinforcing Section 8's point that a larger pool is not a free lever.

## 12. Root Causes, by Confidence

**Confirmed (direct measurement, not inference):**
- 6 of 10 documents (587/1650 chunks) have no Mongo `files` record and would be excluded by the real, unmodified fail-closed `GenerationAuthorityClient`, independent of retrieval quality.
- For English→Hindi (8/8) and Hinglish→Hindi (7/8) queries, the correct chunk is absent from the top 100 of both the semantic leg and the BM25 leg — confirmed by direct search, not assumed.
- BM25 cannot lexically match across the Devanagari/Latin script boundary, by construction of the tokenizer (Phase 1) — a structural, not empirical, fact.
- For 3 of 8 Hindi→Hindi queries, BM25 alone succeeds (rank 1, 1, 7) where semantic search alone finds nothing in the top 100 — Devanagari-aware BM25 is independently load-bearing for Hindi→Hindi recall.
- Reranking cannot recover a candidate that never enters the pool (structural property of the reranker's own design, confirmed again here empirically for all 15 English/Hinglish→Hindi failures).

**Strongly supported (consistent evidence, some inherent measurement limits):**
- The weak/absent semantic signal for English/Hindi/Hinglish→Hindi is primarily an embedding-model limitation (`all-MiniLM-L6-v2` is English-centric), not primarily a chunk-quality artifact — the ASR letter-spacing noise is real but affects only the first ~10-15 words of otherwise-clean chunks, and the SAME chunks succeed strongly via BM25 for Hindi queries, meaning the chunk's actual textual content is adequate; it's the query→chunk semantic mapping across scripts that's weak.
- A larger candidate pool would recover most (not all) of the remaining Hindi→Hindi gap, but would not touch English/Hinglish→Hindi at all.

**Unresolved:**
- Why the multilingual candidate embedding model (Phase 4A) sometimes helps (e.g. one query's semantic rank improved 261→27) and sometimes hurts (another query's rank worsened 132→1030) for the same general Hindi→English direction is not explained by this investigation — would need a larger, dedicated embedding-behavior study, out of scope here.
- Whether the ASR letter-spacing artifact has a measurable (vs. negligible) effect on embedding quality specifically was not isolated (would require re-embedding a hand-cleaned version of a chunk for comparison, which is out of scope for a read-only investigation).
- Whether Hinglish text with heavier code-switching (mixing more Devanagari-transliterated vocabulary) would behave differently than the pure-Latin-script Hinglish tested here is unresolved — the benchmark's Hinglish queries are 100% Latin script, a reasonable but not exhaustive sample.

## 13. Recommended Next Phase (Phase 4D)

Focus specifically on **candidate generation for cross-script queries (English/Hinglish→Hindi)**, since this investigation has ruled out reranking, pool size, and chunk quality as the primary levers for that specific failure mode. This is fundamentally a "the query and the target content live in different, poorly-aligned regions of the embedding space, and there is no lexical bridge" problem — the kind of gap that a genuinely cross-lingual embedding model, or a translation/query-normalization step, is designed to close (evaluate rather than assume). Separately, and independently, someone should investigate/resolve the Mongo/Qdrant data-alignment gap (6 orphaned documents) as an operational/data-hygiene matter — it silently affects 28% of the current benchmark's validity and would affect real users querying those 4 duplicate-textbook copies today.

## 14. Explicit Statement of What Was NOT Changed

- `educopilot_chunks` was never written to. Point count: **1650 before this investigation, 1650 after** (verified by a direct check at the start and end of this task).
- No Qdrant collection was created, deleted, or modified. No new temporary collections were created in this phase at all (all diagnosis used direct `search_similar`/`scroll`/in-memory BM25 against the existing canonical collection).
- No MongoDB write occurred — every Mongo access was a `find_one`/`get_current_generations` read.
- No embedding migration occurred; `all-MiniLM-L6-v2` remains the production model throughout every measurement in this document.
- `RERANKER_ENABLED` was not set in production; the reranker was only ever constructed directly inside this investigation's own read-only diagnostic scripts, never through `app/api/dependencies.py`.
- Team4A and Team4C were not touched.
- No `.env` file was read for its secret values or modified; only non-secret settings (URLs, model names, thresholds) already documented in prior phases were used.
- No test was weakened, deleted, or modified to force a pass.
