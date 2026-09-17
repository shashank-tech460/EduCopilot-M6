"""Team 4B FastAPI routes (Tasks 8.1, 9.1, 10.1): the Conversational
Query API, the Evaluation API, and Health/Observability.

    POST /api/v1/query
    GET  /api/v1/sessions/{session_id}/history
    POST /api/v1/evaluate
    GET  /health
    GET  /metrics

The first three routes are a thin HTTP boundary: they delegate to the already-
approved `RAGService` (Task 7.1) and `ConversationManager` (Task 4.1),
convert the result via `assemble_query_response` (Task 7.2), and map
domain exceptions to HTTP responses. Neither route queries Qdrant,
Redis, or Ollama directly, builds a prompt, executes retrieval, or
assembles/reorders source attributions itself -- all of that remains
exactly where earlier tasks put it.

CALL CHAIN (preserved exactly, not reimplemented):

    HTTP request -> route -> RAGService -> ConversationManager
                                         -> HybridRetriever
                                         -> LLMGenerator
                                         -> response assembly
                                         -> QueryResponse -> HTTP response

ERROR -> HTTP MAPPING (documented decision, since neither official
document prescribes exact status codes): `VectorStoreUnavailableError`,
`LLMUnavailableError`, and `ConversationStoreUnavailableError` all map
to `503 Service Unavailable` -- each represents a downstream dependency
being unreachable, which is exactly what 503 conventionally signals; a
generic message is returned (`{"detail": "..."}`, FastAPI's own
built-in `HTTPException` shape, not a custom envelope) rather than the
raw exception text, so internal connection details are never leaked to
a client. Pydantic/FastAPI's own automatic `422 Unprocessable Entity`
validation handles malformed request bodies without any code here.
A nonexistent session for the history endpoint maps to `404 Not Found`
(see that route's own docstring for why this state is distinguishable
from "existing but empty" even though the latter cannot actually occur
given `ConversationManager`'s real behavior).

TASK 10.1 (`GET /health`, `GET /metrics`): see each route's own
docstring below for exact semantics. Neither route calls
`RAGService.handle_query()`, executes retrieval, or performs LLM
generation -- both are lightweight, read-only, and cannot fail a normal
query (metrics recording in `post_query` is wrapped so it can never
itself raise and break a request; see that route's own comments).
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.auth_dependency import require_query_identity
from app.models.evaluation import EvaluationItem, EvaluationResponse
from app.models.query import QueryRequest, QueryResponse
from app.security.service_jwt import ServiceIdentity
from app.services.conversation import (
    ConversationManager,
    ConversationStoreUnavailableError,
)
from app.services.evaluation import (
    BatchTooLargeError,
    EvaluationExecutionError,
    EvaluationPersistenceError,
    EvaluationPipeline,
)
from app.services.llm_generator import LLMGenerator, LLMUnavailableError
from app.services.metrics import MetricsCollector
from app.services.rag_service import RAGService
from app.services.response_assembly import assemble_query_response
from app.services.vector_store import (
    VectorStoreManager,
    VectorStoreUnavailableError,
)

from .dependencies import (
    get_conversation_manager,
    get_evaluation_pipeline,
    get_llm_generator,
    get_metrics_collector,
    get_rag_service,
    get_vector_store_manager,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/api/v1/query", response_model=QueryResponse)
def post_query(
    request: QueryRequest,
    rag_service: RAGService = Depends(get_rag_service),
    metrics_collector: MetricsCollector = Depends(get_metrics_collector),
    _identity: ServiceIdentity = Depends(require_query_identity),
) -> QueryResponse:
    """Answer `request.query`, auto-creating/resolving the session and
    resolving retrieval configuration exactly as `RAGService.handle_query()`
    already does (see that method's own docstring) -- this route adds
    no session-management or configuration-resolution logic of its own.

    MVP M3: `workspace_id` is read EXCLUSIVELY from `_identity` (the
    already-verified internal service JWT, Phase 2B/2E) and passed to
    `rag_service.handle_query()` -- `request` (the canonical
    `{query, session_id, retrieval_config}` body) has no `workspace_id`
    field to read from at all (Phase 2A's frozen contract, unchanged),
    so there is no client-suppliable value that could override it even
    if this route's logic were buggy.

    TASK 10.1: records query timing/count/hit/error into
    `metrics_collector` and logs a single timing line at the end of
    every attempt. The log line intentionally includes ONLY the query
    LENGTH, duration, success/hit flags, and (on failure) the exception
    type name -- never the query text, the answer text, retrieved
    context, or any other user content, per the explicit instruction not
    to log sensitive/user data unnecessarily. Metrics recording itself
    is wrapped so that a bug in the metrics/logging code can never turn
    an otherwise-successful query into a failed HTTP response.
    """

    start_time = time.monotonic()
    succeeded = False
    hit = False
    rag_result = None

    try:
        rag_result = rag_service.handle_query(
            request.query,
            workspace_id=_identity.workspace_id,
            session_id=request.session_id,
            retrieval_config=request.retrieval_config,
        )
        succeeded = True
        hit = rag_result.retrieval_metadata.get("chunks_retrieved", 0) > 0

    except VectorStoreUnavailableError as exc:
        logger.exception(
            "Vector store operation failed during query handling"
        )
        _record_query_metrics(
            metrics_collector,
            start_time,
            succeeded=False,
            hit=False,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Vector store is currently unavailable.",
        ) from exc

    except LLMUnavailableError as exc:
        logger.exception(
            "LLM generation failed during query handling"
        )
        _record_query_metrics(
            metrics_collector,
            start_time,
            succeeded=False,
            hit=False,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Language model service is currently unavailable.",
        ) from exc

    except ConversationStoreUnavailableError as exc:
        logger.exception(
            "Conversation store operation failed during query handling"
        )
        _record_query_metrics(
            metrics_collector,
            start_time,
            succeeded=False,
            hit=False,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=503,
            detail="Conversation store is currently unavailable.",
        ) from exc

    except HTTPException:
        raise

    except Exception as exc:
        logger.exception(
            "Unexpected error during query handling"
        )
        _record_query_metrics(
            metrics_collector,
            start_time,
            succeeded=False,
            hit=False,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the query.",
        ) from exc

    _record_query_metrics(
        metrics_collector,
        start_time,
        succeeded=succeeded,
        hit=hit,
        error_type=None,
    )
    return assemble_query_response(rag_result)


def _record_query_metrics(
    metrics_collector: MetricsCollector,
    start_time: float,
    *,
    succeeded: bool,
    hit: bool,
    error_type: str | None,
) -> None:
    """Records timing/count/hit/error and logs one timing line. Wrapped
    in its own try/except so that ANY failure here (a bug in this code,
    an unexpected exception from the collector) is logged and swallowed
    rather than turning an already-successful query into a 500 -- per
    the explicit instruction that observability code must be
    non-critical to core query execution.
    """

    duration_seconds = time.monotonic() - start_time

    try:
        metrics_collector.record_query(
            duration_seconds=duration_seconds,
            succeeded=succeeded,
            hit=hit,
        )
        logger.info(
            "Query processed",
            extra={
                "duration_seconds": duration_seconds,
                "succeeded": succeeded,
                "hit": hit,
                "error_type": error_type,
            },
        )

    except Exception:  # noqa: BLE001 -- observability must never break a request
        logger.warning(
            "Failed to record query metrics",
            exc_info=True,
        )


class HistoryTurn(BaseModel):
    """Minimal API representation of one stored conversation turn.

    Deliberately not `ConversationTurn` itself (a plain dataclass, not a
    Pydantic model, and an internal component type from Task 4.1) --
    this is the smallest sensible, genuinely-Pydantic shape for HTTP/
    OpenAPI purposes, carrying exactly the three fields the official
    specification actually stores: role, content, timestamp. No other
    fields are added.
    """

    role: str
    content: str
    timestamp: float


class SessionHistoryResponse(BaseModel):
    """Minimal API response for GET history: the session_id echoed back
    plus the COMPLETE (never windowed) stored history, in original
    chronological order -- exactly what `ConversationManager.get_history()`
    already returns, serialized. No official Pydantic model for this
    response exists in Task 1.2's contract (only `QueryResponse` and
    `SourceAttribution` are specified there), so this is a Task 8.1-local
    addition, kept intentionally minimal per the explicit instruction not
    to invent an elaborate schema.
    """

    session_id: str
    history: list[HistoryTurn]


@router.get(
    "/api/v1/sessions/{session_id}/history",
    response_model=SessionHistoryResponse,
)
def get_session_history(
    session_id: str,
    conversation_manager: ConversationManager = Depends(
        get_conversation_manager
    ),
) -> SessionHistoryResponse:
    """Return the complete stored conversation history for `session_id`,
    in original chronological order -- never the configured 5-turn
    prompting window (`get_windowed_history`, used only internally by
    `RAGService`/`LLMGenerator`). Read-only: this route never appends,
    trims, or otherwise mutates stored history.

    Raises `404` if `session_id` has never been created (no Redis key
    exists for it) -- distinguished from "exists but has zero turns",
    a state that cannot actually be produced by `ConversationManager`'s
    own API (a session's Redis key is only ever created by
    `append_turn`, which always adds at least one turn in the same
    operation), but the check is implemented as the philosophically
    correct one regardless, per the explicit instruction not to assume
    an empty result means the session exists.
    """

    try:
        exists = conversation_manager.session_exists(session_id)
    except ConversationStoreUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation store is currently unavailable.",
        ) from exc

    if not exists:
        raise HTTPException(
            status_code=404,
            detail=f"Session {session_id!r} was not found.",
        )

    try:
        turns = conversation_manager.get_history(session_id)
    except ConversationStoreUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="Conversation store is currently unavailable.",
        ) from exc

    return SessionHistoryResponse(
        session_id=session_id,
        history=[
            HistoryTurn(
                role=turn.role,
                content=turn.content,
                timestamp=turn.timestamp,
            )
            for turn in turns
        ],
    )


@router.post(
    "/api/v1/evaluate",
    response_model=EvaluationResponse,
)
def post_evaluate(
    items: list[EvaluationItem],
    evaluation_pipeline: EvaluationPipeline = Depends(
        get_evaluation_pipeline
    ),
) -> EvaluationResponse:
    """ADDED IN TASK 9.1. Evaluate a batch of caller-supplied
    query/response/context triples via RAGAS (Requirement 8). Does NOT
    execute retrieval, generation, or any part of the normal RAG query
    path -- `items` are the complete, self-contained evaluation input.

    The request body is a raw JSON array (`list[EvaluationItem]`), not
    an envelope object -- neither official document describes an
    envelope, so the simplest shape matching "a batch of triples" is
    used. Batch-size validation (`Settings.evaluation_batch_max_size`,
    default 50) happens inside `EvaluationPipeline.evaluate_batch()`
    before any evaluation is attempted; `BatchTooLargeError` maps to
    `422` here, consistent with FastAPI/Pydantic's own automatic
    validation semantics for oversized/malformed input. A persistence
    failure maps to `503`, since Requirement 8 requires timestamped
    storage as part of the contract. A total evaluator failure
    (`EvaluationExecutionError` -- the underlying RAGAS/LLM/embeddings
    stack unreachable or erroring, distinct from a per-metric failure
    within an otherwise-successful item, which never raises at all)
    also maps to `503`.
    """

    try:
        return evaluation_pipeline.evaluate_batch(items)

    except BatchTooLargeError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    except EvaluationPersistenceError as exc:
        raise HTTPException(
            status_code=503,
            detail="Evaluation result storage is currently unavailable.",
        ) from exc

    except EvaluationExecutionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Evaluation service is currently unavailable.",
        ) from exc


class ComponentHealth(BaseModel):
    """Minimal per-component health representation for `GET /health`.
    No official Pydantic model for this exists in Task 1.2's contract,
    so this is a Task 10.1-local addition, kept intentionally minimal.
    """

    status: str  # "healthy" | "unavailable"
    detail: str | None = None


class HealthResponse(BaseModel):
    """`GET /health`'s response: an overall status plus one
    `ComponentHealth` per required component (rag, vector_store, redis,
    llm) -- Requirement 9's own four named components, exactly.
    """

    status: str  # "healthy" | "degraded"
    components: dict[str, ComponentHealth]


def _check_component(
    check_fn: Callable[[], bool],
) -> ComponentHealth:
    """Runs one component's health check, tolerating ANY failure mode:
    a `False` return value, or the check itself raising. Never lets an
    exception from a health check propagate and break the `/health`
    endpoint -- per the explicit requirement that "health endpoint
    remains stable when a dependency check raises an exception."
    """

    try:
        return (
            ComponentHealth(status="healthy")
            if check_fn()
            else ComponentHealth(
                status="unavailable",
                detail="Health check reported the component as unavailable.",
            )
        )

    except Exception as exc:  # noqa: BLE001 -- any failure means "unavailable", never a crash
        return ComponentHealth(
            status="unavailable",
            detail=f"Health check raised {type(exc).__name__}.",
        )


@router.get("/health", response_model=HealthResponse)
def get_health(
    vector_store: VectorStoreManager = Depends(get_vector_store_manager),
    conversation_manager: ConversationManager = Depends(
        get_conversation_manager
    ),
    llm_generator: LLMGenerator = Depends(get_llm_generator),
) -> HealthResponse:
    """Reports the health of Requirement 9's four required components:
    `rag`, `vector_store`, `redis`, `llm`. Always returns HTTP 200 --
    failures are represented IN THE BODY (per-component `"unavailable"`
    status, plus an overall `"degraded"` status when any component is
    down), never hidden behind an unconditional "everything is fine."
    This is a documented decision (neither official document prescribes
    an HTTP status-code contract for `/health`): a `503` here could
    cause infrastructure (e.g. a load balancer or orchestrator) to kill
    an otherwise-healthy application process merely because one
    downstream dependency is temporarily degraded, which is a stronger
    and more destructive action than this task's own requirement (accurate
    component-level reporting) calls for.

    "rag" HEALTH, EXPLAINED (fixed during this task's own review -- see
    below for why the first version of this was wrong): "rag" is a
    DERIVED rollup of the other three, not an independent probe of its
    own -- there is no separate external "RAG service" to check (per
    the explicit instruction not to invent one). It is `"healthy"` only
    when `vector_store`, `redis`, AND `llm` are ALL healthy, because
    `RAGService.handle_query()`'s actual implementation (Task 7.1)
    genuinely requires all three to succeed: it calls
    `ConversationManager.append_turn()` (Redis) unconditionally before
    retrieval (`vector_store`) or generation (`llm`) are even attempted,
    so a real query fails end-to-end if ANY of the three is down --
    "rag" reporting that accurately is the whole point of naming it as
    its own required component, distinct from redundantly repeating one
    of the other three.

    An EARLIER VERSION OF THIS FUNCTION reported "rag" as unconditionally
    `"healthy"` on the reasoning that "reaching this function's body at
    all means the RAGService dependency graph was constructed
    successfully." That reasoning is correct but the conclusion is not
    useful: since none of `RAGService`'s constituent components open a
    network connection at construction time (confirmed by inspecting
    each `__init__`), that check could NEVER fail here regardless of
    whether Qdrant/Redis/Ollama were actually reachable -- making "rag"
    tautological and non-diagnostic in every real scenario. Fixed here
    to be a genuine, meaningful signal instead.

    Lightweight and read-only: no LLM generation, no retrieval, no
    Qdrant/Redis writes -- each check is a single cheap call
    (`VectorStoreManager.check_health()`, `ConversationManager.check_health()`,
    `LLMGenerator.check_health()`), documented in their own modules.
    """

    dependency_components = {
        "vector_store": _check_component(vector_store.check_health),
        "redis": _check_component(conversation_manager.check_health),
        "llm": _check_component(llm_generator.check_health),
    }

    rag_healthy = all(
        component.status == "healthy"
        for component in dependency_components.values()
    )

    rag_component = (
        ComponentHealth(status="healthy")
        if rag_healthy
        else ComponentHealth(
            status="unavailable",
            detail=(
                "RAGService requires vector_store, redis, and llm "
                "to all be healthy; at least one is not."
            ),
        )
    )

    components = {
        "rag": rag_component,
        **dependency_components,
    }

    overall_status = (
        "healthy"
        if all(
            component.status == "healthy"
            for component in components.values()
        )
        else "degraded"
    )

    return HealthResponse(
        status=overall_status,
        components=components,
    )


class MetricsResponse(BaseModel):
    """`GET /metrics`'s response. No official Pydantic model exists for
    this in Task 1.2's contract, so this is a Task 10.1-local addition,
    kept to exactly the four fields Requirement 9 names: query count,
    average latency, hit rate, error rate. See `app/services/metrics.py`
    for exact semantics and zero-query behavior.
    """

    query_count: int
    average_latency_seconds: float | None
    hit_rate: float | None
    error_rate: float | None


@router.get(
    "/metrics",
    response_model=MetricsResponse,
)
def get_metrics(
    metrics_collector: MetricsCollector = Depends(get_metrics_collector),
) -> MetricsResponse:
    """Returns real, accumulated query-processing metrics (see
    `app/services/metrics.py`'s module docstring for exact semantics) --
    never fabricated/static values. Lightweight and read-only: reads an
    in-memory snapshot, executes no query, no retrieval, no LLM call.
    """

    snapshot = metrics_collector.snapshot()

    return MetricsResponse(
        query_count=snapshot.query_count,
        average_latency_seconds=snapshot.average_latency_seconds,
        hit_rate=snapshot.hit_rate,
        error_rate=snapshot.error_rate,
    )