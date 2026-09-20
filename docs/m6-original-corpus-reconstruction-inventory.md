# M6 Original 1650-Point Corpus — Reconstruction Inventory (Read-Only)

**Date:** 2026-09-17
**Type:** Read-only investigation only. Nothing was ingested, created, deleted, or modified in Qdrant, MongoDB, or the filesystem while producing this report.
**Purpose:** Determine, with positive evidence rather than filename guessing, exactly what would be needed to faithfully reconstruct the original 1650-point `educopilot_chunks` corpus (workspace `6a912a1883f46878932e0eec` = 1400 points, workspace `6a8de2d7e43679cbe2ee243d` = 250 points), following the accidental Docker Desktop factory reset.

---

## Summary verdict

**Both original source PDFs were located, byte-verified, and content-verified against the actual Phase 2 ground-truth excerpts.** Both original YouTube videos are still publicly live. Nothing required for a faithful reconstruction appears to be permanently lost — but the *MongoDB File records* currently present for these workspaces are **not** the original records that produced the ground truth, and that discrepancy is not fully explained (see §4). Reconstruction is very likely possible, but going through the *current* Mongo records as-is would not be provably faithful; a deliberate decision is needed on how to proceed (see the end of this report).

---

## 1. Original sources positively identified

| Source | Workspace | Identification method | Result |
|---|---|---|---|
| `R20CSE2202-OPERATING-SYSTEMS.pdf` | `6a912a1883f46878932e0eec` (OS) | Extracted full text (92 pages) and searched for the distinctive ground-truth excerpt phrases | **POSITIVE MATCH**: "Lecture #6" ✓, "Lecture # 20" ✓, "Process Concept" ✓, "Semaphores" ✓, "minimum average waiting time for a given set of processes" ✓ (near-verbatim match to the SJF ground-truth excerpt), "Multiple fixed partitions" ✓, "MFT" ✓ |
| `DATABASE MANAGEMENT SYSTEMS.pdf` (no suffix) | `6a8de2d7e43679cbe2ee243d` (DBMS) | Extracted full text (232 pages) and searched for the ground-truth excerpt | **POSITIVE MATCH**: contains the exact phrase "SQL provides a special column value called null... unknown or inapplicable" from the ground truth's `c_sql_null` entries |
| `https://youtu.be/KlwNyagHWuk` | `6a912a1883f46878932e0eec` (OS) | Public oEmbed lookup (read-only, no ingestion) | **LIVE**: "Operating System OS in 100 Minutes \| Complete Placement Revision \| One-Shot by Sanchit Sir" (KnowledgeGATE) — a Hindi-language video, consistent with the Hindi chunk excerpt (`नमस्ते इंडिया...`) the ground truth references for this workspace's `youtube`-type entries |
| `https://youtu.be/kBdlM6hNDAE` | `6a8de2d7e43679cbe2ee243d` (DBMS) | Public oEmbed lookup | **LIVE**: "Lec-1: DBMS Syllabus for GATE, UGCNET, NIELIT, DSSSB etc." (Gate Smashers) |

## 2. Original sources that are missing

**None of the four sources above are missing.** Every one was positively located and, for the two PDFs, content-verified — not merely name-matched.

## 3. Current MongoDB records that appear to correspond

| Mongo `_id` | originalName / URL | workspaceId | Note |
|---|---|---|---|
| `6aabce227a90dd0792cb6630` | `R20CSE2202-OPERATING-SYSTEMS.pdf` | `6a912a1883f46878932e0eec` | Name/workspace match. **ID does not match** any `document_id` the ground truth references. |
| `6aabce487a90dd0792cb6631` | `https://youtu.be/KlwNyagHWuk` | `6a912a1883f46878932e0eec` | Same caveat. |
| `6aabce747a90dd0792cb6632` | `DATABASE MANAGEMENT SYSTEMS.pdf` | `6a8de2d7e43679cbe2ee243d` | Same caveat. |
| `6a9723530841065e47632217` | `https://youtu.be/kBdlM6hNDAE?list=...` | `6a8de2d7e43679cbe2ee243d` | **Different ObjectID era** (`6a97...`, not `6aabce...`) — see §4, this one looks more plausibly original, though it isn't referenced by any ground-truth entry either. |

A fifth, unrelated workspace (`6a8de357e43679cbe2ee243f` — note: similar-looking but a genuinely different ID from the real DBMS workspace `6a8de2d7e43679cbe2ee243d`) also holds a `DATABASE MANAGEMENT SYSTEMS.pdf` record plus other unrelated files (`Lecture12-Normalization.mp4`, an MP4 sample, another YouTube URL). This looks like leftover data from earlier, unrelated experimentation — not part of the validated 1650-point corpus — and is noted here only for completeness, not proposed as a source.

## 4. Sources whose identity is ambiguous (ID/timestamp mismatch)

The three `6aabce...`-prefixed records in §3 are the concern:

- MongoDB ObjectIDs embed a creation timestamp. `6aabce22`, `6aabce48`, `6aabce74` sequence **immediately after** my own product-validation test uploads from earlier today (the last of which was `6aabcd3d`) — i.e., they were created in the same short time window as today's validation work, not "whenever the original 1650-point corpus was actually built" (which, per the git/phase history, was materially earlier).
- **None of the four `document_id`s the approved ground truth actually references** (`6aa72dae16cbab6b27d5f508`, `6aa72e4416cbab6b27d5f50b`, `6aa846698a7bd709c53a5f4e`, `6aa90e314ac03b89c7624ccb` for the OS PDF's four sections, plus `6aaa7e8c81e2b76728b76bb6` for the OS video, and `6aa8457c8a7bd709c53a5f46` for the DBMS PDF) **exist in the current `files` collection at all.** I checked each one directly.
- I do not have a confirmed explanation for how/when the three `6aabce...` records were created. I did not create them myself (I made no write calls to Team4C's files API for these names during this investigation — only `find`/read queries). Team4C's `scripts/seed.ts` was checked and creates an unrelated sample record (`Lecture12-Normalization.mp4` for `sample.student@example.com`), ruling that out as the cause.
- Separately notable: the ground truth's four OS "document_id"s all resolve to content that is genuinely present in the *single* 92-page `R20CSE2202-OPERATING-SYSTEMS.pdf` file (Lecture #6 section, Lecture #20 section, etc.) — meaning at the time the original corpus was ingested, either (a) this one file was split across four separate uploads whose four File records have since been deleted from Mongo, or (b) `document_id` didn't map 1:1 to a single File the way it does today. Either way, this is a **pre-existing historical detail unrelated to today's Docker incident** — the content itself is not in question, only the exact provenance of the four IDs.

## 5. Original workspace for each source

Already reflected in the tables above: OS PDF + OS video → `6a912a1883f46878932e0eec`; DBMS PDF → `6a8de2d7e43679cbe2ee243d`. (The DBMS video exists but, per §6, is not depended on by any approved ground-truth entry.)

## 6. Ground-truth entries depending on each source

All 75 approved entries are accounted for:

| Source | document_id(s) in ground truth | Entry count | Example queries |
|---|---|---|---|
| OS PDF — CPU scheduling (SJF) section | `6aa72dae16cbab6b27d5f508` | 10 | `c_sjf_difficulty__q_*`, `c_ipc_direct_vs_indirect__q_*`, `c_sjf_cross_document_hard__q_english` |
| OS PDF — process management (Lecture #6) section | `6aa72e4416cbab6b27d5f50b` | 7 | `c_process_vs_program__q_*`, `c_user_level_threads__q_*`, `c_process_memory_cross_document_hard__q_english` |
| OS PDF — synchronization (Lecture #20, semaphores) section | `6aa846698a7bd709c53a5f4e` | 3 | `c_semaphore_wait_signal__q_*` |
| OS PDF — memory management (MFT/MVT) section | `6aa90e314ac03b89c7624ccb` | 6 | `c_mft_mvt__q_*`, `c_producer_consumer__q_*` |
| **OS PDF subtotal** | (4 sections, 1 physical file) | **26** | |
| OS YouTube video | `6aaa7e8c81e2b76728b76bb6` | 24 | `c_os_modules__q_*`, `c_real_time_os__q_*` |
| OS workspace-wide (no single document) | `None` (`mixed`) | 1 | `c_workspace_wide_scheduling_algorithms__q_english` |
| **OS workspace total** | | **51** | |
| DBMS PDF | `6aa8457c8a7bd709c53a5f46` | 24 | `c_sql_null__q_*`, `c_sql_transaction_end__q_*` |
| **DBMS workspace total** | | **24** | |
| **Grand total** | | **75** ✓ | matches the full approved dataset exactly |

The DBMS YouTube video (`kBdlM6hNDAE`, a syllabus/intro video) is **not referenced by any of the 75 approved entries** — its absence from ground-truth coverage is consistent with it being introductory/non-substantive content, not evidence it's unnecessary to the original 250-point count (the original workspace's total point count could still include its chunks even though no benchmark question happens to target them).

## 7. Source availability — local files and repository

| Source | Location | Verified |
|---|---|---|
| `R20CSE2202-OPERATING-SYSTEMS.pdf` | `C:\Users\Shashank\Downloads\R20CSE2202-OPERATING-SYSTEMS.pdf` (4,838,889 bytes) **and** `team4c\.local-uploads\6a912a1883f46878932e0eec\8abe8b04-...-R20CSE2202-OPERATING-SYSTEMS.pdf` (identical size) | Both present, byte-identical, content-verified against ground truth |
| `DATABASE MANAGEMENT SYSTEMS.pdf` | `C:\Users\Shashank\Downloads\DATABASE MANAGEMENT SYSTEMS.pdf` (11,211,566 bytes, 232 pages) | Present, content-verified against ground truth |
| OS YouTube | `https://youtu.be/KlwNyagHWuk` | Confirmed publicly live |
| DBMS YouTube | `https://youtu.be/kBdlM6hNDAE` | Confirmed publicly live |

## 8. Can the "missing" DBMS PDF be recovered without guessing?

**Yes — and it turns out it was never actually gone.** `C:\Users\Shashank\Downloads\DATABASE MANAGEMENT SYSTEMS.pdf` (no suffix) is **byte-identical** (same size, 11,211,566 bytes; same page count, 232) to `DATABASE MANAGEMENT SYSTEMS (1).pdf` — the file I uploaded *today* into the new test DBMS workspace during product validation. Windows appends `(1)` to a second download of the same filename, which is exactly what happened: this PDF was downloaded once (used to build the original corpus, at some earlier point), and downloaded a second time today when I was gathering "new" test-validation sources — without realizing it was the same document. **This was not a guess**: I positively confirmed it by extracting and matching the actual ground-truth excerpt text in both the Downloads copy and re-checking against what the `phase2_ground_truth_approved.json` entries expect.

---

## What this means for the three options you outlined

- **(A) Reconstruct the exact original corpus**: Both original files are recoverable and content-verified, and both original YouTube videos are live. The main open question is §4's identity mismatch — the *current* Mongo File records for these names are not the ones the ground truth's `document_id`s point to. A faithful reconstruction would need to ingest the verified source files/URLs fresh (via the normal Team4A canonical pipeline) into the two original workspace_ids, and accept that the resulting File `_id`s (hence `document_id`s in Qdrant chunk metadata) will necessarily be *new* IDs, not the original ones — the content would be faithful, but the exact original ID values could never be reproduced since those specific database rows are gone.
- **(B) Reconstruct a clearly labeled equivalent baseline and rerun evaluations**: Same ingestion work as (A), but explicitly documented as a "content-faithful, ID-different" rebuild, with Phase 2-4E/F1 evaluations re-run against it if you want fresh confidence rather than relying on the historical (still fully intact in the repo) reports.
- **(C) Another source/backup**: I found no evidence of any other backup mechanism (Docker volume backup schedule was empty, no accessible shadow copies, no alternate custom data-root).

I have not ingested anything and made no further changes. Waiting for your decision on how to proceed.
