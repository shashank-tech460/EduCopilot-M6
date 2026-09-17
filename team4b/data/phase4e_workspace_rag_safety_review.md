# Phase 4E — Workspace / RAG Safety Review

Generalized Domain-Agnostic RAG + Workspace Isolation + Retrieval Safety.
This is an ARCHITECTURE + TEST + VALIDATION phase. It proves properties
of the retrieval code, not the quality of the current embedding model or
corpus (that remains the separate, already-completed subject of Phases
4A–4D). Machine-readable companion: `phase4e_workspace_rag_safety_report.json`.

---

## 1. Executive Summary & Final Status

STATUS: **COMPLETE, including the Phase 4E-F1 follow-up fix.** At Phase
4E's original close, all 12 numbered invariants were tested; 11 were
fully proven and 1 (source-type filtering, Invariant 11) was proven for
the semantic leg and semantic-only mode but had a confirmed, documented
gap on the BM25 leg in hybrid mode (PHASE4E-F1). That gap was fixed the
same day in a scoped follow-up task — see the Section 24 addendum — and
Invariant 11 is now fully proven. No production code was changed in
Phase 4E itself; Phase 4E-F1 made exactly two small, targeted production
changes (`bm25_index.py`, `hybrid_retriever.py`) to close the gap. The
canonical Qdrant collection (`educopilot_chunks`) is unchanged at 1650
points before and after both Phase 4E and Phase 4E-F1. 69 Phase 4E tests
plus 14 Phase 4E-F1 tests were added, all passing; the full Team4B suite
(1274 passed, 3 pre-existing skips) shows no regression.

## 2. Scope, Non-Goals, and Explicit Exclusions

In scope: workspace isolation, document filtering, generation-authority
enforcement, source selection, session isolation, multilingual and
domain-generalization *architecture* (not quality), reranker safety, and
citation integrity — proven with a new, reusable, domain-agnostic test
harness.

Explicitly out of scope and not performed: query rewriting/expansion/
decomposition, adaptive top-k or threshold logic, multi-hop retrieval,
production embedding migration, enabling the reranker in production,
citation UI changes, and any Team4A/Team4C changes. No subject name
(e.g. the two real production subjects) or language name is encoded
into any retrieval-code branch anywhere in this work.

## 3. Environment & Git State

The working directory is **not a git repository** — `git status`,
`git branch`, and `git diff --stat` all failed with "fatal: not a git
repository (or any of the parent directories): .git", consistent with
every earlier phase's own check. There is therefore no branch/diff
history to report; all before/after state in this document was
established by direct inspection (`ls`/`find`/`Read`) and by running the
test suite, not by git.

Two file-path assumptions in the master prompt did not match the real
repository and were corrected by discovery rather than assumed:

| Assumed | Actual |
|---|---|
| `team4b/app/config.py` | `team4b/app/core/config.py` |
| `team4b/app/dependencies.py` | `team4b/app/api/dependencies.py` |

## 4. Phase 4D Acceptance Gate Verdict

All eight criteria (A–H) were re-verified at the start of this phase and
**PASS**:

- **A** — Phase 4D's two report files exist and are substantive.
- **B** — Baseline (`all-MiniLM-L6-v2`) and candidate
  (`paraphrase-multilingual-MiniLM-L12-v2`) models are both known and
  documented.
- **C** — Results are reproducible via the documented settings-override
  methodology reusing Phase 4A's temporary collections.
- **D** — The canonical collection was never overwritten (1650 points,
  confirmed unchanged at every phase boundary since).
- **E** — No production embedding migration occurred; `Settings.
  embedding_model_name` is still `all-MiniLM-L6-v2` by live read.
- **F** — Production embedding configuration is known and unchanged.
- **G** — Phase 4D benchmark results are fully recorded in
  `phase4d_cross_lingual_embedding_evaluation.json`/`_review.md`.
- **H** — No migration recommendation was made from a single improved
  metric; Phase 4D's own review separated per-metric movement from an
  overall verdict.

**Verdict: Phase 4D is complete. Phase 4E is authorized to proceed.**

## 5. Current RAG Architecture Summary

Team4B is a FastAPI service (`app/`) built around a `RAGService`
orchestrator that composes: `HybridRetriever` (semantic + BM25 + RRF +
optional reranker), `GenerationAuthorityClient` (fail-closed, Mongo-
backed), `ConversationManager` (Redis-backed session history),
`LLMGenerator` (Ollama), and `response_assembly` (citation/response
contract). Protocol-based dependency injection
(`EmbedderProtocol`/`QdrantClientProtocol`/`RerankerProtocol`/etc.)
throughout means every one of these can be substituted with a fake in
tests without real infrastructure — exploited throughout this phase's
new test harness.

## 6. Current Retrieval Flow

Three modes: `semantic`, `keyword`, `hybrid`. Each mode gathers an
expanded candidate pool (`hybrid_candidate_pool_size`, further expanded
to `reranker_candidate_pool_size` when a reranker is configured),
applies generation-authority filtering, then calls the single shared
`_finalize_results()` method, which either truncates to `top_k`
(reranker disabled — byte-for-byte pre-Phase-4B behavior) or asks the
configured reranker to re-score/reorder before truncating (reranker
enabled), degrading safely back to plain truncation if the reranker
raises `RerankerUnavailableError`.

## 7. Current Filtering Flow

Workspace scoping (`workspace_id`, mandatory, no default) and document
scoping (`document_ids`) are enforced by the vector store and BM25 index
themselves, before any ranking or fusion happens. Generation-authority
filtering runs immediately after candidate gathering and before
`_finalize_results()`, so a reranker never even sees an unauthorized
candidate (verified directly in Section 15/20). Source-type filtering
(`collection_filter`) is enforced on the semantic leg in all modes that
use it, but — a confirmed gap discovered and documented in this phase —
**not** on the BM25 leg during hybrid-mode retrieval (Section 16).

## 8. Current Reranker State

Disabled by default (`Settings.reranker_enabled = False`), confirmed
still `False` in production configuration at the close of this phase.
When enabled, `CrossEncoderReranker` wraps
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` and only ever reorders/
truncates the candidates it is given — it cannot add new candidates or
alter their `chunk_id`/`text`/`metadata` (Section 20).

## 9. Current Embedding State

Production embedding model is `all-MiniLM-L6-v2`, 384-dim, unchanged.
No embedding migration was performed or recommended for production use
in this phase (that decision remains explicitly out of scope, per
Phase 4D's own findings and this phase's instructions).

## 10. Current Test Suite State (Pre-Phase-4E Baseline)

Before this phase's additions, `team4b/tests/` contained 33 files
covering unit, integration, and prior-phase-specific tests (BM25,
hybrid retriever, reranker, RAG service, conversation, vector store,
Phase 2 evaluation harness, Phase 3 ground truth, RAGAS adapter, etc.).
All were passing prior to this phase's changes.

## 11. Canonical Collection Integrity

| Checkpoint | Collection | Point count |
|---|---|---|
| Phase 4D close (carried forward) | `educopilot_chunks` | 1650 |
| Phase 4E start (re-verified live) | `educopilot_chunks` | 1650 |
| Phase 4E close (re-verified live) | `educopilot_chunks` | 1650 |

No write, delete, rename, or re-embed operation was ever issued against
this collection in this phase. All new tests run exclusively against
`InMemoryQdrantClient`, an in-memory test double — the real Qdrant
client is used only for the three read-only `get_collection` count
checks above.

## 12. Generalized Test Harness Design

New file: `team4b/tests/test_phase4e_workspace_rag_safety.py`. Generic,
locally-defined fixtures/builders — `GenericWorkspaceFixture`,
`GenericDocumentFixture`, `GenericChunkFixture` — plus generic fakes
(`GenericEmbedder`, `GenericGenerationAuthorityClient`,
`GenericReranker`) modeled on this codebase's existing `Fake*`
conventions (`tests/test_hybrid_retriever.py`, `tests/test_rag_service.py`,
`tests/fakes.py`). No fixture or test in this file references any real
production subject, document ID, or workspace ID; all identifiers are
arbitrary strings (`ws-alpha`, `doc-pdf`, `chunk-beta-1`, synthetic
subject labels like `physics`/`biology`) chosen to be visibly
interchangeable, not tied to the real corpus.

## 13. Workspace Isolation — Tests & Results (Invariant 1)

`TestWorkspaceIsolation`, 9 tests, all passing. Covers: disjoint results
between two workspaces sharing the same query text; a more-relevant
document in the *wrong* workspace never leaking in; other-workspace
content never influencing the *in-workspace* ranking order; isolation
holding with the reranker both enabled and failing; and isolation
holding for a chunk carrying only minimal required metadata. All three
search modes (`semantic`/`keyword`/`hybrid`) are parametrized across the
relevant tests.

## 14. Document Filtering — Tests & Results (Invariant 2, 7)

`TestDocumentFiltering`, 13 tests, all passing. Covers `document_ids`
= `None` / a single ID / multiple IDs / an empty list, across all three
search modes, plus a reranker-enabled variant confirming a filtered-out
document's chunk never reaches the reranker. The empty-list case is
asserted to return exactly zero results (non-widening), directly proving
Invariant 7.

## 15. Generation Authority — Tests & Results (Invariant 3, 6)

`TestGenerationAuthority`, 7 tests, all passing. Covers: an
authorized/unauthorized mixed pool across all three search modes; a
generation-number mismatch (stale chunk) exclusion; proof the reranker
never receives an unauthorized candidate even when it would rank it
highest; proof the reranker-failure fallback path remains authorized
(never reintroduces the unauthorized chunk); and fail-closed behavior
when the authority backend itself is unavailable (zero results, not a
crash and not an "allow all" default).

## 16. Source Selection — Tests & Results, Including Known Gap (Invariant 11)

**UPDATE (Phase 4E-F1, 2026-09-17): FIXED.** This section originally
recorded a confirmed gap and is preserved below as history, per Phase
4E-F1's explicit instruction not to rewrite the record; the gap no
longer exists in the current code.

`TestSourceSelection`, 3 tests. Two passed at Phase 4E close showing
correct behavior (no filter = all source types eligible;
`collection_filter` correctly restricts results in semantic mode). The
third, originally named
`test_KNOWN_GAP_collection_filter_is_not_enforced_against_the_bm25_leg_in_hybrid_mode`,
was a **documenting** test at the time: it passed because it asserted
the *actual* (gap) behavior, not the desired one. It has since been
renamed to
`test_PHASE4E_F1_FIXED_collection_filter_is_enforced_against_the_bm25_leg_in_hybrid_mode`
and now asserts the correct, filtered behavior — this is the same test
site, updated in place, not a new one added around the old one.
`TestCrossCuttingInvariants::test_invariant_11_source_filtering_enforced_in_semantic_leg_throughout_pipeline`
continues to confirm the semantic leg's own enforcement, unchanged by
this fix.

The fix itself has its own dedicated 14-test regression suite,
`tests/test_phase4e_f1_bm25_source_filter.py` (tests A–K plus 2
supporting unit/end-to-end tests) — see Section 24 for the full
root-cause/fix/verification record.

## 17. Session Isolation — Tests & Results (Invariant 12)

`TestSessionIsolation`, 3 tests, all passing, exercised through
`RAGService` directly (not just `HybridRetriever`) using locally-defined
fakes for the retriever, conversation manager, and LLM generator. Covers
the exact scenario from the master prompt's worked example: two
sessions each ask an initial question, then the identical elliptical
follow-up ("What are its advantages?") — each session's follow-up is
proven to enrich using only its own prior turn, never the other
session's, and the LLM-facing conversation history is proven not to
cross sessions either.

## 18. Multilingual Architecture — Tests & Results

`TestMultilingualArchitecture`, 7 tests, all passing. Six are a single
parametrized test run across every query-language × source-language
combination the product must support (English/Hindi/Hinglish query ×
English/Hindi source). No `if language == ...` branch exists anywhere in
`HybridRetriever` — the same unmodified code path handles every
combination identically. The seventh confirms the BM25 tokenizer
handles a single string mixing Devanagari and Latin script without any
special-casing. **This section makes no claim about the real
embedding/BM25 model's actual cross-lingual retrieval quality** — that
question was already separately and thoroughly answered, with real
data, in Phases 4A/4C/4D.

## 19. Domain Generalization — Tests & Results (Invariant 9, 10)

`TestDomainGeneralization`, 6 tests, all passing, using entirely
synthetic subjects (physics, biology, mathematics, history,
computer-science) never present in the real corpus. Proves a brand-new
subject/workspace works against the unmodified retriever with zero code
changes, and that five simultaneous synthetic-subject workspaces never
cross-contaminate each other's results. **This is an architecture claim
only** — it does not claim the current production model or corpus
performs well on any of these subjects, since none of this test data is
real.

## 20. Reranker Safety — Tests & Results (Invariant 4, 5)

`TestRerankerSafetyInvariants`, 5 tests, all passing, exercised directly
against the real `CrossEncoderReranker` class (not only a fake): it
cannot introduce a chunk_id absent from its input; it cannot modify a
candidate's `metadata`/`text`/`chunk_id` (only its score/position);
authorization is structurally proven to happen before reranking (source
inspection of `_retrieve_hybrid` confirms `_passes_generation_check`
runs strictly before `_finalize_results`, the only call site of
`reranker.rerank(...)`); disabling the reranker preserves prior,
deterministic behavior; and candidate-pool size vs. final `top_k` are
independently configurable and both honored.

## 21. Citation Integrity — Tests & Results (Invariant 8)

`TestCitationIntegrity`, 4 tests, all passing. Confirms
`to_source_attribution()` reads only from `RetrievalResult.metadata`
(never from generated answer text — verified both behaviorally and by
inspecting that function's source for any reference to an "answer"
value); a missing `document_id`/`document_title` raises rather than
fabricating a citation; and an assembled `QueryResponse`'s citations
correspond exactly to the actual retrieval results even when the LLM's
generated answer text mentions a fabricated, non-existent document by
name — that fabricated name never appears among the returned citation
document IDs.

## 22. Edge Cases & Failure Handling — Tests & Results

`TestEdgeAndFailureCases`, 9 tests, all passing. Covers: empty and
whitespace-only queries; a non-existent workspace; a non-existent
document-id filter; an invalid search-mode string (raises
`InvalidSearchModeError` rather than silently defaulting); reranker
unavailability never surfacing unauthorized evidence as a "fallback";
duplicate chunk IDs passed into the reranker not being silently
deduplicated away; a candidate pool smaller than the requested `top_k`
returning all available results without error; and an empty candidate
pool still safely invoking a configured reranker with an empty list
rather than skipping it inconsistently.

## 23. Invariant Traceability Matrix

| # | Invariant | Status | Primary test(s) |
|---|---|---|---|
| 1 | Workspace A query never returns workspace B evidence | Proven | `TestWorkspaceIsolation` (9) |
| 2 | document_ids membership correctly enforced | Proven | `TestDocumentFiltering` (13) |
| 3 | Generation-authority satisfaction enforced pre-fusion | Proven | `TestGenerationAuthority` (7) |
| 4 | Reranker cannot introduce new evidence | Proven | `TestRerankerSafetyInvariants::test_reranker_cannot_introduce_a_candidate_not_present_in_input` |
| 5 | Reranker cannot modify evidence identity | Proven | `TestRerankerSafetyInvariants::test_reranker_cannot_modify_metadata_identity` |
| 6 | Fallback cannot weaken authorization | Proven | `TestGenerationAuthority::test_fallback_on_reranker_failure_remains_authorized` |
| 7 | Empty document filter → zero results | Proven | `TestDocumentFiltering::test_document_ids_empty_list_returns_zero_results` |
| 8 | Citation metadata refers only to actual retrieved chunks | Proven | `TestCitationIntegrity` (4) |
| 9 | New domain requires zero retrieval-code changes | Proven | `TestDomainGeneralization` (6) |
| 10 | New workspace requires zero retrieval-code changes | Proven | `TestDomainGeneralization::test_five_synthetic_subject_workspaces_never_cross_contaminate` |
| 11 | Source filtering enforced through full pipeline | **Proven** (fixed 2026-09-17, Phase 4E-F1; was Partial at Phase 4E close) | Semantic leg (unchanged) + BM25 leg (`test_PHASE4E_F1_FIXED_...`, `test_phase4e_f1_bm25_source_filter.py` A–K) |
| 12 | Session context cannot cross workspace boundaries | Proven | `TestSessionIsolation` (3) |

## 24. Master Safety Checklist, Acceptance Criteria, Limitations, and Next-Phase Recommendation

**PHASE4E-F1 ADDENDUM (2026-09-17, follow-up to this phase):**

- **Root cause:** `BM25Index.search()` had no source-type parameter at
  all, and `HybridRetriever` never passed `collection_filter` to it in
  either keyword-only or hybrid mode.
- **Fix:** Added `BM25Document.source_type` (populated from each
  chunk's already-normalized metadata) and a `collection_filter`
  parameter on `BM25Index.search()`, filtering candidates by source type
  before the per-query BM25 index is built — mirroring the existing
  `document_ids` mechanism, but preserving `collection_filter`'s own
  distinct "empty means no restriction" contract rather than adopting
  `document_ids`'s "empty means zero" one. `HybridRetriever` now threads
  `collection_filter` into both `_retrieve_keyword_only()` (which
  previously didn't accept the parameter at all) and `_retrieve_hybrid()`'s
  BM25 leg call (which previously only forwarded it to the semantic leg).
- **Files changed:** `team4b/app/services/bm25_index.py`,
  `team4b/app/services/hybrid_retriever.py`. Three existing test-double
  subclasses of `BM25Index` (`SlowBM25`, `_RaisingBM25`, `_CountingBM25`
  in `tests/test_hybrid_retriever.py`/`tests/test_hybrid_retriever_properties.py`)
  needed a one-line signature update to accept the new keyword parameter
  — a mechanical consequence of the fix, not a behavior change.
- **Tests added:** `tests/test_phase4e_f1_bm25_source_filter.py` (14
  tests: A–K from the fix's own acceptance list, plus a BM25Index unit
  test and an end-to-end test using the real "document"/"video"
  vocabulary). `tests/test_phase4e_workspace_rag_safety.py`'s former
  KNOWN_GAP test was renamed to
  `test_PHASE4E_F1_FIXED_collection_filter_is_enforced_against_the_bm25_leg_in_hybrid_mode`
  and now asserts the corrected behavior.
- **Regression results:** targeted sequence (BM25/HybridRetriever/
  properties/reranker/Phase 4E/4E-F1/Phase 2/Phase 3) — 368 passed, 0
  failed. Full Team4B suite — 1274 passed, 3 pre-existing skips, 0
  failed (1260 at Phase 4E close + 14 new).
- **Canonical collection:** `educopilot_chunks` — 1650 points before,
  1650 after. Production config re-verified unchanged:
  `embedding_model_name=all-MiniLM-L6-v2`, `reranker_enabled=False`.
- **Not a git repository** (confirmed again before and after this fix,
  same as every prior phase) — no commit/diff was created; all
  before/after state above was established by direct inspection and
  test runs.
- **Domain generalization preserved:** the fix's own tests use synthetic
  source-type labels (`type-alpha`/`type-beta`/`type-gamma`) to prove
  the mechanism has no dependency on the real "document"/"video"
  vocabulary; `BM25Index`/`HybridRetriever` still contain no
  subject/source-specific branching.

**Master safety checklist (updated to reflect the Phase 4E-F1 fix):**

- [x] Workspace isolation holds across all search modes and reranker states
- [x] Document filtering (including empty-list) correctly enforced
- [x] Generation authority fail-closed and enforced pre-reranking
- [x] Source-type filtering enforced through the *entire* pipeline (fixed in Phase 4E-F1; was a documented BM25/hybrid gap at Phase 4E close)
- [x] Session isolation holds, including elliptical follow-ups
- [x] No language-specific retrieval branching exists
- [x] No subject/domain-specific retrieval branching exists
- [x] Reranker cannot fabricate, add, or corrupt evidence
- [x] Citation metadata is never derived from generated text
- [x] Canonical collection (`educopilot_chunks`) untouched (1650 points, before = after)
- [x] Production reranker remains disabled
- [x] No embedding migration performed
- [x] No secrets logged, printed, or exposed anywhere in this work
- [x] No Team4A/Team4C/UI/auth/deployment files touched
- [x] No query rewriting/expansion/decomposition/adaptive-retrieval logic added

**Acceptance criteria verdict:** at Phase 4E's original close, all
criteria requiring proof of architecture properties were met with
passing, non-fabricated tests except one — source-type filtering in
hybrid mode was honestly reported as a partial result with a confirmed
root cause, per that phase's own anti-fabrication requirements. As of
the Phase 4E-F1 follow-up (2026-09-17, same day), that exception is
closed: the fix is implemented, regression-tested, and verified against
the full suite and the canonical collection. All acceptance criteria now
pass. No measurable claim in this document uses the word "perfect."

**Known limitations:**
1. ~~PHASE4E-F1 — `collection_filter` is not enforced on the BM25 leg in
   hybrid-mode retrieval~~ **FIXED in Phase 4E-F1 (2026-09-17)** — see
   the addendum above and Section 16. No longer an open limitation;
   struck through rather than deleted so the historical record stays
   intact.
2. This phase's multilingual and domain-generalization tests are
   architecture proofs using synthetic/controlled data — they make no
   claim about current real-corpus retrieval quality, which remains
   governed by the separate, already-completed findings of Phases
   4A/4C/4D. Still true after Phase 4E-F1; unaffected by that fix.
3. Three pre-existing test skips remain in the full suite, unrelated to
   and unmodified by either Phase 4E or Phase 4E-F1.

**Next-phase recommendation:** PHASE4E-F1 is complete — no further
action is required for it. No other production issue is currently
known. This document does not propose starting a specific Phase 4F;
per the governing instructions for both this phase and its follow-up,
that decision is left to the user.
