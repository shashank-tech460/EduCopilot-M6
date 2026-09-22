# M6 Documentation Cleanup Recommendation

**Date:** 2026-09-22
**Type:** Read-only audit and recommendation only. No file was created,
deleted, moved, renamed, or edited as part of this task other than this
report. No commit or push was made.
**Scope:** `README.md`, `infra/README.md`, and every file under `docs/`
(31 Markdown files + 1 JSON manifest), with a brief inventory note on
documentation found outside those locations.

## 1. Executive summary

The repository's `docs/` folder contains **32 files**: 17 current
authoritative documents (clean, cross-linked, verified accurate in prior
audits), 2 sequential real audit-trail reports of actual repository
actions, 3 substantive Team4B-specific technical references, and **10
files that are internal development-history artifacts** — one-off
incident investigations tied to a single resolved Docker-volume-loss
event, superseded pre-consolidation status snapshots, and intermediate
"final" development-session reports whose substantive conclusions are
already folded into the current authoritative docs. None of the 10
REMOVE candidates is referenced by `README.md` or by any of the 17
current authoritative documents — every reference to them originates
from other historical/internal reports, confirmed by a repository-wide
search (§8). Two pairs of documents were investigated for duplication;
neither is a true duplicate needing consolidation, though one pair
(`M6_GITHUB_RELEASE_READINESS.md` / `M6_PRE_GITHUB_FINAL_CHECK.md`) is
flagged as a near-term consolidation candidate for a future release
cycle (§6).

**No file should be deleted as a result of this report alone** — this is
a recommendation only, per the task's explicit instruction.

## 2. Current documentation inventory

| Location | File | Size |
|---|---|---|
| root | `README.md` | 11.5 KB |
| `infra/` | `README.md` | 236 B |
| `docs/` | `ARCHITECTURE.md` | 9.5 KB |
| `docs/` | `CHANGELOG.md` | 5.4 KB |
| `docs/` | `DEVELOPER_HANDOFF.md` | 12.6 KB |
| `docs/` | `EDUCOPILOT_MASTER_HANDOFF.md` | 25.9 KB |
| `docs/` | `ENVIRONMENT.md` | 7.7 KB |
| `docs/` | `INTEGRATION.md` | 7.6 KB |
| `docs/` | `KNOWN_LIMITATIONS.md` | 5.3 KB |
| `docs/` | `LIMITATIONS.md` | 4.8 KB |
| `docs/` | `M6-LOCAL-ENV.md` | 7.2 KB |
| `docs/` | `M6-LOCAL-INTEGRATION-FINAL.md` | 12.0 KB |
| `docs/` | `M6_FINAL_DOCUMENTATION_AUDIT.md` | 20.3 KB |
| `docs/` | `M6_FINAL_POLISH_AND_DOCS_REPORT.md` | 15.9 KB |
| `docs/` | `M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md` | 12.8 KB |
| `docs/` | `M6_GITHUB_RELEASE_READINESS.md` | 14.2 KB |
| `docs/` | `M6_PRE_GITHUB_FINAL_CHECK.md` | 10.3 KB |
| `docs/` | `M6_REPOSITORY_CLEANUP_AUDIT.md` | 32.4 KB |
| `docs/` | `M6_STATUS.md` | 6.0 KB |
| `docs/` | `PROJECT_OVERVIEW.md` | 5.3 KB |
| `docs/` | `PROJECT_QA.md` | 34.2 KB |
| `docs/` | `RAG_ARCHITECTURE.md` | 7.9 KB |
| `docs/` | `RAG_VALIDATION.md` | 10.2 KB |
| `docs/` | `REPOSITORY_CLEANUP_REPORT.md` | 14.2 KB |
| `docs/` | `ROADMAP.md` | 4.0 KB |
| `docs/` | `SECURITY.md` | 7.2 KB |
| `docs/` | `SECURITY_ARCHITECTURE.md` | 9.5 KB |
| `docs/` | `SETUP.md` | 15.2 KB |
| `docs/` | `TEAM4A.md` | 8.3 KB |
| `docs/` | `TEAM4B.md` | 8.1 KB |
| `docs/` | `TEAM4C.md` | 9.2 KB |
| `docs/` | `TESTING.md` | 8.3 KB |
| `docs/` | `TROUBLESHOOTING.md` | 9.6 KB |
| `docs/` | `m6-historical-vs-rebuilt-rag-comparison.md` | 9.1 KB |
| `docs/` | `m6-original-corpus-reconstruction-inventory.md` | 11.6 KB |
| `docs/` | `m6-os-1400-point-discrepancy-investigation.md` | 12.1 KB |
| `docs/` | `m6-product-validation-isolation-environment.md` | 5.3 KB |
| `docs/` | `m6-rebuilt-baseline-manifest.json` | 6.8 KB |

**Outside primary scope, noted for completeness (not fully classified
here):** `team4c/README.md`, `team4b/README.md`, `team4c/docs/api-contracts.md`
(explicitly labeled "PROPOSED — NOT YET CONFIRMED", a pre-integration
Phase-1 planning artifact), `team4c/docs/decisions.md` (Phase-1
architecture-planning notes), `team4b/docs/CONTRACT_DECISIONS.md` (an
approved, still-consistent Team4A↔Team4B contract record — appears
genuinely still accurate, not flagged for removal), `team4c/AGENTS.md`
and `team4c/CLAUDE.md` (auto-regenerated Next.js/Claude Code tooling
convention files, not authored project documentation — out of scope for
a documentation cleanup entirely).

## 3. KEEP — authoritative (17 files + README + infra/README)

All verified in prior audit passes this session (link integrity, content
accuracy against live source/services, no stale test/data counts as of
the last check) and confirmed to be the sole documents README.md's
navigation table presents as current:

`README.md`, `infra/README.md`, `docs/PROJECT_OVERVIEW.md`,
`docs/ARCHITECTURE.md`, `docs/TEAM4A.md`, `docs/TEAM4B.md`,
`docs/TEAM4C.md`, `docs/INTEGRATION.md`, `docs/SETUP.md`,
`docs/ENVIRONMENT.md`, `docs/TESTING.md`, `docs/TROUBLESHOOTING.md`,
`docs/PROJECT_QA.md`, `docs/DEVELOPER_HANDOFF.md`, `docs/SECURITY.md`,
`docs/LIMITATIONS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`,
`docs/M6_STATUS.md`.

## 4. KEEP — historical but useful

- **`docs/RAG_ARCHITECTURE.md`, `docs/RAG_VALIDATION.md`,
  `docs/SECURITY_ARCHITECTURE.md`, `docs/KNOWN_LIMITATIONS.md`** —
  Team4B's own frozen, evidence-backed technical decision records
  (rejected retrieval alternatives with real evaluation data, the
  phase-by-phase RAG validation journey, the prompt-injection threat
  model with real adversarial-testing numbers, and detailed
  retrieval/generation limitations). Heavily and correctly cross-linked
  from `README.md`, `SECURITY.md`, `LIMITATIONS.md`, `TEAM4B.md`,
  `ARCHITECTURE.md`, `M6_STATUS.md`, `PROJECT_QA.md`, and `SETUP.md` —
  load-bearing, not clutter.
- **`docs/REPOSITORY_CLEANUP_REPORT.md`** — a real audit-trail record of
  an actual repository action (the first RAG-accepted git checkpoint,
  commit/tag/push, and secrets/inventory audit). **Directly referenced
  by `README.md`** to explain why the gitignored backup/duplicate
  directories exist rather than being deleted — removing this file would
  break that explanation.
- **`docs/M6_REPOSITORY_CLEANUP_AUDIT.md`** — the earlier, foundational
  cleanup audit (pre-git-init) that actually deleted 18 confirmed
  one-off/backup files and established the current backup-directory
  policy. Not directly linked from README, but **is a direct dependency
  of `REPOSITORY_CLEANUP_REPORT.md`** (§1 of that report: "A previous,
  thorough cleanup audit already exists... This report builds on that
  audit rather than repeating it"), which *is* linked from README.
  Removing it would leave a dangling reference inside a document README
  depends on. Recommend keeping.
- **`docs/m6-product-validation-isolation-environment.md`** — explains
  why the gitignored `team4c-validation/` directory and the
  non-frozen `educopilot_chunks_product_validation` Qdrant collection
  exist (a deliberate, disposable parallel-instance design for
  product-level validation without risking the frozen canonical corpus).
  This is the only document that explains two artifacts a curious
  developer would otherwise find unexplained (an ignored directory, a
  second Qdrant collection referenced in `TESTING.md`/`README.md`).
  Recommend keeping.

## 5. REMOVE — historical/internal clutter (10 files)

All 10 are real, honest records of real work — none are being
characterized as low-quality — but none are necessary for a developer,
evaluator, or maintainer of the *final* M6 product, and each is either
fully superseded by a current authoritative document or tied to a single
resolved internal incident with no ongoing relevance.

1. **`docs/m6-historical-vs-rebuilt-rag-comparison.md`**,
   **`docs/m6-original-corpus-reconstruction-inventory.md`**,
   **`docs/m6-os-1400-point-discrepancy-investigation.md`**,
   **`docs/m6-rebuilt-baseline-manifest.json`** — a forensic-investigation
   quartet tied to one specific, resolved incident (an accidental Docker
   Desktop factory reset that deleted the Qdrant data volume on
   2026-09-17, followed by corpus reconstruction). Their conclusion — the
   canonical collection was rebuilt at 542 points and is now the
   permanent frozen baseline — is already the single fact that matters
   going forward, and it is already stated as current, authoritative fact
   in `docs/TESTING.md`, `docs/RAG_ARCHITECTURE.md`, and `docs/M6_STATUS.md`.
   The investigation detail itself (which specific PDF bytes were
   recovered, exact point-count arithmetic per workspace) has no
   forward-looking value once the corpus is already accepted as frozen.
2. **`docs/EDUCOPILOT_MASTER_HANDOFF.md`** — a large, early
   engineering-planning document. Its own banner already admits it is
   "badly stale," and inspection confirms why: it contains a 12-phase
   speculative roadmap that does not match what was actually built, a
   "Team4C Status" section that incorrectly states product integration
   "has not started" (it is complete), and sections that are literally
   meta-instructions to an AI coding assistant ("Claude Code Protocol,"
   "Golden Rule," "Immediate Next Action") rather than developer-facing
   documentation — inappropriate and confusing in a professional,
   public-facing repository. Its one disclosed remaining value — early
   RAG-design rationale in sections 10–20 — is a phase-by-phase account
   (Phase 1 BM25, Phase 2 multilingual embedding evaluation, etc.) that
   is **already fully and more accurately captured** in
   `docs/RAG_VALIDATION.md` (the same phases, as actually completed) and
   `docs/RAG_ARCHITECTURE.md` (the same rejected-alternatives rationale,
   in its final, correct form).
3. **`docs/M6-LOCAL-ENV.md`**, **`docs/M6-LOCAL-INTEGRATION-FINAL.md`** —
   already banner-marked SUPERSEDED in a prior pass. Their exact
   environment values and integration-blocker findings from their
   respective points in time are fully superseded by `docs/ENVIRONMENT.md`
   (current, generic variable reference) and the current, green,
   live-verified test suite. No unique current-relevance information
   remains.
4. **`docs/M6_FINAL_DOCUMENTATION_AUDIT.md`**,
   **`docs/M6_FINAL_POLISH_AND_DOCS_REPORT.md`**,
   **`docs/M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md`** — three sequential
   intermediate development-session "final" reports, each already
   banner-marked historical. Matches the task's own listed REMOVE
   example ("intermediate UI/documentation audit reports") precisely.
   Their substantive, still-relevant conclusions have already been
   folded into current authoritative documents: the CSS `mask-image`
   root-cause narrative and fix are condensed into `docs/CHANGELOG.md`'s
   "UI/UX and accessibility" section; the documentation-consolidation
   methodology and resulting document set are the current `docs/`
   structure itself; test baselines are in `docs/TESTING.md`. Keeping
   three near-identically-named "final" reports (plus the two genuinely
   final release-readiness reports below) is itself a source of the
   clutter and naming confusion this audit was asked to find.

## 6. CONSOLIDATE — duplicate/overlapping

**`docs/DEVELOPER_HANDOFF.md` vs. `docs/EDUCOPILOT_MASTER_HANDOFF.md`**:
**not a true duplicate** — they serve different purposes.
`DEVELOPER_HANDOFF.md` is the current, accurate, structured onboarding
document (ZIP path, GitHub-clone path, what to read first, what not to
modify casually). `EDUCOPILOT_MASTER_HANDOFF.md` is an early internal
engineering/planning log, now stale (see §5.2). **Recommend:
`DEVELOPER_HANDOFF.md` remains the sole authoritative handoff document.**
No merge needed — `EDUCOPILOT_MASTER_HANDOFF.md`'s remaining archival
value is redundant with `RAG_ARCHITECTURE.md`/`RAG_VALIDATION.md`, so
there is nothing left to fold in.

**`docs/LIMITATIONS.md` vs. `docs/KNOWN_LIMITATIONS.md`**: **not a
duplicate** — already correctly structured as authoritative-summary +
detailed-evidence pair. `LIMITATIONS.md` explicitly states in its own
opening line: "For Team4B's retrieval/generation limitations
specifically, with full evidence citations, see
[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) — not duplicated here in
full detail, only summarized," and every limitation it lists that
overlaps with Team4B's domain links out rather than repeating.
**Recommend: keep both, no change** — this is the correct pattern, not a
problem.

**`docs/M6_GITHUB_RELEASE_READINESS.md` vs. `docs/M6_PRE_GITHUB_FINAL_CHECK.md`**
(both created this session, minutes apart): these have genuinely
different declared scope — the first is the comprehensive 16-section
release audit (repo cleanliness, secrets, `.gitignore`, README,
links, setup, ZIP/clone, Q&A, doc status, root content, tests, build,
accessibility, data safety, git status, final recommendation); the
second is a narrower, targeted documentation-consistency re-check run
immediately before the actual commit. They are not literal duplicates,
but **they do overlap substantially** (both re-run the same test suite
and restate largely the same secret/`.gitignore`/data-safety findings).
**Recommend for a future cleanup pass** (not this one, since the task
instructs no modification now): once the release they document is no
longer the *current* release, consolidate both into a single dated
`docs/RELEASE_AUDIT_<version>.md` per release, rather than accumulating
a new pair of overlapping audit reports on every release cycle.

**`docs/M6_REPOSITORY_CLEANUP_AUDIT.md` vs. `docs/REPOSITORY_CLEANUP_REPORT.md`**:
investigated and found **not duplicative** — the second explicitly
states it "builds on [the first] rather than repeating it." Both KEEP
(§4).

## 7. Final recommended documentation structure

```
README.md                                    — entry point, navigation, quick start

docs/
├── Essential (current authoritative — 17 files)
│   ├── PROJECT_OVERVIEW.md, ARCHITECTURE.md
│   ├── TEAM4A.md, TEAM4B.md, TEAM4C.md, INTEGRATION.md
│   ├── SETUP.md, ENVIRONMENT.md
│   ├── TESTING.md, TROUBLESHOOTING.md
│   ├── PROJECT_QA.md, DEVELOPER_HANDOFF.md
│   ├── SECURITY.md, LIMITATIONS.md
│   ├── ROADMAP.md, CHANGELOG.md, M6_STATUS.md
│
├── Optional historical (real technical/audit evidence, kept)
│   ├── RAG_ARCHITECTURE.md, RAG_VALIDATION.md
│   ├── SECURITY_ARCHITECTURE.md, KNOWN_LIMITATIONS.md
│   ├── REPOSITORY_CLEANUP_REPORT.md, M6_REPOSITORY_CLEANUP_AUDIT.md
│   ├── m6-product-validation-isolation-environment.md
│   └── M6_GITHUB_RELEASE_READINESS.md, M6_PRE_GITHUB_FINAL_CHECK.md
│       (this release's audit trail — candidates for future
│        per-release consolidation, see §6)
│
└── Internal development artifacts (recommended for removal from the
    current tree — see §5 for the full list and rationale)
    ├── EDUCOPILOT_MASTER_HANDOFF.md
    ├── M6-LOCAL-ENV.md, M6-LOCAL-INTEGRATION-FINAL.md
    ├── M6_FINAL_DOCUMENTATION_AUDIT.md
    ├── M6_FINAL_POLISH_AND_DOCS_REPORT.md
    ├── M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md
    ├── m6-historical-vs-rebuilt-rag-comparison.md
    ├── m6-original-corpus-reconstruction-inventory.md
    ├── m6-os-1400-point-discrepancy-investigation.md
    └── m6-rebuilt-baseline-manifest.json
```

This structure is readable end-to-end by: a new developer cloning the
repo (README → SETUP → DEVELOPER_HANDOFF), a college evaluator/professor
(README → PROJECT_OVERVIEW → PROJECT_QA), a technical reviewer
(ARCHITECTURE → TEAM4A/B/C → INTEGRATION → SECURITY), a future
maintainer (TROUBLESHOOTING → LIMITATIONS → ROADMAP), and someone
assessing deployability (SETUP → ENVIRONMENT → LIMITATIONS' "local,
single-machine infrastructure" item → ROADMAP) — without wading through
10 internal, single-incident, or superseded documents first.

## 8. Dependency/reference checks

A repository-wide search (`grep` across `README.md` and every
`docs/*.md`) was run for the filename of every REMOVE candidate. Result
for all 10 files: **every reference to each REMOVE candidate originates
exclusively from other historical/internal reports** (mostly the REMOVE
candidates referencing each other, plus the 5 development-session
reports created across this engagement referencing them as their own
prior-work citations). **Zero references from `README.md` or from any of
the 17 current authoritative documents.** Full detail:

| REMOVE candidate | Referenced only by |
|---|---|
| `EDUCOPILOT_MASTER_HANDOFF.md` | `M6_FINAL_DOCUMENTATION_AUDIT.md`, `M6_FINAL_POLISH_AND_DOCS_REPORT.md`, `M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md`, `M6_GITHUB_RELEASE_READINESS.md`, `M6_REPOSITORY_CLEANUP_AUDIT.md`, `REPOSITORY_CLEANUP_REPORT.md` (all historical) |
| `m6-historical-vs-rebuilt-rag-comparison.md` | `M6_FINAL_DOCUMENTATION_AUDIT.md`, `M6_FINAL_POLISH_AND_DOCS_REPORT.md`, `REPOSITORY_CLEANUP_REPORT.md` (all historical) |
| `m6-original-corpus-reconstruction-inventory.md` | same + its own sibling `m6-historical-vs-rebuilt-rag-comparison.md` (all historical) |
| `m6-os-1400-point-discrepancy-investigation.md` | same set (all historical) |
| `m6-rebuilt-baseline-manifest.json` | `REPOSITORY_CLEANUP_REPORT.md` and its two sibling `m6-*.md` files (all historical) |
| `M6-LOCAL-ENV.md` | `M6-LOCAL-INTEGRATION-FINAL.md` + the 5 development-session reports (all historical) |
| `M6-LOCAL-INTEGRATION-FINAL.md` | the 5 development-session reports (all historical) |
| `M6_FINAL_DOCUMENTATION_AUDIT.md` | `M6_GITHUB_RELEASE_READINESS.md`, `M6_PRE_GITHUB_FINAL_CHECK.md` (both historical/audit-trail) |
| `M6_FINAL_POLISH_AND_DOCS_REPORT.md` | same set |
| `M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md` | same set |

No setup instruction, no README link, and no GitHub navigation path
depends on any of these 10 files.

## 9. Files that should NOT be deleted

All 17 authoritative documents (§3), all 4 documents in §4 (KEEP —
historical but useful), and both release-audit reports created this
session (§6, pending future consolidation, not removal). In particular:
`docs/REPOSITORY_CLEANUP_REPORT.md` and `docs/M6_REPOSITORY_CLEANUP_AUDIT.md`
must not be removed — README depends on the former, which in turn
depends on the latter.

## 10. Files that are safe candidates for removal

The 10 files listed in §5, in full:

1. `docs/EDUCOPILOT_MASTER_HANDOFF.md`
2. `docs/M6-LOCAL-ENV.md`
3. `docs/M6-LOCAL-INTEGRATION-FINAL.md`
4. `docs/M6_FINAL_DOCUMENTATION_AUDIT.md`
5. `docs/M6_FINAL_POLISH_AND_DOCS_REPORT.md`
6. `docs/M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md`
7. `docs/m6-historical-vs-rebuilt-rag-comparison.md`
8. `docs/m6-original-corpus-reconstruction-inventory.md`
9. `docs/m6-os-1400-point-discrepancy-investigation.md`
10. `docs/m6-rebuilt-baseline-manifest.json`

## 11. Explanation of why each removal candidate is unnecessary

See §5 for the full, file-by-file rationale. In one line each:

- The 4 incident-forensics files: tied to one resolved, one-time data-loss
  incident; their conclusion (542-point frozen baseline) is already
  stated as current fact elsewhere.
- `EDUCOPILOT_MASTER_HANDOFF.md`: contains stale/incorrect status claims
  and AI-agent-internal meta-instructions unsuited for a public repo;
  its valid archival content is redundant with `RAG_ARCHITECTURE.md`/
  `RAG_VALIDATION.md`.
- `M6-LOCAL-ENV.md`/`M6-LOCAL-INTEGRATION-FINAL.md`: already
  self-declared superseded; fully replaced by `ENVIRONMENT.md` and the
  current, passing test suite.
- The 3 "final" development-session reports: intermediate progress
  reports whose conclusions are already folded into `CHANGELOG.md`,
  `TESTING.md`, and the current `docs/` structure itself.

## 12. Statement confirming Git history will remain intact

**Removing any of these 10 files from the current working tree, if the
user later chooses to act on this recommendation, would not erase them
from Git history.** They were committed in `e151128` (already pushed to
`origin/phase5-cross-script-retrieval`); a future `git rm` and commit
would only stop tracking them going forward — every prior version
remains fully retrievable via `git log`, `git show`, and `git checkout
<commit> -- <path>` for as long as the repository and its history exist.
This report does not use, and does not recommend using, `git
filter-repo`, `git filter-branch`, `git rebase`, `git reset --hard`, or
any force-push. **No file was deleted, moved, renamed, or modified as
part of producing this report. No commit or push was made.**

## 13. Classification table

| FILE | CATEGORY | RECOMMENDATION | REASON |
|---|---|---|---|
| README.md | A | KEEP | Entry point/navigation, verified accurate |
| infra/README.md | A | KEEP | Explains intentionally minimal infra/ directory |
| docs/PROJECT_OVERVIEW.md | A | KEEP | Current authoritative product explanation |
| docs/ARCHITECTURE.md | A | KEEP | Current authoritative technical architecture |
| docs/TEAM4A.md | A | KEEP | Current authoritative service doc |
| docs/TEAM4B.md | A | KEEP | Current authoritative service doc |
| docs/TEAM4C.md | A | KEEP | Current authoritative service doc |
| docs/INTEGRATION.md | A | KEEP | Current authoritative cross-service contracts |
| docs/SETUP.md | A | KEEP | Current authoritative install/startup walkthrough |
| docs/ENVIRONMENT.md | A | KEEP | Current authoritative env-var reference |
| docs/TESTING.md | A | KEEP | Current authoritative test strategy/baselines |
| docs/TROUBLESHOOTING.md | A | KEEP | Current authoritative diagnostics |
| docs/PROJECT_QA.md | A | KEEP | Current authoritative full Q&A reference |
| docs/DEVELOPER_HANDOFF.md | A | KEEP | Current authoritative ZIP/GitHub onboarding |
| docs/SECURITY.md | A | KEEP | Current authoritative security model |
| docs/LIMITATIONS.md | A | KEEP | Current authoritative limitations (3-way split) |
| docs/ROADMAP.md | A | KEEP | Current authoritative future work |
| docs/CHANGELOG.md | A | KEEP | Current authoritative milestone log |
| docs/M6_STATUS.md | A | KEEP | Current authoritative status |
| docs/RAG_ARCHITECTURE.md | B | KEEP | Frozen RAG pipeline + rejected alternatives, heavily linked |
| docs/RAG_VALIDATION.md | B | KEEP | Phase-by-phase RAG validation evidence, heavily linked |
| docs/SECURITY_ARCHITECTURE.md | B | KEEP | Prompt-injection threat model with real evidence, heavily linked |
| docs/KNOWN_LIMITATIONS.md | B | KEEP | Team4B's detailed evidence-backed limitations, linked from LIMITATIONS.md |
| docs/REPOSITORY_CLEANUP_REPORT.md | B | KEEP | Directly linked from README.md; real audit trail |
| docs/M6_REPOSITORY_CLEANUP_AUDIT.md | B | KEEP | Dependency of REPOSITORY_CLEANUP_REPORT.md; documents real deletions |
| docs/m6-product-validation-isolation-environment.md | B | KEEP | Explains currently-visible ignored dir + non-frozen collection |
| docs/M6_GITHUB_RELEASE_READINESS.md | E | KEEP (flag for future consolidation) | Real pre-commit release evidence; overlaps with next row |
| docs/M6_PRE_GITHUB_FINAL_CHECK.md | E | KEEP (flag for future consolidation) | Real pre-commit release evidence; overlaps with prior row |
| docs/EDUCOPILOT_MASTER_HANDOFF.md | C | REMOVE | Stale/incorrect status claims, AI-meta-instructions, redundant archival value |
| docs/M6-LOCAL-ENV.md | C | REMOVE | Self-declared superseded; replaced by ENVIRONMENT.md |
| docs/M6-LOCAL-INTEGRATION-FINAL.md | C | REMOVE | Self-declared superseded; replaced by current test suite |
| docs/M6_FINAL_DOCUMENTATION_AUDIT.md | C | REMOVE | Intermediate audit report; superseded by later release audits |
| docs/M6_FINAL_POLISH_AND_DOCS_REPORT.md | C | REMOVE | Intermediate progress report; content folded into CHANGELOG.md |
| docs/M6_FINAL_UI_AND_DOCS_REWORK_REPORT.md | C | REMOVE | Intermediate progress report; bug narrative folded into CHANGELOG.md |
| docs/m6-historical-vs-rebuilt-rag-comparison.md | C | REMOVE | One-off incident forensics, conclusion already stated as current fact |
| docs/m6-original-corpus-reconstruction-inventory.md | C | REMOVE | One-off incident forensics, no forward-looking value |
| docs/m6-os-1400-point-discrepancy-investigation.md | C | REMOVE | One-off incident forensics, no forward-looking value |
| docs/m6-rebuilt-baseline-manifest.json | C | REMOVE | Machine-readable companion to the incident-forensics trio |
| docs/DEVELOPER_HANDOFF.md vs. EDUCOPILOT_MASTER_HANDOFF.md | D | Keep DEVELOPER_HANDOFF.md only | Not true duplicates; master handoff is stale, redundant with B-category docs |
| docs/LIMITATIONS.md vs. KNOWN_LIMITATIONS.md | D | Keep both, no change | Correctly structured summary + detailed-evidence pair, already cross-linked |
