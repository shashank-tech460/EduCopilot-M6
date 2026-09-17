"""Redis-backed Ingestion_Job progress tracking.

Matches the official design document exactly:
    "Create app/utils/progress.py with update_progress() helper storing
     progress in Redis"
    Requirements: 8.1, 8.6

This module only stores/reads a job's progress percentage in Redis, keyed
by `IngestionJob.job_id`. It does not implement job persistence generally
(no full IngestionJob is stored here — see Task 1.3 report, section on
scope decisions) and does not implement any ingestion logic.

The Redis client is injectable so unit tests can pass a fake/stub client
instead of requiring a live Redis server.
"""

from __future__ import annotations

from typing import Protocol

from app.config.settings import get_settings


class SupportsGetSet(Protocol):
    """The minimal Redis client surface this module depends on."""

    def set(self, name: str, value: str) -> object: ...

    def get(self, name: str) -> str | bytes | None: ...


def _progress_key(job_id: str) -> str:
    return f"team4a:job:{job_id}:progress"


def _allowed_progress_values() -> set[int]:
    """The valid pipeline-stage progress values, drawn from Settings.

    Matches the validation already enforced on `IngestionJob.progress`
    (Task 1.2) so this helper can't write a value the model would reject.
    """

    settings = get_settings()
    return {
        0,
        settings.progress_extraction_pct,
        settings.progress_chunking_pct,
        settings.progress_embedding_pct,
        settings.progress_publication_pct,
    }


def get_redis_client() -> SupportsGetSet:
    """Build a Redis client from the configured result-backend URL.

    Requirement 8.6: Redis is used as both the Celery broker and the
    result backend / status-persistence store. Job progress is
    status-persistence, so it is stored via the result-backend URL.
    """

    import redis  # imported lazily so importing this module never requires

    settings = get_settings()
    return redis.Redis.from_url(settings.redis_result_backend_url, decode_responses=True)


def update_progress(job_id: str, percentage: int, *, redis_client: SupportsGetSet | None = None) -> None:
    """Persist an Ingestion_Job's progress percentage to Redis.

    Args:
        job_id: The IngestionJob.job_id this progress belongs to.
        percentage: One of the configured pipeline-stage percentages
            (default: 0, 25, 50, 75, 100).
        redis_client: Optional injected client (for tests). Defaults to a
            real client built from Settings.

    Raises:
        ValueError: if job_id is empty or percentage is not one of the
            configured pipeline-stage values.
    """

    if not job_id:
        raise ValueError("job_id must be a non-empty string")

    allowed = _allowed_progress_values()
    if percentage not in allowed:
        raise ValueError(
            f"percentage must be one of {sorted(allowed)} (configured pipeline "
            f"stage boundaries), got {percentage}"
        )

    client = redis_client or get_redis_client()
    client.set(_progress_key(job_id), str(percentage))


def get_progress(job_id: str, *, redis_client: SupportsGetSet | None = None) -> int | None:
    """Read back an Ingestion_Job's last recorded progress percentage.

    Returns None if no progress has been recorded yet for this job_id.
    """

    if not job_id:
        raise ValueError("job_id must be a non-empty string")

    client = redis_client or get_redis_client()
    value = client.get(_progress_key(job_id))
    if value is None:
        return None
    return int(value)
