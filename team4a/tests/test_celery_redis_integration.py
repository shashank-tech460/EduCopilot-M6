"""Live-Redis integration check for Task 1.3.

Deliberately separate from the default unit test suite
(`test_celery_app.py`, `test_progress.py`): those verify configuration and
logic without needing any running service. This file additionally checks
an actual Redis connection, and skips itself automatically if no Redis
server is reachable at the configured broker URL — it never fails the
suite just because Redis isn't running locally.

This test does NOT start a Celery worker or execute a task through the
broker; it only confirms that a real Redis connection can be opened and
used, which is a prerequisite for that. Actual worker execution is a
separate, manual verification step (see the Task 1.3 report).
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

import pytest

from app.config.settings import get_settings


def _redis_is_reachable(url: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


settings = get_settings()
_broker_reachable = _redis_is_reachable(settings.redis_broker_url)

pytestmark = pytest.mark.skipif(
    not _broker_reachable,
    reason=(
        f"No Redis server reachable at {settings.redis_broker_url}; "
        "skipping live-Redis integration check."
    ),
)


def test_can_open_a_real_redis_connection_and_round_trip_a_value():
    import redis

    client = redis.Redis.from_url(settings.redis_broker_url, decode_responses=True)
    client.set("team4a:integration_test_key", "ok")
    try:
        assert client.get("team4a:integration_test_key") == "ok"
    finally:
        client.delete("team4a:integration_test_key")


def test_update_progress_against_real_redis():
    from app.utils.progress import get_progress, update_progress

    job_id = "integration-test-job"
    update_progress(job_id, 50)
    try:
        assert get_progress(job_id) == 50
    finally:
        from app.utils.progress import get_redis_client

        get_redis_client().delete(f"team4a:job:{job_id}:progress")
