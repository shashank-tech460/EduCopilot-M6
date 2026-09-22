# Troubleshooting

For every problem: **Symptoms → Cause → Safe diagnostic → Safe fix.**
None of these recommend deleting data unless a symptom section says so
explicitly and only as a last resort.

## Docker not running / containers exited

**Symptoms**: Qdrant/Redis/Team4A-in-Docker unreachable; `docker ps` shows
nothing, or `docker ps -a` shows containers in `Exited` state.

**Cause**: Docker Desktop wasn't running, or the host machine restarted.

**Safe diagnostic**:
```powershell
docker ps -a
```

**Safe fix**: start Docker Desktop, then bring the existing containers
back up **without recreating them** (recreating can be unnecessary and,
depending on the container, risks losing unmounted state — always prefer
`start` over `up`/`--force-recreate` when the containers already exist):
```powershell
docker start qdrant team4a-redis team4b-redis   # or your actual container names
```
If using `docker-compose.yml`:
```powershell
cd team4a  # or team4b
docker compose start
```
Verify data survived (point/key counts unchanged):
```powershell
curl http://localhost:6333/collections/educopilot_chunks
```

## MongoDB unavailable

**Symptoms**: Team4C fails to connect on startup; Team4A/Team4B's
generation-authority reads/writes fail.

**Cause**: MongoDB service isn't running.

**Safe diagnostic** (PowerShell):
```powershell
Get-NetTCPConnection -LocalPort 27017 -ErrorAction SilentlyContinue
```

**Safe fix**: start the MongoDB Windows service, or `docker start mongo`
if running it via Docker. Never delete MongoDB's data directory to "fix"
a connection problem — a connection failure is almost never a data
problem.

## Redis unavailable (either instance)

**Symptoms**: Team4A ingestion jobs never start (Celery can't reach its
broker); Team4B's conversation history/session errors.

**Cause**: the Redis container/process isn't running. Remember there are
**two separate Redis instances** — Team4A's (port 6379) and Team4B's
(port 6380) — check both.

**Safe diagnostic**:
```powershell
Get-NetTCPConnection -LocalPort 6379,6380 -ErrorAction SilentlyContinue
docker exec <redis-container> redis-cli ping
```

**Safe fix**: `docker start <redis-container>`, or restart the native
service. Redis's AOF persistence (`--appendonly yes`, if configured — see
`team4a/docker-compose.yml`) means a restart does not lose recent writes.

## Qdrant unavailable

**Symptoms**: ingestion fails at the publish step; retrieval returns
nothing or errors.

**Safe diagnostic**:
```powershell
curl http://localhost:6333/collections
```

**Safe fix**: `docker start qdrant` (or your container name). **Never**
delete or recreate a Qdrant collection to "fix" an availability problem —
recreating discards every point in it. If a collection genuinely doesn't
exist yet on a brand-new setup, Team4A's own startup provisioning check
creates it automatically on first run; you should not need to create one
by hand.

## Ollama unavailable / model not pulled

**Symptoms**: every AI Tutor question fails or times out; Team4B logs show
a connection error to `OLLAMA_URL`.

**Safe diagnostic**:
```powershell
curl http://localhost:11434/api/tags
```

**Safe fix**: start Ollama (`ollama serve`, or via its own background
service), then confirm the configured model exists:
```powershell
ollama pull llama3
```
`OLLAMA_MODEL_NAME` in Team4B's `.env` must match exactly.

## Team4A / Team4B / Team4C unavailable

**Symptoms**: `curl http://localhost:<port>/health` (or `/`) fails to
connect.

**Safe diagnostic**: check the terminal each service is running in for a
startup error (most commonly: a missing/misconfigured environment
variable, or a port already in use).

**Safe fix**: fix the reported error and restart that one service. If a
service has been running for many hours with heavy code-reload activity
during development and starts behaving strangely for no apparent reason
(a real pattern observed during this project's own development: an
unrelated auth-redirect test began timing out after ~7.5 hours of
continuous `next dev` uptime with extensive hot-reload activity), a clean
restart of just that service resolves it — this is a normal characteristic
of long-lived development servers, not a code defect, and is safe (no
data is stored in the dev server process itself).

## Authentication problems

**Symptoms**: "UntrustedHost" error from Auth.js; login redirects loop;
session doesn't persist.

**Cause**: usually `AUTH_URL`/`AUTH_TRUST_HOST` misconfigured, or a stale
cached Next.js build from before an auth-config change.

**Safe fix**:
```powershell
cd team4c
Remove-Item -Recurse -Force .next
npm run dev
```
Confirm `AUTH_URL` matches the URL you're actually opening in the browser
exactly (including port), and `AUTH_TRUST_HOST=true` is set.

## Ingestion stuck / never reaches "Ready"

**Symptoms**: a material stays at `processing` indefinitely, with no
error surfaced.

**Most common cause (real, source-confirmed): a Mongo database-name
mismatch.** Team4A's *default* `MONGO_DATABASE_NAME` (`educopilot`) does
not match Team4C's actual database (`edu-copilot-team-c`). If Team4A is
started with its default, it writes its ingestion-completion record to a
**different Mongo database that quietly exists in parallel** — nothing
errors anywhere, because both databases are valid; Team4C simply never
sees the completion write.

**Safe diagnostic**: confirm Team4A's configured `MONGO_DATABASE_NAME`
matches the database name in Team4C's `MONGODB_URI`:
```powershell
# Compare these two values by hand — do not print full connection strings if they contain credentials
```

**Safe fix**: set `MONGO_DATABASE_NAME=edu-copilot-team-c` in
`team4a\.env` and restart Team4A. See [ENVIRONMENT.md](ENVIRONMENT.md).

**Other causes**: Celery worker not running (the API accepts the job but
nothing processes it — check the worker's own terminal), or the
ingestion-lock lease (see below) genuinely still held by a prior attempt.

## Stale ingestion lock

**Symptoms**: re-ingesting the same document returns `409` — "An
ingestion attempt is already in progress for this document" — even though
no ingestion is actually running.

**Cause**: Team4A's per-document Redis lock (default lease 4 hours) wasn't
released after an abnormal termination.

**Safe diagnostic** (read-only — do not modify the key until you've
confirmed what you're looking at):
```powershell
docker exec <team4a-redis-container> redis-cli TTL "lock:ingestion:<document_id>"
```
A `-2` result means the key is already gone (no lock held); a positive
number is the seconds remaining before it expires naturally.

**Safe fix**: wait for the lease to expire naturally (locks are designed
to self-heal this way), or restart the environment cleanly (a full,
non-destructive service restart — see "Docker not running" above — has
been observed to clear a stale lock as a side effect of the underlying
Redis container restarting). Only delete the specific lock key directly
as a last resort, and only after confirming via the TTL check above that
it is genuinely stale, not actively held by a real in-progress job.

## Qdrant collection mismatch

**Symptoms**: material shows "Ready," but AI Tutor answers never cite it
— as if the material doesn't exist, even though ingestion reported
success.

**Cause**: Team4A (ingestion, writes to `CANONICAL_QDRANT_COLLECTION_NAME`)
and Team4B (retrieval, reads from `QDRANT_COLLECTION_NAME`/whatever
collection it's actually configured against) are pointed at **different**
Qdrant collections. This is a real, previously-encountered failure mode
in this project — an entire collection of correctly-ingested material can
exist while Team4B is configured to query a different, empty-for-that-content
collection.

**Safe diagnostic**: confirm both services' effective collection name
(check each service's own startup logs — both log the collection they
resolved on boot), and directly inspect point counts:
```powershell
curl http://localhost:6333/collections/<collection-name>
```

**Safe fix**: align the two services' collection environment variables
(see [ENVIRONMENT.md](ENVIRONMENT.md)) and restart both. Never delete or
merge collections to "fix" a mismatch — the data in the wrong-configured
collection is not lost, it's just not the one being read; realigning the
configuration is sufficient.

## Environment variable mistakes

See the "Cross-service invariants" section of
[ENVIRONMENT.md](ENVIRONMENT.md) for every value that must match across
services — most "nothing works and there's no clear error" symptoms trace
back to one of those.

## Port conflicts

**Symptoms**: a service fails to start with an "address already in use"
error.

**Safe diagnostic**:
```powershell
Get-NetTCPConnection -LocalPort <port> -ErrorAction SilentlyContinue | Select-Object OwningProcess
Get-Process -Id <OwningProcess>
```

**Safe fix**: stop whatever's already using the port (often a previous,
still-running instance of the same service you're trying to start), or
change the port for one of them consistently across every place that
port is referenced (see [ENVIRONMENT.md](ENVIRONMENT.md) and
[INTEGRATION.md](INTEGRATION.md)).

## Browser / session issues

**Symptoms**: the UI behaves inconsistently after many code changes during
active development (stale content, a component that doesn't reflect a
recent edit).

**Safe fix**: hard-refresh the browser tab, or clear `.next` and restart
the dev server (see "Authentication problems" above) — Turbopack/Next.js
can serve a stale cached build across certain kinds of config changes.
