"""Team 4A Celery ingestion tasks (Task 10.2).

Implements Requirements 8.1-8.6 (Job_Manager) by wiring the already-approved
pipeline stages together:

    Source Processor -> 25% -> Chunker -> 50% -> Embedder -> 75%
        -> MetadataEnricher -> Publisher -> 100%

Registers three Celery tasks (`process_pdf`, `process_video`,
`process_youtube`) on the existing `celery_app` (Task 1.3) -- no second
Celery application is created. Each task is a thin wrapper around a plain,
dependency-injectable function (`_run_pdf_pipeline` etc.) so unit tests can
exercise the real orchestration logic with fake processors/chunker/
embedder/metadata enricher/publisher/job store, without Celery, Redis,
Qdrant, Whisper, or network access.

This module does not reimplement anything the approved components already
do: no second Qdrant client, no duplicated retry/backoff logic (Publisher
already owns that), no reparsing of PDFs/videos, no direct calls to
sentence-transformers. It only sequences existing calls and persists job
status/progress at each stage boundary.

SOURCE-TO-CHUNK RELATIONSHIP (Task 10.2 section 5):
Chunker.chunk() takes plain text and has no notion of "source segment," so
each source segment's text is chunked *individually*
(`chunker.chunk(segment.text)`), producing `(segment, chunks)` pairs. This
is what allows MetadataEnricher's existing `enrich_pdf`/`enrich_video`/
`enrich_youtube` methods (which require exactly this pairing) to attach
each chunk's real page/timestamp/heading context with zero fabrication --
Task 8.1's report already flagged this as the assumption Task 10.2 would
need to confirm; it is confirmed here as the only shape compatible with
the existing MetadataEnricher interface.

KNOWN LIMITATION -- audio-absent video (see the Task 10.2 report for full
analysis): when `VideoProcessingResult.audio_absent` is True, there are no
VideoSegments, hence no chunks, hence nothing to publish for that video,
even though Requirement 2.5 says the system should "proceed with frame
analysis only." The current `Chunk`/`ChunkMetadata` contract requires
non-empty text per record, so there is no existing way to publish a
frame-only, textless record without inventing a new record type or
fabricating placeholder text (both explicitly out of scope for this task).
The job still completes successfully with `chunk_count=0` rather than
being reported as a failure -- this is a real, reported interface gap, not
a silent one.

UPLOAD CLEANUP (Production Hardening Task 3): once a PDF or video pipeline
function reaches any of its three possible outcomes -- COMPLETED, FAILED,
or PUBLISH_FAILED -- the saved upload is deleted via `_cleanup_upload`.
See that function's own docstring for the full retry-safety analysis
(short version: there is no application-level "retry, keep the file"
resting state in this codebase; the only real retry is Celery's own
crash-redelivery, which is safe regardless of cleanup placement because a
crash prevents this cleanup code from ever running). YouTube ingestion
saves no local file, so `_run_youtube_pipeline` calls no cleanup helper at
all -- there is nothing to clean up, by construction, not by a special case.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.api.job_store import JobStore, RedisJobStore
from app.celery_app import celery_app
from app.config.settings import Settings, get_settings
from app.logging_config import job_id_var
from app.models.exceptions import Team4AError
from app.models.schemas import ErrorDetail, IngestionJob, JobStatus
from app.pipeline.chunker import Chunker
from app.pipeline.embedder import Embedder
from app.pipeline.metadata import MetadataEnricher
from app.pipeline.publisher import Publisher
from app.processors.pdf_processor import PDFProcessor
from app.processors.video_processor import VideoProcessor
from app.processors.youtube_processor import YouTubeProcessor
from app.utils.progress import update_progress

logger = logging.getLogger(__name__)


def _touch_and_persist(job: IngestionJob, job_store: JobStore) -> None:
    """Refresh `updated_at` and persist -- called at every state transition."""

    job.updated_at = datetime.now(timezone.utc)
    job_store.update(job)


_STAGE_NAMES_BY_PERCENT = {25: "extraction", 50: "chunking", 75: "embedding", 100: "publication"}


def _advance_progress(job: IngestionJob, job_store: JobStore, percent: int, redis_client=None) -> None:
    """Advance both the persisted job record and the Redis progress key together.

    Requirement 10 ("the persisted job state and Redis progress state
    must not contradict each other") is satisfied by always updating both
    in the same call, using the existing `update_progress` helper
    (Task 1.3) rather than a second, competing progress mechanism.
    """

    job.progress = percent
    _touch_and_persist(job, job_store)
    stage = _STAGE_NAMES_BY_PERCENT.get(percent, "unknown")
    logger.info(
        "Pipeline stage completed",
        extra={"job_id": job.job_id, "stage": stage, "progress": percent},
    )
    try:
        update_progress(job.job_id, percent, redis_client=redis_client)
    except Exception:  # noqa: BLE001
        # Redis progress mirroring is a secondary, best-effort signal --
        # the authoritative state is the persisted IngestionJob itself
        # (already updated above). Do not fail the whole job over this.
        logger.warning("Failed to mirror progress to Redis for job %s", job.job_id, extra={"job_id": job.job_id})


def _build_error_detail(exc: Exception) -> ErrorDetail:
    """Classify any exception into an ErrorDetail without leaking a raw traceback."""

    if isinstance(exc, Team4AError):
        return ErrorDetail.from_exception(exc)
    return ErrorDetail(
        error_type=type(exc).__name__,
        status_code="ProcessingFailed",
        message=str(exc) or "Unexpected processing failure",
        detail={},
    )


def _cleanup_upload(job_id: str, file_path: str, upload_directory: str) -> None:
    """Delete a saved upload once its task has reached a terminal outcome (Production Hardening Task 3).

    RETRY-SAFETY ANALYSIS (see the Task 3 report for the full inspection
    this is based on): the current implementation has no application-level
    "retry, keep the file, try again later" resting state -- every
    exception raised anywhere in a pipeline function is caught and turned
    into `_mark_failed` (job.status = FAILED) *before that function
    returns normally*, so no exception ever escapes `process_pdf`/
    `process_video` for Celery itself to see, and no `autoretry_for`/
    `self.retry()` is configured anywhere. The only real "retry" in the
    system is Celery's own crash-redelivery (`task_acks_late=True` +
    `visibility_timeout=60`, Task 1.3): if a worker process crashes
    mid-task, the broker redelivers the *same* task message to another
    worker later. That scenario is safe regardless of where this function
    is called from, because a crash means the process was killed before
    ever reaching a `return` statement -- this cleanup call (placed only
    at each pipeline function's own return points, see
    `_run_pdf_pipeline`/`_run_video_pipeline`) would never have run in
    that case, correctly leaving the file in place for the redelivered
    attempt. Therefore COMPLETED, FAILED, and PUBLISH_FAILED are all
    genuinely, unconditionally terminal for a given task invocation, and
    all three call this helper identically -- no special-casing between
    them is needed or performed.

    Safety properties:
        - Idempotent: `Path.unlink(missing_ok=True)` never raises merely
          because the file is already gone (e.g. a duplicate cleanup
          call, or a file removed by an operator).
        - Never raises: any OS-level failure (permissions, a locked
          file, etc.) is caught and logged with job_id/path context --
          per this task's explicit instruction, a cleanup failure must
          never retroactively corrupt an already-persisted terminal job
          status (e.g. turn a COMPLETED job into FAILED).
        - Path-safety, defense in depth: `file_path` here is always the
          exact server-generated path produced by `FileStorage.save()`
          (Task 10.1/Production Hardening Task 2) and passed through
          unchanged as a Celery task argument -- never derived from
          client input at any point in that chain, so no *new*
          path-traversal risk is introduced by cleanup itself. As an
          additional, independent safety net, this function still
          refuses to delete anything outside the configured
          `upload_directory`, in case a future change ever passes an
          unexpected path.
    """

    try:
        resolved_path = Path(file_path).resolve()
        resolved_upload_dir = Path(upload_directory).resolve()
        if not resolved_path.is_relative_to(resolved_upload_dir):
            logger.warning(
                "Refusing to clean up path outside the configured upload directory for job %s: %s",
                job_id,
                file_path,
                extra={"job_id": job_id, "stage": "cleanup", "outcome": "refused"},
            )
            return
        resolved_path.unlink(missing_ok=True)
        logger.info(
            "Uploaded file cleaned up",
            extra={"job_id": job_id, "stage": "cleanup", "outcome": "succeeded"},
        )
    except OSError as exc:
        logger.warning(
            "Failed to clean up uploaded file for job %s at %s: %s",
            job_id,
            file_path,
            exc,
            extra={"job_id": job_id, "stage": "cleanup", "outcome": "failed"},
        )


def _mark_failed(job: IngestionJob, job_store: JobStore, exc: Exception) -> IngestionJob:
    job.status = JobStatus.FAILED
    job.error_details = _build_error_detail(exc)
    _touch_and_persist(job, job_store)
    logger.error(
        "Job %s failed during processing: %s",
        job.job_id,
        exc,
        exc_info=True,
        extra={"job_id": job.job_id, "stage": "processing", "outcome": "failed"},
    )
    return job


def _apply_publication_result(
    job: IngestionJob, job_store: JobStore, result, redis_client=None
) -> IngestionJob:
    job.chunk_count = result.published_count
    if result.status == JobStatus.COMPLETED:
        job.status = JobStatus.COMPLETED
        job.progress = get_settings().progress_publication_pct  # 100
        try:
            update_progress(job.job_id, job.progress, redis_client=redis_client)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to mirror final progress to Redis for job %s", job.job_id, extra={"job_id": job.job_id})
    else:
        job.status = JobStatus.PUBLISH_FAILED
        job.error_details = result.error_details
    _touch_and_persist(job, job_store)
    logger.info(
        "Job reached terminal status",
        extra={
            "job_id": job.job_id,
            "outcome": job.status.value,
            "chunk_count": job.chunk_count,
        },
    )
    return job


class _PipelineDependencies:
    """Bundles the injectable stage objects shared by all three tasks.

    A plain container (not a DI framework) -- every field defaults to a
    real implementation built from `settings`, and every field can be
    overridden individually by tests.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        job_store: JobStore | None = None,
        chunker: Chunker | None = None,
        embedder: Embedder | None = None,
        metadata_enricher: MetadataEnricher | None = None,
        publisher: Publisher | None = None,
        redis_client: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.job_store = job_store or RedisJobStore(settings=self.settings)
        self.chunker = chunker or Chunker(settings=self.settings)
        self.embedder = embedder or Embedder(settings=self.settings)
        self.metadata_enricher = metadata_enricher or MetadataEnricher(settings=self.settings)
        self.publisher = publisher or Publisher(settings=self.settings)
        # Injectable so tests never need a live Redis server just to
        # exercise progress mirroring (see `_advance_progress`).
        self.redis_client = redis_client


def _require_job(job_id: str, job_store: JobStore) -> IngestionJob:
    job = job_store.get(job_id)
    if job is None:
        raise ValueError(f"Unknown job_id: {job_id!r} (no job record found in the job store)")
    return job


# ---------------------------------------------------------------------------
# PDF pipeline
# ---------------------------------------------------------------------------


def _run_pdf_pipeline(
    job_id: str,
    file_path: str,
    deps: _PipelineDependencies,
    processor: PDFProcessor | None = None,
) -> IngestionJob:
    job_id_var.set(job_id)
    job_store = deps.job_store
    job = _require_job(job_id, job_store)
    logger.info("Task started", extra={"job_id": job_id, "source_type": "pdf"})
    job.status = JobStatus.PROCESSING
    _touch_and_persist(job, job_store)

    processor = processor or PDFProcessor(settings=deps.settings)
    filename = Path(file_path).name

    try:
        segments = processor.process(file_path)
        _advance_progress(job, job_store, deps.settings.progress_extraction_pct, deps.redis_client)  # 25

        segments_with_chunks = [(segment, deps.chunker.chunk(segment.text)) for segment in segments]
        _advance_progress(job, job_store, deps.settings.progress_chunking_pct, deps.redis_client)  # 50

        flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
        embeddings = deps.embedder.embed(flat_texts)
        _advance_progress(job, job_store, deps.settings.progress_embedding_pct, deps.redis_client)  # 75

        enriched_chunks = deps.metadata_enricher.enrich_pdf(
            job_id, filename, job.created_at, segments_with_chunks
        )
    except Exception as exc:  # noqa: BLE001
        result_job = _mark_failed(job, job_store, exc)
        _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
        return result_job

    try:
        result = deps.publisher.publish(enriched_chunks, embeddings)
    except Exception as exc:  # noqa: BLE001
        result_job = _mark_failed(job, job_store, exc)
        _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
        return result_job

    result_job = _apply_publication_result(job, job_store, result, deps.redis_client)
    _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
    return result_job


@celery_app.task(name="team4a.process_pdf")
def process_pdf(job_id: str, file_path: str) -> None:
    """Celery entry point for PDF ingestion. See module docstring for the pipeline."""

    _run_pdf_pipeline(job_id, file_path, _PipelineDependencies())


# ---------------------------------------------------------------------------
# Video pipeline
# ---------------------------------------------------------------------------


def _run_video_pipeline(
    job_id: str,
    file_path: str,
    deps: _PipelineDependencies,
    processor: VideoProcessor | None = None,
) -> IngestionJob:
    job_id_var.set(job_id)
    job_store = deps.job_store
    job = _require_job(job_id, job_store)
    logger.info("Task started", extra={"job_id": job_id, "source_type": "mp4"})
    job.status = JobStatus.PROCESSING
    _touch_and_persist(job, job_store)

    processor = processor or VideoProcessor(settings=deps.settings)
    filename = Path(file_path).name

    try:
        result = processor.process(file_path)
        _advance_progress(job, job_store, deps.settings.progress_extraction_pct, deps.redis_client)  # 25

        # audio_absent -> result.segments is already [] (Task 3.1); no
        # transcript text exists to fabricate, so this naturally proceeds
        # with zero chunks rather than guessing at spoken content. See the
        # module docstring's "KNOWN LIMITATION" for the full analysis.
        segments_with_chunks = [
            (segment, deps.chunker.chunk(segment.text)) for segment in result.segments
        ]
        _advance_progress(job, job_store, deps.settings.progress_chunking_pct, deps.redis_client)  # 50

        flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
        embeddings = deps.embedder.embed(flat_texts)
        _advance_progress(job, job_store, deps.settings.progress_embedding_pct, deps.redis_client)  # 75

        enriched_chunks = deps.metadata_enricher.enrich_video(
            job_id, filename, job.created_at, result.keyframes, segments_with_chunks
        )
    except Exception as exc:  # noqa: BLE001
        result_job = _mark_failed(job, job_store, exc)
        _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
        return result_job

    try:
        publication_result = deps.publisher.publish(enriched_chunks, embeddings)
    except Exception as exc:  # noqa: BLE001
        result_job = _mark_failed(job, job_store, exc)
        _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
        return result_job

    result_job = _apply_publication_result(job, job_store, publication_result, deps.redis_client)
    _cleanup_upload(job_id, file_path, deps.settings.upload_directory)
    return result_job


@celery_app.task(name="team4a.process_video")
def process_video(job_id: str, file_path: str) -> None:
    """Celery entry point for MP4 ingestion. See module docstring for the pipeline."""

    _run_video_pipeline(job_id, file_path, _PipelineDependencies())


# ---------------------------------------------------------------------------
# YouTube pipeline
# ---------------------------------------------------------------------------


def _run_youtube_pipeline(
    job_id: str,
    url: str,
    language: str | None,
    deps: _PipelineDependencies,
    processor: YouTubeProcessor | None = None,
) -> IngestionJob:
    job_id_var.set(job_id)
    job_store = deps.job_store
    job = _require_job(job_id, job_store)
    logger.info("Task started", extra={"job_id": job_id, "source_type": "youtube"})
    job.status = JobStatus.PROCESSING
    _touch_and_persist(job, job_store)

    processor = processor or YouTubeProcessor(settings=deps.settings)

    try:
        result = processor.process(url, language)
        _advance_progress(job, job_store, deps.settings.progress_extraction_pct, deps.redis_client)  # 25

        segments_with_chunks = [
            (segment, deps.chunker.chunk(segment.text)) for segment in result.segments
        ]
        _advance_progress(job, job_store, deps.settings.progress_chunking_pct, deps.redis_client)  # 50

        flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
        embeddings = deps.embedder.embed(flat_texts)
        _advance_progress(job, job_store, deps.settings.progress_embedding_pct, deps.redis_client)  # 75

        enriched_chunks = deps.metadata_enricher.enrich_youtube(
            job_id, url, job.created_at, result.metadata, segments_with_chunks
        )
    except Exception as exc:  # noqa: BLE001
        return _mark_failed(job, job_store, exc)

    try:
        publication_result = deps.publisher.publish(enriched_chunks, embeddings)
    except Exception as exc:  # noqa: BLE001
        return _mark_failed(job, job_store, exc)

    return _apply_publication_result(job, job_store, publication_result, deps.redis_client)


@celery_app.task(name="team4a.process_youtube")
def process_youtube(job_id: str, url: str, language: str | None = None) -> None:
    """Celery entry point for YouTube ingestion. See module docstring for the pipeline."""

    _run_youtube_pipeline(job_id, url, language, _PipelineDependencies())
