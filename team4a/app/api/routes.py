"""Team 4A FastAPI routes and file-handling boundary (Task 10.1).

Implements Requirement 9.1-9.7:
    9.1 POST /ingest/pdf accepts multipart PDF uploads, returns a job id.
    9.2 POST /ingest/video accepts multipart MP4 uploads, returns a job id.
    9.3 POST /ingest/youtube accepts a JSON YouTube URL, returns a job id.
    9.4 GET /jobs/{job_id} returns status, progress, and metadata.
    9.5 GET /jobs returns a paginated list of jobs.
    9.6 Missing/invalid fields or unsupported file types -> HTTP 422 with a
        descriptive message.
    9.7 Uploaded files must match their declared content type before
        processing is initiated.

ARCHITECTURE BOUNDARY (read before modifying):
This module implements the API boundary -- request validation, file
saving, job-record bookkeeping, and dispatching each job to the real
Celery task that does the actual work. It deliberately does NOT:
    - call PDFProcessor / VideoProcessor / YouTubeProcessor directly
    - call Chunker / Embedder / MetadataEnricher / Publisher directly
    - advance job status past "queued" itself (the Celery task does
      that, in the separate worker process)
Every route creates an IngestionJob with status=queued, dispatches the
matching Celery task (`process_pdf`/`process_video`/`process_youtube`,
imported from app.tasks -- the same singleton task objects a real
worker has registered on the same `celery_app` instance, see
app/celery_app.py), and returns it.

TASK 10.2 INTEGRATION FIX (this was a real, previously-undiscovered gap,
found via a real Docker Compose diagnosis, not a hypothetical): Task
10.1 deliberately left this dispatch call unimplemented (marked with
`# TASK 10.2:` comments), and Task 10.2 itself implemented the Celery
task functions and fixed their *registration* on the worker, but never
actually wired these API routes to call them. The result: every upload
was accepted (HTTP 202, a real job_id, a real "queued" job record) but
never enqueued to Celery at all -- confirmed in a real environment via
`LLEN team4a_ingestion` / `LLEN celery` / `LLEN default` all reading 0
after a real POST. This was invisible to every prior automated test in
this project because orchestration tests call `_run_pdf_pipeline` etc.
directly (bypassing the HTTP boundary) and API tests never asserted a
Celery dispatch actually happened. This gap is now closed.

Job state (`JobStore`) and file storage (`FileStorage`) are both injected
via FastAPI dependencies -- see app/api/job_store.py and
app/api/file_storage.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status

from app.api.file_storage import FileStorage
from app.api.job_store import JobStore, RedisJobStore
from app.config.settings import Settings, get_settings
from app.models.exceptions import UploadTooLargeError
from app.models.schemas import IngestionJob, JobListResponse, JobResponse, SourceType, YouTubeRequest
from app.tasks import _cleanup_upload, _mark_failed, process_pdf, process_video, process_youtube

logger = logging.getLogger(__name__)

router = APIRouter()

_PDF_CONTENT_TYPE = "application/pdf"
_VIDEO_CONTENT_TYPE = "video/mp4"
_BYTES_PER_MB = 1024 * 1024
_BYTES_PER_GB = 1024**3

# Task 10.2 integration fix (see app/api/job_store.py's module docstring):
# a Celery worker runs in a separate process from this API, so an
# in-memory store here would be invisible to it. RedisJobStore is
# constructed lazily (redis-py does not connect until the first command is
# issued), so importing this module never requires a live Redis server --
# exactly like every other lazy client in this project (Whisper,
# sentence-transformers, qdrant-client). Tests override this dependency
# with a fresh InMemoryJobStore for isolation (see tests/test_api_routes.py).
_default_job_store = RedisJobStore()


def get_job_store() -> JobStore:
    return _default_job_store


def get_file_storage(settings: Settings = Depends(get_settings)) -> FileStorage:
    return FileStorage(settings=settings)


def _reject_wrong_content_type(declared_content_type: str | None, expected: str, kind: str) -> None:
    """Raise HTTP 422 unless `declared_content_type` matches `expected` exactly.

    Deliberately strict (Requirement 9.7 / Task 10.1 section 10): does not
    accept a wildcard (e.g. "video/*"), does not accept
    "application/octet-stream" as a substitute, and does not infer type
    from the filename extension -- only the client-declared Content-Type
    header is checked, which is the specific, minimal interpretation Task
    10.1 asks for (see the Task 10.1 report for the "declared type" vs.
    "byte-sniffed type" scoping decision).
    """

    if declared_content_type != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Invalid {kind} content type: expected '{expected}', "
                f"got {declared_content_type!r}."
            ),
        )


def _parse_content_length(raw_header_value: str | None) -> int | None:
    """Parse the `Content-Length` header into a non-negative int, or None.

    Production Hardening Task 2: Content-Length can be missing or
    malformed -- both are treated the same as "no early size hint
    available" (the caller falls back entirely on the authoritative
    streaming byte-count check in `FileStorage.save`), never as an error
    in their own right and never trusted as authoritative even when
    present and well-formed.
    """

    if raw_header_value is None:
        return None
    try:
        parsed = int(raw_header_value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


@router.post("/ingest/pdf", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_pdf(
    request: Request,
    file: UploadFile = File(...),
    job_store: JobStore = Depends(get_job_store),
    file_storage: FileStorage = Depends(get_file_storage),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    """Accept a PDF upload, save it, and dispatch it to the Celery worker.

    Does not extract or process the PDF itself in this process -- this
    route only saves the file and enqueues `process_pdf` (app.tasks),
    which runs PDFProcessor and the rest of the pipeline in the separate
    worker process using the saved file path.

    Production Hardening Task 2: the configured `pdf_max_size_mb` limit is
    enforced here, at upload time, as defense in depth alongside
    PDFProcessor's own existing (unchanged) check against the file once
    it's on disk. An oversized upload is rejected with 422 -- the same
    convention already used for every other upload-validation failure on
    this endpoint -- before its complete body is ever written to disk,
    and no IngestionJob is created for it.
    """

    _reject_wrong_content_type(file.content_type, _PDF_CONTENT_TYPE, "PDF")

    max_bytes = settings.pdf_max_size_mb * _BYTES_PER_MB
    declared_content_length = _parse_content_length(request.headers.get("content-length"))

    job = IngestionJob(source_type=SourceType.PDF)
    try:
        saved_path = file_storage.save(
            file.file,
            job_id=job.job_id,
            extension=".pdf",
            max_bytes=max_bytes,
            declared_content_length=declared_content_length,
        )
    except UploadTooLargeError as exc:
        logger.warning(
            "Upload rejected: exceeds size limit",
            extra={"source_type": "pdf", "reason": "too_large"},
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc

    job_store.create(job)
    logger.info("Upload accepted", extra={"job_id": job.job_id, "source_type": "pdf"})

    # TASK 10.2 INTEGRATION FIX: dispatch the real Celery task. The job
    # was already created (status=queued) above, using the SAME job_id
    # now passed to the task -- this ordering is required (a job record
    # must exist before a worker could ever look it up) and matches the
    # dispatch contract exactly:
    #   process_pdf.delay(job_id=job.job_id, file_path=saved_path)
    # `process_pdf` is the real, singleton task object imported from
    # app.tasks -- the SAME object a Celery worker started via
    # `celery -A app.celery_app worker` has registered on the SAME
    # `celery_app` instance (verified directly: `routes.process_pdf is
    # tasks.process_pdf` and `.app is celery_app`, both True). No second
    # Celery application or task implementation is created here.
    try:
        process_pdf.delay(job_id=job.job_id, file_path=saved_path)
    except Exception as exc:  # noqa: BLE001
        # DISPATCH FAILURE HANDLING: if the broker is unreachable (or any
        # other error occurs) at the moment of enqueueing, the job record
        # already exists but will never be picked up by any worker --
        # exactly the "job that can never run" this task explicitly warns
        # against silently returning. Reusing the existing, approved
        # `_mark_failed` helper (app/tasks.py) marks the job FAILED with
        # a real ErrorDetail -- the same terminal-failure representation
        # already used for every other failure mode in this project, so
        # `GET /jobs/{job_id}` accurately reflects that this job will not
        # be processed, rather than showing "queued" forever. The saved
        # upload is cleaned up via the existing `_cleanup_upload` helper
        # (Production Hardening Task 3's terminal-failure convention),
        # since this job will never reach any later stage that would
        # otherwise do so. The response itself is a 503 (not the normal
        # 202) -- consistent with this project's existing convention of
        # using 503 for "a required downstream dependency is unavailable"
        # (see app/api/health.py's GET /readyz) -- so the client is never
        # told "accepted for processing" when that is not true.
        logger.error(
            "Failed to enqueue Celery task for job %s: %s",
            job.job_id,
            exc,
            extra={"job_id": job.job_id, "source_type": "pdf"},
            exc_info=True,
        )
        _mark_failed(job, job_store, exc)
        _cleanup_upload(job.job_id, saved_path, settings.upload_directory)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue the ingestion task for processing. Please retry the request.",
        ) from exc

    return JobResponse(job_id=job.job_id, status=job.status)


@router.post("/ingest/video", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_video(
    request: Request,
    file: UploadFile = File(...),
    job_store: JobStore = Depends(get_job_store),
    file_storage: FileStorage = Depends(get_file_storage),
    settings: Settings = Depends(get_settings),
) -> JobResponse:
    """Accept an MP4 upload, save it, and dispatch it to the Celery worker.

    Does not run VideoProcessor/Whisper/ffmpeg in this process -- this
    route only saves the file and enqueues `process_video` (app.tasks),
    which runs the pipeline in the separate worker process.

    Production Hardening Task 2: the configured `video_max_size_gb` limit
    is enforced here, at upload time, as defense in depth alongside
    VideoProcessor's own existing (unchanged) check against the file once
    it's on disk. See `ingest_pdf` above for the identical rationale.
    """

    _reject_wrong_content_type(file.content_type, _VIDEO_CONTENT_TYPE, "video")

    max_bytes = settings.video_max_size_gb * _BYTES_PER_GB
    declared_content_length = _parse_content_length(request.headers.get("content-length"))

    job = IngestionJob(source_type=SourceType.MP4)
    try:
        saved_path = file_storage.save(
            file.file,
            job_id=job.job_id,
            extension=".mp4",
            max_bytes=max_bytes,
            declared_content_length=declared_content_length,
        )
    except UploadTooLargeError as exc:
        logger.warning(
            "Upload rejected: exceeds size limit",
            extra={"source_type": "mp4", "reason": "too_large"},
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.message) from exc

    job_store.create(job)
    logger.info("Upload accepted", extra={"job_id": job.job_id, "source_type": "mp4"})

    # TASK 10.2 INTEGRATION FIX: see ingest_pdf above for the full
    # rationale (identical pattern, applied to the video task).
    try:
        process_video.delay(job_id=job.job_id, file_path=saved_path)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to enqueue Celery task for job %s: %s",
            job.job_id,
            exc,
            extra={"job_id": job.job_id, "source_type": "mp4"},
            exc_info=True,
        )
        _mark_failed(job, job_store, exc)
        _cleanup_upload(job.job_id, saved_path, settings.upload_directory)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue the ingestion task for processing. Please retry the request.",
        ) from exc

    return JobResponse(job_id=job.job_id, status=job.status)


@router.post("/ingest/youtube", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED)
def ingest_youtube(
    request: YouTubeRequest,
    job_store: JobStore = Depends(get_job_store),
) -> JobResponse:
    """Accept a YouTube URL request and dispatch it to the Celery worker.

    `request.url` is validated as a real HTTP/HTTPS URL by Pydantic's
    `HttpUrl` (via the existing `YouTubeRequest` model) before this
    handler body ever runs -- an invalid or missing URL never reaches
    here; FastAPI returns HTTP 422 automatically. This route does not
    call YouTubeProcessor or make any network request itself -- it only
    enqueues `process_youtube` (app.tasks), which does so in the
    separate worker process.
    """

    job = IngestionJob(source_type=SourceType.YOUTUBE)
    job_store.create(job)

    # TASK 10.2 INTEGRATION FIX: see ingest_pdf above for the full
    # rationale. YouTube ingestion saves no local file (confirmed:
    # _run_youtube_pipeline takes a `url`, never a `file_path`), so a
    # dispatch failure here has nothing to clean up -- `_cleanup_upload`
    # is correctly not called, matching app/tasks.py's own established
    # "nothing to clean up, by construction, not a special case" pattern
    # for this source type.
    try:
        process_youtube.delay(
            job_id=job.job_id,
            url=str(request.url),
            language=request.language,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Failed to enqueue Celery task for job %s: %s",
            job.job_id,
            exc,
            extra={"job_id": job.job_id, "source_type": "youtube"},
            exc_info=True,
        )
        _mark_failed(job, job_store, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue the ingestion task for processing. Please retry the request.",
        ) from exc

    return JobResponse(job_id=job.job_id, status=job.status)


@router.get("/jobs/{job_id}", response_model=IngestionJob)
def get_job(job_id: str, job_store: JobStore = Depends(get_job_store)) -> IngestionJob:
    """Return the current state of one Ingestion_Job.

    Exposes job_id, source_type, status, progress, chunk_count,
    error_details, created_at, updated_at -- exactly IngestionJob's own
    fields (Requirement 9.4), so the model is returned directly rather
    than restated in a parallel response schema.
    """

    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Job '{job_id}' not found.")
    return job


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    job_store: JobStore = Depends(get_job_store),
) -> JobListResponse:
    """Return a paginated list of Ingestion_Jobs (Requirement 9.5).

    `page`/`page_size` are validated by FastAPI's `Query(..., ge=..., le=...)`
    constraints, which produce HTTP 422 automatically for out-of-range
    values (e.g. page=0, page_size=0, or page_size > 100) before this
    handler body runs.
    """

    jobs, total = job_store.list(page=page, page_size=page_size)
    return JobListResponse(jobs=jobs, page=page, page_size=page_size, total=total)
