"""Team 4A Vector_DB_Publisher.

Location matches the same pattern as the Chunker, Embedder, and
Metadata_Enricher (app/pipeline/chunker.py, embedder.py, metadata.py):
app/pipeline/publisher.py.

Implements Requirement 7:
    7.1 Publish complete records (vector + metadata) to Qdrant.
    7.2 Transmit each chunk as a record containing the vector embedding,
        raw text content, and the full metadata object.
    7.3 Batch publications into groups of up to the configured batch size
        (default 100).
    7.4 Retry a failed batch publication up to the configured retry count
        (default 3) with exponential backoff.
    7.5 Report the number of successfully published chunks.
    7.6 Mark publication as publish_failed (and retain error information)
        if a batch permanently fails after exhausting retries; mark it
        completed only when every record was published.

Does not implement job orchestration, Celery tasks, or API endpoints --
those belong to later tasks (10.x). Makes no network calls except via the
injected Qdrant client abstraction, so unit tests never require a live
Qdrant server.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Protocol, Sequence

from app.config.settings import Settings, get_settings
from app.models.schemas import EnrichedChunk, ErrorDetail, JobStatus, PublicationResult

logger = logging.getLogger(__name__)

#: Fixed, arbitrary namespace UUID used to derive deterministic Qdrant
#: point IDs from a chunk's own deterministic chunk_id (Task 8.1). Using
#: uuid.uuid5 (name-based, deterministic) rather than uuid.uuid4 (random)
#: is what makes re-publishing the same chunk produce the same point ID,
#: satisfying the "no random IDs / safe repeatability" requirement.
_QDRANT_ID_NAMESPACE = uuid.UUID("6f1e6d3a-3b8b-4b8b-9b8b-1a2b3c4d5e6f")


def chunk_id_to_point_id(chunk_id: str) -> str:
    """Deterministically map a Task 8.1 chunk_id to a Qdrant-valid point ID.

    Qdrant point IDs must be an unsigned integer or a UUID -- an arbitrary
    64-character hex string (our chunk_id) is not directly valid, so it is
    deterministically mapped into a UUID via `uuid.uuid5`. The same
    chunk_id always maps to the same UUID; different chunk_ids map to
    different UUIDs (for all practical purposes).
    """

    return str(uuid.uuid5(_QDRANT_ID_NAMESPACE, chunk_id))


class QdrantClientProtocol(Protocol):
    """The minimal interface Publisher needs from a Qdrant client.

    `RealQdrantClient` (below) is the real implementation. Tests inject a
    fake implementing this same interface, so they exercise Publisher's
    real control flow (batching, retry, backoff, failure handling)
    without a live Qdrant server.
    """

    def upsert(self, collection_name: str, points: Sequence[Any]) -> Any:
        """Write a batch of points to `collection_name`. Raise on failure."""
        ...


class RealQdrantClient:
    """Real qdrant-client integration, per Requirement 7.1.

    The `qdrant_client` package and the actual `QdrantClient` connection
    are constructed lazily inside `_ensure_client()`, not at module import
    time or at `Publisher.__init__` -- the same lazy pattern already used
    for Whisper (Task 3.1) and sentence-transformers (Task 7.1). Importing
    this module, or even constructing a `Publisher`, never opens a
    connection; only calling `publish()` does.
    """

    def __init__(self, url: str, api_key: str | None) -> None:
        self._url = url
        self._api_key = api_key
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            # check_compatibility=False: avoid an implicit version-check
            # network call at construction time, keeping construction lazy
            # and side-effect-free until an actual upsert is requested.
            self._client = QdrantClient(url=self._url, api_key=self._api_key, check_compatibility=False)
        return self._client

    def upsert(self, collection_name: str, points: Sequence[Any]) -> Any:
        from qdrant_client.models import PointStruct  # noqa: F401  (import kept local/lazy, mirrors client)

        client = self._ensure_client()
        return client.upsert(collection_name=collection_name, points=list(points))


def _build_point(enriched: EnrichedChunk, embedding: list[float]):
    """Build one Qdrant PointStruct from an EnrichedChunk + its embedding.

    Requirement 7.2 / Property 22 (Publication record completeness): each
    published record must contain exactly three components -- the vector
    embedding, the raw text content, and the full metadata object. The
    payload is therefore `{"text": <chunk text>, **metadata fields}`:
    every populated `ChunkMetadata` field (common + the relevant
    source-specific fields) is preserved; fields that don't apply to this
    chunk's source_type (left as None by the Task 8.1 MetadataEnricher)
    are simply omitted rather than stored as null, keeping the payload
    compact and source-accurate without fabricating anything.
    """

    from qdrant_client.models import PointStruct

    point_id = chunk_id_to_point_id(enriched.metadata.chunk_id)
    payload = {
        "text": enriched.chunk.text,
        **enriched.metadata.model_dump(mode="json", exclude_none=True),
    }
    return PointStruct(id=point_id, vector=embedding, payload=payload)


class Publisher:
    """Publishes embeddings + metadata to Qdrant in retrying, backed-off batches.

    Collection name, batch size, retry count, and backoff base are all
    read from `Settings` (never hardcoded), matching this project's
    established pattern (PDFProcessor, VideoProcessor, YouTubeProcessor,
    Chunker, Embedder, MetadataEnricher).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        qdrant_client: QdrantClientProtocol | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        alert_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = qdrant_client or RealQdrantClient(
            url=self._settings.qdrant_url, api_key=self._settings.qdrant_api_key
        )
        # Injectable so unit tests never actually sleep for the real
        # (multi-second, exponentially growing) backoff duration.
        self._sleep = sleep_fn or time.sleep
        # Injectable "alert" -- deliberately just a callback/log hook, not
        # a real email/Slack/PagerDuty integration (explicitly out of
        # scope for Task 8.2); the later orchestration layer can wire
        # this to a real alerting system without changing Publisher.
        self._alert_callback = alert_callback or self._log_alert

    def publish(
        self,
        enriched_chunks: list[EnrichedChunk],
        embeddings: list[list[float]],
        collection_name_override: str | None = None,
    ) -> PublicationResult:
        """Publish N enriched chunks with their N embeddings to Qdrant.

        Args:
            enriched_chunks: Task 8.1 output, in order.
            embeddings: Task 7.1 output, in the same order -- `embeddings[i]`
                must correspond to `enriched_chunks[i]`.
            collection_name_override: Phase 1 (Rev.4.4) addition. When
                provided, publishes to this collection instead of
                `self._settings.qdrant_collection_name` (4A's legacy
                collection). `None` (the default) preserves the exact,
                unchanged legacy behavior every existing caller/test
                already depends on -- this parameter is purely additive.
                Used by `app.pipeline.canonical_ingestion` to target the
                Rev.4.4 canonical collection (`educopilot_chunks`)
                without this class ever needing to know that name itself.

        Returns:
            A `PublicationResult` with status `completed` (every record
            published) or `publish_failed` (a batch permanently failed
            after exhausting retries; `published_count` reflects only the
            batches that succeeded *before* the failing one).

        Raises:
            ValueError: if `len(enriched_chunks) != len(embeddings)` --
                fails explicitly rather than silently truncating via
                `zip()`, per Task 8.2's explicit instruction.
        """

        if len(enriched_chunks) != len(embeddings):
            raise ValueError(
                f"enriched_chunks and embeddings length mismatch: "
                f"{len(enriched_chunks)} != {len(embeddings)}"
            )

        total_count = len(enriched_chunks)
        # Extracted purely for log correlation -- Publisher's own public
        # signature is unchanged; every chunk's metadata already carries
        # the same job_id (Task 8.1), so this never fabricates anything.
        job_id = enriched_chunks[0].metadata.job_id if enriched_chunks else "-"

        if total_count == 0:
            logger.info("Publication started", extra={"job_id": job_id, "total_count": 0})
            return PublicationResult(status=JobStatus.COMPLETED, published_count=0, total_count=0)

        batch_size = self._settings.qdrant_publish_batch_size
        collection_name = collection_name_override or self._settings.qdrant_collection_name
        published_count = 0

        logger.info(
            "Publication started",
            extra={"job_id": job_id, "total_count": total_count, "batch_size": batch_size},
        )

        for batch_start in range(0, total_count, batch_size):
            batch_chunks = enriched_chunks[batch_start : batch_start + batch_size]
            batch_embeddings = embeddings[batch_start : batch_start + batch_size]
            points = [_build_point(chunk, embedding) for chunk, embedding in zip(batch_chunks, batch_embeddings)]

            logger.info(
                "Publish batch attempt",
                extra={"job_id": job_id, "batch_start": batch_start, "batch_size": len(points)},
            )
            success, last_error = self._publish_batch_with_retry(collection_name, points, job_id=job_id)

            if not success:
                error_details = ErrorDetail(
                    error_type="PublicationFailedError",
                    status_code="PublicationFailed",
                    message=(
                        f"Failed to publish batch starting at index {batch_start} "
                        f"({len(points)} records) after {self._settings.publisher_retry_count} retries"
                    ),
                    detail={
                        "batch_start": batch_start,
                        "batch_size": len(points),
                        "published_before_failure": published_count,
                        "total_count": total_count,
                        "last_error": str(last_error) if last_error else None,
                    },
                )
                logger.error(
                    "Publication permanently failed",
                    extra={
                        "job_id": job_id,
                        "batch_start": batch_start,
                        "published_before_failure": published_count,
                        "total_count": total_count,
                    },
                )
                self._alert_callback("Qdrant publication failed permanently", error_details.model_dump())
                return PublicationResult(
                    status=JobStatus.PUBLISH_FAILED,
                    published_count=published_count,
                    total_count=total_count,
                    error_details=error_details,
                )

            published_count += len(points)
            logger.info(
                "Batch published successfully",
                extra={"job_id": job_id, "batch_start": batch_start, "published_count": published_count},
            )

        logger.info(
            "Publication completed",
            extra={"job_id": job_id, "published_count": published_count, "total_count": total_count},
        )
        return PublicationResult(status=JobStatus.COMPLETED, published_count=published_count, total_count=total_count)

    def _publish_batch_with_retry(
        self, collection_name: str, points: list[Any], job_id: str = "-"
    ) -> tuple[bool, Exception | None]:
        """Attempt to publish one batch, retrying on failure with exponential backoff.

        `publisher_retry_count` (default 3) is the number of RETRY
        attempts made *after* the initial attempt fails -- matching its
        own Settings docstring ("Number of retry attempts on Vector DB
        write failure") -- so up to `1 + publisher_retry_count` total
        attempts are made (4 by default) before giving up.

        `job_id` is accepted purely for log correlation (Production
        Hardening Task 6) -- it does not affect retry/backoff behavior at
        all, and this remains a private method with no change to
        `publish()`'s own public contract.
        """

        max_retries = self._settings.publisher_retry_count
        attempt = 0
        last_error: Exception | None = None

        while True:
            try:
                self._client.upsert(collection_name=collection_name, points=points)
                return True, None
            except Exception as exc:  # noqa: BLE001 -- any Qdrant client failure is retryable here
                last_error = exc
                attempt += 1
                if attempt > max_retries:
                    return False, last_error
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Retrying Qdrant publish after transient failure",
                    extra={"job_id": job_id, "attempt": attempt, "max_retries": max_retries, "backoff_seconds": delay},
                )
                self._sleep(delay)

    def _backoff_delay(self, retry_number: int) -> float:
        """Exponential backoff delay before retry attempt `retry_number` (1-indexed).

        delay = publisher_initial_backoff_seconds * 2^(retry_number - 1)
        e.g. with the default 2.0s base: retry 1 -> 2.0s, retry 2 -> 4.0s,
        retry 3 -> 8.0s ("doubles on each subsequent retry", per the
        existing Settings docstring).
        """

        return self._settings.publisher_initial_backoff_seconds * (2 ** (retry_number - 1))

    @staticmethod
    def _log_alert(message: str, detail: dict[str, Any]) -> None:
        logger.error("%s: %s", message, detail)
