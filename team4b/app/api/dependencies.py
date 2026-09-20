"""Team 4B API dependency injection (Task 8.1).

Lazily constructs (and caches) the real component graph
(`VectorStoreManager` -> `HybridRetriever`, `ConversationManager`,
`LLMGenerator` -> `RAGService`) for use as FastAPI `Depends()`
providers. Nothing here is constructed at import time -- each function
below only builds its object the first time it's actually called
(`functools.lru_cache` caches the result after that, giving the API
layer a single shared instance of each component without a module-level
singleton created at import).

TESTABILITY: every route depends on these functions via `Depends(...)`,
so tests override them with `app.dependency_overrides[get_rag_service] = ...`
(or `get_conversation_manager`) to inject fakes -- no live Qdrant, Redis,
or Ollama is ever required to exercise the API boundary. See
`tests/test_api.py`.

SCOPE NOTE (superseded by PHASE 5C-2): this module itself still does not
call `HybridRetriever.refresh_bm25_corpus()` -- ongoing BM25
freshness/rebuild strategy (e.g. re-refreshing after new ingestion)
remains out of scope here, unchanged. What HAS changed: the
long-standing gap where NOTHING in the live application ever called
`refresh_bm25_corpus()` at all (confirmed in
team4b/data/m6_phase5b_retrieval_reliability_diagnosis.md -- the BM25
corpus was permanently empty in every deployed process) is now closed
by `app/api/main.py`'s `lifespan` handler, which calls
`get_hybrid_retriever().refresh_bm25_corpus()` exactly once at process
startup, using this module's own existing, cached `HybridRetriever`
instance -- no second instance, no duplicated BM25 wiring here.

TASK 10.1 ADDITIONS: `get_vector_store_manager()`, `get_bm25_index()`,
and `get_embedder()` were extracted out of `get_hybrid_retriever()`'s
previously-inline construction so `GET /health` can inject and check the
exact same `VectorStoreManager` instance the query path uses, rather
than building a second one just for health checks.
`get_metrics_collector()` provides the single process-wide
`MetricsCollector` (`app/services/metrics.py`) shared between
`POST /api/v1/query` (which records into it) and `GET /metrics` (which
reads it) -- see `app/api/routes.py` for how both are wired.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.services.bm25_index import BM25Index
from app.services.conversation import ConversationManager
from app.services.embedder import Embedder
from app.services.evaluation import EvaluationPipeline, JSONLEvaluationStore
from app.services.generation_authority import GenerationAuthorityClient
from app.services.hybrid_retriever import HybridRetriever
from app.services.llm_generator import LLMGenerator
from app.services.metrics import MetricsCollector
from app.services.rag_service import RAGService
from app.services.ragas_adapter import RagasEvaluationAdapter
from app.services.reranker import CrossEncoderReranker, RerankerProtocol
from app.services.vector_store import VectorStoreManager


@lru_cache
def get_generation_authority() -> GenerationAuthorityClient:
    """MVP M4: constructs the ONE, narrow, read-only Mongo authority
    client (app/services/generation_authority.py) -- the sole Mongo
    connection anywhere in this codebase, used exclusively to read
    `File.currentIngestionGeneration`. `@lru_cache` gives one shared
    `pymongo.MongoClient` connection per process (matching every other
    provider in this module) -- this does NOT cache query RESULTS;
    `GenerationAuthorityClient.get_current_generations()` always issues a
    fresh Mongo read.
    """

    from pymongo import MongoClient

    settings = get_settings()
    mongo_client: MongoClient = MongoClient(
        settings.mongo_url, serverSelectionTimeoutMS=settings.generation_authority_mongo_timeout_ms
    )
    return GenerationAuthorityClient(
        mongo_client=mongo_client,
        database_name=settings.mongo_database_name,
        collection_name=settings.mongo_files_collection_name,
    )


@lru_cache
def get_vector_store_manager() -> VectorStoreManager:
    """ADDED IN TASK 10.1: extracted out of `get_hybrid_retriever()` so
    `GET /health` can inject and health-check the SAME VectorStoreManager
    instance the query path actually uses, rather than constructing a
    second, separate one. `get_hybrid_retriever()` below now calls this
    function instead of constructing its own `VectorStoreManager`
    inline -- its own return type/behavior is otherwise unchanged.
    """

    return VectorStoreManager(settings=get_settings())


@lru_cache
def get_bm25_index() -> BM25Index:
    """ADDED IN TASK 10.1, extracted for the same reason as
    `get_vector_store_manager()` above (consistency/symmetry) -- BM25 has
    no Task 10.1 health check of its own (it is a pure in-memory index,
    not an external dependency), but decomposing `get_hybrid_retriever()`
    uniformly keeps the DI graph easy to reason about.
    """

    return BM25Index()


@lru_cache
def get_embedder() -> Embedder:
    """ADDED IN TASK 10.1, extracted for the same reason as
    `get_vector_store_manager()` above."""

    return Embedder(settings=get_settings())


@lru_cache
def get_reranker() -> RerankerProtocol | None:
    """ADDED IN PHASE 4B. Returns `None` (reranking disabled) unless an
    operator explicitly sets `RERANKER_ENABLED=true` -- `Settings.reranker_enabled`
    defaults to `False`, so this function changes no existing deployment's
    behavior automatically. Like every other provider in this module,
    nothing is constructed (in particular, no model weights are loaded)
    unless this function is actually called and the flag is on.
    """

    settings = get_settings()
    if not settings.reranker_enabled:
        return None
    return CrossEncoderReranker(settings=settings)


@lru_cache
def get_hybrid_retriever() -> HybridRetriever:
    settings = get_settings()
    return HybridRetriever(
        vector_store=get_vector_store_manager(),
        bm25_index=get_bm25_index(),
        embedder=get_embedder(),
        generation_authority=get_generation_authority(),
        settings=settings,
        reranker=get_reranker(),
    )


@lru_cache
def get_conversation_manager() -> ConversationManager:
    return ConversationManager(settings=get_settings())


@lru_cache
def get_llm_generator() -> LLMGenerator:
    return LLMGenerator(settings=get_settings())


@lru_cache
def get_rag_service() -> RAGService:
    return RAGService(
        hybrid_retriever=get_hybrid_retriever(),
        conversation_manager=get_conversation_manager(),
        llm_generator=get_llm_generator(),
    )


@lru_cache
def get_evaluation_pipeline() -> EvaluationPipeline:
    """ADDED IN TASK 9.1. Wires the real `RagasEvaluationAdapter`
    (`app/services/ragas_adapter.py`) and `JSONLEvaluationStore`
    (`app/services/evaluation.py`) -- both lazily constructed, nothing
    built at import time, consistent with every other provider in this
    module. See `app/services/ragas_adapter.py`'s module docstring for
    the important caveat that this real path has not been exercised
    against a live Ollama/embedding stack in this environment.
    """

    settings = get_settings()
    return EvaluationPipeline(
        evaluator=RagasEvaluationAdapter(settings=settings),
        store=JSONLEvaluationStore(settings.evaluation_results_path),
        settings=settings,
    )


@lru_cache
def get_metrics_collector() -> MetricsCollector:
    """ADDED IN TASK 10.1. A single process-wide `MetricsCollector`
    instance (thread-safe internally -- see that module's docstring),
    shared by `POST /api/v1/query` (which records into it) and
    `GET /metrics` (which reads a snapshot from it). `@lru_cache` gives
    exactly one instance per process, same convention as every other
    provider in this module.
    """

    return MetricsCollector()
