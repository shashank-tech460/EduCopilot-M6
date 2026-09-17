"""Unit tests for Task 1.3: Celery application configuration.

These tests verify configuration wiring only — they do not require a live
Redis server or a running Celery worker. See
`tests/test_celery_redis_integration.py` for the separate, auto-skipping
live-Redis check.
"""

from app.celery_app import SMOKE_TEST_TASK_NAME, _ensure_local_demo_qdrant_collection, build_celery_app, celery_app, queue_smoke_test
from app.config.settings import Settings


def test_celery_app_imports_successfully():
    # If this module failed to import, this test file would fail to collect.
    assert celery_app is not None


def test_broker_url_comes_from_settings():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert app.conf.broker_url == settings.redis_broker_url


def test_result_backend_comes_from_settings():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert app.conf.result_backend == settings.redis_result_backend_url


def test_late_acknowledgement_is_enabled():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert settings.celery_task_acks_late is True
    assert app.conf.task_acks_late is True


def test_worker_prefetch_multiplier_is_one():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert settings.celery_worker_prefetch_multiplier == 1
    assert app.conf.worker_prefetch_multiplier == 1


def test_visibility_timeout_is_60_seconds():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert settings.celery_visibility_timeout_seconds == 60
    assert app.conf.broker_transport_options["visibility_timeout"] == 60
    assert app.conf.result_backend_transport_options["visibility_timeout"] == 60


def test_worker_concurrency_defaults_to_ten():
    settings = Settings(_env_file=None)
    app = build_celery_app(settings)
    assert settings.celery_worker_concurrency == 10
    assert app.conf.worker_concurrency == 10


def test_environment_overrides_flow_through_to_celery_config(monkeypatch):
    monkeypatch.setenv("CELERY_WORKER_CONCURRENCY", "20")
    monkeypatch.setenv("CELERY_VISIBILITY_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("REDIS_BROKER_URL", "redis://redis.internal:6379/0")
    monkeypatch.setenv("REDIS_RESULT_BACKEND_URL", "redis://redis.internal:6379/1")

    overridden_settings = Settings(_env_file=None)
    app = build_celery_app(overridden_settings)

    assert app.conf.worker_concurrency == 20
    assert app.conf.broker_transport_options["visibility_timeout"] == 120
    assert app.conf.broker_url == "redis://redis.internal:6379/0"
    assert app.conf.result_backend == "redis://redis.internal:6379/1"

    # The default module-level app was built once at import time from the
    # cached Settings singleton, before these env vars were set. It must
    # remain unaffected — confirming build_celery_app() does not mutate
    # global state and each call is independently configurable.
    assert celery_app.conf.worker_concurrency == 10


def test_smoke_test_task_is_registered():
    assert SMOKE_TEST_TASK_NAME in celery_app.tasks
    assert celery_app.tasks[SMOKE_TEST_TASK_NAME] is queue_smoke_test


def test_smoke_test_task_runs_synchronously_without_a_broker():
    # Calling a Celery task directly (not via .delay()/.apply_async())
    # executes it in-process and requires no broker connection — this is
    # the standard way to unit test task logic.
    result = queue_smoke_test(job_id="abc-123")
    assert result == {"job_id": "abc-123", "ok": True}


def test_smoke_test_task_rejects_empty_job_id():
    import pytest

    with pytest.raises(ValueError):
        queue_smoke_test(job_id="")


def test_build_celery_app_registers_smoke_task_on_each_instance():
    # Each call builds an independent Celery app with its own task registry.
    settings = Settings(_env_file=None)
    app_a = build_celery_app(settings)
    app_b = build_celery_app(settings)
    assert app_a is not app_b
    assert SMOKE_TEST_TASK_NAME in app_a.tasks
    assert SMOKE_TEST_TASK_NAME in app_b.tasks


# ---------------------------------------------------------------------------
# _ensure_local_demo_qdrant_collection (Option B: self-contained Compose/
# local/demo Qdrant provisioning -- NOT Team 4A taking ownership of Team
# 4B's shared production collection; see that function's own docstring
# and the diagnosis report this responds to).
# ---------------------------------------------------------------------------


class _FakeCollection:
    def __init__(self, name):
        self.name = name


class _FakeCollectionsResponse:
    def __init__(self, names):
        self.collections = [_FakeCollection(n) for n in names]


class _FakeQdrantAdminClient:
    """A fake exposing only the two methods this function actually needs
    (`get_collections`, `create_collection`) -- matching the real
    `qdrant_client.QdrantClient`'s own interface for those two calls,
    not `Publisher`'s deliberately narrower `QdrantClientProtocol`
    (which only has `upsert`) -- these are two genuinely different
    concerns, confirmed not to overlap.
    """

    def __init__(self, existing_names=(), raise_on_get_collections=None):
        self.existing = set(existing_names)
        self.create_calls: list[tuple[str, object]] = []
        self.get_collections_calls = 0
        self._raise_on_get_collections = raise_on_get_collections

    def get_collections(self):
        self.get_collections_calls += 1
        if self._raise_on_get_collections is not None:
            raise self._raise_on_get_collections
        return _FakeCollectionsResponse(self.existing)

    def create_collection(self, collection_name, vectors_config):
        self.create_calls.append((collection_name, vectors_config))
        self.existing.add(collection_name)


def test_qdrant_collection_already_exists_does_nothing():
    settings = Settings(qdrant_collection_name="team4a_ingested_chunks", _env_file=None)
    client = _FakeQdrantAdminClient(existing_names=["team4a_ingested_chunks"])

    _ensure_local_demo_qdrant_collection(settings, client=client)

    assert client.create_calls == []
    assert client.get_collections_calls == 1


def test_qdrant_collection_missing_is_created():
    settings = Settings(qdrant_collection_name="team4a_ingested_chunks", _env_file=None)
    client = _FakeQdrantAdminClient(existing_names=[])

    _ensure_local_demo_qdrant_collection(settings, client=client)

    assert len(client.create_calls) == 1
    created_name, _vectors_config = client.create_calls[0]
    assert created_name == "team4a_ingested_chunks"


def test_qdrant_collection_initialization_is_idempotent_across_repeated_calls():
    settings = Settings(qdrant_collection_name="team4a_ingested_chunks", _env_file=None)
    client = _FakeQdrantAdminClient(existing_names=[])

    _ensure_local_demo_qdrant_collection(settings, client=client)
    _ensure_local_demo_qdrant_collection(settings, client=client)
    _ensure_local_demo_qdrant_collection(settings, client=client)

    # Only the FIRST call actually creates it; the client's own state
    # (existing_names, mutated by create_collection) makes every
    # subsequent call correctly take the "already exists" branch.
    assert len(client.create_calls) == 1


def test_qdrant_collection_uses_the_configured_embedding_dimensions_not_hardcoded():
    for configured_size in (384, 512, 768):
        settings = Settings(
            qdrant_collection_name="team4a_ingested_chunks",
            embedding_dimensions=configured_size,
            _env_file=None,
        )
        client = _FakeQdrantAdminClient(existing_names=[])

        _ensure_local_demo_qdrant_collection(settings, client=client)

        _name, vectors_config = client.create_calls[0]
        assert vectors_config.size == configured_size


def test_qdrant_collection_uses_cosine_distance():
    from qdrant_client.models import Distance

    settings = Settings(qdrant_collection_name="team4a_ingested_chunks", _env_file=None)
    client = _FakeQdrantAdminClient(existing_names=[])

    _ensure_local_demo_qdrant_collection(settings, client=client)

    _name, vectors_config = client.create_calls[0]
    assert vectors_config.distance == Distance.COSINE


def test_qdrant_temporarily_unavailable_does_not_raise():
    """Requirement 8: Qdrant can be transiently unavailable at worker
    startup (Compose's healthcheck-gated `depends_on` ordering is still
    asynchronous with respect to Qdrant's own internal readiness) -- this
    must never crash worker startup, only log a warning.
    """

    settings = Settings(qdrant_collection_name="team4a_ingested_chunks", _env_file=None)
    client = _FakeQdrantAdminClient(raise_on_get_collections=ConnectionError("simulated: Qdrant not ready yet"))

    _ensure_local_demo_qdrant_collection(settings, client=client)  # must not raise

    assert client.create_calls == []


def test_qdrant_unavailable_warning_does_not_leak_connection_details(caplog):
    import logging

    settings = Settings(
        qdrant_collection_name="team4a_ingested_chunks",
        qdrant_url="http://secret-internal-host:6333",
        qdrant_api_key="super-secret-key-12345",
        _env_file=None,
    )
    client = _FakeQdrantAdminClient(
        raise_on_get_collections=ConnectionError("connect to super-secret-key-12345@secret-internal-host failed")
    )

    with caplog.at_level(logging.WARNING):
        _ensure_local_demo_qdrant_collection(settings, client=client)

    warning_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-key-12345" not in warning_text
    assert "secret-internal-host" not in warning_text


def test_qdrant_collection_construction_reuses_the_real_qdrant_client_type_when_no_client_injected(monkeypatch):
    """No second Qdrant client abstraction is introduced -- when no
    `client` is injected, this constructs the same real
    `qdrant_client.QdrantClient` class `RealQdrantClient` itself wraps.
    """

    import qdrant_client

    captured = {}

    class _RecordingQdrantClient:
        def __init__(self, url, api_key, check_compatibility):
            captured["url"] = url
            captured["api_key"] = api_key
            captured["check_compatibility"] = check_compatibility

        def get_collections(self):
            return _FakeCollectionsResponse(["team4a_ingested_chunks"])

    monkeypatch.setattr(qdrant_client, "QdrantClient", _RecordingQdrantClient)

    settings = Settings(
        qdrant_collection_name="team4a_ingested_chunks",
        qdrant_url="http://qdrant:6333",
        _env_file=None,
    )

    _ensure_local_demo_qdrant_collection(settings)  # no client injected

    assert captured["url"] == "http://qdrant:6333"
    assert captured["check_compatibility"] is False


def test_existing_publisher_retry_and_failure_behavior_is_completely_unmodified():
    """This fix must not touch Publisher's own retry/backoff/publish_failed
    contract at all -- verified by re-running the exact existing
    Publisher property tests' underlying scenario here: a genuine (not
    "collection missing") write failure still retries and still reports
    publish_failed exactly as before.
    """

    from app.pipeline.publisher import Publisher
    from app.models.schemas import JobStatus
    from tests.test_publisher import FakeQdrantClient, make_settings, make_pdf_enriched
    from app.pipeline.chunker import Chunker
    from app.pipeline.metadata import MetadataEnricher

    chunker = Chunker()
    enricher = MetadataEnricher()
    enriched = make_pdf_enriched(chunker, enricher, page_numbers=(1,))
    embeddings = [[0.1] * 384 for _ in enriched]

    client = FakeQdrantClient(fail_batch_indices={1})  # page_number 1 -> always fails -> permanent failure
    publisher = Publisher(settings=make_settings(publisher_retry_count=3), qdrant_client=client, sleep_fn=lambda s: None)

    result = publisher.publish(enriched, embeddings)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert client._call_count == 4  # 1 initial attempt + 3 retries, unchanged
