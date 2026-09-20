# Phase 5A — Controlled Cross-Script Query Retrieval Evaluation

**Date:** 2026-09-17
**Branch:** `phase5-cross-script-retrieval` (started from checkpoint `m6-phase4e-f1` / commit `6f8a933`)
**Type:** Evaluation only. No production code path was enabled, no canonical data was modified.

## 1. Executive Summary

**Decision: NO-GO** (for the specific mechanism evaluated).

Deterministic Latin→Devanagari transliteration, combined with a generic
multi-query retrieval wrapper, was evaluated against the full approved
75-entry ground truth on the real, restored canonical `educopilot_chunks`
collection (1650 points). It reproduces the same failure pattern Phase
4D found with the multilingual embedding candidate: a real improvement
in deep candidate-pool recall (Recall@100: 0.620 → 0.693) that **does
not translate into improved real, delivered retrieval** (Recall@10:
0.487 → 0.473; production hit-rate @10/threshold=0.3: 0.507 → 0.493 —
both essentially flat-to-slightly-worse). It costs ~83% additional
retrieval latency and introduces at least one measured, root-caused
regression (a Hindi-language query with an embedded Latin acronym had
its correct answer pushed out of the top-100 pool entirely). All Phase
4E/F1 safety invariants are preserved. Genuine translation (as opposed
to transliteration) remains untested — no offline translation
capability exists in this environment and none was downloaded, per this
phase's own constraints — so this verdict is scoped to the mechanism
actually evaluated, not to query-side transformation in general.

## 2. Problem Statement

Phase 4D established that English/Hinglish queries frequently fail to
retrieve Hindi-script source content in the real hybrid BM25+RRF
pipeline, even when a multilingual embedding model shows better
isolated semantic recall — because BM25 and RRF fusion can prevent a
better semantic candidate from ever surfacing in the final result.
Phase 5A investigates the next generalized candidate: transforming the
**query**, not the embedding model.

## 3. Phase 4D Evidence Being Addressed

From `team4b/data/phase4d_cross_lingual_embedding_evaluation.json`/
`_review.md`: the multilingual candidate embedding model improved
isolated semantic candidate recall for English/Hinglish→Hindi queries,
but this improvement "largely disappeared" once BM25 and RRF fusion
were applied in the real hybrid pipeline, and reranking could not
recover documents that never entered the candidate pool. Phase 4D's own
conclusion: do not migrate to the multilingual embedding model based on
that evidence alone.

## 4. Existing Baseline Architecture

Unmodified `HybridRetriever` (`app/services/hybrid_retriever.py`):
semantic (all-MiniLM-L6-v2) + BM25 legs run in parallel in hybrid mode,
combined via Reciprocal Rank Fusion, normalized, thresholded, optionally
reranked (disabled in production and in this evaluation). No line of
this file was changed for Phase 5A.

## 5. Candidate Architecture

Two new, unwired modules:
- `app/services/query_transform.py` — `generate_query_variants(query)`
  always returns the original query, plus a deterministic
  Latin→Devanagari transliteration variant when it differs from the
  original.
- `app/services/multi_query_retrieval.py` — `MultiQueryRetriever` wraps
  an existing `HybridRetriever` by composition. For each variant, it
  calls the retriever's own, unmodified `retrieve()` independently
  (its own candidate pool, its own RRF fusion), tags every result with
  which variant(s) produced it, deduplicates by chunk_id keeping the
  best (max) relevance_score, and truncates to the requested `top_k`.

Neither module is imported by `app/api/dependencies.py` or
`app/services/rag_service.py` — verified by a source-inspection test
(`TestProductionSafety::test_multi_query_retriever_is_not_imported_by_production_wiring`).

## 6. Why the Candidate Is Generalized

The transliteration tables encode Devanagari phonetics (consonants,
vowels, matras) — properties of the script, not of any subject,
workspace, or document. `MultiQueryRetriever` operates on arbitrary
query strings, workspace_ids, and retrieval parameters with no keyword
list, no subject name, and no per-language branch anywhere in either
new file — verified by a structural test scanning the source for
subject-specific vocabulary. The multi-query *architecture* itself
(independent pools → provenance → candidate-preserving merge) is
transformation-agnostic: a different transformation for a different
language pair could be substituted without changing `MultiQueryRetriever`
at all.

## 7. Local Environment / Model Availability

Inspected before choosing a mechanism (see prior turn's investigation):
`pip list` in the team4b environment contains no translation or
transliteration library; the local HuggingFace cache contains only the
two embedding models and two cross-encoder rerankers already used in
Phases 4A/4B/4D (no MarianMT/NLLB/argos-translate/indic-nlp model).
DNS to huggingface.co resolved (so the environment is not fully
offline), but downloading a new translation model for this evaluation
was deliberately avoided — an unnecessary, unjustified infrastructure
addition for a single evaluation phase, per this phase's own
instructions. A deterministic, rule-based transliteration requires no
model and is fully reproducible offline; genuine translation was
therefore **not evaluated** (see Limitations, §19).

## 8. Exact Experimental Methodology

Script: `team4b/scripts/phase5a_cross_script_retrieval_evaluation.py`.
For each of the 75 approved ground-truth entries, both approaches were
run against the same live canonical collection, using the real
production `Embedder` (all-MiniLM-L6-v2) and a freshly-refreshed BM25
corpus scrolled read-only from `educopilot_chunks` (1650 chunks). A
documented, evaluation-only `PermissiveGenerationAuthorityClient` was
used for the retrieval-quality comparison itself (matching the
established Phase 4B/4C/4D rationale: several approved entries'
document_ids have no Mongo record in this dev environment, which would
confound a retrieval-mechanism comparison specifically) — generation-
authority **enforcement** is separately and exhaustively verified by
unit tests using a real fail-closed fake (§17). Two retrieval
configurations were measured per approach:
- **Pool**: `top_k=100, score_threshold=0.0` — an unfiltered candidate
  pool, for Recall@k/MRR.
- **Production**: `top_k=10, score_threshold=0.3` (the real
  `Settings.default_score_threshold`) — exactly what a live request
  receives today.

Reranker disabled throughout (matches production default). No
temporary Qdrant collection was created; `educopilot_chunks` was read
via `VectorStoreManager.search_similar`/`scroll_all_chunks` only.

## 9. Dataset

`team4b/data/phase2_ground_truth_approved.json`, all 75 entries, used
unmodified. Distribution (query_language → source_language): english→english
16, hindi→english 16, hinglish→english 16, english→hindi 8, hindi→hindi
8, hinglish→hindi 8, english→mixed 3.

## 10. Metrics

Recall@1/3/5/10/100 and MRR (pool config); hit-rate at production
top_k=10/threshold=0.3 ("final retrieval recall"); per-language-pair and
per-query-type breakdowns; hit/miss transition counts; rank-change
analysis; latency per stage.

## 11. Results — Overall

| Metric | Baseline | Candidate | Δ |
|---|---|---|---|
| Recall@1 | 0.2467 | 0.2467 | 0.0000 |
| Recall@3 | 0.3867 | 0.3733 | −0.0134 |
| Recall@5 | 0.4467 | 0.4333 | −0.0134 |
| Recall@10 | 0.4867 | 0.4733 | −0.0134 |
| Recall@100 | 0.6200 | 0.6933 | **+0.0733** |
| MRR | 0.3465 | 0.3443 | −0.0022 |
| Production hit-rate (top_k=10, threshold=0.3) | 0.5067 (38/75) | 0.4933 (37/75) | −0.0134 (−1 query) |

Recall@100 improved; every shallower cut (Recall@1/3/5/10) and the
production-threshold hit-rate were flat or slightly worse.

## 12. Language-Pair Results

| Pair (n) | Baseline R@10 / R@100 / prod-hit | Candidate R@10 / R@100 / prod-hit |
|---|---|---|
| english→english (16) | 0.938 / 1.000 / 0.938 | 0.938 / 1.000 / 0.938 |
| english→hindi (8) | 0.000 / 0.000 / 0.000 | 0.000 / **0.312** / 0.000 |
| english→mixed (3) | 0.333 / 0.500 / 0.667 | 0.333 / 0.667 / 0.667 |
| hindi→english (16) | 0.312 / 0.312 / 0.312 | 0.250 / 0.312 / 0.250 |
| hindi→hindi (8) | 0.312 / **1.000** / 0.375 | 0.312 / **0.875** / 0.375 |
| hinglish→english (16) | 0.812 / 1.000 / 0.812 | 0.812 / 1.000 / 0.812 |
| hinglish→hindi (8) | 0.000 / 0.000 / 0.000 | 0.000 / **0.438** / 0.000 |

**English→Hindi** and **Hinglish→Hindi**: candidate Recall@100 rose
from 0.000 to 0.312 and 0.438 respectively — a real, verified signal
(confirmed by direct BM25-score inspection on one english→hindi query:
raw scores were NOT degenerately tied, ranging 0.0–4.76 across 1400
workspace candidates; the transliterated variant achieved a genuine,
if weak, partial lexical/semantic match at BM25 rank 261 of 1400,
contributing via RRF). **This never once reached Recall@10 or the
production threshold for either pair** — the signal exists only deep in
the pool, never in what a user would actually receive.

**Hindi→Hindi**: Recall@10/production unchanged exactly; Recall@100
*regressed* (1.000 → 0.875) — see §16 for the root cause.

**English→English**: zero regression at any cut — candidate is
byte-for-byte identical to baseline here at Recall@10/production.

**Hindi→English / Hinglish→English**: hindi→english shows a small
Recall@10/production decline (0.312 → 0.250, i.e. one query, the same
one analyzed in §16); hinglish→english is unchanged.

## 13. Query-Type Results

Full breakdown is in
`team4b/data/phase5a_cross_script_retrieval_evaluation_report.json`'s
`by_query_type` key (all query types present in the 75-entry set, with
baseline/candidate pool recall for each). No query type shows a pattern
materially different from the overall result: pool Recall@100 flat-or-up,
shallower cuts flat-or-down.

## 14. Latency

| Stage | Mean seconds |
|---|---|
| Variant generation (transliteration itself) | 0.00016 (negligible) |
| Baseline, production shape (top_k=10, threshold=0.3) | 0.1364 |
| Candidate, production shape (top_k=10, threshold=0.3) | 0.2503 |
| **Candidate / baseline overhead (production shape)** | **1.83×** |

61 of 75 queries (81%) generated a second (transliterated) variant —
the mechanism fires for nearly every query, not selectively, because no
language-detection gate was added (doing so would have reintroduced the
kind of heuristic this phase's generalization requirement discourages).
The pool-config timing in the raw JSON shows candidate appearing
*faster* than baseline (0.252s vs 0.483s) — this is a measurement-order
artifact (baseline is always the first, coldest call for each query;
by the time candidate runs, connections/caches are warm), not a real
speedup: `MultiQueryRetriever` calls `retrieve()` sequentially per
variant and can only add work. The production-shape numbers, measured
identically for both, are the honest read: **~83% additional latency**
for a mechanism that did not improve production-facing recall.

## 15. Hit/Miss Analysis

| Transition (at production top_k=10) | Count |
|---|---|
| unchanged_hit | 37 |
| unchanged_miss | 37 |
| hit_to_miss_regression | 1 |
| miss_to_hit_improvement | **0** |

Zero queries were newly rescued into the top-10 by the candidate
mechanism; exactly one previously-correct query regressed.

## 16. Regression Analysis

**The one production-level regression:** `c_sql_query_evaluation_steps__q_hindi`
(hindi→english). Baseline pool rank 6 → candidate pool rank 12 (still a
pool hit, but now outside the production top_k=10). Root cause: adding
a second query variant increases competition for the merged top-k
slots — even with independent per-variant pools and a candidate-
preserving, max-score merge, the union of two variants' results can
still push a correct-but-modest-ranking hit further down once truncated
to the requested `top_k`. This is a structural property of any
multi-query fusion, not a bug in the merge logic itself.

**The one pool-level (Recall@100) regression:** `c_fcfs_disk_scheduling__q_hindi`
(hindi→hindi). Baseline pool rank 86 (a marginal hit, barely inside the
100-slot pool) → candidate: **dropped out of the pool entirely**. This
query's `query_language` is "hindi" (expected to be pure Devanagari),
yet it generated a second variant — meaning the query text contains an
embedded Latin-script acronym (e.g. "FCFS") inside an otherwise
Devanagari sentence. The transliteration mechanism does not distinguish
"a token that should be phonetically transliterated" from "a
genuine English/acronym token embedded in otherwise-Hindi text," so it
transliterates indiscriminately; the resulting spurious variant
introduced enough new competing candidates to push an already-marginal
hit out of the pool. Notably, a *different* hindi→hindi query in the
same run, `c_sjf_not_implementable__q_hindi`, improved dramatically
(rank 60 → 12) via the identical mechanism (an embedded "SJF" acronym) —
the same root cause produces both a real improvement and a real
regression depending on the specific corpus content, which is itself
evidence the mechanism's effect is closer to noise than to a reliable,
predictable signal.

## 17. Safety Verification

29 focused tests (`tests/test_phase5a_cross_script_retrieval_evaluation.py`),
all passing, directly prove: workspace isolation across all variants;
document-id filtering across all variants; collection (source-type)
filtering across all variants; generation-authority enforcement
(fail-closed, using a real fail-closed fake, not the permissive
evaluation-only one) across all variants; the `document_ids == []`
short-circuit returns `[]` before any variant is even generated
(verified with a variant generator that raises if ever called);
citation integrity (`to_source_attribution` reads real metadata
unaffected by the added provenance field); no subject-specific
vocabulary in either new module; no production-wiring import. Session
safety is preserved structurally and trivially: neither new module
touches `ConversationManager`, session_id, or any RAGService code path
at all — `MultiQueryRetriever` operates purely at the retrieval layer.

## 18. Production-Safety Verification

- Canonical collection `educopilot_chunks` point count: **1650 before,
  1650 after** this evaluation (verified by direct, read-only Qdrant
  query both times).
- Phase 2 evaluation collections (`phase2_eval_all_minilm_l6_v2_20260917T113049`,
  `phase2_eval_paraphrase_multilingual_minilm_l12_v2_20260917T113049`)
  confirmed still present at 1650 points each.
- `Settings.embedding_model_name` = `all-MiniLM-L6-v2` (unchanged).
- `Settings.reranker_enabled` = `False` (unchanged); reranker was not
  used anywhere in this evaluation.
- No document was ingested, re-ingested, or modified.
- `app/api/dependencies.py` and `app/services/rag_service.py` are
  byte-for-byte unmodified (only two new, unwired service files were
  added).
- Full Team4B suite: **1303 passed, 3 skipped (pre-existing,
  unrelated), 0 failed** — no regressions.

## 19. Limitations

1. **Genuine translation was not evaluated.** No offline translation
   model/library exists in this environment; downloading one was
   deliberately avoided per this phase's scope constraints. This
   verdict applies to the transliteration mechanism actually tested,
   not to query-side transformation as a concept — a translation-based
   approach remains a genuinely open, untested question.
2. The transliteration scheme is a practical, common-romanization
   heuristic (documented in `query_transform.py`), not a linguistically
   complete Sanskrit-grade (IAST/ITRANS) standard; casual Hinglish's
   inherent short/long-vowel ambiguity (e.g. "kya" vs. "kyaa") is not
   resolved.
3. A pre-existing, out-of-scope-for-this-phase quirk was identified
   (not this phase's bug and not fixed here): `HybridRetriever`'s BM25
   score normalization treats an all-tied-at-zero raw score (nothing
   lexically matched at all) as "everyone is maximally relevant."
   Direct diagnostic inspection of the actual english→hindi query
   analyzed in §12 confirmed this quirk did NOT fire for that query
   (scores were genuinely non-degenerate), but it was not exhaustively
   checked across all 75×2 variant calls, so it cannot be fully ruled
   out as a minor contributor elsewhere in the dataset.
4. n=8 for each Hindi-source language pair is a small sample; the
   language-pair-level percentages (e.g. "0.312") represent 2–3 queries
   out of 8 and should be read as directional, not statistically
   precise.
5. Latency was measured single-threaded, sequentially, on CPU, matching
   production's own no-GPU-assumption — but not measured under
   concurrent multi-request load.

## 20. Decision

**NO-GO** for production adoption of this mechanism (deterministic
Latin→Devanagari transliteration + generic multi-query retrieval), based
on directly measured evidence:
- It does not improve Recall@10 or production-threshold hit-rate for
  any language pair, including the two pairs it targets (english→hindi,
  hinglish→hindi) — both stayed at exactly 0.000 in production-shaped
  retrieval, unchanged from baseline.
- It costs ~83% additional retrieval latency.
- It introduces at least one measured, root-caused regression, and the
  same root cause (indiscriminate transliteration of embedded Latin
  acronyms) produces both a large improvement and a real regression
  elsewhere in the same language pair — closer to noise than to a
  dependable signal.
- All safety invariants are preserved, but safety alone does not
  justify shipping a change with a real latency cost and no real
  retrieval benefit.

This is not an INCONCLUSIVE result: the evidence directly and clearly
answers the acceptance-criteria questions (§21 of the task) in the
negative for the mechanism tested. It does not, however, rule out a
genuine translation-based approach, which remains untested.

### Acceptance criteria — answered from measured evidence

| # | Question | Answer |
|---|---|---|
| A | Materially improves real retrieval? | **No** — Recall@10/production flat-to-worse overall. |
| B | Improves English→Hindi in the real architecture? | **No** at Recall@10/production (0.000 → 0.000); a real but sub-threshold Recall@100 signal exists (0.000 → 0.312). |
| C | Improves Hinglish→Hindi? | **No** at Recall@10/production (0.000 → 0.000); Recall@100 rose 0.000 → 0.438. |
| D | Preserves Hindi→Hindi? | Preserved exactly at Recall@10/production; **not** preserved at Recall@100 (1.000 → 0.875, one root-caused regression). |
| E | Avoids unacceptable English→English regression? | **Yes** — zero regression at any cut. |
| F | Improves final Recall@10, not merely Recall@100? | **No.** Recall@100 rose (+0.073); Recall@10 fell (−0.013). |
| G | Latency cost? | **~1.83×** (83% additional) on the production-shaped call; transformation itself is negligible (<1ms). |
| H | Preserves Phase 4E/F1 safety guarantees? | **Yes** — verified by 29 passing tests plus structural/source-inspection checks. |
| I | Generalized enough for arbitrary subjects/workspaces? | The multi-query **architecture** yes (subject/workspace-agnostic by construction); the specific transliteration **transformation** is inherently script-pair-specific by its own linguistic nature, as any concrete transformation choice would be. |
| J | Proceed to production implementation? | **No**, for this mechanism, based on the above. |

## 21. Recommended Next Phase

Do not enable this mechanism in production. If cross-script query
transformation is still worth pursuing, the evidence here suggests two
directions, neither started in this phase:
1. Evaluate genuine translation (not transliteration) once an offline
   translation capability can be justified and provisioned deliberately
   (not as an incidental download inside an evaluation script) — this
   phase could not test the one mechanism that actually changes query
   *meaning* rather than *script*.
2. If transliteration is revisited, it needs a way to avoid
   transliterating embedded Latin acronyms/loanwords inside otherwise-
   Devanagari text (§16), since that specific failure mode produced
   both this phase's only real improvement and its only real
   regression from the identical root cause.

No other next phase is proposed. Phase 5B is explicitly not started.
