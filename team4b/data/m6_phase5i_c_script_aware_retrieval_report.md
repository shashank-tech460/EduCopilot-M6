# M6 Phase 5I-C — Generalized Script-Aware BM25 + Cross-Language Retrieval Experiment

**Status:** OFFLINE FORENSIC EXPERIMENT COMPLETE. No production code changed.
**Branch:** `phase5-cross-script-retrieval` | **Baseline commit:** `6f8a933`

## 1. Executive Summary

This phase investigated whether a generic, algorithmic, script-aware lexical
normalization strategy could improve BM25 cross-script retrieval (Latin-script
query ↔ Devanagari-script source) without damaging the generalized system.

**Mechanism tested:** for every Devanagari token, deterministically
transliterate it to the Harvard-Kyoto (HK) Latin romanization scheme via the
established `indic_transliteration` library, and append the lowercased result
as an **additional** token alongside the original — a strict additive superset
of today's tokenization, containing zero per-term dictionaries, zero subject
lists, zero hardcoded mappings.

**Result: CATEGORY C — NO SAFE IMPROVEMENT FOUND.** At the production-relevant
level (hybrid search, top_k≤10 — what the system actually serves), aggregate
Recall@k/MRR are **exactly identical** between current production and the
script-aware variant. The mechanism does not help. Worse, on several
finer-grained axes it is measurably negative: BM25-only aggregate recall and
MRR both **decreased**, the specific target miss (`ci_os_race_condition__q_hinglish`)
got a **worse** RRF rank inside the real hybrid pipeline (14 → 39) despite
looking improved in isolated BM25-only view, BM25-leg latency increased
**~4.9x**, hybrid latency increased **~3.8x**, and one out-of-scope query
picked up 8 new spurious candidate matches due to common Hindi function-word
transliteration collisions. This is the same trap Phase 5I-B's master prompt
warned against for the embedding experiment — an isolated-leg improvement
that does not survive (and here, actively degrades within) the real
RRF-fused pipeline — now independently reproduced for a completely different
mechanism. Production is unchanged.

## 2. Baseline Configuration

- Repository: `D:\Major_Project\project\EduCopilot-M6-Local\EduCopilot-M6-Local`
- Branch: `phase5-cross-script-retrieval`, commit `6f8a933` (unchanged throughout)
- Qdrant: canonical `educopilot_chunks` = 542 points, validation
  `educopilot_chunks_product_validation` = 4938 points (verified unchanged
  before and after all experiments)
- Production hybrid config (unchanged): `top_k=5`, `score_threshold=0.3`,
  `search_mode=hybrid`, `rrf_k=60`, `hybrid_candidate_pool_size=100`,
  `reranker=disabled`, `embedding_model=all-MiniLM-L6-v2`
- Production Phase 5I-B baseline hybrid metrics: R@1=0.474, R@3=0.789,
  R@5=0.842, R@10=0.895, MRR=0.618

## 3. Evaluation Dataset

21 total entries, real, unmodified retrieval, real Qdrant collections:

- `phase5i_a_current_corpus_ground_truth_candidate.json` — 19 entries,
  canonical collection (`educopilot_chunks`), CANDIDATE status (not
  human-approved), covering OS and DBMS subjects.
- `phase5i_b_generalization_supplement_candidate.json` — 2 entries,
  validation collection (`educopilot_chunks_product_validation`), Data
  Structures and Computer Networks subjects.

No new ground-truth entries were fabricated this phase; the corpus
limitation (see Section 4) made adding further clean cross-script examples
infeasible within this phase's scope.

## 4. Dataset Limitations

- Only **1 Hinglish→Hindi** entry and **1 English→Hindi** entry exist in the
  entire 21-entry set — every conclusion about those two specific directions
  is `INSUFFICIENT SAMPLE SIZE` (n=1) and must not be generalized.
- Both cross-script "difficult" entries happen to be the same 2 of the 3
  Phase 5I-B misses (`ci_os_race_condition__q_hinglish`,
  `ci_os_virtual_memory__q_english_over_hindi_source`) — the dataset gives
  no INDEPENDENT confirmation of the mechanism's cross-script behavior
  beyond these 2 already-known cases.
- Attempting to add more Hindi cross-script examples from other subjects
  (Mathematics, Machine Learning workspaces in the validation collection)
  was already ruled out in Phase 5I-B: most sampled Hindi content there was
  garbled at the source, not a genuine evaluation opportunity.
- The 19-entry canonical set remains CANDIDATE, not human-validated.

## 5. Current BM25 Behavior (traced from source, not assumed)

`app/services/bm25_index.py`: `BM25Index.search()` builds a **fresh,
temporary, per-workspace `BM25Okapi`** instance on every call (no
incremental index, no cross-query caching) from documents filtered by
`workspace_id` (mandatory) + `document_ids`/`collection_filter` (optional),
computed *before* any BM25 scoring — so IDF statistics are always
workspace-local, never contaminated by other workspaces. The tokenizer is
**injectable** via `BM25Index(tokenizer=...)`, explicitly documented for
exactly this kind of substitution. The default tokenizer
(`_TOKEN_PATTERN = r"[A-Za-z0-9]+" r"|[ऀ-ॣ०-९ॲ-ॿ]+"`) already splits ASCII
alnum runs and Devanagari runs as **separate, non-overlapping token
alternatives** — Hindi text tokenizes correctly today, but a Devanagari
token and a Latin token can never lexically match each other, by
construction, regardless of meaning.

`app/services/hybrid_retriever.py`: `_retrieve_hybrid()` runs the semantic
and BM25 legs concurrently, applies fail-closed generation-authority
filtering to both legs' candidates *before* fusion, then calls the real
`reciprocal_rank_fusion(bm25_ranked, vector_candidates, k=rrf_k)` — a
pure `1/(k+rank)` sum keyed by each list's own internal order, then
normalizes by the theoretical max RRF score and thresholds. Critically,
`_retrieve_hybrid()` passes BM25 `top_k=None` (the *entire* workspace-scoped
ranked list, unbounded) into RRF — unlike `_retrieve_keyword_only()`, which
re-sorts and tie-breaks by `chunk_id` before truncating to `top_k`. This
means the "BM25 rank" quoted in this phase's Section 9/11 two different
ways (`keyword`-mode result vs. raw `bm25_ranked` list position as fed to
RRF) reflects **two different tie-break orders for the same tied scores** —
documented explicitly to avoid the reader conflating them.

## 6. Script-Aware Algorithm Investigated

**Library selected:** `indic_transliteration` (PyPI, network-installed this
phase for the offline experiment only — not added to `requirements.txt`, not
installed into any running service). Chosen over building a custom mapping
because it is an established, deterministic, rule-based Sanskrit/Hindi
transliteration engine used across many CLIR/NLP projects — not a
term-specific dictionary. `unidecode`, `aksharamukha`, and
`indic-transliteration` were all confirmed reachable via `pip index
versions`; `indic_transliteration`'s `sanscript` module was selected as the
most directly fit-for-purpose (character/script-level rules, not a general
Unicode-decomposition heuristic like `unidecode`, which would mangle
Devanagari far more crudely).

**Algorithm** (`phase5ic_script_aware_tokenizer.py`, offline-only, never
imported by any application module):

1. Tokenize exactly as `default_tokenizer` does today (same
   `_TOKEN_PATTERN`).
2. For every Devanagari token, deterministically transliterate it to the
   Harvard-Kyoto (HK) Latin scheme via `sanscript.transliterate(tok,
   DEVANAGARI, HK)`, lowercase it, and **append it as an extra token**.
3. Latin/ASCII tokens are kept as-is — no reverse (Latin→Devanagari)
   transliteration is attempted, since informal Hinglish spelling has no
   single deterministic target spelling (a genuine, disclosed asymmetry,
   not an oversight).

This is a **strict additive superset**: every existing exact-token match
(English↔English, Hindi↔Hindi) is completely unaffected; only Devanagari
documents gain an additional Latin-script token that a Latin-script query
could now lexically match. Zero subject terms, zero manually maintained
Hindi↔English mappings, zero query-specific or document-specific
special-casing.

**Empirical smoke test** (`रेस कंडीशन क्या होता है` → HK → lowercase):
`resa kaMDIzana kyA hotA hai` → `resa kamdizana kya hota hai`. Function
words `kya`/`hota`/`hai` transliterate to an **exact** match against
casual Hinglish spelling. English loanwords rendered phonetically in
Devanagari (`कंडीशन` → `kamdizana`) do **not** reconstruct their original
English spelling (`condition`) — this asymmetry turns out to be the single
most important finding of this phase (Section 9).

## 7. BM25-Only Comparison (System A vs. System B)

Real, unmodified `BM25Index`, only the injected tokenizer differs.
Permissive pool capture: `threshold=0.0, top_k=100`, all 21 entries.

| System | R@1 | R@3 | R@5 | R@10 | MRR@10 |
|---|---|---|---|---|---|
| A — current (`default_tokenizer`) | 0.4762 | 0.7143 | 0.8095 | **0.9048** | **0.6188** |
| B — script-aware | 0.4286 | 0.7143 | 0.8095 | **0.8571** | **0.5902** |

**BM25-only aggregate recall and MRR are strictly worse for System B** at
k=1, k=10, and MRR at every k. Per-query diff (only 3 of 21 queries changed
rank at all):

| query_id | A (BM25-only) | B (BM25-only) |
|---|---|---|
| `ci_os_process_definition__q_english` | 10 | 12 (worse) |
| `ci_os_race_condition__q_hinglish` | not in top-100 | **49** (found) |
| `sup_ds_bubble_sort__q_english` | 1 | 2 (worse) |

The two English-only queries regressed by 1-2 positions purely from
**collateral corpus-wide IDF/length-normalization shift**: adding
transliterated tokens to Devanagari documents changes BM25's average
document length statistic for the *whole workspace*, which measurably
shifts ranking even for queries with zero Devanagari overlap. This is a
real, generalized side effect of the mechanism, not a bug specific to any
one query.

## 8. Hybrid/RRF Comparison (System D vs. System E) — the decisive test

Both systems run the **real, unmodified** `HybridRetriever._retrieve_hybrid()`
end-to-end (no hand-rolled simulation needed — the tokenizer is a native
injection point) — only the BM25 leg's tokenizer differs.

| System | R@1 | R@3 | R@5 | R@10 | MRR@10 |
|---|---|---|---|---|---|
| D — current production hybrid | 0.5238 | 0.8095 | 0.8571 | 0.9048 | 0.6607 |
| E — script-aware hybrid | 0.5238 | 0.8095 | 0.8571 | 0.9048 | 0.6607 |

**Exactly identical at every k.** This is the central, decisive result:
at the level the product actually serves (`search_mode=hybrid`, top_k≤10),
script-aware BM25 changes **nothing** in aggregate. This is not because
nothing changed underneath — Section 9 shows the target miss's *rank*
moved substantially — but because that movement never crosses a k≤10
threshold in either direction. **System E: SYSTEM C — semantic-only** is
included for reference only (unaffected by BM25 tokenizer): R@1=0.4762,
R@5=0.6667, confirming hybrid still outperforms semantic-only regardless.

## 9. Three-Miss Analysis

| query_id | A (BM25) | B (BM25) | C (semantic) | D (hybrid) | E (hybrid) |
|---|---|---|---|---|---|
| Miss 1: `ci_os_process_definition__q_english` | 10 | 12 | 4 | **8** | **8** (unchanged) |
| Miss 2: `ci_os_race_condition__q_hinglish` | not found | 49 | 48 | **14** | **39 (worse)** |
| Miss 3: `ci_os_virtual_memory__q_english_over_hindi_source` | not found | not found | not found | **not found** | **not found (unresolved either way)** |

**Miss 1** (mild RRF ranking issue, no cross-script component): preserved
identically by System E, as expected — script-aware BM25 does not touch
this query's tokens at all (no Devanagari involved).

**Miss 2** (the mechanism's literal target case) — this is the most
important, and most counter-intuitive, finding of the phase. In isolated
BM25-only view, script-aware tokenization *does* newly find the target
chunk (not-present → rank 49) — this alone would look like a clean win if
evaluated in isolation, **exactly the trap this phase's master prompt
explicitly warned against**. But `_retrieve_hybrid()` feeds BM25's
**unbounded, un-tie-broken** ranked list directly into
`reciprocal_rank_fusion()`. Under System A (current), the target chunk's
raw BM25 score was a **tied zero** shared with hundreds of other
zero-scoring chunks; its position in Python's stable-sort insertion order
happened to land it favorably. Under System B (script-aware), the same
chunk now gets a **genuine, non-zero partial match** (via `kya`/`hota`/`hai`)
— but so do many *other* Devanagari chunks in the same workspace that
happen to contain the same extremely common Hindi function words for
unrelated reasons, and several of them accumulate *more* such matches than
the target. The properly-sorted, genuinely-scored list therefore ranks the
target *behind* those competitors, at position 49 — worse than the lucky
zero-tie position it held before. Fused with the unchanged semantic rank
(48), this produces RRF rank **39, worse than production's rank 14**.
**Both ranks remain misses at every standard k (1/3/5/10)**, so this does
not show up in the aggregate table above — but it is a real, measured
degradation, and the opposite of the intended effect.

**Miss 3** — confirmed unresolved by design, not merely by bad luck.
`वर्चुअल मेमोरी` → HK → `varcuala memori`, neither of which lexically
resembles `virtual memory`. Devanagari phonetic spellings of *English
loanwords* do not reconstruct their original English spelling under any
deterministic script-level transliteration scheme — this is a
fundamentally different failure mode than Miss 2's native-Hindi
function-word case, and no script-aware BM25 mechanism can close it. This
confirms Phase 5I-B's original diagnosis: Miss 3 is a genuine embedding
cross-language weakness, entirely orthogonal to the lexical-matching
mechanism tested here.

## 10. Language Matrix (hybrid, k=5)

| Direction | n | D (current) | E (script-aware) |
|---|---|---|---|
| english→english | 13 | R=0.9231, MRR=0.8269 | R=0.9231, MRR=0.8269 (identical) |
| hinglish→english | 3 | R=1.0, MRR=0.4444 | R=1.0, MRR=0.4444 (identical) |
| hindi→hindi | 3 | R=1.0, MRR=0.5556 | R=1.0, MRR=0.5556 (identical) |
| hinglish→hindi | 1 | R=0.0 | R=0.0 — **INSUFFICIENT SAMPLE SIZE (n=1)** |
| english→hindi | 1 | R=0.0 | R=0.0 — **INSUFFICIENT SAMPLE SIZE (n=1)** |

No direction shows any aggregate change at k=5. The two directions the
mechanism specifically targets are each n=1 and cannot support a general
conclusion in either direction from this dataset alone.

## 11. Generalization Analysis

Tested beyond OS/DBMS using the 2 Phase 5I-B supplement entries (Data
Structures `bubble_sort`, Computer Networks `rpc_stub`, both English→English,
canonical validation collection). `sup_ds_bubble_sort__q_english` showed
the same collateral BM25-only degradation pattern seen in Section 7 (rank
1→2), with zero hybrid-level impact (rank 1→1 unchanged) — directionally
consistent with the OS/DBMS findings: the mechanism is genuinely
subject-agnostic in its *side effects* (small, workspace-wide IDF noise),
not merely in its intended cross-script matching. No subject-term list,
document list, or per-subject configuration exists anywhere in
`script_aware_tokenizer` — the same function ran unmodified against 4
distinct subjects (OS, DBMS, Data Structures, Computer Networks) across 2
Qdrant collections. **Caveat:** genuine cross-script generalization
evidence (i.e., a *second* independent Hinglish→Hindi or English→Hindi
example outside OS) could not be obtained this phase — see Section 4.

## 12. Source-Type Analysis

| source_type | n | D (hybrid, k=5) | E (hybrid, k=5) |
|---|---|---|---|
| pdf | 16 | R=0.9375, MRR=0.7552 | R=0.9375, MRR=0.7552 (identical) |
| youtube | 5 | R=0.6, MRR=0.3333 | R=0.6, MRR=0.3333 (identical) |

Identical across both source types — the mechanism operates purely on
indexed text and contains no source-type-specific logic, confirmed by
code (the tokenizer receives only `text: str`, with no source-type
parameter at all).

## 13. False-Positive Analysis

4 OOS queries tested (unrelated subject, real production workspaces,
`score_threshold=0.0, top_k=10`, keyword-only mode):

| Query (workspace) | A vs. B identical ranking? | New chunk_ids only in B |
|---|---|---|
| Biology/Hindi in OS workspace | No | 1 new |
| Astronomy/English in DBMS workspace | **Yes, identical** | 0 |
| Cooking/Hinglish ("biryani banane ka recipe kya hai") in OS workspace | No | **8 new** |
| History/Hindi in DBMS workspace | **Yes, identical** | 0 |

The astronomy and history OOS queries — which share **no** common function
words with the workspace's content — show **zero** difference between
System A and System B, as expected (nothing to transliterate-match). The
cooking query, which happens to contain the same ubiquitous Hindi function
words (`kya`, `hai`) that appear throughout the OS workspace's Devanagari
content, pulled in 8 additional candidate chunk_ids under System B that
System A never surfaced. **Important nuance, disclosed rather than hidden:**
System A *also* shows unusually flat, tied top-5 scores (all 1.0) for this
same query, because per-query BM25 min-max normalization already assigns
1.0 to every top tied-score chunk regardless of true relevance — this
"stopword tie inflation" is a **pre-existing production characteristic**,
not something System B introduces. What System B *does* add is a
**genuinely wider set** of spuriously-matching candidates, because common
Hindi function words that were previously invisible to a Latin-script BM25
leg become newly matchable. This is a real, generalized false-positive
risk specifically for queries dominated by common Hindi function words
against any Devanagari-containing workspace — not a subject-specific or
query-specific defect, but a structural consequence of making stopword-
level transliteration matches possible at all.

## 14. Workspace/Document Isolation

Tested: the real Miss-2 query (`race condition kya hota hai`) issued against
the **wrong** (DBMS) workspace, and a real DBMS query issued against the
**wrong** (OS) workspace, both in `keyword` and `hybrid` modes, both
systems. **Result: System A and System B returned byte-identical
chunk_id lists in every case** — workspace filtering happens inside
`BM25Index.search()`'s `workspace_id`-scoped document list *before* any
tokenization or scoring occurs, so it is structurally unaffected by which
tokenizer is injected. No cross-workspace leak observed or possible by
construction; this was empirically confirmed, not merely assumed.

## 15. Security Impact

Traced by code: `script_aware_tokenizer` only affects what
`BM25Okapi.get_scores()` sees internally as tokenized term lists. Every
`RetrievalResult` this experiment produced — in both `_retrieve_keyword_only`
and `_retrieve_hybrid` — is built from `source.text` (the original, hydrated
chunk text from `self._chunk_cache`/vector search), never from the
tokenized/transliterated representation. Transliterated text is **never**
returned, displayed, cited, or passed to the LLM as context under any code
path exercised this phase. No new injection surface: retrieved text remains
exactly as untrusted as it is today, and Phase 5F's untrusted-context
delimiter/neutralization defense in `llm_generator.py` (unmodified this
phase, confirmed via `git status`) is entirely unaffected since it operates
downstream of retrieval on the same original chunk text.

## 16. Performance / Latency

Measured on the full canonical corpus (542 chunks) and live retrieval calls:

| Metric | Current | Script-aware | Change |
|---|---|---|---|
| Total corpus tokens (tokenize-only pass) | 110,091 | 136,159 | **+23.7%** |
| Per-document tokenize time | 0.081ms | 0.490ms | **~6.0x slower** |
| Avg BM25-only query latency (live) | 0.0383s | 0.1862s | **~4.9x slower** |
| Avg hybrid query latency (live) | 0.0598s | 0.2282s | **~3.8x slower** |
| Avg semantic-only latency (unaffected, reference) | 1.6559s | — | (embedding model load/inference, unrelated to this experiment) |

The overhead stems directly from `BM25Index.search()`'s existing,
documented, per-query, per-workspace `BM25Okapi` rebuild design: every
query re-tokenizes the *entire* workspace-scoped corpus from scratch, so
the tokenizer's own per-call cost multiplies by however many chunks are in
that workspace, on every single query, indefinitely. This is a genuine,
generalized latency cost with zero accompanying accuracy benefit at the
production-relevant k≤10 level (Section 8).

## 17. Production-Change Decision

**CATEGORY C — NO SAFE IMPROVEMENT FOUND.** None of the Category A
acceptance criteria are met:

1. Improved cross-script retrieval — **NOT satisfied.** Aggregate hybrid
   metrics are identical; the one targeted miss got measurably worse inside
   RRF.
2. No unacceptable English regression — **marginally violated.**
   BM25-only English-only queries lost 1-2 rank positions from collateral
   IDF shift (does not cross a hybrid-level k threshold, but is real).
3. No unacceptable Hindi/Hinglish regression — **violated.** Miss 2's RRF
   rank worsened from 14 to 39.
4. No unacceptable false-positive increase — **marginally violated.** One
   OOS query gained 8 new spurious candidates from common Hindi
   function-word collisions.
5. Workspace/document isolation intact — **satisfied,** verified
   empirically.
6. No subject-specific logic — **satisfied.**
7. No query-specific mappings — **satisfied.**
8. Acceptable latency — **NOT satisfied.** ~3.8-4.9x BM25/hybrid latency
   increase for zero net accuracy benefit.
9. Full hybrid/RRF improvement, not merely BM25-only — **NOT satisfied.**
   The one case that improved in isolated BM25-only view got *worse* after
   real RRF fusion.
10. Test coverage addable — not evaluated (moot given criteria 1/3/8/9 fail).
11. Full Team4B regression clean — not exercised (no code change made; see
    Section 18).

**No production code was modified.** Per the phase's explicit gate ("If
ANY of these are not satisfied: DO NOT modify production"), implementation
was correctly never attempted.

## 18. Exact Files Changed

**Production code: none.** `bm25_index.py`, `hybrid_retriever.py`,
`vector_store.py`, and every other application file are byte-identical to
the start of this phase (verified via `git status`/`git diff`).

**Files created (data/reports only):**
- `team4b/data/m6_phase5i_c_script_aware_retrieval_report.md` (this file)
- `team4b/data/m6_phase5i_c_script_aware_retrieval_report.json`

**Scratchpad-only artifacts (outside the repository, not committed):**
`phase5ic_script_aware_tokenizer.py`, `phase5ic_capture_pools.py`,
`phase5ic_compute_metrics.py`, `phase5ic_falsepos_isolation.py`, and their
JSON/JSONL outputs.

**Dependency note:** `indic-transliteration` was `pip install`ed into the
local Python environment to run this offline experiment. It was **not**
added to `team4b/requirements.txt` and is not imported by any application
module — it exists only in the local environment as a side effect of
running the experiment scripts, exactly as `paraphrase-multilingual-MiniLM-L12-v2`
was in Phase 5I-B.

## 19. Recommended Next Direction

1. **Do not pursue token-level Devanagari→Latin transliteration as a BM25
   augmentation further** without a fundamentally different design — this
   phase's evidence is that it trades a small amount of newly-possible
   genuine matching for (a) collateral corpus-wide noise from added tokens,
   (b) new competition from common-function-word false matches that can
   outrank the genuine target within RRF, and (c) real latency cost, for
   zero net benefit at the k≤10 level that matters.
2. A more targeted mechanism might restrict transliteration-matching to
   **content words only** (e.g., excluding a small, closed, script-agnostic
   set of grammatical function words common to both languages) to prevent
   the exact false-positive/competition mechanism identified in Sections 9
   and 13 — this was NOT tested this phase and would need its own
   forensic evaluation before any production consideration; note this
   itself risks drifting toward exactly the kind of hardcoded/curated list
   this phase's own instructions prohibited, so any such design would need
   very careful scoping (e.g., algorithmically derived stopword lists from
   corpus frequency statistics, not manually authored).
3. Miss 3's root cause (embedding cross-language weakness for English
   loanwords phonetically spelled in Devanagari) is untouched by any BM25-
   side mechanism and remains open; Phase 5I-B already showed the one
   tested embedding alternative doesn't safely fix it either. No new
   candidate approach for Miss 3 was identified this phase.
4. If cross-script retrieval quality remains a priority, the next
   investigation should focus on the ground-truth limitation itself
   (Section 4) — genuinely independent Hinglish→Hindi and English→Hindi
   examples are needed before any mechanism's cross-script behavior can be
   evaluated with statistical confidence beyond n=1.

## 20. Data Safety / Closing Verification

- `educopilot_chunks`: 542 before, 542 after — unchanged.
- `educopilot_chunks_product_validation`: 4938 before, 4938 after — unchanged.
- Team4B test suite: not re-run this phase (no application code changed;
  the historical baseline of 1302 passed / 3 skipped / 1 known
  pre-existing failure remains the last-verified state from Phase 5I-B).
- Git: no commit, no push, no PR. `git status --short` shows only the two
  new report files as untracked, plus the pre-existing carryover
  modifications from earlier phases (`llm_generator.py` et al.), unchanged
  from the start of this phase.
