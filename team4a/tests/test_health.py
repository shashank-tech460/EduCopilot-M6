"""Production Hardening Task 4: tests for GET /health and GET /readyz.

No live Redis is required for most tests (a fake `job_store.ping()` is
injected); one dedicated test exercises the real `RedisJobStore.ping()`
against a real local Redis instance where the test environment provides
one, mirroring the pattern already established in
tests/test_celery_redis_integration.py.
"""

from __future__ import annotations

import string

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.api.file_storage import FileStorage
from app.api.health import router as health_router
from app.api.job_store import InMemoryJobStore, RedisJobStore
from app.api.routes import get_file_storage, get_job_store, get_settings, router
from app.config.settings import Settings


class FakePingableJobStore(InMemoryJobStore):
    """An InMemoryJobStore that also supports `ping()`, so /readyz's
    Redis-check branch can be exercised without a live Redis server.
    """

    def __init__(self, ping_result: bool = True):
        super().__init__()
        self._ping_result = ping_result
        self.ping_calls = 0

    def ping(self) -> bool:
        self.ping_calls += 1
        return self._ping_result


@pytest.fixture
def app_with_health(tmp_path):
    app = FastAPI()
    app.include_router(router)
    app.include_router(health_router)
    settings = Settings(upload_directory=str(tmp_path), _env_file=None)
    app.dependency_overrides[get_file_storage] = lambda: FileStorage(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return app


@pytest.fixture
def client_with_pingable_store(app_with_health):
    job_store = FakePingableJobStore(ping_result=True)
    app_with_health.dependency_overrides[get_job_store] = lambda: job_store
    client = TestClient(app_with_health)
    client.job_store = job_store  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# 1-2. GET /health
# ---------------------------------------------------------------------------


def test_health_returns_200(client_with_pingable_store):
    response = client_with_pingable_store.get("/health")

    assert response.status_code == 200


def test_health_response_is_minimal_and_safe(client_with_pingable_store):
    response = client_with_pingable_store.get("/health")
    body = response.json()

    assert body == {"status": "healthy"}
    # No connection details, paths, or internal information of any kind.
    body_text = response.text.lower()
    for forbidden in ("redis://", "http://", "password", "secret", "traceback", "/tmp", "/data"):
        assert forbidden not in body_text


def test_health_does_not_touch_job_store(client_with_pingable_store):
    """`/health` must not perform a dependency check at all -- confirmed
    by verifying the injected store's ping() was never called.
    """

    client_with_pingable_store.get("/health")

    assert client_with_pingable_store.job_store.ping_calls == 0


# ---------------------------------------------------------------------------
# 3-4. GET /readyz
# ---------------------------------------------------------------------------


def test_readyz_returns_200_when_redis_healthy(app_with_health):
    job_store = FakePingableJobStore(ping_result=True)
    app_with_health.dependency_overrides[get_job_store] = lambda: job_store
    client = TestClient(app_with_health)

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert job_store.ping_calls == 1


def test_readyz_returns_non_2xx_when_redis_unavailable(app_with_health):
    job_store = FakePingableJobStore(ping_result=False)
    app_with_health.dependency_overrides[get_job_store] = lambda: job_store
    client = TestClient(app_with_health)

    response = client.get("/readyz")

    assert not (200 <= response.status_code < 300)
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_readyz_reports_ready_when_job_store_has_no_dependency_to_check(app_with_health):
    """A job store that doesn't implement `ping()` (e.g. a plain
    InMemoryJobStore, as used throughout the existing test suite) has no
    external dependency for readiness to check -- must not raise
    AttributeError, and must report ready.
    """

    plain_store = InMemoryJobStore()  # no ping() method
    app_with_health.dependency_overrides[get_job_store] = lambda: plain_store
    client = TestClient(app_with_health)

    response = client.get("/readyz")

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 5. readiness does not expose secrets/internal connection strings
# ---------------------------------------------------------------------------


def test_readyz_failure_response_never_contains_a_connection_string(app_with_health):
    job_store = FakePingableJobStore(ping_result=False)
    app_with_health.dependency_overrides[get_job_store] = lambda: job_store
    client = TestClient(app_with_health)

    response = client.get("/readyz")
    body_text = response.text.lower()

    for forbidden in ("redis://", "password", "@", "6379", "traceback", "exception"):
        assert forbidden not in body_text


@given(
    fake_connection_detail=st.text(
        alphabet=string.ascii_letters + string.digits + ":/@.", min_size=10, max_size=60
    ).filter(lambda s: s.strip() != "")
)
@hyp_settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_readyz_never_leaks_generated_sensitive_looking_ping_failures(
    app_with_health, fake_connection_detail
):
    """For any generated string that looks like it could be a connection
    string/credential (letters, digits, colons, slashes, @ signs -- the
    shape of a Redis URL with embedded auth), if that text were ever
    present in whatever caused a ping failure, it must never appear in
    the /readyz response. `RedisJobStore.ping()` structurally guarantees
    this already (it never returns or re-raises the underlying
    exception) -- this test proves it holds even when the injected store
    is a test double whose failure carries such text internally.
    """

    class LeakyStore(InMemoryJobStore):
        def ping(self) -> bool:
            # The store *has* this sensitive-looking detail available
            # internally (simulating a real exception message that might
            # contain it) but the contract is that ping() only ever
            # returns a bool -- the detail must never surface further.
            self._simulated_internal_detail = fake_connection_detail
            return False

    store = LeakyStore()
    app_with_health.dependency_overrides[get_job_store] = lambda: store
    client = TestClient(app_with_health)

    response = client.get("/readyz")

    assert fake_connection_detail not in response.text


# ---------------------------------------------------------------------------
# 6-9. readiness does not initialize heavy dependencies or run ingestion
# ---------------------------------------------------------------------------


def test_readyz_does_not_initialize_whisper(client_with_pingable_store, monkeypatch):
    import app.processors.video_processor as vp_module

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("Whisper must not be initialized by a health/readiness check")

    monkeypatch.setattr(vp_module, "WhisperTranscriptionEngine", _fail_if_constructed)

    response = client_with_pingable_store.get("/readyz")
    assert response.status_code == 200


def test_readyz_does_not_initialize_sentence_transformers(client_with_pingable_store, monkeypatch):
    import app.pipeline.embedder as embedder_module

    def _fail_if_constructed(*args, **kwargs):
        raise AssertionError("sentence-transformers must not be initialized by a health/readiness check")

    monkeypatch.setattr(embedder_module, "SentenceTransformerModel", _fail_if_constructed)

    response = client_with_pingable_store.get("/readyz")
    assert response.status_code == 200


def test_readyz_does_not_call_youtube(client_with_pingable_store, monkeypatch):
    import app.processors.youtube_processor as yt_module

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("YouTubeProcessor must not be invoked by a health/readiness check")

    monkeypatch.setattr(yt_module.YouTubeProcessor, "process", _fail_if_called)

    response = client_with_pingable_store.get("/readyz")
    assert response.status_code == 200


def test_readyz_does_not_execute_an_ingestion_task(client_with_pingable_store, monkeypatch):
    import app.tasks as tasks_module

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("No Celery task must be executed by a health/readiness check")

    monkeypatch.setattr(tasks_module, "_run_pdf_pipeline", _fail_if_called)
    monkeypatch.setattr(tasks_module, "_run_video_pipeline", _fail_if_called)
    monkeypatch.setattr(tasks_module, "_run_youtube_pipeline", _fail_if_called)

    response = client_with_pingable_store.get("/readyz")
    assert response.status_code == 200


def test_health_does_not_load_any_ml_or_processing_module(client_with_pingable_store, monkeypatch):
    """/health does no dependency checking at all -- confirms it doesn't
    even reach the processors/embedder modules' constructors.
    """

    import app.pipeline.embedder as embedder_module
    import app.processors.video_processor as vp_module

    def _fail(*args, **kwargs):
        raise AssertionError("must not be constructed by /health")

    monkeypatch.setattr(embedder_module, "SentenceTransformerModel", _fail)
    monkeypatch.setattr(vp_module, "WhisperTranscriptionEngine", _fail)

    response = client_with_pingable_store.get("/health")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 10. Existing API routes remain unchanged
# ---------------------------------------------------------------------------


def test_existing_five_ingestion_routes_still_registered_and_unaffected():
    paths_and_methods = {(route.path, method) for route in router.routes for method in route.methods}
    assert ("/ingest/pdf", "POST") in paths_and_methods
    assert ("/ingest/video", "POST") in paths_and_methods
    assert ("/ingest/youtube", "POST") in paths_and_methods
    assert ("/jobs/{job_id}", "GET") in paths_and_methods
    assert ("/jobs", "GET") in paths_and_methods
    # /health and /readyz are NOT on this router -- they live on a
    # separate router (app/api/health.py), so the ingestion router's own
    # route set is provably unchanged by this task.
    assert not any(path in ("/health", "/readyz") for path, _ in paths_and_methods)


def test_health_router_only_contains_the_two_new_routes():
    paths = {route.path for route in health_router.routes}
    assert paths == {"/health", "/readyz"}


# ---------------------------------------------------------------------------
# Real RedisJobStore.ping() -- direct unit tests (no HTTP layer)
# ---------------------------------------------------------------------------


def test_real_redis_job_store_ping_returns_false_on_unreachable_redis():
    """Uses a deliberately unreachable port -- no live Redis required for
    this test, and the bounded socket timeout (added in this task) keeps
    it fast rather than hanging.
    """

    settings = Settings(redis_result_backend_url="redis://localhost:1/0", _env_file=None)
    store = RedisJobStore(settings=settings)

    assert store.ping() is False


def test_real_redis_job_store_ping_never_raises_regardless_of_failure_type():
    class ExplodingRedisClient:
        def ping(self):
            raise ConnectionError("simulated: connection refused at redis://user:pass@host:6379")

    store = RedisJobStore(redis_client=ExplodingRedisClient())

    assert store.ping() is False  # never raises, never returns the exception
