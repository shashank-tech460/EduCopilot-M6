# Integration — How Team4C, Team4A, and Team4B Work Together

This is the document to read to understand exactly how the three services
talk to each other. Architecture context: [ARCHITECTURE.md](ARCHITECTURE.md).
Service-specific detail: [TEAM4A.md](TEAM4A.md), [TEAM4B.md](TEAM4B.md),
[TEAM4C.md](TEAM4C.md).

## Service URLs and ports (local development)

| Service | URL | Notes |
|---|---|---|
| Team4C | http://localhost:3000 | |
| Team4A | http://localhost:8001 | Manual `uvicorn` run; Docker Compose's own default is port 8000 internally |
| Team4B | http://localhost:8002 | Manual `uvicorn` run; Docker Compose's own default is port 8000 internally |
| Qdrant | http://localhost:6333 | |
| MongoDB | localhost:27017 | One database, shared by Team4C (owns the schema) and Team4A (writes one field) and Team4B (reads that field) |
| Redis (Team4A) | localhost:6379 | Celery broker/result, ingestion locks |
| Redis (Team4B) | localhost:6380 | Conversation history — deliberately a separate instance/port from Team4A's Redis |
| Ollama | http://localhost:11434 | Local LLM, used only by Team4B |

## Startup order

Order matters because Team4C's health checks and first real requests
expect the others to already be reachable:

1. Infrastructure: MongoDB, Redis ×2, Qdrant, Ollama (with the model pulled).
2. Team4A (needs Qdrant, Redis, MongoDB).
3. Team4B (needs Qdrant, Redis, MongoDB, Ollama).
4. Team4C (needs MongoDB directly, and Team4A/Team4B over HTTP for any
   request that isn't served by its own local mock).

Exact commands: [SETUP.md](SETUP.md).

## Authentication between services

Team4C mints a fresh, short-lived (default 300s), ES256-signed internal
service JWT immediately before each call to Team4A or Team4B — never a
long-lived static API key, never a client-supplied value.

| Claim | Team4A call | Team4B call |
|---|---|---|
| `sub` | the authenticated user's id (server-verified, from the session — never taken from the request body) | same |
| `workspace_id` | the already-authorized workspace's id | same |
| `scope` | `"ingest"` | `"query"` |
| `aud` | `"team4a-ingestion"` | `"team4b-query"` |
| `iss` | `https://educopilot.internal` | same |

Team4A and Team4B each hold **only the public verification key** for this
keypair — Team4C is the only service that ever holds the private signing
key. A token minted for one audience is rejected by the other service (the
`aud` claim is checked, not just presence of a valid signature).

## Identity propagation

- **`workspace_id`**: resolved server-side from the authenticated user's
  own, already-ownership-checked workspace — never taken directly from an
  unauthenticated or unverified part of a request.
- **`document_id`**: the MongoDB `File._id` — the same identifier Team4C
  created, Team4A writes ingestion metadata onto, and Team4B filters
  retrieval by. One id, three services, never translated or re-minted in
  between.
- **`account`/user id**: only ever leaves Team4C as the JWT's `sub` claim;
  Team4A/Team4B never see a user's email, name, or any other profile
  field.

## Ingestion lifecycle — what happens when a user uploads a PDF or adds a YouTube link

1. Team4C creates a `File` document in MongoDB: `status: "uploading"`,
   a fresh `document_id` (its own `_id`).
2. Team4C mints a service JWT (`scope: "ingest"`, `aud: "team4a-ingestion"`)
   and calls Team4A's `POST /v1/ingest` with the file reference (an
   uploaded file's URL, or the YouTube URL), `workspace_id`, `document_id`.
3. Team4A's ingestion-lock/generation mechanism authorizes this attempt
   (see [TEAM4A.md](TEAM4A.md)) and returns `202 Accepted` with a job id.
   Team4C sets `status: "processing"`.
4. Team4A's Celery worker extracts → chunks → embeds → publishes chunks to
   the canonical Qdrant collection, tagged with `workspace_id`,
   `document_id`, and the generation number this attempt was issued.
5. On success, Team4A writes `currentIngestionGeneration` and `ingestionId`
   onto the same `File` document (the one narrow field it's allowed to
   touch). Team4C's UI reflects `status: "ready"`.
6. On failure, Team4A's job reports an error; Team4C sets
   `status: "failed"` with the real `processingError` message — never
   silently retried as "ready."

If ingestion is attempted again for the same document (a duplicate
request, or a legitimate re-ingestion), the Redis lock and generation
counter (§ [TEAM4A.md](TEAM4A.md)) make this safe: only one attempt runs
at a time, and whichever one finishes last with the highest generation
number is the one Team4B will actually retrieve from — an old, slow
attempt finishing late does not un-supersede a newer one.

## Query lifecycle — what happens when a student asks the AI Tutor a question

1. Team4C's `/api/chat` route resolves (all server-side): the
   authenticated user, the already-authorized `Conversation`, its stable
   `ragSessionId`, and the effective document scope (workspace-wide, or
   the one material the conversation is scoped to — re-validated against
   current `File` state on every request).
2. Team4C mints a service JWT (`scope: "query"`, `aud: "team4b-query"`)
   and calls Team4B's `POST /api/v1/query` with `{query, session_id,
   retrieval_config}` — exactly three fields on the wire; nothing else
   Team4C knows (workspace name, user email, etc.) is ever sent.
3. Team4B retrieves, filters by generation authority, fuses, generates,
   and returns `{answer, source_attributions, ...}`.
4. Team4C loads the real files in the authenticated user's workspace from
   its own MongoDB and re-filters `source_attributions` against them
   (defense-in-depth — a citation naming a file outside the caller's
   workspace is marked `disabled`, logged server-side, and never rendered
   as clickable, regardless of what Team4B returned).
5. Team4C persists both turns (`user`, `assistant` + citations) to
   MongoDB, then streams the answer to the browser word-by-word via the
   AI SDK's streaming primitives — the full answer already exists at this
   point; the streaming is a presentation choice, not token-by-token
   generation happening live over the wire from Ollama.

## Citation flow

A citation displayed in the UI has passed through, in order: Team4B's own
retrieval-metadata-derived attribution (never re-derived from the model's
free-text output) → Team4C's workspace-ownership re-filter → the specific
message's `data-citations` part → `SourceAttribution` component. At no
point is a citation's target file, page, or timestamp taken from anything
the LLM wrote in its answer text.

## What Team4C sends Team4B — the exact wire contract

```json
POST /api/v1/query
Authorization: Bearer <service JWT, aud=team4b-query, scope=query>
{
  "query": "What is inheritance?",
  "session_id": "<the Conversation's stable ragSessionId>",
  "retrieval_config": { "document_ids": ["<File._id>", "..."] }  // or null for workspace-wide
}
```

Team4B's response includes `answer`, `source_attributions` (each with
`document_id`, `document_title`, `chunk_id`, `relevance_score`, and either
`page_number`/`section_heading` for a PDF source or
`start_timestamp`/`end_timestamp` for a video source), and
`retrieval_metadata`.

## Related documents

- [ARCHITECTURE.md](ARCHITECTURE.md) — the system-level diagram and data-flow summary this document expands on.
- [ENVIRONMENT.md](ENVIRONMENT.md) — every variable involved in the above (JWT keys, URLs, database names).
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — what to do when a step above doesn't happen as described (stuck ingestion, a 401/403 from a service call, empty retrieval).
