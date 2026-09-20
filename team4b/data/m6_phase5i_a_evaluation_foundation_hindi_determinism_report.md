# M6 Phase 5I-A — Ground-Truth Rebuild + Hindi Retrieval Determinism Forensic

**Status: FORENSIC COMPLETE. No production code changed. No retrieval algorithm, threshold, reranker, embedding model, or LLM behavior modified.**

---

## 1. Executive Summary

This phase had two objectives. **Objective A** (build a trustworthy current-corpus evaluation foundation) succeeded: a new, real, evidence-based ground truth (19 entries) was built by directly reading current canonical chunk text, and live-verified at an 84% top-5 hit rate (16/19) — a credible number, with the 3 misses themselves informative (Hindi-script vs. Hinglish retrieval divergence, cross-language retrieval weakness) rather than dataset defects. Building this dataset also surfaced and corrected a real methodological error carried since Phase 5H: `RetrievalResult.chunk_id` (what the pipeline actually returns to callers) is the **payload-level** `chunk_id` field, not Qdrant's own raw point `id` (a deterministic `uuid5` hash of the former, confirmed via direct code read of `vector_store.py`). Phase 5H's ground-truth-ID check used the wrong field; re-run correctly this phase, it still confirms 0/26 old ground-truth IDs exist in canonical — so Phase 5H's bottom-line conclusion (the old ground truth is unusable) **stands**, but the verification method needed this correction for future rigor.

**Objective B** (determine the source of the Phase 5H-observed Hindi retrieval nondeterminism) produced a clean, decisive, and unexpected result: **the retrieval pipeline is provably 100% deterministic.** Every traced stage — query embedding, semantic Qdrant search, BM25, RRF fusion, generation-authority filtering, and final top-k — was bit-for-bit identical across 90 repeated calls spanning 8 query/collection/search-mode combinations, including a direct reproduction of the exact Hindi query ("स्टैक क्या है?") previously implicated. **Zero variation was found anywhere.** Investigating further, the specific pair of Phase 5H observations previously cited as evidence of "the identical query behaving inconsistently" is confirmed, by direct re-reading of that phase's own script, to have used **two different retrieval queries** — Hindi "स्टैक क्या है?" in one case, English "What is a stack?" in the other. **This was never a same-input, different-output nondeterminism bug — it was a mischaracterization in Phase 5H's own report**, now corrected here. The apparent "inconsistency" reflects ordinary (if imperfect) cross-language retrieval-quality variance — the already-documented Hindi/Hinglish weakness from Phase 5E/5H — not a new determinism defect.

**No production retrieval change is recommended or implemented.** The evidence-supported direction for Phase 5I-B is to continue investigating retrieval *quality* (especially cross-language) using the new, validated ground truth — not retrieval *determinism*, which this phase closes out as a non-issue.

---

## 2. Exact Repository/Branch/Commit

- Repository: `D:\Major_Project\project\EduCopilot-M6-Local\EduCopilot-M6-Local`
- Branch: `phase5-cross-script-retrieval`
- Commit at phase start: `6f8a93377fdaf7ebca3ef3b8851ff541fb2b14d8`
- Git status at phase start: identical to Phase 5H's end state (`llm_generator.py` shows Phase 5F's retained diff; all other listed files are untracked reports from prior phases). No new modifications beyond this phase's own additions.

---

## 3. Canonical Corpus State

- Collection: `educopilot_chunks` — confirmed **542 points**, vector config `{size: 384, distance: Cosine}`, status `green`, before and after this phase.
- Validation collection: `educopilot_chunks_product_validation` — confirmed **4938 points**, same vector config, before and after this phase.
- Team4B retrieval configuration confirmed via direct read of `app/core/config.py`: `default_top_k=5`, `default_score_threshold=0.3`, `default_search_mode="hybrid"`, `rrf_k=60`, `hybrid_candidate_pool_size=100`, `reranker_enabled=False` (confirmed disabled), `reranker_model_name="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"`, `embedding_model_name="all-MiniLM-L6-v2"`.
- **Canonical corpus structure (surveyed this phase via full read-only scroll):** only **2 workspaces**, **3 documents**, **542 points** total — `6a8de2d7e43679cbe2ee243d` (250 points, 1 DBMS PDF), `6a912a1883f46878932e0eec` (292 points, split across 1 OS PDF [115 points] and 1 OS YouTube video in Hindi [177 points]). This is a real, concrete limitation on how "generalized" any canonical-corpus ground truth can be (Section 6).
- **Architectural finding**: every one of the 542 points' Qdrant point `id` differs from its own payload `chunk_id` field. Confirmed via direct code read (`vector_store.py`'s `_point_id_for()`): the Qdrant point ID is a deterministic `uuid5(fixed_namespace, chunk_id)` hash of the logical `chunk_id`, which is separately stored in the payload and is what `search_similar()`/`scroll_all_chunks()` actually return as `RetrievalResult.chunk_id`. This is intentional, consistent, deterministic architecture — not a bug — but it is an easy trap for any external verification script (including this engagement's own Phase 5H script) that queries Qdrant's raw point ID instead of the payload field.

---

## 4. Old Ground-Truth Validity Assessment

Both `team4b/data/phase3_generalized_ground_truth_candidate.json` and `team4b/data/phase2_ground_truth_approved.json` were inspected this phase:

- **`phase2_ground_truth_approved.json`** (75 entries): despite its filename, its own entries still carry `"status": "CANDIDATE_NOT_VALIDATED"` — it was never actually approved. Its first entry is verbatim identical to `phase3`'s (same `query_id`, same `relevant_chunk_ids`), confirming it is not an independently-produced or human-reviewed dataset. **This filename is misleading and should not be trusted as "approved" evidence.**
- **`phase3_generalized_ground_truth_candidate.json`** (75 entries): already correctly flagged by its own embedded notice as `CANDIDATE_NOT_VALIDATED`. Re-verified this phase, **using the correct `payload.chunk_id` field** (Section 3's correction) rather than Qdrant's raw point ID: **still 0 of 26 unique referenced chunk IDs exist in the current canonical corpus.** Phase 5H's substantive conclusion (this ground truth is unusable against the current corpus) is **reconfirmed**, with the verification method now corrected for rigor.
- Neither file is silently overwritten or reinterpreted by this phase's work — both remain in place, and this phase's new file is a separate, clearly-named addition.

---

## 5. New Current-Corpus Evaluation Dataset

Created: `team4b/data/phase5i_a_current_corpus_ground_truth_candidate.json` — **19 entries**, every `relevant_chunk_ids` value built by **directly reading real, current chunk text** from a fresh, complete read-only scroll of the canonical collection performed this phase (not copied, remapped, or inferred from any prior file).

Coverage achieved:
- **Language:** 12 English, 4 Hinglish, 3 Hindi query entries (source content is English for the 2 PDFs, Hindi for the video).
- **Cross-lingual pairs, deliberately constructed:** 2 entries pair a Hindi-phrased and a Hinglish-phrased query against the identical target chunk (`ci_os_race_condition__q_hindi` / `__q_hinglish`), and 2 entries pair a Hindi-phrased and a genuinely English-phrased query against the identical Hindi-source-audio target chunk (`ci_os_virtual_memory_paging__q_hindi` / `ci_os_virtual_memory__q_english_over_hindi_source`) — specifically to let future work isolate script effects from true cross-language effects.
- **Source type:** 14 PDF, 5 YouTube.
- **Domain:** 13 Operating Systems, 6 DBMS (matching the only two domains the current canonical corpus actually contains).
- **Query type:** 7 factual, 7 explanation, 5 conceptual.
- Every entry stores: the real payload-level `chunk_id` (plus, separately, the underlying Qdrant point ID for direct lookups), `workspace_id`, `document_id`, `source_type`, `query_language`, `source_language`, a real verbatim `chunk_text_excerpt` read directly from the current chunk, a truncated SHA-256 hash of that excerpt for integrity re-verification, an explicit `rationale`, and `status: "CANDIDATE"` for every single entry — **none are marked "VALIDATED" or "approved."** No human review has occurred.

**Live verification performed this phase** (retrieval-only, real production `HybridRetriever`, production-default `top_k=5, score_threshold=0.3, search_mode=hybrid`): **16/19 entries (84%) had their target chunk within the real top-5 results.** The 3 misses are documented, not hidden: `ci_os_process_definition__q_english` missed for an as-yet-uninvestigated reason; `ci_os_race_condition__q_hinglish` missed while its Hindi-script sibling hit at rank 3 (a real script-sensitivity data point); `ci_os_virtual_memory__q_english_over_hindi_source` missed while its Hindi-phrased sibling hit at rank 3 (a real cross-language data point, consistent with the already-known F2 finding).

---

## 6. Dataset Limitations (explicit, per the task's own instruction)

- **The current canonical corpus supports only 2 domains (Operating Systems, DBMS) and 2 workspaces.** It cannot support a "multiple subjects" claim — this dataset is domain-limited by the corpus itself, not by design choice. A genuinely multi-subject ground truth (covering Data Structures, Computer Networks, Mathematics, Machine Learning, etc., as those subjects exist only in the separate 4938-point validation collection) would require building against that collection instead, which was out of this phase's explicit scope (the old ground truth, and this phase's replacement, both target canonical specifically).
- **No genuine multi-document query was constructed.** The OS workspace does have 2 documents (a PDF and a video), but no natural question in this phase's review required combining evidence from both without artificially forcing it — recorded as a gap, not silently worked around.
- **No "English → Hindi" query (an English question whose ONLY correct evidence is Hindi-language source content) beyond the 1 constructed pair (`ci_os_virtual_memory__q_english_over_hindi_source`)** — a deliberately minimal test of true cross-language retrieval, not a broad one.
- **Only 3 documents total** limits statistical power for any future Recall@k computation — findings from a 19-entry, 3-document dataset should be treated as indicative, not conclusive, for the whole product.

---

## 7. Hindi Query Matrix

| Query | Language | Collection | Workspace | Evidence status |
|---|---|---|---|---|
| स्टैक क्या है? | Hindi | validation (4938) | Data Structures | Reproduces the exact Phase 5G/5H case; evidence exists (real DS content) |
| What is a stack? | English | validation | Data Structures | Control for the above |
| Stack kya hota hai? | Hinglish | validation | Data Structures | Control for the above |
| मल्टी प्रोग्रामिंग ऑपरेटिंग सिस्टम क्या होता है? | Hindi | canonical (542) | OS (`6a912a18...`) | Confirmed rank-1 real evidence (Section 5) |
| What are the five services provided by an operating system? | English | canonical | OS | Confirmed rank-1 real evidence, strong unambiguous English control |

`स्टैक क्या है?`'s relevant evidence does **not** exist in the current 542-point canonical corpus (no "stack" data-structure content exists there — canonical is OS/DBMS-only, Section 3) — per the task's own conditional instruction, it was tested against the **validation** collection instead, where it originally succeeded/failed in Phase 5G/5H, and where its evidence is confirmed present.

---

## 8. Repetition Methodology

For each of 5 query/collection pairs above (plus 3 additional single-mode variants for the primary Hindi case), the query was run **15 times** (5 for the semantic-only/keyword-only/hybrid mode comparison) through a from-scratch instrumented pipeline that independently calls each real, unmodified production component — `Embedder.embed_query()`, `VectorStoreManager.search_similar()`, `BM25Index.search()`, `HybridRetriever.reciprocal_rank_fusion()`, and `HybridRetriever`'s own (unmodified) generation-authority-filtering methods — rather than treating `HybridRetriever.retrieve()` as an opaque black box, so every stage's output could be captured and hashed independently within the same call. All of: exact query text, workspace_id, collection, top_k, score_threshold, embedding model, search_mode, document filter (`None` throughout), and reranker state (never attached) were held constant across every repeat. **90 total runs, 0 errors.**

---

## 9. Embedding Determinism Results

**100% identical across every repeat, every query.** The full 384-dimension query embedding vector (not just its first/last values — the complete vector, formatted to 10 decimal places and SHA-256 hashed) produced exactly 1 distinct hash across all 15 repeats, for every one of the 8 query/mode/collection combinations tested. `sentence-transformers` in this environment, on this hardware, with this model, run in evaluation mode (no dropout), is confirmed deterministic for repeated identical input within a process.

---

## 10. Qdrant Determinism Results

**100% identical.** The raw semantic-leg candidate list (chunk_id + score, top 15 recorded per run) showed exactly 1 distinct result set across all 15 repeats for every query tested. No evidence of Qdrant-side nondeterminism (equal-score ordering instability, HNSW search variance, or similar) was found in this environment for any tested query.

---

## 11. BM25 Determinism Results

**100% identical.** The raw BM25-leg ranked list (chunk_id + score, top 15 recorded) showed exactly 1 distinct result set across all 15 repeats for every query. The BM25 index was rebuilt fresh once per query-block (mirroring `refresh_bm25_corpus()`'s real, documented on-demand-rebuild behavior) and was stable within that build — no evidence of iteration-order-dependent scoring instability (e.g., from Python dict/set iteration) was found.

---

## 12. RRF Determinism Results

**100% identical.** The fused (chunk_id, raw_rrf_score) list (top 15 recorded, full float precision) showed exactly 1 distinct result set across all 15 repeats for every query — consistent with `reciprocal_rank_fusion()`'s own explicit, documented tie-break-by-chunk_id-ascending design (confirmed by code read in an earlier phase), which eliminates any Python dict/set-ordering-dependent instability at the fusion step by construction.

---

## 13. Generation-Authority Results

**100% identical.** The number of candidates dropped by generation-authority filtering (both legs) was identical across all 15 repeats for every query (0 drops observed in every tested case — every candidate's `document_id`/`ingestion_generation` metadata matched the authoritative current generation in every run). No evidence of Mongo-lookup-driven variability was found for these specific queries; this does not rule out authority-driven variability under different conditions (e.g., a document actively being re-ingested mid-query), which was not tested this phase.

---

## 14. Final Retrieval Determinism

**100% identical, exact scores included.** The final top-5 `(chunk_id, relevance_score)` list, and independently the SHA-256 hash of each returned chunk's actual text, were identical across all 15 repeats for every one of the 8 query/mode/collection combinations — **90/90 runs, 0 variation, at every stage, with zero exceptions.**

---

## 15. LLM Generation Variability

**Not tested this phase**, by deliberate scope choice, consistent with the task's own Section 7-G instruction to separate retrieval determinism from generation variability and only test generation "after retrieval behavior is understood." Since retrieval was found fully deterministic, LLM-generation-stage variability (already separately documented as real and significant in Phase 5D/5F/5G's evidence — e.g., `SPOOF-5`'s stochastic response content across repeated identical prompts) remains a known, separate, unaffected phenomenon. **Retrieval nondeterminism and LLM generation nondeterminism are confirmed, this phase, to be two entirely separate concerns — only the latter is real in this codebase, based on all evidence gathered across this engagement so far.**

---

## 16. Root-Cause Analysis

**No retrieval nondeterminism exists to root-cause — none was found.** The investigation instead root-caused the *original Phase 5H observation itself*: re-reading that phase's own script confirmed the two contrasting cases used **different retrieval queries** (Hindi "स्टैक क्या है?" vs. English "What is a stack?"), not a repeated identical query. Phase 5H's report characterized this as "the identical query... called twice in one process, materially different candidate sets" — **that characterization was incorrect**, and is corrected here. The true, mundane explanation is ordinary cross-language retrieval-quality variance (a real, already-documented phenomenon from Phase 5E/5H) between two different-language phrasings of a conceptually similar question — not a same-input-different-output bug.

---

## 17. Evidence For/Against Each Possible Cause

Per the task's Section 8 list — every item's evidence status, from this phase's testing:

| Possible cause | Evidence found |
|---|---|
| Nondeterministic embedding inference | **Against** — 100% identical hashes across all repeats |
| Lazy model loading | Not implicated — models load once per process, before any repeats; no mid-run reload observed |
| Multiprocessing/threading | **Against** for the specific concurrency this pipeline uses (a 2-worker pool running the two legs in parallel within one query) — results were stable across repeats despite this concurrency being exercised identically each time |
| Floating-point/tie behavior | **Against** — no tied-score instability observed; RRF's explicit tie-break-by-id design was directly confirmed effective |
| Qdrant equal-score ordering | **Against** — no evidence found |
| BM25 index rebuilding | **Against** — stable within a build; cross-build stability (different process, fresh rebuild) was not separately isolated this phase but is a natural next check (Section 18) |
| Python set/dict iteration | **Against** — no evidence of iteration-order effects at any stage |
| Unstable sorting | **Against** — all sort keys use deterministic explicit tie-breaks (confirmed by code read) |
| Duplicate chunks | **Investigated, not confirmed as a live issue**: initial confusion between Qdrant point ID and payload chunk_id (Section 3) briefly looked like it might indicate duplication, but was fully explained as the intentional ID-mapping architecture, not duplicate content. A true duplicate-text scan across all 542 canonical points found **zero exact-duplicate chunk texts**. |
| Duplicate documents | **Against** for canonical (3 distinct documents, no duplication found) |
| Mutable metadata | Not directly tested; no evidence of it this phase |
| Generation-authority database lookups | **Against** for the tested queries — 0 drops, identical every run |
| Workspace filtering | **Against** — consistent scoping observed every run |
| Document filtering | Not exercised (all tests used `document_ids=None`) |
| RRF tie handling | **Against** — confirmed deterministic by design and by evidence |
| Reranker accidentally being invoked | **Confirmed NOT invoked** — `reranker=None` throughout, never attached to any test instance this phase |
| Random seeds | Not applicable — no stochastic sampling exists anywhere in the traced retrieval path |
| Model temperature/randomness | Not applicable to retrieval (this is an LLM-generation-only concept); retrieval itself has no such parameter |
| Concurrent requests | **Not tested this phase** — all 90 runs were sequential, single-request-at-a-time. Genuine concurrent-request interference (e.g., shared mutable state across simultaneous FastAPI requests) was NOT ruled out and remains a real, untested gap. |
| Collection changes during testing | **Ruled out** — canonical/validation point counts verified unchanged before and after |

---

## 18. Security Implications

**None discovered this phase.** No security-relevant defect was found in the retrieval determinism investigation — the "vulnerability" implicitly suspected (unpredictable/exploitable retrieval behavior) was not found to exist. This is a negative-but-informative result: it does not weaken or change any of Phase 5F/5G's confirmed prompt-injection findings, which are generation-stage, not retrieval-stage, issues.

---

## 19. Recommended Phase 5I-B Direction

Given retrieval is confirmed deterministic, **Phase 5I-B should not investigate determinism further** (per this phase's own closing evidence) and should instead:

1. **Use the new `phase5i_a_current_corpus_ground_truth_candidate.json`** to compute genuine, trustworthy Recall@k/MRR/threshold-tradeoff numbers against the canonical corpus (the work Phase 5H's blocker prevented) — now unblocked.
2. **Investigate the 3 documented misses** (Section 5) specifically — `ci_os_process_definition__q_english`'s miss is unexplained and worth a quick, targeted look; the Hindi-vs-Hinglish and Hindi-vs-English pairs' contrasting hit/miss results are a genuine, small, ready-made dataset for studying the cross-language retrieval gap directly, without needing new corpus data.
3. **Test concurrent-request interference** (Section 17's one remaining untested item) as a quick, cheap addition before fully closing the determinism question — this phase's 90 runs were all sequential; genuine concurrency was never exercised.
4. **Correct Phase 5H's own report** to reflect this phase's finding — flagged here rather than silently left inconsistent across the engagement's report history.

---

## 20. Explicit Statement of What Was NOT Changed

No change was made to: the retrieval algorithm, RRF, BM25, the embedding model, score thresholds, `top_k` defaults, reranker configuration (remained disabled throughout, never attached to any test instance), Team4A, Team4C, LLM prompt construction, or LLM generation behavior. The only new artifacts created are this report, its JSON counterpart, and `team4b/data/phase5i_a_current_corpus_ground_truth_candidate.json` — all outside the application's runtime code path. No existing test was modified or weakened; the known pre-existing `TestRelevantChunkIdsExistInCanonicalCorpus` failure was left exactly as-is and not "fixed." No commit, no push, no PR.

---

## Data Safety Confirmation

`educopilot_chunks`: 542 → 542, confirmed unchanged. `educopilot_chunks_product_validation`: 4938 → 4938, confirmed unchanged. Team4B full test suite: 1302 passed / 3 skipped / 1 known pre-existing failure — identical to every prior phase's baseline, zero regression.
