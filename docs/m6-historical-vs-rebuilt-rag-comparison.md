# M6 Historical vs. Rebuilt RAG Comparison

**Date:** 2026-09-17/18
**Incident:** Docker Desktop Factory Reset destroyed the Qdrant data volume. Original source content (both PDFs, both YouTube videos) was positively recovered and re-ingested through the normal canonical pipeline — see `docs/m6-original-corpus-reconstruction-inventory.md` and `docs/m6-rebuilt-baseline-manifest.json`.

This document keeps two things strictly separate, as required:

- **(A) Historical Phase 1–4E/F1 results** — the pre-incident findings, unmodified, still fully valid as a record of what was measured against the original 1650-point corpus at the time.
- **(B) Fresh rebuilt-corpus results** — what was actually measured just now, against the rebuilt 542-point corpus with entirely new chunk/document IDs.

**No claim here says the rebuilt result proves the historical result right or wrong.** They are different corpora at the chunk-ID level, and are compared only where a comparison is actually meaningful.

---

## 1. Point counts

| Workspace | (A) Historical | (B) Rebuilt | Difference | Match? |
|---|---|---|---|---|
| OS (`6a912a1883f46878932e0eec`) | 1400 | 292 | −1108 | No |
| DBMS (`6a8de2d7e43679cbe2ee243d`) | 250 | 250 | 0 | **Yes, exact** |
| **Total** | **1650** | **542** | **−1108** | No |

### Possible explanations investigated for the OS gap

- **Not a chunking/extraction regression**: no chunking code, embedding model, or extraction library was changed (confirmed via `git status` throughout — only `team4a/docker-compose.yml`'s volume pin and the already-known Phase 5A/docs additions are modified/new; no application code touched).
- **Confirmed content loss**: the DBMS YouTube video (`kBdlM6hNDAE`) could not be re-ingested — `youtube_transcript_api` returns `TranscriptsDisabled` for it (confirmed by direct, isolated testing, bypassing Team4A). This is a genuine, permanent YouTube-side change, not an environment or code issue. However, **no ground-truth entry depends on this video** (see the reconstruction inventory, §6), and it belongs to the DBMS workspace, which still hit the historical count exactly — so this specific loss does not explain the OS gap.
- **Most likely explanation for the OS gap**: the approved 75-entry ground truth only ever sampled **one PDF's four sections plus one YouTube video** for the OS workspace. The historical 1400-point count very likely included **additional source material** (more documents/videos) that was never captured by the ground truth sample and that this investigation had no record of (no Mongo File record, no local file, no ground-truth reference) — i.e., content that existed in the original corpus but left no discoverable trace after the File-record/vhdx loss. This is a plausible, evidence-consistent explanation, not a confirmed one — it cannot be fully verified without the original ingestion history, which no longer exists.
- **What is NOT the explanation**: this is not a sign of broken extraction on the recovered PDF — the recovered `R20CSE2202-OPERATING-SYSTEMS.pdf` was independently content-verified (§1 of the reconstruction inventory) against the exact ground-truth excerpts before ingestion, and ingested cleanly with generation=1, no processing errors.

**Conclusion: the DBMS point count is fully reproduced. The OS point count is not, and the most likely cause is that the original OS workspace contained source material beyond what could be positively identified and recovered — not a defect introduced by this rebuild.**

---

## 2. Chunk/document ID reproducibility

**Not reproducible, and not expected to be.** Every one of the 75 approved ground-truth entries' `relevant_chunk_ids` was checked directly against the rebuilt corpus:

- `tests/test_phase3_generalized_ground_truth.py::TestRelevantChunkIdsExistInCanonicalCorpus` — **FAILS**: all 83 chunk-id references across all 75 entries (including the 24 DBMS entries, despite the DBMS *point count* matching exactly) are absent from the rebuilt corpus.
- Running `scripts/phase2_multilingual_embedding_evaluation.py` against the rebuilt corpus with the approved ground truth: the harness's own safety guard **refuses to compute any Recall@k/MRR metric at all**, logging `"Ground truth references chunk_ids not present in the copied canonical data -- refusing to compute metrics against an inconsistent ground truth"` for every one of the 72 evaluable entries (3 more use `source_language: "mixed"`, which this harness has never supported, unrelated to the rebuild).

This is the correct, expected, harness-enforced outcome — chunk IDs are deterministically derived from each chunk's own `document_id` (itself the new File `_id` MongoDB assigned on re-ingestion), so a fresh ingestion of even byte-identical source content necessarily produces entirely new, different chunk IDs. **This is not a retrieval-quality regression** — it is the direct, unavoidable, and already-documented consequence of the historical document/chunk IDs being permanently lost (see the rebuilt baseline manifest's explicit `"Historical point IDs... are permanently lost"` note). No ID-based recall/MRR number can be honestly computed against the rebuilt corpus using the existing ground truth, and none is reported here as if it could be.

---

## 3. What WAS meaningfully re-verified against the rebuilt corpus

Metrics that do **not** depend on the historical chunk IDs were re-run and are directly comparable:

| Check | (A) Historical | (B) Rebuilt | Result |
|---|---|---|---|
| Full Team4B test suite | 1303 passed, 3 skipped (Phase 5A close) | **1302 passed, 3 skipped, 1 failed** | The 1 failure is `TestRelevantChunkIdsExistInCanonicalCorpus` — expected per §2, not a code regression. Every other test (workspace isolation, document filtering, generation authority, citation integrity, BM25 tokenizer, hybrid retrieval, RRF, Phase 4E/F1 safety suite, Phase 5A tests) passes identically. |
| Canonical collection schema | 384-dim, Cosine | 384-dim, Cosine | **Identical** |
| Embedding model | all-MiniLM-L6-v2 | all-MiniLM-L6-v2 | **Identical** |
| Reranker | disabled | disabled | **Identical** |
| Metadata schema (workspace_id, document_id, ingestion_generation, source-specific fields) | established contract | verified present and correct on sampled points from both workspaces | **Identical structure** |
| Phase 4E/F1 workspace/document/generation-authority/citation safety tests | passed (synthetic fixtures, infra-independent) | passed (same tests, same fixtures — do not touch the canonical collection at all) | **Identical** — these tests were never coupled to specific chunk IDs in the first place |

---

## 4. Metrics that could NOT be honestly re-computed

- **Phase 2 Recall@k / MRR** (embedding evaluation harness): refused by the harness's own consistency check (§2). Not computed. Not estimated. Not fabricated.
- **Phase 3 ground-truth chunk-existence validation**: fails by design (§2) — the same underlying cause.
- **Phase 4A embedding comparison, Phase 4C candidate-recall diagnosis, Phase 4D cross-lingual evaluation**: these phases' own driver scripts were, per their own documented convention, kept in a session-scoped scratchpad directory and never committed to the repository (only `phase2_multilingual_embedding_evaluation.py` was committed and reusable). That scratchpad no longer exists in this session. Reconstructing 4A/4C/4D's exact methodology would itself be a multi-hour undertaking equivalent to re-running those phases from scratch, and any such run would hit the identical chunk-ID refusal §2 describes for the ID-dependent parts of their methodology. This was not attempted, to avoid fabricating a result or silently downgrading these phases' rigor.

---

## 5. Explicit statement on reproducibility

- **Content reproducibility**: high confidence — both recovered PDFs and one of two recovered YouTube videos were positively content-verified against actual ground-truth excerpts before re-ingestion, not merely name-matched.
- **Structural/architectural reproducibility**: exact — same embedding model, same vector schema, same collection name, same generation-authority contract, same retrieval code (byte-for-byte, confirmed via `git status`).
- **ID-level reproducibility**: **none, and this was never claimed**. Historical document/chunk IDs are permanently gone.
- **Quantitative retrieval-quality reproducibility (Recall@k/MRR against the approved ground truth)**: **not measurable** against the rebuilt corpus with the existing ID-based ground truth. A new, freshly-validated ground truth against the rebuilt chunk IDs would be required to measure this — not attempted here, as it is out of this recovery task's scope.

**This document does not claim the rebuilt corpus "passes" or "fails" the historical RAG evaluation. It reports, honestly, that the historical evaluation's ID-based methodology cannot be applied to the rebuilt corpus at all, while the corpus's structural correctness, safety properties, and code-level regression status were all independently and successfully verified.**
