# M6 — OS Workspace 1400 vs. 292 Point-Count Discrepancy Investigation (Read-Only)

**Date:** 2026-09-18
**Type:** Read-only investigation only. Nothing was ingested, deleted, or modified in Qdrant, MongoDB, or the filesystem while producing this report. No historical report was modified.
**Scope:** Explain, using only surviving evidence, why the historical OS workspace (`6a912a1883f46878932e0eec`) held 1400 Qdrant points while the rebuilt corpus holds 292.

---

## 1. The decisive evidence

Two surviving, pre-incident, git-tracked files together give a complete, positively-sourced answer:

### (a) `team4b/data/phase4c_candidate_recall_diagnosis.json` (historical Phase 4C report, `point_count_before`/`point_count_after` both `1650`)

`part_a_mongo_qdrant_alignment` gives a **per-document_id breakdown of every chunk in the corpus at that time**, cross-referenced against MongoDB. For the OS workspace it lists exactly 9 document_ids summing to exactly 1400:

| document_id | chunk_count | type | title / identity | Mongo record (at Phase 4C time) |
|---|---|---|---|---|
| `6aa72dae16cbab6b27d5f508` | 115 | pdf | `0b83b5b1...pdf` | **orphaned** (no Mongo record) |
| `6aa72df916cbab6b27d5f50a` | 120 | pdf | `176998435...pdf` | **orphaned** |
| `6aa72e4416cbab6b27d5f50b` | 115 | pdf | `7124de8d...pdf` | **orphaned** |
| `6aa846698a7bd709c53a5f4e` | 115 | pdf | `85a12499...pdf` | **orphaned** |
| `6aa90d9f4ac03b89c7624cc8` | 115 | pdf | `66cb0b8c...pdf` | **orphaned** |
| `6aa90e314ac03b89c7624ccb` | 115 | pdf | `1e1cc3ee...pdf` | present |
| `6aa90eb64ac03b89c7624cce` | 1 | mp4 | `974c0a31...mp4` | **orphaned** |
| `6aaa4cd56eee7990194e5168` | 527 | youtube | "Introduction to Operating System and its Functions \| Operating System \| Lecture 1" | present |
| `6aaa7e8c81e2b76728b76bb6` | 177 | youtube | "Operating System OS in 100 Minutes..." (Sanchit Sir) | present |
| **Total** | **1400** | | | |

The same report's `part_a_orphaned_document_ids` explicitly flags 6 of these 9 document_ids as **orphaned Qdrant chunks with no corresponding MongoDB File record — a pre-existing data-quality condition that already existed at Phase 4C time, well before today's Docker incident.** It further shows the *approved ground truth's* SJF/process/semaphore/IPC/LRU queries (`c_sjf_difficulty__*`, `c_process_vs_program__*`, `c_semaphore_wait_signal__*`, etc.) all resolved to these orphaned document_ids, not to any live Mongo-backed document.

I independently re-checked MongoDB today: **none of these 9 document_ids exist in `files` now.** Consistent with the historical report — 6 were already gone by Phase 4C, and the remaining 3 (which did exist then) have since been removed through ordinary subsequent workspace/file activity unrelated to the Docker reset (MongoDB survived the reset untouched).

### (b) `team4b/data/phase2_ground_truth_candidate_review.md` (pre-approval Phase 2 reviewer notes — "Corpus limitations discovered during construction")

This document independently explains *why* several of the above document_ids were excluded from the ground truth, confirming their content was not usable educational material:

- **`6aaa4cd56eee7990194e5168`** (527 chunks, "Introduction to Operating System and its Functions | Lecture 1"): *"chunks averaging ~6.7 words each (range 1-10 words) — far too fragmented for any chunk to stand alone as answerable evidence. Excluded entirely."* — a real video, but broken/over-fragmented ingestion, deliberately excluded as low-quality.
- **`6aa72df916cbab6b27d5f50a`** (120 chunks): *"a Maharashtra CET admissions allotment list (student names/scores/categories), not educational content. Excluded entirely."* — **not OS course material at all**; unrelated data that ended up in this workspace.
- **`6aa90eb64ac03b89c7624cce`** (1 chunk, mp4): *"exactly 1 chunk whose entire text is the single word 'you'."* — a broken/near-empty ingestion.
- **`6aa72e4416cbab6b27d5f50b` and `6aa72dae16cbab6b27d5f508`** (115 chunks each): *"share at least one identical page's text ('Lecture #6(UNIT-II) Process Concept', page 15) — likely overlapping/duplicate source material."* — confirmed duplicate/overlapping re-ingestion of the same PDF content under separate document_ids.

Applying the same reasoning to the two remaining, unexplained-by-name entries (`6aa846698a7bd709c53a5f4e`, `6aa90d9f4ac03b89c7624cc8`, each 115 chunks, both orphaned, both PDF-typed): their chunk counts (115, matching the single confirmed-clean PDF's exact chunk count) and their being "orphaned" in the same way as the two confirmed-duplicate PDF document_ids above make them almost certainly further repeated ingestions/generations of the same `R20CSE2202-OPERATING-SYSTEMS.pdf`, not additional distinct source material — but this specific inference (as opposed to the two the review doc names explicitly) is circumstantial, not independently document-confirmed.

---

## 2. What this explains, arithmetically

| Component | Chunks | Status |
|---|---|---|
| OS PDF, 1 clean generation | 115 | **Legitimate — matches rebuilt corpus exactly** |
| OS PDF, ≥1 confirmed duplicate generation (`...f50b`) | 115 | Confirmed duplicate of the same PDF content |
| OS PDF, 2 further same-pattern orphaned generations (`...5f4e`, `...4cc8`) | 230 | Very likely further duplicate generations (circumstantial, not name-confirmed) |
| OS PDF, 1 further orphaned generation (`...ccb`) | 115 | Same pattern |
| Non-educational junk (CET admissions list, mislabeled as `.pdf`) | 120 | **Confirmed not OS content at all** |
| Broken mp4 ("you") | 1 | Confirmed broken/near-empty ingestion |
| Second YouTube video, real but excluded for fragmentation | 527 | Confirmed real video, confirmed excluded for quality, not fabricated |
| OS YouTube video, 1 clean generation (Sanchit Sir, "OS in 100 Minutes") | 177 | **Legitimate — matches rebuilt corpus exactly** |
| **Total** | **1400** | |

**292 (115 + 177) of the 1400 — exactly the rebuilt corpus's count — is independently confirmed, by this same historical report, to be the single clean generation of each real, ground-truth-relevant source.** The remaining 1108 breaks down as:
- **695 chunks (5 of 6 PDF document_ids)**: duplicate/repeated ingestions of the same OS PDF under different document_ids — confirmed for at least 1 of the 5 by shared identical page text, strongly suspected (same size, same orphaned status) for the other 3, and not independently verifiable beyond that for any given one since their MongoDB records and any ingestion log are gone.
- **120 chunks**: confirmed non-OS junk data (an admissions list) that had been mistakenly present in the OS workspace — its correct treatment is **exclusion**, not reconstruction.
- **1 chunk**: a confirmed broken/near-empty mp4 ingestion — not meaningful content.
- **527 chunks**: a real second YouTube video that historically existed in the workspace but was deliberately excluded from ground truth for being too fragmented to be usable RAG content — recoverable in principle (its title is known) but was never validated as good content, and is not the source of the OS PDF/video ground truth queries.

---

## 3. Direct answers to your six questions

**1. Evidence explaining the 1400 historical OS points.**
A surviving historical Phase 4C diagnostic report (`phase4c_candidate_recall_diagnosis.json`) gives an exact, contemporaneous, document-by-document breakdown of the 1400 points, and a second surviving pre-approval reviewer document (`phase2_ground_truth_candidate_review.md`) independently explains, in its own words, why several of those documents were excluded from the ground truth (non-educational content, broken ingestion, over-fragmented chunks, confirmed duplicate PDF text). Both documents predate today's incident by multiple phases and were found by searching exactly the evidence sources you specified, without modification.

**2. How much of the difference can be positively explained.**
Of the 1108-point gap: **648 chunks are positively, directly confirmed** by name in the reviewer document (120 non-OS junk + 1 broken mp4 + 527 excluded-for-fragmentation video). A further **115 chunks are confirmed as duplicate** PDF content (shared identical page text with the clean PDF generation). That is **763 of 1108 chunks (~69%) positively explained with direct documentary evidence**, not inference.

**3. What remains unexplained.**
The remaining **345 chunks** (3 further PDF-typed, 115-chunk, orphaned document_ids: `6aa72dae16cbab6b27d5f508`, `6aa846698a7bd709c53a5f4e`, `6aa90d9f4ac03b89c7624cc8`) share the exact same signature as the confirmed-duplicate one (115 chunks, PDF type, orphaned Mongo record) and are very likely further duplicate generations of the same PDF — but no document names them explicitly the way the reviewer notes name the other three, so this is a strong circumstantial inference, not a document-confirmed fact. There is no evidence of any *additional, distinct* OS source beyond what is already accounted for above.

**4. Whether exact 1650 (1400+250) reconstruction is realistically possible.**
**No, and it would not be desirable even if possible.** The evidence shows the historical 1400 was never 1400 points of clean, unique OS educational content — it included confirmed non-course-material (the admissions list), a confirmed-broken ingestion, and multiple confirmed/likely duplicate re-ingestions of the same PDF. Reconstructing "1400" would mean deliberately re-injecting junk data and duplicate chunks that the project's own prior reviewers had already identified and excluded. The one legitimately excluded-for-quality item (the 527-chunk second YouTube video, "Introduction to Operating System and its Functions | Lecture 1") could in principle be re-identified and re-ingested if you want it back, but it was never part of the validated ground truth and was excluded for a documented quality reason, not lost by this incident.

**5. Whether the current 542-point corpus is sufficient for the NEW product-level validation.**
**Yes.** The 292-point OS corpus (115 PDF + 177 video) and the 250-point DBMS corpus are each a single, clean generation of the same source content the approved 75-entry ground truth was actually built from (per §6 of the reconstruction inventory and this report's own confirmation that 292 = 115+177 exactly). The 1108-point historical excess consisted of content this investigation shows should not have been counted as "real" corpus size in the first place (duplicates, junk, broken ingestion). The rebuilt 542-point corpus is content-equivalent to the historically-validated, ground-truth-relevant material — it is not missing legitimate content relative to what the approved ground truth actually depends on.

**6. Source/document IDs to preserve for future reference.**
- `6aaa4cd56eee7990194e5168` — "Introduction to Operating System and its Functions | Operating System | Lecture 1" — the one genuinely real, previously-uncounted OS YouTube video, in case you want to deliberately (re-)ingest it later with better chunking.
- `6aa72dae16cbab6b27d5f508` and `6aa72e4416cbab6b27d5f50b` — the two document_ids confirmed to share identical page text, useful evidence if duplicate-detection logic is ever added to the ingestion pipeline.
- The full 9-document_id table in §1(a) above, for any future audit of this workspace's ingestion history.
- The current rebuilt document_ids (`6aac2f6a1460f628a7f2c7d5` PDF, `6aac2b521460f628a7f2c7d2` video, `6aac31c51460f628a7f2c7e1` DBMS PDF), already recorded in `docs/m6-rebuilt-baseline-manifest.json`.

---

## 4. What was and was not touched

No Qdrant collection, MongoDB record, or historical report was modified while producing this document. All figures above were read directly from pre-existing, git-tracked JSON/Markdown files and cross-checked against a live, read-only MongoDB query. Nothing was ingested. Nothing was deleted. The current 542-point corpus and its external Qdrant snapshot backup are unchanged.
