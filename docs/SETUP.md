# Setup

Installing and running EduCopilot, from a fresh Windows machine that has
never seen this project to a working product at `http://localhost:3000`.

## Quick start — existing developer (everything already installed/configured)

```powershell
# Terminal 1 — infrastructure (skip anything already running)
docker start qdrant team4a-redis team4b-redis   # or your container names

# Terminal 2 — Team4A
cd team4a
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
# Terminal 2b — Team4A's worker
cd team4a
celery -A app.celery_app worker --loglevel=info

# Terminal 3 — Team4B
cd team4b
uvicorn app.api.main:app --host 0.0.0.0 --port 8002

# Terminal 4 — Team4C
cd team4c
npm run dev
```
Open http://localhost:3000. If something doesn't come up cleanly, skip to
[Part O — Common Startup Failures](#part-o--common-startup-failures) or
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## Full setup — new machine

### Part A — Before starting: verify prerequisites

Run each check. Versions shown are what this project was actually built
and tested against (read from `team4c/package.json`, `team4a/Dockerfile`,
`team4b/Dockerfile` — not guessed).

| Tool | Check command | Expected | If missing |
|---|---|---|---|
| Git | `git --version` | any recent version | https://git-scm.com/downloads |
| Node.js | `node --version` | `v20.x` or higher (project built against `v22.17.1`) | https://nodejs.org (LTS) |
| npm | `npm --version` | `10.x` (bundled with Node) | comes with Node.js |
| Python | `python --version` | `3.12.x` (both `team4a/Dockerfile` and `team4b/Dockerfile` pin `python:3.12-slim`) | https://www.python.org/downloads/ |
| pip | `pip --version` | any recent version, matching your Python 3.12 install | comes with Python |
| Docker Desktop | `docker --version` | any recent version | https://www.docker.com/products/docker-desktop/ |
| MongoDB | `mongod --version` (if installed natively) | any recent 6.0+ | https://www.mongodb.com/try/download/community, or run via Docker (Part E) |
| Ollama | `ollama --version` | any recent version | https://ollama.com/download |

**Hardware note**: local LLM generation is CPU-bound in this project's
own development environment (no GPU configured) — expect **30–140+
seconds per AI Tutor answer**. A GPU-capable machine with Ollama
configured to use it will be significantly faster; this is not required,
but budget demo/test time accordingly either way. See
[LIMITATIONS.md](LIMITATIONS.md).

### Part B — Get the project

```powershell
git clone <repository-url> EduCopilot-M6-Local
cd EduCopilot-M6-Local
```

Expected folder structure (the actual, current layout of this repository):

```
EduCopilot-M6-Local/
├── team4a/     Ingestion service (FastAPI, Python)
├── team4b/     RAG/retrieval service (FastAPI, Python)
├── team4c/     Next.js frontend/API
├── infra/      infra placeholder (intentionally minimal)
├── docs/       project-level documentation (this file's companions)
└── scripts/    top-level orchestration helpers
```

### Part C — Environment configuration

| File | Exists as an example? | Action |
|---|---|---|
| `team4c/.env.local` | Yes — `team4c/.env.example` | Copy and fill in |
| `team4b/.env` | Yes — `team4b/.env.example` (also `.env.docker.example` for the containerized variant) | Copy and fill in |
| `team4a/.env` | **No — create it directly** | Create from the values in Part C below and [ENVIRONMENT.md](ENVIRONMENT.md) |

**Do not copy another developer's real `.env` file** — generate your own
secrets (commands below); every other value is a safe local default, not
a secret.

```powershell
cd team4c
Copy-Item .env.example .env.local
cd ..\team4b
Copy-Item .env.example .env
cd ..
```

Fill in `team4c\.env.local`:
```
MONGODB_URI=mongodb://localhost:27017/edu-copilot-team-c
AUTH_SECRET=<generate below>
AUTH_URL=http://localhost:3000
AUTH_TRUST_HOST=true
USE_MOCK_TEAM_A=false
USE_MOCK_TEAM_B=false
TEAM_A_API_URL=http://localhost:8001
TEAM_B_API_URL=http://localhost:8002
SERVICE_JWT_PRIVATE_KEY=<generate below>
SERVICE_JWT_KID=m6-es256-2026-01
SERVICE_JWT_ISSUER=https://educopilot.internal
SERVICE_JWT_TTL_SECONDS=300
STORAGE_PROVIDER=
```

Generate `AUTH_SECRET`:
```powershell
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

Generate the service-JWT keypair (one keypair, shared correctly — Team4C
gets the private key, Team4A **and** Team4B both get the same public key):
```powershell
openssl ecparam -genkey -name prime256v1 -noout | openssl pkcs8 -topk8 -nocrypt -out private.pem
openssl ec -in private.pem -pubout -out public.pem
```

Create `team4a\.env` directly (no example file exists for this service):
```
QDRANT_URL=http://localhost:6333
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE_NAME=edu-copilot-team-c
REDIS_BROKER_URL=redis://localhost:6379/0
REDIS_RESULT_BACKEND_URL=redis://localhost:6379/1
CANONICAL_QDRANT_COLLECTION_NAME=educopilot_chunks
SERVICE_JWT_EXPECTED_ISSUER=https://educopilot.internal
SERVICE_JWT_EXPECTED_AUDIENCE=team4a-ingestion
SERVICE_JWT_REQUIRED_SCOPE=ingest
SERVICE_JWT_PUBLIC_KEYS_JSON={"m6-es256-2026-01": "<public.pem contents>"}
FILE_URL_TRUSTED_ORIGINS_JSON=["localhost"]
FILE_URL_REQUIRE_HTTPS=false
```

> **`MONGO_DATABASE_NAME` must be `edu-copilot-team-c`** — Team4A's own
> code default (`educopilot`) does not match Team4C's database. This is
> the single most common local-setup mistake; see
> [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Fill in `team4b\.env`:
```
QDRANT_URL=http://localhost:6333
MONGO_URL=mongodb://localhost:27017
MONGO_DATABASE_NAME=edu-copilot-team-c
REDIS_URL=redis://localhost:6380
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL_NAME=llama3
SERVICE_JWT_EXPECTED_ISSUER=https://educopilot.internal
SERVICE_JWT_EXPECTED_AUDIENCE=team4b-query
SERVICE_JWT_REQUIRED_SCOPE=query
SERVICE_JWT_PUBLIC_KEYS_JSON={"m6-es256-2026-01": "<the SAME public.pem contents>"}
```

Full variable reference: [ENVIRONMENT.md](ENVIRONMENT.md).

### Part D — Install dependencies

```powershell
cd team4c
npm install
cd ..

cd team4a
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..

cd team4b
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
deactivate
cd ..
```
(A virtual environment per Python service is recommended, not strictly
required.)

### Part E — Start infrastructure first

Infrastructure must be up before any of the three services, because they
all connect to it on startup and will fail (or hang) if it isn't
reachable yet.

```powershell
docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest
docker run -d --name team4a-redis -p 6379:6379 redis:7-alpine
docker run -d --name team4b-redis -p 6380:6379 redis:7-alpine
docker run -d --name mongo -p 27017:27017 mongo:7   # or install MongoDB natively instead
```

Qdrant and Redis are always Docker containers in this setup; MongoDB may
be either a Docker container (above) or a native Windows service — both
work identically from Team4A/4B/4C's point of view (`localhost:27017`
either way).

Health checks:
```powershell
curl http://localhost:6333/collections
docker exec team4a-redis redis-cli ping
docker exec team4b-redis redis-cli ping
```

### Part F — Start Ollama

```powershell
ollama list                # see what's already pulled
ollama pull llama3         # the model this project is configured to use
ollama serve                # if not already running as a background service
curl http://localhost:11434/api/tags   # should list llama3
```

### Part G — Start Team4A (Terminal 1)

```powershell
cd team4a
# (activate your venv if you created one)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```
In a **second** terminal, start its Celery worker (required — ingestion
jobs are queued to Celery, not processed inline by the API process):
```powershell
cd team4a
celery -A app.celery_app worker --loglevel=info
```

Expected: `Team4A → http://localhost:8001`.
Health check: `curl http://localhost:8001/health` → `200 OK`.

**On the canonical/product-validation collection**: this local setup's
`CANONICAL_QDRANT_COLLECTION_NAME` default is `educopilot_chunks`, the
frozen collection the Phase 5 RAG validation arc's results are tied to
(see [RAG_ARCHITECTURE.md](RAG_ARCHITECTURE.md)). Do not repoint this at
a different collection casually — if you ever need an isolated
collection for experimentation, override it at the **process level**
(an environment variable set when launching the process, not a `.env`
edit) and never on the collection the validated results depend on.

### Part H — Start Team4B (Terminal 2)

```powershell
cd team4b
uvicorn app.api.main:app --host 0.0.0.0 --port 8002
```
Expected: `Team4B → http://localhost:8002`.
Health check: `curl http://localhost:8002/health` → `200 OK`.

Team4B retrieves and generates grounded answers — see
[TEAM4B.md](TEAM4B.md).

### Part I — Start Team4C (Terminal 3)

```powershell
cd team4c
npm run dev
```
Expected: `Team4C → http://localhost:3000`. This is the actual product —
the frontend/application layer a student uses.

### Part J — Final health check

| Service | Port | Purpose | Health check |
|---|---|---|---|
| MongoDB | 27017 | Product data (Users/Workspaces/Files/Conversations/Messages) | `Get-NetTCPConnection -LocalPort 27017` |
| Team4A | 8001 | Ingestion | `curl http://localhost:8001/health` |
| Team4B | 8002 | RAG/query | `curl http://localhost:8002/health` |
| Team4C | 3000 | Product UI | `curl http://localhost:3000` |
| Qdrant | 6333 | Vector store | `curl http://localhost:6333/collections` |
| Redis (Team4A) | 6379 | Celery broker/result, ingestion locks | `docker exec team4a-redis redis-cli ping` |
| Redis (Team4B) | 6380 | Conversation history | `docker exec team4b-redis redis-cli ping` |
| Ollama | 11434 | Local LLM | `curl http://localhost:11434/api/tags` |

All eight should respond before proceeding.

### Part K — Open the application

http://localhost:3000

1. **Sign up** — create a real local account (any email/password).
2. **Log in** (if not already logged in after signup).
3. **Create a workspace** — name it after a course/subject.
4. **Add material** — upload a PDF, or paste a YouTube URL.
5. **Wait for "Ready"** — status moves uploading → processing → ready.
6. **Open the AI Tutor** tab.
7. **Ask a question** about the material you added.
8. **Verify the answer** is grounded and relevant.
9. **Verify citations** — click one; a PDF citation opens the source file
   at the cited page, a video citation seeks the player to the cited
   timestamp.

### Part L — First-time end-to-end smoke test

```
SIGN UP
  ↓
LOG IN
  ↓
CREATE WORKSPACE
  ↓
ADD PDF (or YouTube URL)
  ↓
WAIT FOR "READY"
  ↓
ASK A QUESTION ABOUT THE MATERIAL
  ↓
VERIFY A GROUNDED ANSWER ARRIVES
  ↓
VERIFY AT LEAST ONE CITATION IS PRESENT AND CLICKABLE
```

Expected results at each step: account created and logged in
immediately; workspace appears in the dashboard; material status reaches
`Ready` (timing depends on document length — see Part A's hardware note);
the AI Tutor produces a real, non-generic answer referencing your
material's actual content; at least one citation chip appears below the
answer and opens/seeks to the correct source location when clicked.

### Part M — How to stop the project

Safe to stop at any time, in any order:
```powershell
# Ctrl+C in each of the Team4A / Team4A-worker / Team4B / Team4C terminals
docker stop qdrant team4a-redis team4b-redis mongo   # if running Mongo via Docker
```

**Do not** run `docker compose down -v` or otherwise delete volumes as a
normal shutdown step — that destroys the data in Qdrant/Redis/MongoDB
containers. `docker stop` (or plain `Ctrl+C` for the manually-run
services) is always sufficient and always safe.

### Part N — Starting again the next day

1. Open Docker Desktop (if it isn't already running).
2. `docker start qdrant team4a-redis team4b-redis mongo` (whichever you
   run via Docker) — **`start`, not `up` or `run`**, so nothing is
   recreated.
3. Confirm Ollama is running (`curl http://localhost:11434/api/tags`).
4. Start Team4A (+ its worker), then Team4B, then Team4C — same commands
   as Parts G–I.
5. Open http://localhost:3000.

### Part O — Common startup failures

| Symptom | Check | Cause | Safe fix |
|---|---|---|---|
| Port already in use | `Get-NetTCPConnection -LocalPort <port>` | Another process (often a previous run of the same service) already bound | Stop the other process, or see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Docker not running | `docker ps` errors | Docker Desktop isn't started | Start Docker Desktop |
| MongoDB not running | `Get-NetTCPConnection -LocalPort 27017` empty | Service/container not started | Start it (Part E) |
| Redis unavailable | `docker exec <container> redis-cli ping` fails | Container not started — remember there are **two** Redis instances | `docker start <container>` |
| Qdrant unavailable | `curl http://localhost:6333/collections` fails | Container not started | `docker start qdrant` |
| Ollama unavailable | `curl http://localhost:11434/api/tags` fails | Ollama not running | `ollama serve` |
| Ollama model missing | `ollama list` doesn't show `llama3` | Model never pulled | `ollama pull llama3` |
| Team4A won't start | error in its own terminal | Usually a missing/wrong `.env` value | Check `team4a\.env` against [ENVIRONMENT.md](ENVIRONMENT.md) |
| Team4B won't start | error in its own terminal | Same as above | Check `team4b\.env` |
| Team4C won't start | error in its own terminal | Same as above, or a stale `.next` build | Check `team4c\.env.local`; `Remove-Item -Recurse -Force .next` and retry |
| Environment variable missing | service logs a config error on boot | A required `.env` value wasn't set | See [ENVIRONMENT.md](ENVIRONMENT.md) |
| Authentication failure | "UntrustedHost" or login loop | `AUTH_URL`/`AUTH_TRUST_HOST` misconfigured, or stale `.next` cache | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Ingestion stuck at "processing" | never reaches "Ready" | Most commonly the Mongo database-name mismatch (Part C) | Set `MONGO_DATABASE_NAME=edu-copilot-team-c` in `team4a\.env` |
| Material "Ready" but AI Tutor never cites it | — | Team4A/Team4B pointed at different Qdrant collections | See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Team4B returns no results | empty retrieval for a real question | Collection mismatch, or the material genuinely isn't ingested yet | Confirm both services' effective collection name in their own startup logs |

Full symptom → cause → diagnostic → fix detail for every item above:
[TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Part P — Orchestration helpers

`scripts/start-all.ps1`, `stop-all.ps1`, `health-check.ps1`,
`e2e-smoke.ps1` exist at the repository root as a starting point for
automating the above — read them before running them on a machine you
care about, since they were authored for one specific development
machine's layout and may need small path adjustments on yours.
