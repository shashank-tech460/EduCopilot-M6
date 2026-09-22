# Environment Variables

Every variable used across the three services. No real secret values
appear anywhere in this document — only safe example/placeholder values.
**Never commit a real `.env`, `.env.local`, or `*.pem` file** — all are
git-ignored (see the [Repository hygiene](#repository-hygiene) note at the
end). Setup walkthrough with these values in context: [SETUP.md](SETUP.md).

## Team4C (`team4c/.env.local`, from `team4c/.env.example`)

| Variable | Purpose | Example / safe value | Required | Machine-specific |
|---|---|---|---|---|
| `MONGODB_URI` | MongoDB connection string, database name in the path | `mongodb://localhost:27017/edu-copilot-team-c` | Yes | No (assuming default local Mongo) |
| `AUTH_SECRET` | Auth.js session encryption key | generate: `node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"` | Yes | Yes — generate your own, never reuse |
| `AUTH_URL` | Base URL Auth.js runs at | `http://localhost:3000` | Yes | No |
| `AUTH_TRUST_HOST` | Lets Auth.js v5 trust the Host header locally | `true` | Yes | No |
| `STORAGE_PROVIDER` | Object storage provider selector | *(blank — uses the local-storage dev mock)* | No | — |
| `STORAGE_API_KEY` / `STORAGE_API_SECRET` | Only used if `STORAGE_PROVIDER` is set | *(blank)* | No | — |
| `USE_MOCK_TEAM_A` | Use Team4A's local mock instead of a real HTTP call | `false` for real integration, `true` for frontend-only dev | Yes | No |
| `TEAM_A_API_URL` | Team4A's internal base URL (server-side only, never sent to the browser) | `http://localhost:8001` | If `USE_MOCK_TEAM_A=false` | Yes (matches wherever Team4A actually runs) |
| `USE_MOCK_TEAM_B` | Use Team4B's local mock instead of a real HTTP call | `false` for real integration, `true` for frontend-only dev | Yes | No |
| `TEAM_B_API_URL` | Team4B's internal base URL | `http://localhost:8002` | If `USE_MOCK_TEAM_B=false` | Yes |
| `SERVICE_JWT_PRIVATE_KEY` | PKCS8 PEM ES256 **private** key — Team4C is the only service that ever holds this | *(generate — see SETUP.md)* | Yes for real Team4A/4B integration | Yes — never reuse across machines/deployments |
| `SERVICE_JWT_KID` | Key id, must match what Team4A/4B expect in `SERVICE_JWT_PUBLIC_KEYS_JSON` | `m6-es256-2026-01` | Yes | No, but must match all three services |
| `SERVICE_JWT_ISSUER` | Must match `SERVICE_JWT_EXPECTED_ISSUER` on Team4A/4B | `https://educopilot.internal` | Yes | No, but must match |
| `SERVICE_JWT_TTL_SECONDS` | Token lifetime | `300` | No (has a code default) | No |

## Team4A (`team4a/.env` — no `.env.example` is currently committed; create it directly)

Every field below has a code-level default in `app/config/settings.py`
(read there for the full, authoritative list — includes chunking,
embedding, video-processing, and Celery tuning knobs not repeated here).
The ones that actually need a **non-default** local value:

| Variable | Purpose | Example / safe value | Required override |
|---|---|---|---|
| `QDRANT_URL` | Vector store | `http://localhost:6333` | No (matches default) |
| `CANONICAL_QDRANT_COLLECTION_NAME` | Where the canonical `/v1/ingest` path publishes chunks | `educopilot_chunks` | No (matches default) |
| `MONGO_URL` | Generation-authority Mongo connection | `mongodb://localhost:27017` | No (matches default) |
| `MONGO_DATABASE_NAME` | **Must match Team4C's database name** | `edu-copilot-team-c` | **Yes — the code default (`educopilot`) is wrong for this integration** |
| `REDIS_BROKER_URL` | Celery broker | `redis://localhost:6379/0` | No (matches default) |
| `REDIS_RESULT_BACKEND_URL` | Celery result backend | `redis://localhost:6379/1` | No (matches default) |
| `SERVICE_JWT_EXPECTED_ISSUER` | Must match Team4C's `SERVICE_JWT_ISSUER` | `https://educopilot.internal` | Yes |
| `SERVICE_JWT_EXPECTED_AUDIENCE` | This service's own audience | `team4a-ingestion` | Yes |
| `SERVICE_JWT_REQUIRED_SCOPE` | Scope Team4A requires | `ingest` | Yes |
| `SERVICE_JWT_PUBLIC_KEYS_JSON` | `{kid: PEM public key}` map — **public key only, never a private key** | `{"m6-es256-2026-01": "-----BEGIN PUBLIC KEY-----..."}` | Yes |
| `FILE_URL_TRUSTED_ORIGINS_JSON` | Exact hostnames Team4A's PDF/MP4 `file_url` retrieval is allowed to fetch from | `["localhost"]` | Yes for local dev |
| `FILE_URL_REQUIRE_HTTPS` | Reject `http://` file URLs unless disabled | `false` for local dev, `true` in any real deployment | Yes for local dev only |

## Team4B (`team4b/.env`, from `team4b/.env.example`; `.env.docker.example` for the containerized variant)

| Variable | Purpose | Example / safe value |
|---|---|---|
| `QDRANT_URL` | Vector store | `http://localhost:6333` |
| `QDRANT_COLLECTION_NAME` | Team4B's own legacy default — production traffic actually reads whatever collection Team4A publishes to; this may be left at its default | `team4b_shared_production_chunks` |
| `MONGO_URL` | Generation-authority Mongo connection | `mongodb://localhost:27017` |
| `MONGO_DATABASE_NAME` | **Must match Team4C's database name** | `edu-copilot-team-c` |
| `REDIS_URL` | Conversation history store — **port 6380**, a separate Redis instance from Team4A's | `redis://localhost:6380` |
| `OLLAMA_URL` | Local LLM host | `http://localhost:11434` |
| `OLLAMA_MODEL_NAME` | Model to use | `llama3` |
| `EMBEDDING_MODEL_NAME` | Must match Team4A's embedding model | `all-MiniLM-L6-v2` |
| `EMBEDDING_DIMENSIONS` | Must match Team4A's | `384` |
| `DEFAULT_TOP_K` | Retrieval count | `5` |
| `DEFAULT_SCORE_THRESHOLD` | Retrieval cutoff | `0.3` |
| `DEFAULT_SEARCH_MODE` | `semantic` / `keyword` / `hybrid` | `hybrid` |
| `RRF_K` | Reciprocal Rank Fusion damping constant | `60` |
| `CONVERSATION_WINDOW_SIZE` | Turns of history included in the generation prompt | see `.env.example` for the current default |
| `SESSION_TTL_MINUTES` | Redis conversation-history expiry | see `.env.example` |
| `LOG_LEVEL` | `INFO` / `DEBUG` / … | `INFO` |
| `SERVICE_JWT_EXPECTED_ISSUER` | Must match Team4C's | `https://educopilot.internal` |
| `SERVICE_JWT_EXPECTED_AUDIENCE` | This service's own audience | `team4b-query` |
| `SERVICE_JWT_REQUIRED_SCOPE` | Scope Team4B requires | `query` |
| `SERVICE_JWT_PUBLIC_KEYS_JSON` | The **same** keypair's public key as Team4A's | `{"m6-es256-2026-01": "-----BEGIN PUBLIC KEY-----..."}` |

## Cross-service invariants (must match across services)

- `MONGO_DATABASE_NAME` (Team4A, Team4B) must equal the database name in
  Team4C's `MONGODB_URI` path.
- `SERVICE_JWT_KID` / `SERVICE_JWT_ISSUER` (Team4C) must equal
  `SERVICE_JWT_EXPECTED_ISSUER` (Team4A, Team4B), and the `kid` inside
  `SERVICE_JWT_PUBLIC_KEYS_JSON` must match `SERVICE_JWT_KID`.
- `SERVICE_JWT_PUBLIC_KEYS_JSON`'s PEM value must be the **public** key
  derived from Team4C's own `SERVICE_JWT_PRIVATE_KEY` — the same keypair,
  everywhere.
- `EMBEDDING_MODEL_NAME` / `EMBEDDING_DIMENSIONS` (Team4B) must match
  Team4A's embedding configuration, or retrieval will silently return
  poor/empty results without any error (a dimension mismatch is a Qdrant
  configuration property, checked at collection-creation time, not at
  every query).

## Repository hygiene

`.env`, `.env.*` (except `*.example`), and `*.pem` are git-ignored at the
repository root (see `.gitignore`). Never commit:

- `.env` / `.env.local` files with real values
- `*.pem` private or public key files
- MongoDB connection strings containing real credentials
- Any API key, JWT signing key, or password

`.env.example` / `.env.docker.example` files contain placeholders only —
audited for real-looking secret patterns as part of this documentation
pass; see the final report in the repository preparation summary.
