# Testing & Validation

## Team4B unit/integration test suite

```bash
cd team4b
python -m pytest -q
```

**Expected baseline:** `1302 passed, 3 skipped, 1 known pre-existing
failure`. This exact baseline has been re-verified, unchanged, at the end
of every phase in the Phase 5D–5K RAG validation arc, and again in Phase
5L after documentation/cleanup changes.

If this changes:
- **A new failure** → investigate before doing anything else; do not
  weaken or delete the failing test to get a green suite.
- **The known failure disappears** → investigate why (it may mean the
  underlying stale-ground-truth data was fixed, which would be good news,
  but must be confirmed, not assumed).
- **Fewer tests collected** → likely an accidental deletion or import
  break; treat as a stop condition.

### The known pre-existing failure, explained

```
tests/test_phase3_generalized_ground_truth.py::TestRelevantChunkIdsExistInCanonicalCorpus
    ::test_every_relevant_chunk_id_exists_in_the_canonical_collection
```

This test asserts that every `relevant_chunk_id` in the Phase 3 ground
truth file still exists in the canonical Qdrant collection. It fails
because the canonical corpus was legitimately rebuilt after that ground
truth file was authored (confirmed in Phase 5H/5I-A: the corpus content
itself changed — a real MFT/MVT-vs-Hindi-transcript mismatch example was
found — not merely chunk-ID drift). The fix is to regenerate the ground
truth against the current corpus, not to change the test's assertion.
Phase 5I-A's `phase5i_a_current_corpus_ground_truth_candidate.json` is a
step toward that (19 entries, live-verified, but still explicitly marked
`CANDIDATE`, not human-approved) — it has not replaced the Phase 3 file
this test checks against, so the test correctly still fails until that
replacement is made deliberately, not accidentally.

**Do not delete or weaken this test.** Its failure is accurate, explained,
and tracked — silencing it would hide a real data-provenance fact.

## Integration/acceptance test approach (not pytest — live, scripted)

The RAG validation arc (Phases 5D–5K) used **live, end-to-end scripted
batteries** — real `HybridRetriever` + real `LLMGenerator` + real Ollama
calls, real Qdrant collections — rather than only unit tests, because the
properties being validated (grounding correctness, honest refusal,
prompt-injection resistance) are about actual model behavior, not just
code correctness. These scripts lived outside the repository (in a
session-local scratchpad) and are not part of the committed codebase;
their **results** are committed as the `team4b/data/m6_phase5*_report.{md,json}`
evidence files.

### RAG acceptance methodology (Phase 5J)

17 test categories (grounding, irrelevant-context, out-of-scope,
fresh-session, follow-up, prompt-injection, workspace isolation, document
isolation, citation integrity, source-type coverage, language coverage,
subject coverage, security boundary, error handling, performance) were
each exercised with real queries against real workspaces, in English,
Hindi, and Hinglish, across PDF and YouTube sources and multiple subjects.
67 live generation calls total. Full detail and every individual result:
`team4b/data/m6_phase5j_rag_final_acceptance_report.md`.

### Security acceptance methodology (Phases 5F, 5J, 5K)

A fixed 17-category adversarial threat corpus + 7 legitimate controls
(Phase 5F) has been re-run live, unmodified, at multiple later
checkpoints (5J, 5K) to confirm defenses hold on the *current* code, not
just at the time they were written. Phase 5K additionally forensically
tested two candidate fix designs (an ingestion-side detector and two
generations of an output-side detector) against real captured evidence
before implementing anything, then re-ran the full 31-case battery +
5-case supplement + the full 31-case main acceptance battery post-fix.
Full detail: `team4b/data/m6_phase5k_prompt_injection_architecture_report.md`.

## Team4A and Team4C test suites

Not modified, re-baselined, or newly validated by the Phase 5D–5L arc.

```bash
cd team4a && python -m pytest -q
cd team4c && npm test        # or the project's configured test script
```

Their own existing baselines (from before this arc) apply; consult each
service's own test output/CI history, not this document, for their
current numbers.

## Reproducibility

Every RAG-validation phase report documents its own exact git commit,
Qdrant point counts (before/after), and configuration, so results can be
correlated to a specific, known code/data state. Qdrant collection point
counts have been verified unchanged at the start and end of every phase
in the arc:

- `educopilot_chunks` (canonical): 542
- `educopilot_chunks_product_validation`: 4938
