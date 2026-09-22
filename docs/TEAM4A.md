# Team4A — Ingestion Service

FastAPI + Celery service that turns a PDF or YouTube video into searchable,
embedded chunks in Qdrant. Stable and frozen throughout the entire Phase 5
RAG validation arc and all of this project's Team4C UI work — no code in
this service was modified by that work.

## Purpose

Team4A is the only service that reads a raw document/video and turns it
into vector-searchable data. Team4B never extracts or chunks anything
itself; it only reads what Team4A has already published to Qdrant.

## Architecture

```
FastAPI API  --(Celery task)-->  Celery Worker (Redis broker/result backend)
                                        |
                    +-------------------+-------------------+
                    |                   |                   |
              PDF Processor      Video Processor      YouTube Processor
              (PyMuPDF)          (Whisper, MP4)        (transcript API)
                    |                   |                   |
                    +-------------------+-------------------+
                                        |
                                     Chunker
                                        |
                                Embedding Generator
                              (sentence-transformers,
                               all-MiniLM-L6-v2)
                                        |
                                Metadata Enricher
                                        |
                              Vector DB Publisher --> Qdrant
```

The API process and the Celery worker process share one Docker image
(`team4a/Dockerfile`) — only the container start command differs between
the `api` and `worker` Compose services.

## Ingestion pipeline

1. **Extraction** — PDF text via PyMuPDF; YouTube transcript via
   `youtube-transcript-api` (requests `youtube_default_language`, `en` by
   default, falling back exactly once to `youtube_fallback_language`, `hi`
   by default, if the primary request raises `TranscriptUnavailableError` —
   not a translated retry, a second request for a transcript track that may
   already exist); MP4 audio transcription via `openai-whisper`.
2. **Chunking** — target `chunk_size` tokens (default 512) with
   `chunk_overlap` (default 50).
3. **Embedding** — `sentence-transformers`, model `all-MiniLM-L6-v2` pinned
   to a specific commit SHA (`embedding_model_revision`) so an upstream
   model-repo push can never silently change what gets loaded. 384-dimensional
   vectors, batched (`embedding_batch_size`, default 32).
4. **Metadata enrichment** — attaches `workspace_id`, `document_id`,
   `ingestion_generation`, source type, and page/timestamp locators to each
   chunk.
5. **Publishing** — writes to Qdrant in batches (`qdrant_publish_batch_size`,
   default 100, max 100), with retry (`publisher_retry_count`, default 3,
   exponential backoff from `publisher_initial_backoff_seconds`).

## The canonical ingestion path and the ingestion-generation/authority mechanism

The route Team4C actually calls is `POST /v1/ingest` (accepts a
`file_url`/YouTube URL, `workspace_id`, `document_id`), not the older
per-type routes below it in the same router. This canonical path writes to
`canonical_qdrant_collection_name` (default `educopilot_chunks`) — a
collection distinct from the legacy `qdrant_collection_name`
(`team4a_ingested_chunks`) that the older, non-canonical routes still use.
The two are never conflated.

**Why a generation number exists**: a document can be re-ingested (a user
re-adds the same YouTube URL, or a fix is deployed and content is
re-processed). Without a way to know which ingestion attempt is "current,"
a slow, superseded ingestion could finish *after* a newer one and have its
now-stale chunks treated as valid. Team4A solves this with:

- **A Redis-coordinated per-document lock** (`ingestion_lock_lease_seconds`,
  default 14400s/4h) — only one ingestion attempt per `document_id` runs at
  a time.
- **A generation counter** (also Redis-coordinated) that increments each time
  an ingestion attempt is authorized for a given `document_id`.
- **A narrow, explicitly-scoped MongoDB write**: on successful completion,
  Team4A's Mongo-authority client (`app/pipeline/mongo_authority.py`) writes
  `currentIngestionGeneration` and `ingestionId` onto the `File` document
  Team4C created — the *only* field on `File` Team4A ever touches; it does
  not own or otherwise modify the `File` schema.
- Team4B then reads that same field to filter out chunks from a
  superseded generation before they ever reach fusion or generation — see
  [TEAM4B.md](TEAM4B.md) and [INTEGRATION.md](INTEGRATION.md).

If two ingestion requests for the same document arrive together, the lock
means the second one waits (or is rejected, depending on how it arrives) —
it does not silently interleave with the first. If an old, slow ingestion
finishes after a newer one, its generation number is lower than the current
one, and Team4B's authority check excludes its chunks regardless of when
they were written to Qdrant.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/ingest` | **Canonical** ingestion entrypoint — PDF/video/YouTube URL, workspace/document-scoped, writes to `canonical_qdrant_collection_name` |
| `POST` | `/ingest/pdf` | Legacy per-type PDF upload |
| `POST` | `/ingest/video` | Legacy per-type MP4 upload |
| `POST` | `/ingest/youtube` | Legacy per-type YouTube URL |
| `GET` | `/jobs/{job_id}` | Poll one ingestion job's status |
| `GET` | `/jobs` | List ingestion jobs |
| `GET` | `/health` | Liveness |
| `GET` | `/readyz` | Readiness |

All ingestion routes require a valid internal service JWT
(`aud: "team4a-ingestion"`, `scope: "ingest"`) — see
[INTEGRATION.md](INTEGRATION.md) for the exact claims and how Team4C mints
one.

## Environment variables

Every setting is defined with a sensible default in
`app/config/settings.py` and is environment-overridable (case-insensitive).
Full reference with every field: [ENVIRONMENT.md](ENVIRONMENT.md). The ones
that matter most for local setup:

| Variable | Default | Notes |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | |
| `CANONICAL_QDRANT_COLLECTION_NAME` | `educopilot_chunks` | The collection the canonical `/v1/ingest` path writes to |
| `MONGO_URL` | `mongodb://localhost:27017` | |
| `MONGO_DATABASE_NAME` | `educopilot` | **Must be overridden** to match Team4C's actual database name (see [ENVIRONMENT.md](ENVIRONMENT.md) — this is the single most common local-setup mistake) |
| `REDIS_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `REDIS_RESULT_BACKEND_URL` | `redis://localhost:6379/1` | Celery result backend |
| `SERVICE_JWT_EXPECTED_ISSUER` / `_AUDIENCE` / `_REQUIRED_SCOPE` / `_PUBLIC_KEYS_JSON` | see [ENVIRONMENT.md](ENVIRONMENT.md) | Verification-only — Team4A never holds a private signing key |

No `.env.example` currently exists in `team4a/` — a real `.env` is required
to run the service; see [SETUP.md](SETUP.md) for the values a fresh setup
needs.

## Dependencies

`fastapi`, `uvicorn`, `celery`, `redis`, `qdrant-client`, `pymupdf`, `yt-dlp`,
`youtube-transcript-api`, `openai-whisper`, `sentence-transformers`,
`pydantic` + `pydantic-settings`, `python-multipart`. Python 3.12
(`team4a/Dockerfile`'s base image).

## Startup

```powershell
# Docker (recommended)
cd team4a
docker compose up --build

# Manual (two processes)
cd team4a
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
celery -A app.celery_app worker --loglevel=info
```

## Health check

```powershell
curl http://localhost:8001/health
curl http://localhost:8001/readyz
```

## Tests

```powershell
cd team4a
python -m pytest -q
```

Not re-baselined by the Phase 5 RAG validation arc or the Team4C UI work —
consult the service's own test output for its current numbers.

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for: stuck/stale ingestion,
the Redis lock, the Mongo database-name mismatch, and Qdrant collection
mismatches. Do not delete Redis keys or Qdrant points to "fix" a stuck
ingestion without first reading that document — several of these states
are self-healing (locks expire) or have a safe, documented diagnostic
before any destructive action.
