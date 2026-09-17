"""Health/readiness endpoints (Production Hardening Task 4).

A separate, dedicated router from app/api/routes.py -- that module's own
docstring states it implements "ONLY the API boundary" for the five
official ingestion/job endpoints (Requirement 9), and operational
health/readiness checks are a distinct concern from that public
ingestion contract. Keeping them here means routes.py (and its five
existing, already-approved endpoints) is completely untouched by this
task.

Two endpoints, with two different purposes:

    GET /health
        "Is this API process alive and able to respond at all?" --
        analogous to a Kubernetes liveness probe / a simple Docker
        HEALTHCHECK target. Does nothing but return 200 -- no
        dependency is checked, so this endpoint stays useful (accurately
        reports "the process itself is fine") even if Redis, Qdrant, or
        anything else is temporarily unavailable. This is the endpoint
        wired into docker-compose.yml's `api` service HEALTHCHECK.

    GET /readyz
        "Is this API capable of serving real Team 4A ingestion
        requests?" -- analogous to a Kubernetes readiness probe.
        Every existing route depends on `JobStore` (Depends(get_job_store))
        for job creation/retrieval/listing (Requirement 9.1-9.5), and in
        production that's always `RedisJobStore` -- so Redis
        reachability is the one dependency whose absence would make this
        API's actual public contract fail for *every* request, not just
        a specific operation. Qdrant is deliberately NOT checked here:
        inspection of app/api/routes.py and app/api/file_storage.py
        confirms the API process itself never imports or contacts
        Qdrant at all (only the Celery worker's Publisher does, later,
        asynchronously) -- so Qdrant's availability has no bearing on
        whether this process can currently accept an ingestion request.
        Whisper and sentence-transformers are not checked for the same
        reason (worker-only, and loaded lazily on first real use, never
        at API-request time).

Both endpoints reuse the exact same `get_job_store` dependency-injection
seam already established in app/api/routes.py -- no second Redis
configuration or connection mechanism is introduced. `RedisJobStore.ping()`
(added in this task) is a bounded, timeout-protected connectivity check
that never raises and never returns the underlying exception, so no
connection string, credential, or stack trace can ever reach an HTTP
response through this path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.api.job_store import JobStore
from app.api.routes import get_job_store

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Process-alive check. No dependency is touched -- always 200 if this
    handler runs at all, since FastAPI itself must be up to run it.

    No explicit log call here beyond what `RequestLoggingMiddleware`
    already emits for every request (Production Hardening Task 6) -- that
    middleware already logs successful /health requests at DEBUG rather
    than INFO (Requirement 9), so a second, redundant log line here would
    add noise, not value.
    """

    return {"status": "healthy"}


@router.get("/readyz")
def readiness(job_store: JobStore = Depends(get_job_store)) -> JSONResponse:
    """Request-serving-capability check.

    Checks Redis reachability via `job_store.ping()` when the injected
    store supports it (the real `RedisJobStore` always does; a test
    double that doesn't implement `ping` is treated as having no
    external dependency to check, so it reports ready -- this never
    raises `AttributeError` against, e.g., `InMemoryJobStore`, which has
    no live connection to ping in the first place).

    A failure is logged here explicitly at WARNING (Requirement 9) --
    more prominent than the generic per-request INFO line
    `RequestLoggingMiddleware` already emits for every request regardless
    of endpoint -- without ever including the Redis URL or any exception
    detail (`job_store.ping()` itself never returns or raises the
    underlying exception, so there is nothing sensitive available here to
    accidentally log in the first place).
    """

    ping = getattr(job_store, "ping", None)
    redis_reachable = ping() if callable(ping) else True

    if not redis_reachable:
        logger.warning("Readiness check failed: Redis unavailable", extra={"dependency": "redis"})
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "reason": "redis_unavailable"},
        )

    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready"})
