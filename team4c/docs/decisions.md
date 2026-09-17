# Team C — Architecture Decisions

**Project:** Multi-Modal Educational Intelligence Copilot — Project 4, Team C (Application State & Chat UI)
**Phase:** 1 — Architecture & Planning (no code written)
**Status:** Approved decisions for Phase 2 onward. Anything not marked CONFIRMED below is either an internal team decision (final, ours to make) or an external dependency (Team A/B, marked separately in `api-contracts.md`).

---

## 1. System Architecture

```
                              USER (Student)
                                    |
                                    ▼
                    ┌───────────────────────────────┐
                    │   CLIENT (Browser)              │
                    │   Next.js React frontend        │
                    │   - Dashboard, Workspace pages   │
                    │   - Chat UI (Vercel AI SDK)      │
                    │   - Upload UI                     │
                    │   - Video player (react-player)   │
                    └───────────────┬───────────────────┘
                                    │  HTTPS (fetch/streaming)
                                    ▼
                    ┌───────────────────────────────┐
                    │  SERVER — Next.js Route Handlers│
                    │  (app/api/*)                     │
                    │  - Auth (Auth.js)                 │
                    │  - Ownership/authorization checks │
                    │  - Input validation (Zod)          │
                    │  - Business logic                   │
                    └───┬───────────┬───────────┬────────┘
                        │           │           │
            ┌───────────┘           │           └───────────┐
            ▼                       ▼                       ▼
   ┌─────────────────┐   ┌───────────────────┐   ┌────────────────────┐
   │  MongoDB Atlas    │   │  Object Storage     │   │  External Services  │
   │  (Mongoose)        │   │  (provider TBD)      │   │                      │
   │  - users             │   │  - Raw PDF/MP4 bytes  │   │  Team A API (ingest)│
   │  - workspaces          │   │  - Returns storageUrl  │   │  Team B API (RAG)   │
   │  - conversations         │   └───────────────────┘   └────────────────────┘
   │  - messages                 │
   │  - files (metadata only)      │
   └─────────────────┘
```

### Responsibility split

| Layer | Responsibility |
|---|---|
| **Client (browser)** | Renders UI, captures user input, manages ephemeral UI state (Zustand for cross-component state like "currently active video/timestamp"), calls Team C's own API routes only — **never calls Team A/B directly from the browser** (all external calls are server-to-server, so API keys for Team A/B are never exposed to the client) |
| **Server (Next.js Route Handlers)** | Authenticates every request, enforces ownership (a user can only touch their own workspaces/files/conversations), validates input, talks to MongoDB, talks to object storage, talks to Team A/B on the client's behalf, streams Team B's response back to the browser |
| **Database (MongoDB Atlas)** | Stores all structured metadata: users, workspaces, conversations, messages (including citations), and file *metadata* (never raw file bytes) |
| **Object storage** | Stores actual PDF/MP4 bytes; MongoDB only holds a URL/reference to it |
| **Team A (external)** | Owns ingestion: takes a file reference from Team C, extracts text/embeddings, reports processing status back |
| **Team B (external)** | Owns retrieval + generation: takes a question from Team C, returns a streamed answer with citations (file + timestamp/page) |

---

## 2. Folder Structure (final — used from Phase 2 onward)

```
project-root/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   └── signup/page.tsx
│   ├── (dashboard)/
│   │   ├── dashboard/page.tsx
│   │   └── workspace/[id]/page.tsx
│   ├── api/
│   │   ├── auth/[...nextauth]/route.ts
│   │   ├── workspaces/route.ts
│   │   ├── workspaces/[id]/route.ts
│   │   ├── workspaces/[id]/files/route.ts
│   │   ├── workspaces/[id]/conversations/route.ts
│   │   ├── conversations/[id]/messages/route.ts
│   │   ├── files/[id]/status/route.ts
│   │   └── chat/route.ts
│   ├── layout.tsx
│   └── page.tsx                    (landing page)
│
├── components/
│   ├── ui/                          shadcn/ui primitives (button, dialog, card, etc.) — generated, not hand-authored
│   └── shared/                      app-specific composed components (ChatWindow, FileUploadZone, VideoPanel, CitationChip, ConversationSidebar, ...)
│
├── lib/
│   ├── mongodb.ts                   cached DB connection singleton
│   ├── auth.ts                      Auth.js config
│   ├── ownership.ts                 assertOwnership() helper — shared authorization check
│   └── utils.ts                     small generic helpers (formatTimestamp, cn, etc.)
│
├── models/                          Mongoose schemas — one file per collection
│   ├── User.ts
│   ├── Workspace.ts
│   ├── Conversation.ts
│   ├── Message.ts
│   └── File.ts
│
├── types/                           shared TypeScript types/interfaces, including the Team A/B contract shapes (single source of truth referenced by both real and mock clients)
│   ├── teamA.ts
│   └── teamB.ts
│
├── hooks/                           custom React hooks (useVideoSeek, useFileStatusPolling, ...)
│
├── services/                        external-service clients — this is what makes the mock-to-real swap clean
│   ├── teamA/
│   │   ├── client.ts                 real Team A HTTP client (built in Phase 7)
│   │   ├── mock.ts                   mock/stub implementation (built in Phase 6)
│   │   └── index.ts                  exports whichever implementation is active, chosen by an env flag — application code imports only from here, never from client.ts/mock.ts directly
│   ├── teamB/
│   │   ├── client.ts
│   │   ├── mock.ts
│   │   └── index.ts
│   └── storage.ts                    object storage client (provider TBD)
│
├── store/                           Zustand stores (kept minimal — only true cross-component state, e.g. useActiveMediaStore)
│
├── tests/
│   ├── unit/                         Vitest — pure logic
│   ├── component/                     React Testing Library — component behavior
│   └── e2e/                           Playwright — full workflows
│
├── scripts/
│   └── seed.ts                       local dev seed data
│
├── docs/
│   ├── decisions.md                   (this file)
│   └── api-contracts.md
│
├── middleware.ts                     route protection
└── .env.local.example
```

**Design note on `services/`:** this is the one refinement beyond the original roadmap's plan of a single `lib/teamA.ts` file. Splitting each integration into `client.ts` / `mock.ts` / `index.ts` directly satisfies the roadmap's own requirement ("swap the mock for the real endpoint without rebuilding the frontend") — application code (API routes, hooks) imports only `services/teamA` and `services/teamB`, never the mock or real file directly, so switching is a one-line env flag change, not a code change. This does not alter the 15-phase plan or any phase's deliverables, only clarifies *how* the swap is implemented.

**Folders deliberately not included:** no `redux/`, no `graphql/`, no `pages/` (App Router only), no per-feature micro-folders — kept flat and predictable rather than over-engineered for a project of this scope.

---

## 3. Database Relationships

```
User
 └── Workspace  (1 user → many workspaces; workspace.userId → User._id)
       ├── File          (1 workspace → many files; file.workspaceId → Workspace._id, file.userId → User._id, denormalized for fast ownership checks)
       └── Conversation  (1 workspace → many conversations; conversation.workspaceId → Workspace._id)
             └── Message (1 conversation → many messages; message.conversationId → Conversation._id)
                    └── citations[] → reference File._id (message.citations[].fileId → File._id) — a message does not "belong" to a file, it cites one
```

### Ownership & isolation rules
- Every `workspace` has exactly one owning `user` (`workspace.userId`).
- Every `file` and `conversation` belongs to exactly one `workspace`, and is **also** stamped with `userId` directly (denormalized) so ownership can be checked in one query without an extra join back to the workspace.
- Every `message` belongs to exactly one `conversation`; ownership is resolved by looking up the conversation's workspace's user — enforced through the shared `assertOwnership()` helper (`lib/ownership.ts`), not re-implemented per route.
- **Rule:** no route ever trusts a client-supplied `userId`. The authenticated session's user ID (from Auth.js) is the only source of truth for "who is asking."

### Indexes
| Collection | Index | Reason |
|---|---|---|
| `users` | `email` (unique) | login lookup, prevent duplicate accounts |
| `workspaces` | `userId` | list-my-workspaces query, ownership checks |
| `files` | `workspaceId`, `userId` | file list per workspace, ownership checks |
| `conversations` | `workspaceId` | conversation list per workspace |
| `messages` | `conversationId` | message list per conversation (highest-read-volume query in the app) |

---

## 4. Database Schemas (fields only — no Mongoose code yet)

### `users`
| Field | Type | Required | Purpose |
|---|---|---|---|
| `_id` | ObjectId | auto | primary key |
| `name` | String | yes | display name |
| `email` | String | yes | login identifier, unique |
| `passwordHash` | String | yes* | *only required because we're using Auth.js's Credentials provider — see Auth section |
| `createdAt` | Date | auto | |

### `workspaces`
| Field | Type | Required | Purpose |
|---|---|---|---|
| `_id` | ObjectId | auto | primary key |
| `userId` | ObjectId | yes | owning user (ref → `users`) |
| `name` | String | yes | e.g. "DBMS", "Semester 7 - Networks" |
| `createdAt` / `updatedAt` | Date | auto | |

### `conversations`
| Field | Type | Required | Purpose |
|---|---|---|---|
| `_id` | ObjectId | auto | primary key |
| `workspaceId` | ObjectId | yes | parent workspace (ref → `workspaces`) |
| `title` | String | yes | auto-generated from first message, user-editable |
| `createdAt` / `updatedAt` | Date | auto | |

### `messages`
| Field | Type | Required | Purpose |
|---|---|---|---|
| `_id` | ObjectId | auto | primary key |
| `conversationId` | ObjectId | yes | parent conversation (ref → `conversations`) |
| `role` | String enum: `"user"` \| `"assistant"` | yes | who sent it |
| `content` | String | yes | message text |
| `citations` | Array of `{ fileId: ObjectId, type: "video"\|"pdf", timestampSeconds?: Number, pageNumber?: Number }` | no | only present on assistant messages that cite a source |
| `createdAt` | Date | auto | |

### `files`
| Field | Type | Required | Purpose |
|---|---|---|---|
| `_id` | ObjectId | auto | primary key |
| `workspaceId` | ObjectId | yes | parent workspace |
| `userId` | ObjectId | yes | owning user (denormalized for fast ownership checks) |
| `originalName` | String | yes | e.g. "Lecture12.mp4" |
| `type` | String enum: `"pdf"` \| `"video"` \| `"youtube_url"` | yes | |
| `storageUrl` | String | yes | where the actual bytes live (object storage) or the YouTube URL itself |
| `storageProvider` | String | no | which provider (Cloudinary/UploadThing/S3) — not applicable for `youtube_url` |
| `publicId` | String | no | provider's internal asset ID, needed to manage/delete the file |
| `status` | String enum: `"uploading"` \| `"processing"` \| `"ready"` \| `"failed"` | yes | see status lifecycle below — **no other value permitted** |
| `processingError` | String | no | populated only when `status === "failed"` |
| `ingestionId` | String | no | Team A's job/task identifier, used to poll status |
| `pageCount` | Number | no | PDFs only |
| `durationSeconds` | Number | no | video only |
| `createdAt` / `updatedAt` | Date | auto | |

### Status lifecycle (locked, used identically everywhere in the system)
```
uploading → processing → ready
processing → failed
```
No `"uploaded"` state, and no other status values, anywhere in the schema, the file-upload flow, the Team A contract, or the UI — unless Team A's *confirmed* contract later requires a value not listed here, which would be a deliberate, explicitly-flagged addition, not an assumption.

---

## 5. Team Responsibilities

### Team C (this team) owns:
- Learning dashboard, workspace management, user authentication
- File upload interface and file metadata management (not ingestion itself)
- Conversation management and persistent chat history
- Chat interface, consuming Team B's Query API (not implementing RAG)
- Video player and timestamp synchronization
- Loading/error/empty states, responsive product-level UI
- Testing (Vitest, RTL, Playwright) and deployment (Vercel)

### Team A owns (external dependency):
- PDF/video/YouTube ingestion, content/transcript extraction
- Embedding generation, metadata generation
- The ingestion pipeline itself

**Team C does NOT implement any part of Team A's ingestion pipeline.** Team C only sends a file reference and polls/receives a status.

### Team B owns (external dependency):
- RAG, retrieval, vector database
- LLM response generation, query processing
- Citation generation (which file, which timestamp/page)

**Team C does NOT implement any part of Team B's RAG system.** Team C only sends a question and workspace/conversation context, and renders whatever answer + citations come back.

---

## 6. Mock API Strategy

Both Team A and Team B integrations are built against **local mock implementations first**, so Team C's development is never blocked waiting on either team.

**Mock Team A (`services/teamA/mock.ts`):**
- Simulates the real lifecycle: on file submission, immediately returns a fake `ingestionId`
- A timer/state machine simulates `processing` for a few seconds, then resolves to `ready` (or, on a small random chance, `failed` with a sample `processingError`) — so the UI's polling and status-badge logic can be fully built and tested without Team A existing yet

**Mock Team B (`services/teamB/mock.ts`):**
- Given any question, returns a canned streamed answer (simulated token-by-token delay) with 1–2 fake citations (one video timestamp, one PDF page) — enough to build and test the full chat UI, citation chips, and video-seek behavior end-to-end

**How the swap happens without rebuilding the frontend:**
- `services/teamA/index.ts` and `services/teamB/index.ts` are the **only** import path the rest of the app is allowed to use (enforced by convention/code review, not a technical restriction)
- Each `index.ts` exports either `mock.ts` or `client.ts`'s implementation based on an environment variable (e.g., `USE_MOCK_TEAM_A=true`)
- Both `mock.ts` and `client.ts` implement the **same TypeScript interface**, defined once in `types/teamA.ts` / `types/teamB.ts` — so the real client is a drop-in replacement, not a rewrite
- Practically: Phase 6/9 set `USE_MOCK_*=true` in `.env.local`; Phase 7/10 flips it to `false` once the real endpoint + auth key are available, with zero changes to any UI component

---

## 7. Authentication Architecture

- **Provider:** Auth.js, Credentials provider (email + password) for the initial implementation — no external OAuth app registration required to start; additional providers (Google, etc.) can be added later without breaking existing sessions
- **Registration:** password hashed with bcrypt before storage; plaintext password never persisted or logged
- **Login:** Auth.js validates credentials against the hashed password, issues a session
- **Session strategy:** JWT-based (stateless, works cleanly with Next.js serverless/edge functions — no server-side session store needed)
- **Protected routes:** `middleware.ts` intercepts all `/dashboard/*` and data-bearing `/api/*` routes, redirecting unauthenticated requests to `/login`
- **User ID as source of truth:** every server-side operation resolves the current user from the verified session (`getCurrentUser()`), never from a client-supplied field
- **Ownership enforcement:** `lib/ownership.ts`'s `assertOwnership()` is called in every route touching a `workspace`, `file`, `conversation`, or `message` — checks that the resource's `userId` (directly or via its parent workspace) matches the session user; throws a 403/404 otherwise
- **Result:** Student A cannot access Student B's workspace, files, or messages even by guessing/editing a URL's ID, because every read/write is gated by this ownership check, not just hidden by UI navigation

---

## 8. File Upload Architecture

```
Student selects PDF / MP4 / pastes YouTube URL
        ↓
Client-side validation (file type, size limit)
        ↓
Upload to object storage directly (or store the URL as-is for YouTube)
        ↓
Create `files` document → status: "uploading"
        ↓
Upload completes → hand off file reference to Team A (services/teamA — mock or real)
        ↓
status: "processing" (ingestionId stored)
        ↓
Poll status endpoint (app/api/files/[id]/status)
        ↓
status: "ready"  — or —  status: "failed" (processingError populated)
        ↓
File becomes selectable/queryable in chat
```

**What's stored where:**
- **MongoDB:** filename, type, `storageUrl` (a reference, not the bytes), status, ingestion ID, processing error, page count/duration, ownership fields, timestamps
- **Object storage:** the actual PDF/MP4 bytes. **Raw file bytes are never stored in MongoDB, under any circumstance.**

**Still dependent on Team A's contract (see `api-contracts.md`):** the exact shape of the file reference Team A expects (direct URL vs. upload-then-notify vs. presigned access), and whether status updates arrive via polling or a webhook Team C would need to expose.

---

## 9. Chat Architecture

```
Student types a question
        ↓
useChat() (Vercel AI SDK, client-side) → POST /api/chat
        ↓
Route handler resolves session, validates workspace/conversation ownership
        ↓
Calls services/teamB (mock or real) with { workspaceId, conversationId, question }
        ↓
Team B streams back: answer tokens + citations
        ↓
Vercel AI SDK relays the stream to the browser — tokens render live in ChatWindow
        ↓
On stream completion: full assistant message + citations persisted to `messages`
        ↓
Citation chips render, clickable
```

**Storage:** both the user's question and the assistant's full response (with citations) are persisted as separate `messages` documents under the active `conversation`, once the stream completes — not token-by-token, to avoid partial/corrupted messages if a stream is interrupted mid-flight.

---

## 10. Video Timestamp Architecture

```
Team B citation: { fileId, type: "video", timestampSeconds: 1935 }
        ↓
CitationChip renders formatted time ("▶ Lecture12.mp4 — 32:15")
        ↓
User clicks the chip
        ↓
useActiveMediaStore (Zustand) sets { activeFileId, targetTimestamp }
        ↓
VideoPanel opens (if not already open) or updates to the new file
        ↓
react-player onReady fires → seekTo(1935)
```

**Edge case handling:**
- **Multiple citations in one message** — each renders its own independent chip; clicking any one updates the shared active-media state
- **Different videos across citations** — clicking a citation for a different file swaps the active file in the panel before seeking
- **YouTube vs. MP4** — `react-player` exposes the same `seekTo()` API for both; no branching needed in our logic
- **Invalid/out-of-range timestamp** — clamp to the video's known duration if it exceeds it; silently ignore or toast on a clearly invalid value (e.g., negative)
- **Missing timestamp** (e.g., a PDF citation) — routed to a PDF viewer/page-jump instead of `seekTo()`, not treated as an error
- **Loading state** — if the target file isn't loaded yet, show a spinner in the panel until `onReady` fires, then seek

---

## 11. Security Requirements

- Authentication required for all data-bearing routes (Auth.js + middleware)
- Authorization enforced per-request via `assertOwnership()` — never inferred from UI state alone
- Workspace, file, and conversation ownership checked on every read and write, not just writes
- Input validation on every API route (Zod schemas) before data reaches Mongoose
- File validation: MIME type and size checked client-side (UX) **and** server-side (security — client checks are not trustworthy alone)
- API authentication between Team C and Team A/B: a server-side secret/key, read only from environment variables, never sent to or exposed in the browser
- Environment variables: all secrets in `.env.local` (dev) / Vercel's environment settings (prod); `.env.local` is git-ignored; `.env.local.example` documents required keys without real values
- Object storage URLs use signed/expiring links where the provider supports it, rather than permanently public URLs
- Errors returned to the client are sanitized (no stack traces, internal error details, or connection strings ever reach the browser)
- Rate limiting on `/api/chat` specifically (the most cost-sensitive route, since it triggers a Team B/LLM call) — targeted for Phase 12, flagged as best-effort given project timeline, not a hard blocker

---

## 12. Product-Level Requirements Checklist

- [ ] Responsive design (all core screens usable on mobile width)
- [ ] Authentication (Phase 4)
- [ ] Authorization / ownership checks (Phase 4–5, enforced throughout)
- [ ] Workspace isolation (Phase 5)
- [ ] Persistent data (all collections, Phase 3 onward)
- [ ] Persistent chat history (Phase 8)
- [ ] File processing states visible in UI (Phase 6–7)
- [ ] Error states (API failures, ingestion failures) (Phase 12)
- [ ] Loading states (skeletons, spinners) (Phase 12)
- [ ] Empty states (no workspaces/files/conversations yet) (Phase 12)
- [ ] Retry handling (failed upload, failed Team B request) (Phase 6, 10, 12)
- [ ] API failure handling (graceful degradation, not blank screens) (Phase 10, 12)
- [ ] Input validation (client + server) (ongoing, formalized Phase 12)
- [ ] Automated testing (Vitest, RTL, Playwright) (Phase 13)
- [ ] Basic logging (server-side error logging — best-effort, not a dedicated phase)
- [ ] Production environment configuration (Phase 14)
- [ ] Deployment (Phase 14)

---

## 13. Phase Dependency Review

Reviewed the full 15-phase roadmap for contradictions or missing dependencies against the decisions above. **No genuine architectural problems found** — the phase order, blocking relationships, and mock strategy already assumed in the roadmap are consistent with everything finalized in this document. One clarification (not a change) was made: the `services/` folder structure above makes the roadmap's "swap mock for real" intention concrete and enforceable, rather than changing what any phase delivers.

| Category | Phases |
|---|---|
| Can start immediately (no external dependency) | 1, 2, 3, 4, 5, 6 (mocked), 8, 9 (mocked), 11 (against mocks), 12 |
| Depend on Team A (real integration) | 7 |
| Depend on Team B (real integration) | 10 |
| Can proceed using mocks | 6, 7 (until real swap), 9, 10 (until real swap), 11 |
| Cannot be *finalized* until contracts confirmed | 7 (final status field names, polling vs. webhook), 10 (final request/response shape, streaming format) |

---

## 14. Confirmed Decisions (final, ours to make — no external dependency)

- Full folder structure as documented in Section 2
- Database collections, relationships, and schemas as documented in Sections 3–4
- Status lifecycle: `uploading → processing → ready`, `processing → failed` — no other values
- Auth provider: Auth.js with Credentials (email/password) for initial implementation
- Session strategy: JWT
- Mock-first strategy for both Team A and Team B, via the `services/*/index.ts` swap pattern
- State management split: React state by default, Zustand only for `useActiveMediaStore`
- Testing stack and folder split (`tests/unit`, `tests/component`, `tests/e2e`)
- No raw file bytes ever stored in MongoDB

## 15. Items Still Waiting on Team A / Team B

See `docs/api-contracts.md` for the full field-by-field breakdown. At a summary level:
- Object storage provider (Cloudinary/UploadThing/S3) — pending Team A's expected file-input format
- Exact status value names Team A will use (we assume they match ours; not confirmed)
- Polling vs. webhook for status updates
- Service-to-service authentication mechanism with both Team A and Team B
- Team B's exact request/response JSON shape and streaming format
- Team B's error response format

---

## 16. Consistency Verification Against `api-contracts.md`

Performed a field-by-field cross-check between this document and `docs/api-contracts.md`. Two naming clarifications and one intentional omission were found and are documented here — none are actual contradictions, but all three could be misread as inconsistencies without this note.

1. **External request field names vs. internal DB field names differ, deliberately.** The proposed Team A submission contract uses `fileUrl` / `fileType` (see `api-contracts.md` §A.5), while our internal `files` schema uses `storageUrl` / `type`. This is not a typo or drift — external API payloads and internal DB fields are allowed to use different vocabularies. The mapping between them belongs in `services/teamA/client.ts` (and `mock.ts`, so both stay in sync), which reads `file.storageUrl` / `file.type` from Mongoose and serializes them as `fileUrl` / `fileType` on the wire. This mapping point is now explicit so Phase 6/7 implementation doesn't have to rediscover it.

2. **Citation `type` enum is a subset of file `type` enum, by design.** `files.type` has three values (`"pdf" | "video" | "youtube_url"`) describing the *uploaded format*. `messages.citations[].type` has only two (`"video" | "pdf"`) describing *how to render the citation*. A citation pointing at a `youtube_url` file uses citation type `"video"` — both MP4 and YouTube files seek the same way via `react-player`'s `seekTo()`, so there is no third citation type. This is confirmed consistent with the Video Timestamp Architecture (§10) edge-case note that YouTube and MP4 share the same seek logic.

3. **Team A's proposed status response intentionally omits `"uploading"`.** The proposed shape in `api-contracts.md` §A.5 only lists `"processing" | "ready" | "failed"` as values Team A can return — this is correct, not a missing status. `"uploading"` is a purely client/Team-C-side state that exists *before* Team A is ever contacted (during the direct-to-object-storage upload). Team A's pipeline only starts once a file has already finished uploading, so it never needs to express that state. The full 4-value enum still lives in one place — the `files.status` field — Team C sets `"uploading"` itself, and only Team A-derived responses can move it to `"processing"`, `"ready"`, or `"failed"`.

**Explicit verification against each item flagged for attention:**

| Item | Verified consistent? | Where |
|---|---|---|
| Status lifecycle (`uploading → processing → ready`, `processing → failed`) | Yes | `decisions.md` §4, `api-contracts.md` §A.3/A.5 (see clarification #3 above) |
| `conversationId` ↔ `messages` relationship | Yes | `decisions.md` §3/§4 (`message.conversationId`), `api-contracts.md` §B.1 (same field name, same purpose) |
| Workspace ownership | Yes | `decisions.md` §3 (`workspace.userId`) — not referenced differently anywhere in `api-contracts.md` |
| File ownership | Yes | `decisions.md` §3/§4 (`file.workspaceId`, `file.userId`), `api-contracts.md` §A.1 (`workspaceId`/`userId` included in submission, same meaning) |
| Citation → file relationship | Yes | `decisions.md` §4 (`citations[].fileId → File._id`), `api-contracts.md` §B.2 (`citations[].fileId`) — identical |
| Team A `ingestionId` | Yes | `decisions.md` §4 (`files.ingestionId`), `api-contracts.md` §A.2 (returned on submission, stored by Team C) — identical |
| Team B `citations` shape | Yes | `decisions.md` §4 (`messages.citations`), `api-contracts.md` §B.2/§B.5 — identical field set (see clarification #2 for the enum subset note) |
| `timestampSeconds` (video) | Yes | Same field name in both documents, no drift |
| `pageNumber` (PDF) | Yes | Same field name in both documents, no drift |
| Mocks replaceable with real APIs without rebuilding frontend | Yes | `decisions.md` §2 (`services/*/index.ts` swap pattern) and §6 (mechanism explained); `api-contracts.md` closing paragraph confirms mocks implement the same proposed shapes |

**Conclusion: no unresolved contradictions between the architecture and the API contract document.** The three items above have been converted from potential ambiguity into explicit, documented mapping rules.


