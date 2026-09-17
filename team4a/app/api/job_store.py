"""Task 10.1/10.2 job-state boundary.

`JobStore` is a small Protocol so the API routes (Task 10.1) and the
Celery tasks (Task 10.2) can share job state without depending on a
concrete storage technology.

`InMemoryJobStore` (Task 10.1) is an explicit, temporary, single-process
stand-in -- fine for isolated tests, but NOT usable in a real deployment:
a Celery worker runs in a *separate process* from the FastAPI app, so an
in-memory dict in one process is invisible to the other. This is exactly
the "genuine Task 10.2 integration issue" the official Task 10.2 brief
anticipated: `GET /jobs/{job_id}` cannot see updates a Celery worker makes
unless both share real, cross-process storage.

`RedisJobStore` (Task 10.2) resolves this using Redis -- already the
approved technology for "Job_Manager task distribution and status
persistence" (Requirement 8.6) and already configured in Task 1.1's
Settings and used the same way by `app/utils/progress.py` (Task 1.3).
This is a minimal addition: one Redis LIST for job-creation order (so
pagination has a stable order) plus one Redis STRING per job, storing
`IngestionJob.model_dump_json()`. No new database technology was
introduced.
"""

from __future__ import annotations

import threading
from typing import Protocol

from app.config.settings import Settings, get_settings
from app.models.schemas import IngestionJob


class JobStore(Protocol):
    """The minimal interface both the API routes and Celery tasks need for job state."""

    def create(self, job: IngestionJob) -> None:
        """Persist a newly created job."""
        ...

    def get(self, job_id: str) -> IngestionJob | None:
        """Return the job for `job_id`, or None if it doesn't exist."""
        ...

    def update(self, job: IngestionJob) -> None:
        """Persist an already-created job's updated state (status/progress/etc.)."""
        ...

    def list(self, page: int, page_size: int) -> tuple[list[IngestionJob], int]:
        """Return (jobs on this page, total job count), in creation order."""
        ...


class InMemoryJobStore:
    """Temporary in-process JobStore -- see module docstring.

    Thread-safe for the simple dict/list operations used here (a single
    lock around each method), which is sufficient for FastAPI's
    threadpool-backed sync route handlers and for unit tests; it is NOT
    multi-process safe and NOT durable across restarts. Retained
    specifically for isolated Task 10.1/10.2 tests -- production routing
    now defaults to `RedisJobStore` (see app/api/routes.py).
    """

    def __init__(self) -> None:
        self._jobs: dict[str, IngestionJob] = {}
        self._creation_order: list[str] = []
        self._lock = threading.Lock()

    def create(self, job: IngestionJob) -> None:
        with self._lock:
            self._jobs[job.job_id] = job
            self._creation_order.append(job.job_id)

    def get(self, job_id: str) -> IngestionJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job: IngestionJob) -> None:
        with self._lock:
            if job.job_id not in self._jobs:
                raise KeyError(f"Cannot update unknown job_id: {job.job_id!r}")
            self._jobs[job.job_id] = job

    def list(self, page: int, page_size: int) -> tuple[list[IngestionJob], int]:
        with self._lock:
            total = len(self._creation_order)
            start = (page - 1) * page_size
            end = start + page_size
            page_ids = self._creation_order[start:end]
            return [self._jobs[job_id] for job_id in page_ids], total


class RedisJobStore:
    """Redis-backed JobStore (Task 10.2) -- see module docstring for why
    this is required for real (multi-process) Celery/API integration.

    Uses `settings.redis_result_backend_url`, matching the precedent
    already set by `app/utils/progress.py` for job-status-related Redis
    storage (distinct from the broker URL used for task queueing).

    The Redis client is injectable so unit tests can pass a fake/stub
    client instead of requiring a live Redis server (same pattern as
    `app/utils/progress.py`).
    """

    _ORDER_KEY = "team4a:job_order"

    def __init__(self, settings: Settings | None = None, redis_client=None) -> None:
        self._settings = settings or get_settings()
        self._redis = redis_client or self._build_client()

    def _build_client(self):
        import redis

        # Production Hardening Task 4: bounded socket timeouts (not just
        # for the new readiness check -- this applies to every Redis
        # operation this store performs) so a genuinely unreachable Redis
        # fails fast rather than blocking indefinitely. 2 seconds is
        # generous for a local-network Redis call while still keeping a
        # readiness probe fast.
        return redis.Redis.from_url(
            self._settings.redis_result_backend_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    def ping(self) -> bool:
        """Lightweight, bounded connectivity check for GET /readyz.

        Returns True if Redis responds within the client's configured
        socket timeout, False for any failure whatsoever -- deliberately
        never raises and never returns the underlying exception, so a
        caller can never accidentally leak connection details (the
        exception message could contain the Redis URL/credentials) into
        an HTTP response.
        """

        try:
            return bool(self._redis.ping())
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _job_key(job_id: str) -> str:
        return f"team4a:job:{job_id}"

    def create(self, job: IngestionJob) -> None:
        self._redis.set(self._job_key(job.job_id), job.model_dump_json())
        self._redis.rpush(self._ORDER_KEY, job.job_id)

    def get(self, job_id: str) -> IngestionJob | None:
        raw = self._redis.get(self._job_key(job_id))
        if raw is None:
            return None
        return IngestionJob.model_validate_json(raw)

    def update(self, job: IngestionJob) -> None:
        if self._redis.get(self._job_key(job.job_id)) is None:
            raise KeyError(f"Cannot update unknown job_id: {job.job_id!r}")
        self._redis.set(self._job_key(job.job_id), job.model_dump_json())

    def list(self, page: int, page_size: int) -> tuple[list[IngestionJob], int]:
        total = self._redis.llen(self._ORDER_KEY)
        start = (page - 1) * page_size
        end = start + page_size - 1  # LRANGE's end index is inclusive
        job_ids = self._redis.lrange(self._ORDER_KEY, start, end)
        jobs = [self.get(job_id) for job_id in job_ids]
        return [job for job in jobs if job is not None], total
