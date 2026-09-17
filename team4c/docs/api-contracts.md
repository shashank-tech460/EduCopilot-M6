# Team C — API Contracts (Proposed)

**Status: PROPOSED — NOT YET CONFIRMED WITH TEAM A OR TEAM B.**
Every field below is explicitly labeled. Nothing in this document should be read as an agreed contract until the corresponding team confirms it in writing.

Labels used:
- **CONFIRMED** — agreed with the other team (none yet, as of Phase 1)
- **ASSUMPTION** — our best guess, reasonable given the problem statement, used to build our mocks
- **TO CONFIRM** — an open question with no assumed answer; must be resolved before real integration (Phase 7 / Phase 10)

---

## A. Team A → Team C Contract

### A.1 File submission (Team C → Team A)

| Field | Status | Notes |
|---|---|---|
| File reference sent to Team A | ASSUMPTION | We assume we send a `storageUrl` (already uploaded to object storage) rather than raw file bytes — reduces payload size and avoids duplicating storage. |
| `workspaceId` / `userId` included in submission | ASSUMPTION | Needed so Team A can (if relevant to their pipeline) tag embeddings with ownership context, but this may not matter to Team A at all — **TO CONFIRM** whether they need this or only care about the file. |
| Request format (JSON body vs. multipart) | ASSUMPTION | Assumed JSON body containing a URL, not a file upload to Team A directly. |

### A.2 Response to submission

| Field | Status | Notes |
|---|---|---|
| `ingestionId` | ASSUMPTION | Assumed to be returned synchronously on submission, used by Team C to poll status. **TO CONFIRM** — Team A may instead return it asynchronously or use the file's own ID as the tracking ID (no separate ingestion ID at all). |

### A.3 Status checking

| Field | Status | Notes |
|---|---|---|
| Status values: `uploading`, `processing`, `ready`, `failed` | ASSUMPTION | These are **our** internal status values (locked per `docs/decisions.md`). **TO CONFIRM**: Team A almost certainly has their own internal status vocabulary — we will need a mapping layer if their values differ (e.g., their `"complete"` → our `"ready"`), rather than assuming their API speaks our exact enum. |
| Polling vs. webhook | TO CONFIRM | We default to **polling** for Phase 6/7 (`GET` on a status endpoint) since it requires no public inbound endpoint on our side. If Team A only supports webhooks, Phase 7 needs an inbound `POST` route (e.g., `app/api/webhooks/team-a/route.ts`) — not currently in the folder structure, would be a small addition, not a redesign. |
| Processing error detail | ASSUMPTION | Assumed Team A returns a human-readable error string on failure; format (plain string vs. error code) **TO CONFIRM**. |

### A.4 Authentication

| Field | Status | Notes |
|---|---|---|
| Auth mechanism between Team C and Team A | TO CONFIRM | No mechanism assumed yet. Likely candidates: shared API key in a header, or a signed JWT. Needs a decision from whoever owns Team A's endpoint. |

### A.5 Proposed contract shape (for mock-building purposes only)

```json
// Team C → Team A (submission)
POST /ingest
{
  "fileUrl": "string",
  "fileType": "pdf" | "video" | "youtube_url",
  "workspaceId": "string"
}

// Team A → Team C (immediate response)
{
  "ingestionId": "string"
}

// Team C → Team A (status check)
GET /ingest/{ingestionId}/status

// Team A → Team C (status response)
{
  "status": "processing" | "ready" | "failed",
  "error": "string | null"
}
```
**This entire block is ASSUMPTION**, used only to build `services/teamA/mock.ts` so frontend/UI work isn't blocked. It is not a claim that Team A has agreed to this shape.

---

## B. Team C → Team B Contract

### B.1 Request

| Field | Status | Notes |
|---|---|---|
| `workspaceId` | ASSUMPTION | So Team B knows which student's material to search within. |
| `conversationId` | ASSUMPTION | For potential multi-turn context within a thread — **TO CONFIRM** whether Team B needs this or is fully stateless per-question. |
| `question` (the user's query text) | ASSUMPTION | Core required field, low risk this is wrong. |
| Relevant file/context scoping | TO CONFIRM | Unclear whether Team B searches the *entire* workspace's uploaded material automatically, or whether Team C needs to pass a specific list of `fileIds` to search within. This materially affects what Team C's request body looks like. |

### B.2 Response

| Field | Status | Notes |
|---|---|---|
| `answer` (string) | ASSUMPTION | Core required field. |
| `citations[]` | ASSUMPTION | Array of citation objects. |
| `citations[].fileId` | ASSUMPTION | Must match a `files._id` Team C already knows about. |
| `citations[].type` (`"video"` \| `"pdf"`) | ASSUMPTION | Needed so Team C knows whether to seek a video or open a PDF page. |
| `citations[].timestampSeconds` | ASSUMPTION | For video citations. |
| `citations[].pageNumber` | ASSUMPTION | For PDF citations. |
| Source/display metadata (e.g., a snippet of the cited text) | TO CONFIRM | Not assumed yet — would improve the citation chip's usefulness but isn't required for the core seek-to-timestamp feature to work. |

### B.3 Streaming

| Field | Status | Notes |
|---|---|---|
| Streaming format | TO CONFIRM | The Vercel AI SDK expects a specific stream format (its own protocol, or plain SSE/text that we adapt). If Team B streams in a different shape, Phase 10 needs an adapter layer between Team B's raw stream and what `useChat()` expects. This is the single highest-risk unknown in the whole integration. |
| Non-streaming fallback | ASSUMPTION | We assume Team B *can* stream (per the problem statement's emphasis on a chat experience), but Team C's `app/api/chat/route.ts` should tolerate a non-streaming (single JSON) response as a fallback, in case streaming isn't ready in time — this is a defensive design choice on our side, not an assumption about Team B's actual behavior. |

### B.4 Authentication & errors

| Field | Status | Notes |
|---|---|---|
| Auth mechanism | TO CONFIRM | Same open question as Team A — likely a shared key/header. |
| HTTP status codes on error | ASSUMPTION | Assumed standard usage (400 for bad request, 401/403 for auth, 500 for internal failure, 429 if rate-limited) — **TO CONFIRM** Team B actually follows this convention. |
| Error response body format | TO CONFIRM | No shape assumed; Team C's error handling (Phase 10, Phase 12) will need adjusting once this is known. |

### B.5 Proposed contract shape (for mock-building purposes only)

```json
// Team C → Team B
POST /query
{
  "workspaceId": "string",
  "conversationId": "string",
  "question": "string"
}

// Team B → Team C (non-streaming shape, for reference)
{
  "answer": "string",
  "citations": [
    { "fileId": "string", "type": "video", "timestampSeconds": 1935 },
    { "fileId": "string", "type": "pdf", "pageNumber": 32 }
  ]
}
```
**This entire block is ASSUMPTION.** Streaming transport details are explicitly **TO CONFIRM** and not represented in this JSON example, which only illustrates the final resolved data shape our mock produces.

---

## C. Action Items Before Real Integration

**Before Phase 7 (Team A):**
1. Confirm file submission format (URL reference vs. direct upload to Team A)
2. Confirm Team A's actual status vocabulary and get a mapping to our 4 values
3. Confirm polling vs. webhook
4. Confirm auth mechanism

**Before Phase 10 (Team B):**
1. Confirm request shape, especially whether file/context scoping is needed
2. Confirm response shape, especially the citation object fields
3. Confirm streaming format (highest priority — affects `app/api/chat/route.ts`'s core implementation)
4. Confirm auth mechanism and error format

Until these are confirmed, `services/teamA/mock.ts` and `services/teamB/mock.ts` implement the proposed shapes above, and all of Team C's UI/logic is built against them per the mock strategy in `docs/decisions.md`.
