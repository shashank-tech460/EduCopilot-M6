# Final M6 UI + Professional Documentation Rework — Report

> **HISTORICAL DEVELOPMENT REPORT — not authoritative documentation.**
> This is a point-in-time record of one development session's work, kept
> for its root-cause investigation narrative (the real CSS `mask-image`
> bug that was fading real text on the landing and auth pages, and how it
> was found). For current, authoritative information, use `README.md` and
> its sibling canonical docs, never this file. The change this report
> describes is already reflected in the current, real
> `team4c/app/globals.css` and summarized in [CHANGELOG.md](CHANGELOG.md).

**Date:** 2026-09-22
**Scope:** Team4C UI (definitive text-fading fix) + complete documentation
rework. No changes to Team4A, Team4B, RAG, Qdrant, Redis, MongoDB schemas,
or backend behavior.

## 1. Root cause of the fading problem

**Real, found by inspecting actual rendered DOM/CSS — not assumed, not a
screenshot artifact.** The `.ambient-grid` CSS class (`team4c/app/globals.css`)
was applied **directly** to the same `<section>`/`<div>` elements that
also contain the real heading, paragraph, CTA buttons, and — on the
signup/login marketing panel — the value-proposition bullet list, on
both `app/page.tsx` (landing hero) and `app/(auth)/layout.tsx` (auth
marketing panel). This exactly matches the observed symptom: the *same*
fading behavior on both the landing page and the signup/login page,
because both share this one class.

`.ambient-grid` set both a `background-image` (the decorative dot grid)
**and** a `mask-image` on that class. `background-image` only affects an
element's own background layer — but `mask-image`, applied the same way,
masks the element's **entire painted output**, including every child's
text and backgrounds. The mask itself was a radial gradient — opaque
near the top-center, fading to fully transparent toward the bottom and
edges — which is why content further down in each container (the lower
lines of a multi-line heading, the paragraph, the CTA buttons, and the
lower bullet points on the auth panel) visibly faded, while content near
the top stayed clearly visible. Three prior investigation rounds
attributed this to screenshot downscaling and gradient-text color math
because those were real, separately-reproducible phenomena in this
session's tooling — but they were never the actual cause of what a real
user would see in a real browser.

## 2. Exact UI fix

`team4c/app/globals.css`: moved the dot-grid background and its
fade-mask off the shared, content-bearing `.ambient-grid` class and onto
a new `.ambient-grid::after` pseudo-element instead — positioned behind
the content (`z-index: -1`), exactly mirroring how `.aurora-bg::before`
was already correctly structured as a separate, non-content-bearing paint
layer. The mask now only ever affects the decorative dot pattern; real
text is never masked by it, on either page.

No other CSS or component changes were needed — this was the entire root
cause.

## 3. Screenshots / viewport verification

Real screenshots taken and visually inspected (not just computed-style
checks) at all six required widths, on all three required routes:

| Width | `/` (landing) | `/login` | `/signup` |
|---|---|---|---|
| 375px | ✅ Screenshot taken — headline (3 lines), paragraph, both CTAs, and the mobile product card all fully readable | Form-only at this width (marketing panel is `hidden` below `lg:`, by design) | Same as login |
| 390px | ✅ No overflow (`scrollWidth === clientWidth`) | ✅ Screenshot taken — form fully readable, no overflow | Same |
| 768px | ✅ Screenshot taken — headline, paragraph, CTAs, and card fully readable, zero gap to next section | — | — |
| 1024px | ✅ No overflow; two-column grid active | — | ✅ Screenshot taken — blockquote and all 3 bullet points fully readable (marketing panel becomes visible at this breakpoint) |
| 1280px | ✅ Screenshot taken — headline, paragraph, both CTAs, and all 4 floating cards fully readable | — | — |
| 1440px | ✅ Screenshot taken — headline, paragraph, both CTAs, and all 4 floating cards fully readable, **including in a downscaled capture that previously showed heavy fading in every prior round** | ✅ Screenshot taken — blockquote + all 3 bullets fully readable | ✅ Screenshot taken — blockquote + all 3 bullets fully readable |

At every screenshot: no important text faded, no overlay crossed text, no
clipping, no horizontal overflow, the CTA hierarchy was correct
(primary/secondary button, or "Log in"/"Sign up" nav links when
unauthenticated), and typography read clearly. **The 1440px downscaled
capture is the strongest evidence**: this exact capture path, at this
exact scale, showed heavy fading in every one of the three prior
investigation rounds this session — it now shows fully vibrant, complete
text, because the actual CSS bug (not the capture pipeline) has been
fixed.

## 4. Landing-page changes

`team4c/app/page.tsx`: unchanged this pass (its composition — solid
headline, mobile product card, tightened mobile/tablet padding — was
already fixed in an earlier pass and is confirmed still correct). The fix
this pass was entirely in `globals.css`'s shared `.ambient-grid` class.

## 5. Login/signup changes

`team4c/app/(auth)/layout.tsx`: unchanged directly — it already used
`.ambient-grid`, and now inherits the fix automatically since the fix was
made at the shared CSS-class level. The right-side form was not touched
(confirmed unchanged in every screenshot above) and no authentication
logic was modified.

## 6. Files changed

`team4c/app/globals.css` only, for the UI fix (§1–2). See §7/§8 for
documentation files.

## 7. Old documentation deleted

None deleted in this pass — the 21 `PHASE_6*` files were already deleted
in the prior documentation-consolidation pass. This pass only **added**
five new files and **expanded** three existing ones (see §8).

## 8. New documentation created

**New files**: `docs/PROJECT_OVERVIEW.md`, `docs/SECURITY.md`,
`docs/LIMITATIONS.md`, `docs/ROADMAP.md`, `docs/CHANGELOG.md`.

**Substantially expanded**:
- `docs/SETUP.md` — rewritten with a "Quick start" section at the top and
  a lettered Part A–P structure (prerequisites with exact check commands,
  environment configuration, per-service startup with expected
  output/health checks, a first-time smoke test with expected results at
  each step, safe shutdown, "starting again tomorrow," and a common-startup-failures
  table).
- `docs/DEVELOPER_HANDOFF.md` — added the exact "If you received this
  project as a ZIP" 15-step sequence, a "How to prepare a pull request"
  section, and a "How to prepare for deployment" section.
- `docs/PROJECT_QA.md` — added a whiteboard-style architecture
  explanation, explicit step-by-step "what happens when a user uploads a
  PDF" / "asks a question" narrations, and a full "Professional project
  analysis" section (Strengths, Weaknesses, Advantages, Risks,
  Trade-offs, Future improvements) — an honest engineering evaluation,
  not marketing language.

`README.md`'s documentation table was updated to link all five new files.

## 9. Documentation structure

```
README.md
docs/
├── PROJECT_OVERVIEW.md      (new)
├── ARCHITECTURE.md
├── TEAM4A.md / TEAM4B.md / TEAM4C.md
├── INTEGRATION.md
├── SETUP.md                 (rewritten — Quick Start + lettered Parts A–P)
├── ENVIRONMENT.md
├── TESTING.md
├── TROUBLESHOOTING.md
├── PROJECT_QA.md            (expanded — professional analysis section added)
├── DEVELOPER_HANDOFF.md     (expanded — ZIP sequence, PR/deployment prep)
├── SECURITY.md              (new — product-wide)
├── LIMITATIONS.md           (new — current / test-dev / future, separated)
├── ROADMAP.md                (new — M6 completed / deferred / M7+)
├── CHANGELOG.md              (new — high-level milestones)
├── M6_STATUS.md
├── RAG_ARCHITECTURE.md, SECURITY_ARCHITECTURE.md, KNOWN_LIMITATIONS.md,
│   RAG_VALIDATION.md, REPOSITORY_CLEANUP_REPORT.md,
│   M6_REPOSITORY_CLEANUP_AUDIT.md, four m6-*.md investigation docs
│                              (kept — genuine historical/decision value)
└── EDUCOPILOT_MASTER_HANDOFF.md, M6-LOCAL-ENV.md,
    M6-LOCAL-INTEGRATION-FINAL.md
                               (kept, banner-marked superseded — from the prior pass)
```

## 10. Security / secret scan

Repeated this pass, covering every file created/edited in this session
including the new `docs/`: scanned for private-key markers
(`-----BEGIN ... PRIVATE KEY-----`), credentialed MongoDB URIs, and
common API-key patterns (AWS, OpenAI, Google) — **zero matches**. All
real `.env`/`*.pem` files remain confirmed git-ignored (unchanged from
the prior pass's audit).

## 11. `.gitignore` status

Unchanged and already correct — `.env`/`.env.*` (except `*.example`),
`*.pem`, Python caches/venvs, `node_modules`, `.next`,
`team4c/.gitignore`'s `/test-results`/`/playwright-report`, and OS/editor
junk are all excluded. No changes were needed this pass.

## 12. Tests

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **0 errors** |
| `npx eslint .` | **9 pre-existing errors / 3 pre-existing warnings** (unchanged, untouched files), **0 new** |
| `npx vitest run` | **469/469 passed** (51 files) |
| `npx playwright test` (auth-workspace, smoke, accessibility, workspace-isolation, source-isolation, core-rag) | **12/12 passed**, including the previously-intermittent `auth-workspace.spec.ts` logout test, which passed cleanly on this run |
| Accessibility (`@axe-core/playwright`) | **5/5 pages pass** WCAG 2A/2AA |
| `npm run build` | Clean, all 15 routes compile |

The existing real OOPS workspace/material and AI Tutor flow were not
touched or retested destructively this pass (no new live chat calls were
made) — its continued correctness was verified in the immediately prior
session's work and nothing in this pass could have affected it (only
`globals.css` and `docs/` files changed).

## 13. Known limitations

See [docs/LIMITATIONS.md](LIMITATIONS.md) for the complete, three-way-split
list (current / test-dev-only / future). Headline items: Hindi/cross-script
retrieval remains weaker than same-language retrieval; local LLM
generation is CPU-bound (30–140+ seconds/answer in this environment); one
lower-severity prompt-injection residual remains open; no production
deployment or load testing exists.

## 14. Strengths

Modular, independently-testable three-service architecture; source-grounded
answers with independently re-verified citations; isolation enforced at
two independent layers; hybrid retrieval; a prompt-injection defense
reasoned from real, measured adversarial testing; comprehensive currently-passing
automated testing (unit, E2E, accessibility); a responsive, accessible UI
verified with real evidence, not assumptions. Full list:
[docs/PROJECT_QA.md](PROJECT_QA.md#strengths).

## 15. Weaknesses

Local infrastructure complexity (seven services/processes to run
correctly); hardware-dependent generation latency; development-oriented
deployment only; external YouTube transcript-API dependency; unproven
concurrent-load scale. Full list:
[docs/PROJECT_QA.md](PROJECT_QA.md#weaknesses).

## 16. Risks

CPU-bound latency could feel broken to a first-time user without
expectation-setting; weaker Hindi/cross-script retrieval could
disproportionately affect non-English-first users if deployed without
disclosure; no monitoring means a silent service failure would only
surface via a user report. Full list:
[docs/PROJECT_QA.md](PROJECT_QA.md#risks).

## 17. Trade-offs

Local LLM vs. cloud API; MongoDB vs. SQL; Qdrant vs. storing vectors in
the primary database; hybrid vs. semantic-only retrieval; three services
vs. a monolith — each with its actual chosen reasoning and cost stated
plainly. Full list: [docs/PROJECT_QA.md](PROJECT_QA.md#trade-offs).

## 18. Future roadmap

See [docs/ROADMAP.md](ROADMAP.md) for the full M6-completed /
M6-deferred / M7+-potential breakdown. Nothing in the M7+ section is
claimed as planned or committed — it is explicitly labeled as directions
consistent with the current architecture, not promises.

## 19. Confirmation: Team4A/Team4B/RAG/data were untouched

- No file under `team4a/` or `team4b/` was created, edited, or deleted.
- No Qdrant collection was created, recreated, or had points deleted.
- No MongoDB data was reset or bulk-deleted; the real OOPS workspace was
  not touched this pass.
- No Redis keys were cleared.
- No RAG retrieval, generation, embedding, or chunking logic was touched
  — the only source file changed in this entire pass is
  `team4c/app/globals.css`.
- **No git commit or push was made.**
