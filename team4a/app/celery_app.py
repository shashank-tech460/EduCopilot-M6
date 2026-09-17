"""Team 4A Celery application (Job_Manager infrastructure).

Location matches the official design document exactly:
    "1.3 Set up Celery app with Redis broker and backend:
     Create app/celery_app.py configuring broker, backend, task_acks_late=True,
     worker_prefetch_multiplier=1, visibility_timeout=60"
    Requirements: 8.1, 8.6

This module wires the Celery application to Redis using the configuration
already defined in `app.config.settings.Settings` (Task 1.1) — no values are
hardcoded here. It does not implement any ingestion logic: PDF, video,
YouTube, chunking, embedding, and Qdrant-publishing tasks are introduced in
later tasks (2.1, 3.1, 4.1, 6.1, 7.1, 8.1, 8.2, 10.2).

The only task registered in this module is `queue_smoke_test`, a minimal
task used solely to verify that this Celery app can register and run a
task end to end. It performs no ingestion work and is superseded by the
real tasks (`process_pdf`, `process_video`, `process_youtube`) created in
`app/tasks.py` during Task 10.2.
"""

from __future__ import annotations

import logging
from typing import Any

from celery import Celery

from app.config.settings import Settings, get_settings
from app.logging_config import configure_logging

#: Name of the minimal smoke-test task registered on every app built here.
SMOKE_TEST_TASK_NAME = "team4a.queue_smoke_test"


def build_celery_app(settings: Settings | None = None) -> Celery:
    """Build a Celery application wired entirely from `Settings`.

    Exposed as a function (rather than only a module-level singleton) so
    tests can construct an app from an arbitrary `Settings` instance —
    e.g. one with environment-variable overrides applied — without needing
    to reload this module or mutate global state.

    Args:
        settings: Settings to configure the app from. Defaults to the
            cached `get_settings()` singleton.
    """

    settings = settings or get_settings()

    app = Celery(
        "team4a_ingestion",
        broker=settings.redis_broker_url,
        backend=settings.redis_result_backend_url,
    )

    app.conf.update(
        # Requirement 8.6 / late-ack rule (Task 1.3 section 9):
        # a task must not be acknowledged until it has actually completed,
        # so a crashed worker's in-flight job becomes visible for requeue.
        task_acks_late=settings.celery_task_acks_late,
        # Task 1.3 section 9: each worker process reserves only one
        # unacknowledged task at a time, avoiding head-of-line blocking
        # across long-running ingestion jobs.
        worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
        # Task 1.3 section 8 / Requirement 8.5: minimum concurrent
        # Ingestion_Jobs the Job_Manager must support.
        worker_concurrency=settings.celery_worker_concurrency,
        # Task 1.3 section 7 / Requirement 8.5: an unacknowledged task
        # becomes visible again (and eligible for requeue to another
        # worker) after this many seconds. This is the Redis transport's
        # mechanism for "detect the failure within 60 seconds and
        # re-queue the job" — no custom requeue logic is implemented here.
        broker_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
        },
        result_backend_transport_options={
            "visibility_timeout": settings.celery_visibility_timeout_seconds,
        },
        task_default_queue="team4a_ingestion",
        timezone="UTC",
        enable_utc=True,
    )

    @app.task(name=SMOKE_TEST_TASK_NAME)
    def queue_smoke_test(job_id: str) -> dict:
        """Echo back a job_id to prove Celery can register and run a task.

        This is the "Celery task -> IngestionJob.job_id" association point
        that later ingestion tasks (Task 10.2) will build on: a real task
        will receive an `IngestionJob.job_id`, do the actual processing,
        and update job status/progress. This placeholder does neither —
        it only confirms the wiring works.
        """

        if not job_id:
            raise ValueError("job_id must be a non-empty string")
        return {"job_id": job_id, "ok": True}

    return app


#: Module-level Celery app used by `celery -A app.celery_app worker ...`
#: and importable by later worker/task modules.
celery_app = build_celery_app()

# Production Hardening Task 6: configure logging once this module is
# loaded (whether by a real worker process or by importing it for
# tests) -- idempotent, see app/logging_config.py. Startup log is
# deliberately safe: concurrency and log level only, never the
# broker/backend Redis URLs.
_settings = get_settings()
configure_logging(_settings.log_level)
_logger = logging.getLogger(__name__)
_logger.info(
    "Team 4A Celery worker application initialized",
    extra={
        "component": "worker",
        "log_level": _settings.log_level,
        "worker_concurrency": _settings.celery_worker_concurrency,
    },
)


def _ensure_local_demo_qdrant_collection(settings: Settings, client: Any = None) -> None:
    """Idempotently create the Qdrant collection for THIS PROJECT'S OWN
    self-contained Docker Compose / local dev / demo deployment, if it
    does not already exist.

    SCOPE NOTE -- READ BEFORE CHANGING (verified directly against the
    official Team 4A specification, not assumed -- see the real-E2E
    diagnosis this fix responds to): the specification repeatedly and
    explicitly states the Vector Database is "the shared Vector Database
    **managed by Team 4b**" (Requirement 7.1's own wording, the
    glossary's own wording, and the spec's own reference
    `VectorDBPublisher` implementation, which takes an already-connected
    client and an already-existing collection name as external inputs
    and never creates anything itself). This function does NOT change
    that contract and does NOT make Team 4A the owner of the shared
    production Vector Database's schema or lifecycle.

    This function exists ONLY so that this project's own
    docker-compose.yml stack -- which bundles its own Qdrant instance
    purely for local development/demo purposes, since Team 4B does not
    exist as a separately deployed service in this project -- can be run
    end-to-end with a plain `docker compose up`, without an undocumented
    manual setup step. In a real multi-team deployment, Team 4A would
    simply publish to Team 4B's already-provisioned collection, exactly
    as the official specification describes, and this function's create
    branch would never execute (the "already exists" branch would).

    Deliberately lazy and non-blocking, matching this project's existing
    architectural convention for every other external dependency
    (Whisper, sentence-transformers, and Qdrant's own client construction
    in `RealQdrantClient` are all lazy, never blocking process startup).
    Called once at worker startup below; ANY failure here (Qdrant not
    yet ready -- Compose's healthcheck-gated `depends_on` ordering is
    still asynchronous with respect to Qdrant's own internal readiness;
    Qdrant genuinely misconfigured; a transient network blip) is caught
    and logged as a warning, never raised -- the worker still starts and
    becomes ready to consume tasks. If the collection genuinely never
    gets created, the existing, UNMODIFIED `Publisher` retry/backoff/
    `publish_failed` contract (Requirement 7.4/7.6) handles that exactly
    as it already did before this function existed -- this function only
    removes the single most common, avoidable cause of that outcome in a
    fresh local/demo deployment.

    No second Qdrant client abstraction is introduced: this constructs
    the same real `qdrant_client.QdrantClient` class `RealQdrantClient`
    itself wraps (see that class's own `_ensure_client`), used directly
    here only because collection management (`get_collections`,
    `create_collection`) is outside `QdrantClientProtocol`'s deliberately
    minimal, `upsert`-only interface that `Publisher` depends on -- that
    Protocol, and `Publisher`'s own retry/backoff logic, are completely
    untouched by this function.

    Args:
        settings: Provides `qdrant_url`, `qdrant_api_key`,
            `qdrant_collection_name`, and `embedding_dimensions` -- never
            hardcoded, matching this project's established convention.
        client: Injectable for tests (an object exposing
            `get_collections()`/`create_collection()`, matching
            `qdrant_client.QdrantClient`'s own real interface). Defaults
            to constructing a real `QdrantClient` when not provided.
    """

    try:
        if client is None:
            from qdrant_client import QdrantClient

            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_compatibility=False)

        existing_names = {collection.name for collection in client.get_collections().collections}
        if settings.qdrant_collection_name in existing_names:
            _logger.info(
                "Qdrant collection already exists (local/demo provisioning check) -- nothing to do",
                extra={"collection": settings.qdrant_collection_name},
            )
            return

        from qdrant_client.models import Distance, VectorParams

        client.create_collection(
            collection_name=settings.qdrant_collection_name,
            # Explicit Cosine distance: all-MiniLM-L6-v2's embeddings are
            # normalized and specifically trained for cosine similarity
            # (the standard, documented convention for this model) --
            # not something this codebase assumed anywhere before this
            # fix (verified: the official spec's own reference
            # implementation never specifies a distance metric either).
            vectors_config=VectorParams(size=settings.embedding_dimensions, distance=Distance.COSINE),
        )
        _logger.info(
            "Created Qdrant collection for local/demo deployment (Team 4B manages the real production collection)",
            extra={
                "collection": settings.qdrant_collection_name,
                "vector_size": settings.embedding_dimensions,
                "distance": "cosine",
            },
        )
    except Exception as exc:  # noqa: BLE001
        # Never crash worker startup over this -- see the function's own
        # docstring. No connection URL, API key, or exception internals
        # that could contain either are ever logged; only the collection
        # name (already a non-secret, already-logged configuration value
        # elsewhere in this project) and the exception's type name.
        _logger.warning(
            "Could not verify/create the local/demo Qdrant collection at worker startup "
            "(worker will still start; the existing Publisher retry/backoff contract "
            "handles this during actual publication if it remains unresolved)",
            extra={"collection": settings.qdrant_collection_name, "error_type": type(exc).__name__},
        )


_ensure_local_demo_qdrant_collection(_settings)

#: Convenience reference to the smoke-test task registered on `celery_app`.
queue_smoke_test = celery_app.tasks[SMOKE_TEST_TASK_NAME]

# Task 10.2 integration fix: a Celery worker started the standard way
# (`celery -A app.celery_app worker ...`) only imports THIS module -- it
# never imports app/tasks.py on its own, so process_pdf/process_video/
# process_youtube would silently never be registered on a real worker
# (verified directly: `celery inspect registered` showed only the smoke
# test task before this import was added). Importing app.tasks here,
# *after* `celery_app` is fully built above, is the standard Celery
# pattern for this: it triggers app.tasks's `@celery_app.task` decorators
# to run and register themselves, without moving the Celery app
# definition itself out of its existing location. Safe from circular
# imports specifically because `celery_app` is already bound in this
# module's namespace by the time app.tasks does
# `from app.celery_app import celery_app`.
from app import tasks as _tasks  # noqa: E402,F401
