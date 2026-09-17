"""Unit tests for Task 1.3: `app/utils/progress.py`.

Uses a hand-rolled fake Redis client (get/set only) so these tests never
require a live Redis server.
"""

import pytest

from app.utils.progress import get_progress, update_progress


class FakeRedis:
    """Minimal in-memory stand-in for the subset of redis.Redis used here."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, name: str, value: str) -> bool:
        self._store[name] = value
        return True

    def get(self, name: str) -> str | None:
        return self._store.get(name)


def test_update_and_get_progress_round_trip():
    fake = FakeRedis()
    update_progress("job-1", 25, redis_client=fake)
    assert get_progress("job-1", redis_client=fake) == 25


def test_get_progress_returns_none_when_unset():
    fake = FakeRedis()
    assert get_progress("never-seen-job", redis_client=fake) is None


@pytest.mark.parametrize("valid_value", [0, 25, 50, 75, 100])
def test_update_progress_accepts_configured_stage_values(valid_value):
    fake = FakeRedis()
    update_progress("job-1", valid_value, redis_client=fake)
    assert get_progress("job-1", redis_client=fake) == valid_value


@pytest.mark.parametrize("invalid_value", [-1, 10, 40, 60, 99, 101])
def test_update_progress_rejects_non_stage_values(invalid_value):
    fake = FakeRedis()
    with pytest.raises(ValueError):
        update_progress("job-1", invalid_value, redis_client=fake)


def test_update_progress_rejects_empty_job_id():
    fake = FakeRedis()
    with pytest.raises(ValueError):
        update_progress("", 25, redis_client=fake)


def test_get_progress_rejects_empty_job_id():
    fake = FakeRedis()
    with pytest.raises(ValueError):
        get_progress("", redis_client=fake)


def test_progress_keys_are_namespaced_per_job():
    fake = FakeRedis()
    update_progress("job-a", 25, redis_client=fake)
    update_progress("job-b", 75, redis_client=fake)
    assert get_progress("job-a", redis_client=fake) == 25
    assert get_progress("job-b", redis_client=fake) == 75
