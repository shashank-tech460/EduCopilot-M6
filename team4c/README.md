# Educational Intelligence Copilot — Team C

**Application State & Chat UI** module of Project 4: Multi-Modal Educational Intelligence Copilot.

This app is the student-facing layer: authentication, a workspace/learning
dashboard, PDF/YouTube material upload, a streaming AI Tutor chat with
grounded, cited answers, and a video player that jumps to the exact cited
timestamp. It consumes Team A's ingestion pipeline and Team B's RAG/query API —
it does not implement either.

Full architecture, database design, and API contracts: see [`docs/decisions.md`](./docs/decisions.md)
and [`docs/api-contracts.md`](./docs/api-contracts.md). Product-level
documentation (setup, environment, testing, integration with Team A/B):
see the repository root's [`../docs/`](../docs/) — start with
[`../docs/TEAM4C.md`](../docs/TEAM4C.md).

## Technology Stack

| Layer | Technology |
|---|---|
| Framework | Next.js (App Router), React, TypeScript |
| Styling | Tailwind CSS, shadcn/ui, lucide-react |
| AI / Chat | Vercel AI SDK |
| Database | MongoDB, Mongoose |
| Auth | Auth.js — Credentials provider |
| File storage | Local-storage development mock by default; a real object storage provider can be configured via `STORAGE_PROVIDER` |
| Video | react-player |
| State | React state by default, Zustand for cross-component state |
| Testing | Vitest, React Testing Library, Playwright |
| Deployment | Vercel |

## Project Status

Authentication, database connectivity, workspace/material management, the
streaming AI Tutor chat, citations, and video sync are all implemented and
tested — see [`../docs/TEAM4C.md`](../docs/TEAM4C.md) and
[`../docs/TESTING.md`](../docs/TESTING.md) for current detail.
`docs/decisions.md` records the original phased build plan and the
architectural decisions made along the way — read it for *why* things are
built the way they are, not as a live status tracker.

## Local Setup

```bash
npm install
cp .env.example .env.local   # then fill in real values as later phases require them
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Available Commands

| Command | Purpose |
|---|---|
| `npm run dev` | Start the local development server |
| `npm run build` | Production build |
| `npm run start` | Run the production build locally |
| `npm run lint` | Run ESLint |
| `npm test` | Run unit + component tests once (Vitest) |
| `npm run test:watch` | Run tests in watch mode |
| `npm run test:e2e` | Run Playwright end-to-end tests (builds and serves the app first) |

## Folder Structure

```
app/            Routes: (auth), (dashboard), api/
components/     ui/ (shadcn primitives), shared/ (app components)
lib/            DB connection, auth config, ownership checks, utilities
models/         Mongoose schemas
services/       Team A / Team B clients — each has client.ts (real),
                mock.ts, and index.ts (env-flag swap between them)
hooks/          Custom React hooks
types/          Shared TypeScript types, incl. Team A/B contract shapes
store/          Zustand stores (kept minimal)
tests/          unit/, component/ (Vitest + RTL), e2e/ (Playwright)
scripts/        Local dev scripts (e.g. DB seeding)
docs/           Architecture decisions and API contracts
```

## Team Boundaries

- **Team A** owns ingestion (PDF/video/YouTube processing, embeddings). This app only sends a file reference and reads back a status.
- **Team B** owns RAG/retrieval/generation. This app only sends a question and renders the streamed answer + citations it returns.
- **Team C (this repo)** owns everything else: dashboard, auth, uploads, chat UI, video sync, and the application's own database.
