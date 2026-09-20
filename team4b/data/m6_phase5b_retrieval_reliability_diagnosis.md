# M6 Phase 5B — RAG Retrieval Reliability Investigation

**Date:** 2026-09-21
**Type:** Diagnosis only. No fix implemented. No production/canonical data modified. No service restarted or reconfigured. The 123-question battery was NOT rerun.
**Full machine-readable results:** `team4b/data/m6_phase5b_retrieval_reliability_diagnosis.json`

---

## 1. Executive summary

**The previously-suspected root cause — a mis-tuned relevance `score_threshold` — is definitively rejected.** Direct, reproducible tracing of the real production retrieval code against the live, read-only validation Qdrant collection and MongoDB shows that for all 10 confirmed zero-candidate failures, **retrieval never runs at all.**

The actual root cause is a **pre-retrieval query-transformation defect**: `team4b/app/services/followup_context.py`'s `is_elliptical_query()` classifies a query as "needs prior conversation context" whenever **any** of 8 pronoun/demonstrative words (`it`, `this`, `that`, `them`, `these`, `those`, `its`, `their`) appears **anywhere** in the query text — including grammatically self-contained uses like relative pronouns ("a query **that** finds..."), possessives referring to a noun in the same sentence ("...into **its** component parts"), and object pronouns referring to a same-sentence antecedent ("...deliver **them** to the IP layer"). When this misfires on the first message of a fresh conversation, `RAGService.handle_query()` takes an explicit "missing follow-up context" branch that **skips `HybridRetriever.retrieve()` entirely** and returns a scripted, ungrounded clarifying question — the exact same code path used for casual greetings like "Hi".

This was verified with **100% precision**: all 19 confirmed zero-citation failures across both validation rounds (10 from round 2's clean corpus, 9 from round 1) contain at least one trigger word; **0 of 9 sampled confirmed-passing control queries do.**

A second, independent, previously-unknown defect was also discovered: `HybridRetriever.refresh_bm25_corpus()` is **never called anywhere in the running application** — confirmed by full static search of every route/dependency/startup path, and independently reconfirmed by grepping the unique "BM25 corpus refreshed" log line against both the production and validation Team4B processes' complete log history: **zero occurrences.** The live BM25 index has therefore been permanently empty throughout this entire engagement. "Hybrid" search mode has been running as semantic-only in every real query, and the RRF score-normalization formula — which assumes two contributing ranked lists — has been silently capping every citation's `relevance_score` near 0.5, exactly matching the `0.5 / 0.492 / 0.484 / 0.477 / 0.469` sequence observed in nearly every successful citation across both validation rounds. This is not the cause of the 10 zero-citation failures, but it is a real, systemic gap.

The one explicitly-requested forensic case (B-tree node splitting) is a **third, distinct, genuine ranking failure**: the correct chunk (page 128, confirmed present) IS found by Qdrant's semantic search, at rank 29 of 100, with a normalized score (0.343) that clears the 0.3 threshold — it is excluded only because the system keeps just the top 5.

---

## 2. All 10 failure cases, with exact pipeline stage of failure

| Test | Workspace | Trigger word | Stage of failure | Content confirmed present & would rank top-5 if retrieval ran |
|---|---|---|---|---|
| DS-10 | Data Structures | "its" | Query transformation | Yes (pages 116, 117, 121, 109, 113) |
| CN-06 | Computer Networks | "them" | Query transformation | Yes (pages 139, 201, 206, 144, 203) |
| CN-11 | Computer Networks | "this" | Query transformation | Yes (pages 40, 41, 42, 43, 43) |
| MA-08 | Mathematics | "it" | Query transformation | Yes (pages 1, 2, 5, 14, 7) |
| MA-10 | Mathematics | "that" | Query transformation | Yes (pages 6, 14, 3, 12, 5) |
| DB-01 | DBMS | "its" | Query transformation | Yes (pages 1, 6, 1, 5, 12) |
| DB-02 | DBMS | "it" | Query transformation | Yes (pages 53, 41, 52, 54, 3) |
| DB-08 | DBMS | "that" (relative pronoun) | Query transformation | Yes (pages 56, 59, 60, 58, 42) |
| OS-01 | Operating Systems | "it" | Query transformation | No — this workspace's candidates are weak regardless (see §9) |
| OS-04 | Operating Systems | "this" | Query transformation | No — same caveat, plus this is a meta-question about the workspace itself |

Every one of these — and every one of round 1's 9 equivalent failures — matches exactly one mechanism. No other stage of the pipeline needed to be invoked to explain any of them.

---

## 3. Evidence for the diagnosis

### 3.1 The code path, read directly

`app/services/rag_service.py`, `RAGService.handle_query()`:

```python
retrieval_query = query
if is_elliptical_query(query):
    previous_user_turn = _most_recent_user_turn(history)
    if previous_user_turn is None:
        # No usable prior context to enrich with -- ... zero retrieval,
        # zero citations, a clarification reply via the SAME
        # ungrounded-generation mechanism the casual gate already uses
        answer = self._llm_generator.generate_conversational(query, conversation_history=history)
        ...
        return RAGServiceResult(answer=answer, ..., retrieval_results=[], ...)
    retrieval_query = build_enriched_retrieval_query(query, previous_user_turn)

retrieval_results = self._retriever.retrieve(retrieval_query, ...)   # <-- never reached for the 10 failures
```

`app/services/followup_context.py`, `is_elliptical_query()`:

```python
words = normalized.split(" ")
return any(word in _PRONOUN_WORDS for word in words)
# _PRONOUN_WORDS = {"it", "this", "that", "them", "these", "those", "its", "their"}
```

This is a whole-word, anywhere-in-the-sentence match. It has no concept of grammatical role, sentence position, or whether the pronoun's antecedent is inside the very same sentence.

`app/services/llm_generator.py`, the ungrounded fallback's system prompt (`_CASUAL_SYSTEM_INSTRUCTIONS`), explains the exact wording every failure exhibits:

> *"It refers to something from earlier in the conversation ("it", "this", "explain more", etc.) but there is no earlier conversation turn to resolve that reference from. Ask a short, friendly clarifying question about what topic the student means — do not guess a topic."*

The LLM is not malfunctioning — it is correctly following an instruction built on a false premise fed to it by the upstream classifier.

### 3.2 Programmatic verification against every known failure and a control group

The real, unmodified `is_elliptical_query()` was called directly (no mocking, no reimplementation) against all 19 confirmed failures from both rounds and 9 confirmed-passing queries:

```
=== Round-2 confirmed zero-citation failures (10/10 True) ===
DS-10: True | CN-06: True | CN-11: True | MA-08: True | MA-10: True
DB-01: True | DB-02: True | DB-08: True | OS-01: True | OS-04: True

=== Round-1 confirmed zero-citation failures (9/9 True) ===
EN-01: True | EN-05: True | MC-01: True | MC-02: True | MD-02: True
XS-03: True | XS-04: True | NS-01: True | SEC-DOC-01: True

=== Confirmed-passing control queries (0/9 True) ===
DS-01: False | DS-11: False | EN-02: False | EN-03: False | MA-07: False
DB-05: False | CN-13: False | FU-01a: False | DS-14: False
```

**19/19 failures match. 0/9 passing controls match.** The smallest reproducible difference between a passing and failing version of nearly the same question: round 1's passing *"How can trigonometry be used to find the height of a tower like Qutub Minar?"* vs. round 2's failing *"How can trigonometry be used to find the height of the Qutub Minar without measuring **it** directly?"* — the only material difference is the trailing clause that introduces the word "it".

### 3.3 The BM25-never-populated finding, verified two independent ways

1. **Static analysis**: `refresh_bm25_corpus()` is referenced only in comments/docstrings in `app/services/hybrid_retriever.py` and `app/api/dependencies.py`. It is called nowhere in `app/api/main.py` (the actual FastAPI entry point — no startup/lifespan hook exists at all), nowhere in `app/api/routes.py`'s 5 endpoints, and nowhere else in the application. It IS called by `team4b/scripts/phase5a_cross_script_retrieval_evaluation.py` and is exercised by tests — standalone contexts, never the live server.
2. **Live-process confirmation**: `refresh_bm25_corpus()` emits exactly one log line, `"BM25 corpus refreshed"`, on success. Grepping this exact string against `/tmp/team4b_validation.log` and `/tmp/team4b_prod.log` — covering every query issued in both validation rounds across this entire multi-day engagement — returns **zero matches** in either file.

**Consequence, confirmed by direct recomputation of the real `reciprocal_rank_fusion()` and `_max_possible_rrf_score()` functions**: with the BM25 leg always `[]`, a candidate ranked #1 by the vector leg alone gets `raw_rrf = 1/(60+1) = 0.01639`, normalized against a denominator (`_max_possible_rrf_score(k=60, num_lists=2) = 2/61`) that assumes **two** contributing lists → `0.01639 / 0.03279 = 0.5000` exactly. Rank 2 → 0.4919, rank 3 → 0.4841, rank 4 → 0.4766, rank 5 → 0.4692 — **this is precisely the score sequence observed on nearly every successful citation across both validation rounds' 240+ RAG tests.**

---

## 4. B-tree forensic analysis (as explicitly requested)

**Query:** *"What is a B-tree and how does node splitting work during insertion?"* (workspace: Data Structures)

**Content existence proof:** Located independently via direct, read-only PyMuPDF extraction of `Data Structures Full Notes.pdf` (done earlier in this engagement, before this Phase 5B investigation began) and independently re-confirmed present in the exact same chunk via a live, read-only Qdrant scroll of the validation collection:

> chunk_id `a5adc1b7-8bb8-59d2-a4c7-1115daaa1442`, page 128: *"3. Key Order: Keys are stored in sorted order... 4. Node Capacity: A node contains at least ⌈m/2⌉−1 keys and at most m−1 keys... Insertion: insert the key into the appropriate leaf node. If the node overflows (more than m−1 keys), split the node into two and promote the middle key to the parent."*

This is exactly the content the query asks for.

| Stage | Result |
|---|---|
| `is_elliptical_query("What is a B-tree and how does node splitting work during insertion?")` | **False** — this query does NOT trigger the query-transformation bug; retrieval genuinely runs. |
| Semantic leg (Qdrant, live re-embed of the exact query) | Target chunk found at **rank 29 of 100**, raw cosine similarity **0.4612** |
| BM25 leg, actual production | Empty (0 candidates) — see §3.3 |
| RRF fusion, actual production (BM25 always empty) | Target chunk fused rank **29**, raw RRF score 0.01124, **normalized score 0.3427** |
| Relevance threshold (0.3) | **PASSES** (0.3427 ≥ 0.3) |
| Top-5 cutoff (`selection_size = top_k = 5`, no reranker) | **EXCLUDED** — 28 other chunks (pages 119–127, all genuine Binary Search Tree / general tree content from the same PDF) rank higher by pure cosine similarity and fill all 5 slots first |
| Generation-authority check | Passes — document_id resolves correctly in MongoDB, not excluded |
| Reaches the LLM's context | **No** |

**Diagnosis: the correct chunk is never removed by any filter or threshold — it is outranked.** A counterfactual re-run with a diagnostic (temporary, in-memory, never touching production) BM25 index populated from the same content shows the target chunk's counterfactual fused rank would still be outside the top 5 in this specific case too (BM25 alone doesn't fully rescue it either, since "B-tree" and "node splitting" are not rare enough terms in this PDF's own vocabulary to dominate a 129-chunk, heavily tree/BST-themed document) — though BM25 populated does meaningfully reshuffle rankings for several *other* traced queries (see the JSON report's per-case counterfactual tables), so it remains a relevant contributing factor generally, just not sufficient on its own to fix this specific case.

**Classification: SEMANTIC/EMBEDDING CANDIDATE RANKING FAILURE** — distinct from the query-transformation failure affecting the other 10 cases.

---

## 5. Successful-vs-failed comparison

The single smallest reproducible difference separating a passing query from a failing one is the presence of exactly one pronoun-class word, as shown in §3.2. Beyond that binary discriminator:

- **Query length**: no consistent pattern — both short ("DB-02", 11 words) and long ("CN-11", 33 words) queries fail identically once they contain a trigger word.
- **Query language**: all 19 confirmed failures are English (cross-language failures are a separate, already-documented issue, F2, not investigated further here since none of the 10 confirmed-in-scope failures are cross-language).
- **Embedding similarity**: not a discriminator — every failing query's correct-answer chunk, when retrieval is manually re-run, shows a strong, sensible cosine similarity (0.46–0.80) exactly like passing queries.
- **Candidate counts**: identical mechanism (100-candidate pool) for both passing and failing queries — the difference is entirely upstream of this stage.
- **Final context size**: 0 for all 10 failures (retrieval never runs) vs. 5 for passing queries — a direct, mechanical consequence of the query-transformation short-circuit, not evidence of anything about retrieval quality itself.

---

## 6. Root-cause categories (per the task's requested classification)

| Failure | Category |
|---|---|
| DS-10, CN-06, CN-11, MA-08, MA-10, DB-01, DB-02, DB-08, OS-01, OS-04 | **Query transformation failure** |
| DS-11 (B-tree forensic case) | **Semantic/embedding candidate-generation failure (ranking, not absence)** |
| (Systemic, affects every hybrid-mode query, not a specific failure) | **Hybrid/RRF ranking failure** (BM25 leg structurally absent) |

Explicitly ruled out for all 11 cases investigated: query preprocessing beyond the elliptical-query classifier itself, BM25 failure as a standalone cause, Qdrant retrieval failure, document/workspace filtering failure, context assembly failure (in the sense of "found but dropped" — the 10 cases never even attempt to find anything), relevance-threshold failure, and generation-authority failure.

---

## 7. Relevant previous Phase 4 evidence

- **Phase 4A (embedding evaluation)**: not implicated. Every traced case's correct chunk shows a sensible, strong cosine similarity when retrieval actually runs.
- **Phase 4B (reranker evaluation)**: partially relevant. A reranker operates on the post-RRF, post-threshold pool and could plausibly help ranking-position cases like DS-11 within its own pool-size limits (`reranker_candidate_pool_size=40`, wider than the current top-5 but still short of rank 29 in this specific instance) — it would do nothing for the 10 query-transformation failures, which never reach `HybridRetriever.retrieve()` at all.
- **Phase 4C (candidate-recall diagnosis)**: directly corroborating. That historical report's own `part_bcd_stage_by_stage` data records separate timings for `semantic`, `bm25`, and `rrf_00` stages, plus a measured `bm25_refresh_seconds` value — independent, historical proof that whatever script produced that report explicitly called `refresh_bm25_corpus()` itself. Phase 4C's own recall numbers describe a BM25-populated system that production has never actually run.
- **Phase 4D (cross-lingual evaluation)**: not implicated — none of the 10 confirmed failures investigated here are cross-language queries (that remains a separate, already-documented issue).
- **Phase 4E/F1 (workspace/source safety)**: re-confirmed intact. The `collection_filter` threading fix into both the vector and BM25 legs of `_retrieve_hybrid()` was directly re-read in this investigation and matches the fix's own historical description — no regression found.

**This investigation does not recommend an embedding migration.** Nothing found here implicates embedding quality, and the previously-documented multilingual weakness is not implicated in any of the 10 confirmed failures investigated in this phase.

---

## 8. Generalized-RAG implications

Both primary fix directions remain fully subject-independent:

- `is_elliptical_query()` is already domain-agnostic by construction (closed-class English function words only, explicitly never subject vocabulary — confirmed by reading the module's own docstring and code). The defect is a **precision problem** (matching too broadly), not a domain-coupling problem. Any fix narrowing its matching, or changing what happens after a match, requires zero subject-specific code and applies identically to a brand-new workspace/subject.
- Populating `refresh_bm25_corpus()` is a **lifecycle/infrastructure** concern, entirely orthogonal to subject matter — the BM25 tokenizer underneath it is already language-agnostic (confirmed Hindi/Devanagari support in `bm25_index.py`).

One caveat specific to this validation's corpus, not to any code path: OS-01/OS-04's semantic candidates were weak (raw cosine 0.10–0.24) even setting the query-transformation bug aside, because the Operating Systems workspace in this validation contains only two YouTube-transcript videos (one of which was independently found, in the prior validation round, to have genuinely mixed/ML-adjacent content for part of its runtime) and no PDF. This is a property of this specific test workspace's source composition, not a defect in any code path, and implies no OS-specific fix.

---

## 9. Recommended fix options, with risks and acceptance criteria

| Option | Description | Risk | Acceptance criteria |
|---|---|---|---|
| **A** | Narrow `is_elliptical_query()`'s pronoun match (e.g., require sentence-initial position or exclude same-sentence relative/object-pronoun roles) | Any hand-written refinement risks new false negatives/positives; needs a representative test corpus of true-elliptical vs. true-self-contained pronoun-containing questions | All 19 confirmed failures reclassify to `False`; existing `test_followup_context.py` elliptical-positive cases remain `True` |
| **B** | Change the "no previous turn" fallback to attempt plain, unenriched retrieval instead of skipping retrieval entirely (mirrors what `build_enriched_retrieval_query()` already does gracefully in this exact scenario) | Lower risk than A — doesn't touch classifier precision at all; a genuinely-ambiguous single-word query would now retrieve on low signal rather than cleanly asking for clarification | All 19 confirmed failures return grounded, cited answers (8/10 of round 2's cases are independently confirmed retrievable); genuinely ambiguous no-antecedent queries still degrade gracefully, not into fabrication |
| **C** | Combine A and B | Most implementation effort; lowest residual risk | Both A and B's criteria |
| **D** (independent of A/B/C) | Call `refresh_bm25_corpus()` at service startup (and/or after ingestion, and/or on a schedule) | Purely additive; known, already-documented staleness trade-off (BM25 won't see newly-ingested content until next refresh); startup latency scales with corpus size (~1.36s measured historically for 1650 chunks) | The "BM25 corpus refreshed" log line actually appears in production logs; citation `relevance_score` distribution in hybrid mode reflects genuine two-leg fusion (no longer capped near 0.5); DS-11's chunk rank measurably improves in a live re-test |

**Not recommended:** recalibrating `score_threshold` (fixes nothing — see §1); enabling the reranker as a primary fix (too late in the pipeline for the 10 confirmed failures, only partial help for DS-11-style cases); an embedding migration (unsupported by any evidence gathered here); any subject-specific, keyword-specific, or document-specific exception (would violate the generalized-RAG requirement and was not considered).

---

## 10. Final answers to the questions posed

**A. What is definitely broken (confirmed, not suspected):**
1. `is_elliptical_query()` over-broadly matches pronoun words anywhere in a query, regardless of grammatical role — confirmed with 100% precision against 19 failures and 0 false positives on 9 controls.
2. `RAGService`'s missing-context fallback skips retrieval entirely rather than degrading to plain retrieval — confirmed by direct code reading.
3. `refresh_bm25_corpus()` is never called by the live application — confirmed by static analysis of every route/startup path AND by log evidence covering this engagement's entire runtime.

**B. What is only suspected (evidence-based but not fully closed):**
- Whether narrowing the pronoun classifier (Option A) alone, without also changing the fallback behavior (Option B), would fully resolve the OS-01/OS-04 cases — their underlying candidate pool is independently weak, so a query-transformation fix alone may still leave them as honest "insufficient evidence" outcomes rather than good answers (which would be correct, evidence-based behavior, not a new failure).
- Whether BM25 population (Option D) would have rescued DS-11 specifically — the counterfactual trace suggests it alone would not (see §4), though it measurably helps other traced queries' rankings.

**C. Where the correct candidate is being lost:**
- For 10/10 confirmed failures: **before retrieval is ever attempted** (query-transformation stage, `RAGService.handle_query()`'s elliptical-query branch).
- For the B-tree case: **after retrieval, at the top-K selection stage** — the candidate is found, correctly scored, and passes the threshold, but is outranked by 28 topically-adjacent chunks and never makes the final top-5.

**D. What generalized fix should be implemented next:**
Recommend **Option C** (both A and B together) for the query-transformation defect, as the primary Phase 6 implementation target — it resolves all 19 confirmed failures with a subject-independent, domain-agnostic change, and combining both narrows the classifier's error rate while also making any residual misclassification fail gracefully. Recommend **Option D** (BM25 population) as a second, independent, additive fix, since it corrects a genuine, previously-undiscovered architectural gap affecting every hybrid-mode query's ranking quality, not just this investigation's 10 cases.

**E. What tests must pass after that fix:**
1. All 19 confirmed-failing queries from both validation rounds (this report's §2 table plus round 1's equivalent 9) return grounded, cited, correct answers.
2. The existing `test_followup_context.py` and `test_rag_service.py` suites continue to pass unchanged (genuine elliptical follow-ups still correctly enriched with prior-turn context; casual-intent handling untouched).
3. `TestRelevantChunkIdsExistInCanonicalCorpus` remains the only pre-existing, already-explained Team4B failure (not newly caused or newly masked by this fix).
4. A live re-check confirms `refresh_bm25_corpus()`'s log line appears at production startup, and a sample hybrid-mode query's citation scores are no longer capped near 0.5 for a rank-1 result.
5. Canonical collection (`educopilot_chunks`) count remains 542, unchanged, before and after the fix is deployed.
6. A targeted, small-scale re-run of the specific 19 previously-failing queries (not necessarily the full 123-question battery) is sufficient for initial verification; a full battery re-run is recommended only before final release sign-off.

---

## Safety confirmation

- Canonical collection (`educopilot_chunks`): **542**, verified unchanged before and after this investigation.
- Validation collection (`educopilot_chunks_product_validation`): **4938**, verified unchanged — every query in this investigation was a read-only Qdrant search/scroll or a read-only MongoDB lookup, run through a temporary, in-process, diagnostic-only `HybridRetriever`/`BM25Index` instance that never touched the live server's own (separately empty) BM25 index or any shared state.
- No production or validation service was stopped, restarted, or reconfigured.
- No `.env`/`.env.local` file was modified.
- No RAG algorithm, threshold, RRF parameter, embedding, or reranker setting was changed.
- No commit, no push, no rerun of the 123-question battery.

**Report files:**
- `team4b/data/m6_phase5b_retrieval_reliability_diagnosis.json`
- `team4b/data/m6_phase5b_retrieval_reliability_diagnosis.md`
