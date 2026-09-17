"""Project-wide pytest fixtures.

TASK 10.2 INTEGRATION FIX: `process_pdf`/`process_video`/`process_youtube`
are now genuinely dispatched via real `.delay(...)` calls from the API
routes (app/api/routes.py) -- closing a real, previously-hidden gap where
every upload was accepted but never enqueued to Celery at all (see the
Task 10.2 Integration Fix report for the full diagnosis and fix).

Multiple existing test files across this project build their own FastAPI
app instances around the same `router` (not all of them share a single
fixture), and every one of them is designed around the explicit,
long-standing project invariant "no live Celery, Redis, Qdrant, Whisper,
or YouTube access" (stated in several test files' own module docstrings).
Without a project-wide fix, any test that exercises a real `/ingest/*`
route end-to-end would attempt a genuine Celery broker connection --
confirmed empirically while implementing this integration fix: the full
suite hung indefinitely (Celery/kombu has no fast-fail path for an
unreachable Redis broker on `.delay()`), and once fixed only in one
file's fixture, *other* files' independently-built FastAPI apps still
either hung or received a real 503 (the correct failure-handling
response, but not what those tests -- written before dispatch existed --
expected).

This `autouse=True` fixture mocks the actual Celery dispatch boundary --
`.delay` on the three real, shared task objects imported into
app.api.routes (the exact objects a real Celery worker started via
`celery -A app.celery_app worker` has registered on the same
`celery_app` instance) -- for every single test in this project,
regardless of which fixture or file constructs the FastAPI app under
test. This is deliberately global rather than local to any one fixture,
because the dispatch boundary is a cross-cutting concern this entire
test suite depends on staying mocked, not a concern of any single test
file.

Tests that want to assert on exactly what was dispatched (task name,
job_id, file_path, url, language) request the `dispatched_tasks` fixture
below, which exposes the same recorded list the autouse fixture
populates.
"""

from __future__ import annotations

import pytest

from app.api import routes


@pytest.fixture(autouse=True)
def _mock_celery_dispatch(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def _make_fake_delay(task_name: str):
        def _fake_delay(**kwargs):
            calls.append((task_name, kwargs))

            class _FakeAsyncResult:
                id = "fake-task-id-for-tests"

            return _FakeAsyncResult()

        return _fake_delay

    monkeypatch.setattr(routes.process_pdf, "delay", _make_fake_delay("process_pdf"))
    monkeypatch.setattr(routes.process_video, "delay", _make_fake_delay("process_video"))
    monkeypatch.setattr(routes.process_youtube, "delay", _make_fake_delay("process_youtube"))

    return calls


@pytest.fixture
def dispatched_tasks(_mock_celery_dispatch):
    """The (task_name, kwargs) pairs recorded by the autouse Celery
    dispatch mock above, for tests that want to assert on exactly what
    was dispatched through a real `/ingest/*` request.
    """

    return _mock_celery_dispatch
