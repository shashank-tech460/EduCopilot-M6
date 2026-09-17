# Educational Intelligence Copilot — Team C

**Application State & Chat UI** module of Project 4: Multi-Modal Educational Intelligence Copilot.

This app is the student-facing layer: a learning dashboard, file upload interface,
AI chat with streamed answers, and a video player that jumps to the exact cited
timestamp. It consumes Team A's ingestion pipeline and Team B's RAG/query API —
it does not implement either.

Full architecture, database design, and API contracts: see [`docs/decisions.md`](./docs/decisions.md)
and [`docs/api-contracts.md`](./docs/api-contracts.md).

## Technology Stack

| Layer | Technology |
|---|---|
| Framework | Next.js (App Router), React, TypeScript |
| Styling | Tailwind CSS, shadcn/ui, lucide-react |
| AI / Chat | Vercel AI SDK |
| Database | MongoDB Atlas, Mongoose *(wired up in Phase 3)* |
| Auth | Auth.js — Credentials provider *(wired up in Phase 4)* |
| File storage | Object storage, provider TBD *(wired up in Phase 6)* |
| Video | react-player |
| State | React state by default, Zustand for cross-component state |
| Testing | Vitest, React Testing Library, Playwright |
| Deployment | Vercel |

## Project Status

This repository is being built in controlled phases (see `docs/decisions.md` for
the full 15-phase roadmap). **Current phase: Phase 2 — project foundation.**
Authentication, database connectivity, file upload, chat, and video sync are
not implemented yet — the pages under `app/(auth)` and `app/(dashboard)` are
route placeholders only.

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
