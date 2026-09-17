"""Phase 2C / 2C-R -- the canonical `POST /v1/ingest` route (Rev.4.4 /
Phase 2A's frozen 4C -> 4A contract), authenticated via Phase 2B's
internal service JWT verifier, now wired through Phase 2C-R's secure
`file_url` retrieval into the existing Phase 1 canonical orchestration.

DISTINCT FROM LEGACY ROUTES: `/ingest/pdf`, `/ingest/video`,
`/ingest/youtube`, and `/jobs/{job_id}` (all in app/api/routes.py) are
existing, unmodified, unauthenticated, multipart-upload-based routes.
This module implements ONLY the new, separate, JWT-authenticated
canonical contract -- it does not replace, migrate, or share request
handling with the legacy routes in any way.

============================================================
FLOW (pdf / mp4)
============================================================
    JWT verification -> canonical request validation ->
    remote_source_resolver.resolve_pdf_or_mp4_source() (secure,
    IP-pinned, size/timeout/content-validated download to a temp file) ->
    existing PDFProcessor/VideoProcessor (via canonical_extraction.py,
    which reuses the exact same Chunker/Embedder/MetadataEnricher calls
    app/tasks.py's own pipelines use) -> existing Phase 1
    CanonicalIngestionOrchestrator (lock+generation, canonical Qdrant
    publication, Mongo completion-time authority, self-healing, cleanup
    -- all unmodified) -> temp file cleanup (always, success or failure).

============================================================
FLOW (youtube)
============================================================
    JWT verification -> canonical request validation -> `file_url` (a
    real YouTube URL) passed DIRECTLY to the existing, already-hardened
    `YouTubeProcessor.process()` -- `remote_source_resolver` is NEVER
    used for YouTube; that processor's own host validation
    (`_WATCH_HOSTS`/`_SHORT_HOST`) is the only URL check this branch
    relies on, exactly as the legacy `/ingest/youtube` route already
    does -- then into the same Phase 1 orchestration as pdf/mp4.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, field_validator

from app.config.settings import Settings, get_settings
from app.models.exceptions import TranscriptUnavailableError, VideoInaccessibleError
from app.models.schemas import SourceType
from app.pipeline.canonical_extraction import (
    extract_pdf_for_canonical_ingestion,
    extract_video_for_canonical_ingestion,
    extract_youtube_for_canonical_ingestion,
)
from app.pipeline.canonical_ingestion import (
    CanonicalIngestionInput,
    CanonicalIngestionOrchestrator,
    CanonicalIngestionOutcome,
    TrustedIdentityContext,
)
from app.pipeline.canonical_mutations import RealQdrantMutationClient
from app.pipeline.ingestion_lock import DocumentAlreadyLockedError, IngestionLock
from app.pipeline.mongo_authority import MongoAuthorityClient
from app.pipeline.publisher import Publisher, RealQdrantClient
from app.pipeline.remote_source_resolver import (
    ContentValidationError,
    RemoteFetchError,
    TrustedOriginError,
    resolve_pdf_or_mp4_source,
)
from app.security.service_jwt import (
    ServiceIdentity,
    ServiceJWTVerifier,
    ServiceTokenError,
    load_public_keys_json,
)

logger = logging.getLogger(__name__)

canonical_router = APIRouter()

_BEARER_PREFIX = "Bearer "
_AUTH_FAILURE_DETAIL = "Invalid or missing authentication."


class CanonicalIngestRequest(BaseModel):
    """The frozen Phase 2A canonical request body -- EXACTLY
    `{document_id, file_type, file_url}`, nothing else. `extra="forbid"`
    is the tenancy-invariant enforcement mechanism at the contract layer.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str
    file_type: SourceType
    file_url: str

    @field_validator("document_id")
    @classmethod
    def _document_id_must_be_non_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("document_id must not be blank")
        return value

    @field_validator("file_url")
    @classmethod
    def _file_url_must_be_a_well_formed_http_url(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("file_url must not be blank")
        if not (value.startswith("http://") or value.startswith("https://")):
            raise ValueError("file_url must be an http(s) URL")
        return value


class CanonicalIngestResponse(BaseModel):
    document_id: str
    workspace_id: str
    file_type: SourceType
    status: str
    generation: int | None = None


def get_service_jwt_verifier(settings: Settings = Depends(get_settings)) -> ServiceJWTVerifier:
    public_keys = load_public_keys_json(settings.service_jwt_public_keys_json)
    return ServiceJWTVerifier(
        public_keys_by_kid=public_keys,
        expected_issuer=settings.service_jwt_expected_issuer,
        expected_audience=settings.service_jwt_expected_audience,
        required_scope=settings.service_jwt_required_scope,
        clock_skew_seconds=settings.service_jwt_clock_skew_seconds,
    )


def require_ingest_identity(
    request: Request,
    verifier: ServiceJWTVerifier = Depends(get_service_jwt_verifier),
) -> ServiceIdentity:
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.startswith(_BEARER_PREFIX):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL)

    token = auth_header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL)

    try:
        return verifier.verify(token)
    except ServiceTokenError as exc:
        logger.warning(
            "Internal service JWT verification failed for /v1/ingest",
            extra={"failure_category": "service_jwt_verification"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_AUTH_FAILURE_DETAIL) from exc


def get_canonical_orchestrator(settings: Settings = Depends(get_settings)) -> CanonicalIngestionOrchestrator:
    """Constructs the REAL Phase 1 orchestrator from real infrastructure
    clients (Redis, Mongo, Qdrant) -- unmodified Phase 1 classes, used
    exactly as their own test suites use them. Overridden in tests via
    `app.dependency_overrides` with fake-but-real-protocol doubles
    (fakeredis/mongomock/an in-memory Qdrant double), matching Phase 1's
    own established test convention -- never overridden with a mock of
    the orchestrator's own logic.
    """

    import pymongo
    import redis

    redis_client = redis.Redis.from_url(settings.redis_broker_url)
    mongo_client = pymongo.MongoClient(settings.mongo_url)
    lock = IngestionLock(redis_client)
    mongo_authority = MongoAuthorityClient(mongo_client, settings.mongo_database_name, settings.mongo_files_collection_name)
    qdrant_client = RealQdrantClient(settings.qdrant_url, settings.qdrant_api_key)
    qdrant_mutations = RealQdrantMutationClient(settings.qdrant_url, settings.qdrant_api_key)
    publisher = Publisher(settings=settings, qdrant_client=qdrant_client)

    return CanonicalIngestionOrchestrator(
        lock=lock,
        publisher=publisher,
        mutation_client=qdrant_mutations,
        mongo_authority=mongo_authority,
        canonical_collection_name=settings.canonical_qdrant_collection_name,
        lease_seconds=settings.ingestion_lock_lease_seconds,
    )


_OUTCOME_TO_STATUS = {
    CanonicalIngestionOutcome.COMPLETED: status.HTTP_202_ACCEPTED,
    CanonicalIngestionOutcome.ABORTED_LOCK_LOST: status.HTTP_409_CONFLICT,
    CanonicalIngestionOutcome.ABORTED_AUTHORITY_LOST: status.HTTP_409_CONFLICT,
    CanonicalIngestionOutcome.ABORTED_MISSING_FILE: status.HTTP_404_NOT_FOUND,
}


@canonical_router.post("/v1/ingest", response_model=CanonicalIngestResponse, status_code=status.HTTP_202_ACCEPTED)
def canonical_ingest(
    body: CanonicalIngestRequest,
    identity: ServiceIdentity = Depends(require_ingest_identity),
    orchestrator: CanonicalIngestionOrchestrator = Depends(get_canonical_orchestrator),
    settings: Settings = Depends(get_settings),
) -> CanonicalIngestResponse:
    """The canonical Phase 2A ingestion endpoint.

    TENANCY INVARIANT: `workspace_id`/`user_id` are read EXCLUSIVELY from
    `identity` (the verified JWT) -- `body` has no such fields to read
    from at all (schema-enforced, see `CanonicalIngestRequest`).
    """

    workspace_id = identity.workspace_id
    user_id = identity.sub

    temp_file_path: Path | None = None
    try:
        if body.file_type is SourceType.YOUTUBE:
            job_id = f"canonical-{body.document_id}"
            try:
                enriched_chunks, embeddings = extract_youtube_for_canonical_ingestion(job_id, body.file_url, settings)
            except VideoInaccessibleError as exc:
                # Same category as RemoteFetchError below (a real,
                # already-defined, ANTICIPATED YouTube processing failure
                # -- the video itself cannot be reached/read by
                # yt-dlp/youtube_transcript_api), not a client input
                # error and not an unexpected internal failure. Mapped
                # to the SAME status as RemoteFetchError/
                # ContentValidationError, matching the existing
                # PDF/MP4 branch's own convention for "we could not
                # obtain valid, processable content from the given
                # source" -- deliberately not inventing a third status
                # category for what is, at this level, the same kind of
                # failure.
                logger.warning(
                    "YouTube video inaccessible", extra={"document_id": body.document_id}
                )
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
            except TranscriptUnavailableError as exc:
                # Same category/status as VideoInaccessibleError above --
                # the video was reachable, but no usable transcript
                # content could be obtained from it. This task
                # deliberately does NOT add multilingual fallback,
                # translation, or any change to transcript-language
                # selection -- only converts this already-defined,
                # already-raised domain exception into a controlled
                # response instead of an unhandled 500.
                logger.warning(
                    "YouTube transcript unavailable", extra={"document_id": body.document_id}
                )
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.message) from exc
        else:
            try:
                temp_file_path = resolve_pdf_or_mp4_source(body.file_url, body.file_type, settings)
            except TrustedOriginError as exc:
                logger.warning("file_url rejected by trusted-origin policy", extra={"document_id": body.document_id})
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="file_url is not permitted.") from exc
            except (RemoteFetchError, ContentValidationError) as exc:
                logger.warning("file_url retrieval failed", extra={"document_id": body.document_id})
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to retrieve file_url.") from exc

            job_id = f"canonical-{body.document_id}"
            if body.file_type is SourceType.PDF:
                enriched_chunks, embeddings = extract_pdf_for_canonical_ingestion(job_id, temp_file_path, settings)
            else:
                enriched_chunks, embeddings = extract_video_for_canonical_ingestion(job_id, temp_file_path, settings)

        canonical_input = CanonicalIngestionInput(
            identity=TrustedIdentityContext(document_id=body.document_id, workspace_id=workspace_id, user_id=user_id),
            enriched_chunks=enriched_chunks,
            embeddings=embeddings,
        )

        try:
            result = orchestrator.run(canonical_input)
        except DocumentAlreadyLockedError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An ingestion attempt is already in progress for this document.") from exc

        http_status = _OUTCOME_TO_STATUS.get(result.outcome, status.HTTP_500_INTERNAL_SERVER_ERROR)
        if result.outcome != CanonicalIngestionOutcome.COMPLETED:
            raise HTTPException(status_code=http_status, detail=f"Ingestion did not complete: {result.outcome.value}")

        return CanonicalIngestResponse(
            document_id=body.document_id,
            workspace_id=workspace_id,
            file_type=body.file_type,
            status=result.outcome.value,
            generation=result.generation,
        )
    finally:
        if temp_file_path is not None:
            temp_file_path.unlink(missing_ok=True)
