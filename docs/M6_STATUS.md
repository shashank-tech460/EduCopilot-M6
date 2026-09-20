# M6 Status

**Last updated:** end of Phase 5L (repository cleanup/documentation
checkpoint, following Phase 5K's accepted RAG security fix).

This is the single authoritative status document for M6. If another
document (including the older `docs/EDUCOPILOT_MASTER_HANDOFF.md`, whose
roadmap sections predate Phases 5D–5K) conflicts with this one on current
status, this document is correct.

## COMPLETED

### Team4A (ingestion)
Stable throughout the entire Phase 5 RAG validation arc. Not modified by
any phase in this arc (5D–5L). PDF and YouTube ingestion, extraction,
chunking, metadata, embedding, and publishing to the canonical Qdrant
collection are all in active, working use — every retrieval phase in this
arc depended on real, live Team4A-published data.

### Team4B / RAG — validated and frozen
The generalized hybrid-retrieval + generation pipeline has been through a
multi-phase forensic validation arc (Phases 5D through 5K) covering:
grounding correctness, citation integrity, conversation faithfulness,
fresh-session honesty, out-of-scope handling, workspace/document
isolation, multilingual behavior, source-type coverage, prompt-injection
security, and performance. See `docs/RAG_VALIDATION.md` for the
phase-by-phase summary.

**Final acceptance (Phase 5J):** classification C (targeted fix
required), blocked specifically on one security gap.

**Security fix (Phase 5K):** that gap closed with a validated, generalized
output-side guard. FULL-severity prompt-injection cases: 5/31 → 0/32,
zero false-positive regressions, full Team4B regression suite unchanged
(1302 passed / 3 skipped / 1 known pre-existing failure).

**Current state: RAG-accepted / frozen.** No further retrieval,
embedding, BM25, RRF, reranker, threshold, or top_k changes are planned
without new specific evidence. See `docs/KNOWN_LIMITATIONS.md` for what
"accepted" does *not* mean (it does not mean "no limitations" — several
real, documented, bounded limitations remain and are not hidden).

### Security hardening
Phase 5F (prompt-level trust boundary) and Phase 5K (output-side guard)
are both implemented, validated, and unchanged since their respective
acceptance. One lower-severity residual (`REPRO-SPOOF-5`, prompt-scaffold
disclosure, no real secrets) remains open and is explicitly tracked, not
hidden — see `docs/SECURITY_ARCHITECTURE.md`.

### Git state (as of Phase 5L)
Repository audited for secrets, stale clutter, and duplicate/orphaned
files (Phase 5L). See `docs/REPOSITORY_CLEANUP_REPORT.md` for the exact
outcome, including whether a checkpoint commit/tag/push was completed.

## IN PROGRESS / NOT YET STARTED

### Team4C — product integration
Team4C's Next.js frontend exists, runs, and was **used as test
infrastructure** throughout the RAG validation arc (a disposable, isolated
copy — `team4c-validation/` — pointed at a separate Qdrant collection was
used for product-level RAG validation in earlier phases; see
`docs/m6-product-validation-isolation-environment.md`). However:

- Team4C was **explicitly out of scope** for every phase in the 5D–5L
  arc — no Team4C code was read, modified, or newly validated as part of
  this arc.
- Whether Team4C's own UI/UX, auth flows, and product-level features meet
  M6's acceptance bar has **not** been assessed by this arc and should
  not be assumed from anything in `docs/RAG_VALIDATION.md` or the
  `team4b/data/` reports.

**This is the next expected phase of work**, per every RAG-phase report's
own stop condition ("do not begin Team4C implementation"/"do not start
Team4C" — consistently deferred, phase after phase, until RAG was
explicitly accepted).

## PENDING

- **Final end-to-end product integration** between the (now frozen) RAG
  backend and Team4C's frontend, beyond what the disposable validation
  environment already exercised.
- **Full end-to-end product acceptance testing** (UI-driven, not
  API-driven) — everything in the RAG validation arc called
  `HybridRetriever`/`LLMGenerator`/`RAGService` directly or via Team4B's
  own API; none of it drove the product through Team4C's UI.
- **Production-readiness checks** beyond local Docker Compose — no cloud
  deployment, no production infra hardening, no load/scale testing has
  been performed or is claimed anywhere in this arc. All testing in
  Phases 5D–5K ran against local Docker services on one development
  machine.
- **Decision on the residual `REPRO-SPOOF-5` prompt-injection finding**
  by the architecture authority (accept as documented residual, or
  commission a separately-scoped fix).
- **Decision on the ingestion-trust-model question** Phase 5J/5K
  explicitly deferred (whether the current injection risk profile is
  acceptable given who can actually get content indexed) — not decided
  by Team4B alone.

## Do not conclude from this repository

- That M6 is complete. It is not — see PENDING above.
- That Hindi/cross-script retrieval is "fixed." It is not — see
  `docs/KNOWN_LIMITATIONS.md`.
- That prompt injection is eliminated. It is mitigated for one specific,
  validated pattern; one residual remains open.
- That this has been deployed anywhere beyond local development Docker
  Compose.
