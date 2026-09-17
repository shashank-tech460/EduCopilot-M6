# Team 4B — Advanced RAG & Semantic Search

Status: **Tasks 1.1, 1.2 (corrective), 2.1, 2.2, 3.1, 3.2, 3.3, 4.1,
4.2, 6.1, 6.2, 7.1, 7.2, 8.1, 9.1, 9.2, 10.1, 10.2/P19, and 11.1
complete.** Project
structure, configuration, VectorStoreManager (Requirement 1) with its
official Property 1-3 tests, the standalone BM25 index + query embedder,
HybridRetriever (Requirement 2, with its official Property 4-7 tests),
ConversationManager (Requirement 4/5's Redis-backed history) with
its official Property 13-14 tests, LLMGenerator (Requirement 3: grounded prompt construction, Ollama
integration, insufficient-context handling, LLMUnavailable mapping)
with its official Property 8 test, RAGService orchestration (Task 7.1)
with response assembly (Task 7.2, Properties 9-12/15-17), the FastAPI
Conversational Query/History/Evaluation API (Task 8.1), the RAGAS
Evaluation Pipeline (Task 9.1, remediated) with P18 low-faithfulness
flagging (Task 9.2), and Health/Observability (Task 10.1: `GET /health`, `GET /metrics`) with
its official Property 19 test (Task 10.2). Docker/deployment and the
final integration checkpoint remain unimplemented.

**Resolved discrepancy:** an earlier audit (during Task 4.1) found
that Task 1.2 (SearchMode, RetrievalConfig, QueryRequest, QueryResponse,
SourceAttribution) had never actually been implemented despite being
referenced as already-approved. This has now been corrected in
`app/models/query.py`; see that file's docstring for the exact contract
and the design decisions made while implementing it.

## Structure

```
rag_service/
  app/
    api/
      main.py                  # FastAPI app entry point (Task 8.1)
      routes.py                 # POST /api/v1/query, GET /api/v1/sessions/{id}/history (Task 8.1)
      dependencies.py            # FastAPI DI providers (Task 8.1; +get_evaluation_pipeline in 9.1)
    core/
      config.py             # Settings (Task 1.1; +hybrid_candidate_pool_size in Task 3.2)
    models/
      retrieval.py           # RetrievalResult dataclass (internal component contract, Task 2.1)
      query.py                # SearchMode, RetrievalConfig, QueryRequest, SourceAttribution, QueryResponse (Corrective Task 1.2)
    services/
      vector_store.py         # VectorStoreManager + read-side adapter (Task 2.1; +scroll_all_chunks in Task 3.2)
      rag_service.py           # RAGService orchestrator (Task 7.1)
      bm25_index.py            # in-memory BM25 keyword index (Task 3.1)
      embedder.py              # query-time embedding generation (Task 3.1)
      hybrid_retriever.py       # HybridRetriever: mode routing, RRF, normalization (Task 3.2; EmbedderProtocol fix in Task 3.3)
      conversation.py           # ConversationManager: Redis-backed history (Task 4.1)
    api/                       # empty -- Tasks 8.1, 10.1
  tests/
    test_config.py           # Task 1.1 config tests
    test_vector_store.py      # Task 2.1 focused unit/integration/error-path tests
    test_vector_store_properties.py  # Task 2.2: official Property 1-3 tests (Hypothesis-based)
    test_bm25_index.py        # Task 3.1: BM25 index tests
    test_embedder.py          # Task 3.1: Embedder tests
    test_hybrid_retriever.py  # Task 3.2: HybridRetriever/RRF/normalization tests
    test_hybrid_retriever_properties.py  # Task 3.3: official Property 4-7 tests (Hypothesis-based)
    test_conversation.py      # Task 4.1: ConversationManager tests
    test_conversation_properties.py  # Task 4.2: official Property 13-14 tests (Hypothesis-based)
    test_llm_generator.py     # Task 6.1: LLMGenerator tests
    test_llm_properties.py    # Task 6.2: official Property 8 test (Hypothesis-based)
    test_query_models.py      # Corrective Task 1.2: query/response model tests
    test_rag_service.py       # Task 7.1: RAGService orchestration tests
    test_rag_service_properties.py       # Task 7.2: official Property 16-17 tests
    test_response_assembly.py             # Task 7.2: response assembly unit tests
    test_response_assembly_properties.py  # Task 7.2: official Property 9-12,15 tests
    test_api.py                # Task 8.1 route tests + Task 9.1 evaluate route tests (TestClient, real services + fakes)
    test_evaluation.py         # Task 9.1: EvaluationPipeline tests
    test_ragas_adapter.py      # Task 9.1: RAGAS wrapper-class unit tests (no live RAGAS/Ollama execution)
    fakes.py                  # in-memory Qdrant fake (2.2; +scroll in 3.2) + Redis fake (4.1) + LLM fake (6.1)
  docs/
    CONTRACT_DECISIONS.md   # approved Team 4A/4B/4C integration decisions
  requirements.txt
  requirements-dev.txt
  pytest.ini
  .env.example
```

## Known limitation found by Task 3.3's property tests

`TestCandidatePoolRecallLimitation` (in `test_hybrid_retriever_properties.py`)
demonstrates directly that `hybrid_candidate_pool_size` bounds how many
chunks the vector leg ever considers before fusion: with a corpus larger
than the effective pool, chunks ranked below the pool cutoff by cosine
similarity alone never get a chance to contribute their vector-leg RRF
term, even if a strong BM25 match would otherwise have helped them
surface in the final result. This is a real, reportable recall
characteristic of Task 3.2's chosen pooling strategy, not a P4-P7
violation (all four properties hold regardless of pool size, verified
separately in `TestCandidatePoolIndependence`) -- worth revisiting in a
later hardening pass if recall against large corpora becomes a concern.

## Task 4.1 documented interpretations (not spec-mandated, flagged as such)

- **TTL renewal on "interaction":** interpreted as renewing only on
  `append_turn` (a write), not on history reads. See
  `app/services/conversation.py`'s module docstring for the reasoning.
- **Redis failure handling:** no retry/backoff (unlike
  `VectorStoreManager`'s Requirement-1.5-mandated retries) and no
  fallback -- every failure raises `ConversationStoreUnavailableError`.
  Neither Requirement 4 nor 5 specifies Redis retry/degradation
  behavior at this layer, so none was invented.

## Configuration

All runtime configuration lives in `app/core/config.py` (`Settings`,
`get_settings()`), environment-overridable per `.env.example`. See
`docs/CONTRACT_DECISIONS.md` for why each default was chosen.

## Running tests

```
pip install -r requirements-dev.txt --break-system-packages
pytest
```

## Not yet implemented

Task 12, the final integration checkpoint. A real-laptop integration
checkpoint (using live Qdrant/Redis/Ollama rather than unit-test fakes)
remains outstanding -- not performed as part of this repository's
automated test suite.

## Known limitation: no live embedding model in this environment

This sandbox's network allowlist does not include huggingface.co, so the
real all-MiniLM-L6-v2 model cannot be downloaded/run here. `Embedder`'s
own logic (lazy loading, dimension enforcement, query embedding) is
fully tested via an injected fake; `RealEmbeddingModel`'s actual
`sentence-transformers` integration is verified only by inspection and
type-checking, not by execution. A deployment with real network access
to huggingface.co is expected to work as designed, but this has not
been exercised end-to-end here.

## Known limitation: no live Redis in this environment

Similarly, `ConversationManager`'s tests all run against
`tests/fakes.py::FakeRedisClient`, an in-memory stand-in that does not
simulate real TTL countdown/expiry (it only records the TTL value passed
to `expire()`). Real Redis expiration behavior has not been exercised
end-to-end here.

## Known limitation: no live Ollama in this environment

`LLMGenerator`'s tests all run against `tests/fakes.py::FakeLLMClient`
or a stubbed `httpx.post`. A live Ollama connectivity check was
attempted (`curl http://localhost:11434/api/tags`) and failed
(connection refused, exit code 7) -- no Ollama server is running in
this sandbox. No live smoke test was performed or claimed; the 15-second
generation target (Requirement 3.5) has not been measured against a
real model.

## Task 8.1 HTTP error-mapping decisions (documented, not spec-mandated)

- `VectorStoreUnavailableError` / `LLMUnavailableError` /
  `ConversationStoreUnavailableError` -> `503 Service Unavailable`, with
  a generic `{"detail": "..."}` message (FastAPI's own built-in
  `HTTPException` shape) -- never the raw exception text, so connection
  strings/URLs are never leaked to a client.
- Nonexistent session for `GET /api/v1/sessions/{id}/history` -> `404
  Not Found`. Note: `ConversationManager` can never actually produce an
  "exists but has zero turns" state (a session's Redis key is only ever
  created by `append_turn`, which always adds >=1 turn), so this 404
  path is the only reachable "session not found" outcome in practice --
  documented as a forward-looking, philosophically correct check rather
  than dead code.
- Malformed/invalid request bodies (missing `query`, `top_k`/
  `score_threshold` out of range, invalid `search_mode`) all resolve to
  FastAPI/Pydantic's own automatic `422 Unprocessable Entity` -- no
  custom validation code was added.

## Running the API

```
uvicorn app.api.main:app --reload
```

Visit `/docs` for interactive OpenAPI documentation once dependencies
(Qdrant, Redis, Ollama) are configured and reachable per `.env.example`.
No `/health`, `/metrics`, or `/api/v1/evaluate` endpoints exist yet
(Tasks 9.1/10.1).

## Task 9.1: Evaluation Pipeline (RAGAS)

**Input contract:** a raw JSON array of `{query, response, contexts}`
triples (`POST /api/v1/evaluate`) -- no envelope, no session_id, no
document_id, matching the official minimal contract exactly.

**Four metrics:** `faithfulness`, `answer_relevancy`, `context_precision`,
`context_recall`, each `float | None` per item (`None` = failed to
compute, never a fabricated `0.0`).

**Batch size:** max 50 (`Settings.evaluation_batch_max_size`), enforced
before any evaluation is attempted (`BatchTooLargeError` -> HTTP 422).
Empty batches are accepted and persisted with an all-`None` aggregate;
RAGAS is never invoked for zero items.

**Partial failure:** a per-item, per-metric failure never discards the
item or its other successful metrics; `EvaluationItemResult.errors`
names which metric failed and why. Aggregates are the arithmetic mean of
only the successful values per metric (documented decision, since
neither official document specifies the aggregation formula); an
all-failed metric produces an aggregate of `None`, not `0.0`.

**Total evaluator failure** (the whole RAGAS/LLM/embeddings call
failing, as opposed to a per-metric NaN) raises `EvaluationExecutionError`
-> HTTP 503. This was a real gap found while writing the HTTP-level
tests for this task and has since been fixed (see git history / this
task's report).

**Persistence:** timestamped (`datetime.now(timezone.utc)`, timezone-
aware, injectable clock), append-only JSONL at
`Settings.evaluation_results_path` (default
`data/evaluation_results.jsonl`) -- the smallest production-sensible
mechanism that doesn't require a new database dependency.

**Genuine spec-vs-library gap -- REMEDIATED:** RAGAS's `context_precision`
and `context_recall` both structurally require a `reference`
(ground-truth) field the official Team 4B evaluation contract doesn't
supply. An initial implementation substituted `reference = response`
for both; an audit proved (via direct RAGAS source inspection) this was
semantically invalid for `context_recall` specifically -- RAGAS's own
`context_recall` docstring says it measures TP/FN against an
independently-"annotated answer," not the system's own generated
response, and RAGAS 0.4.3 ships no reference-free variant of it.

**Current, corrected behavior:**
- `context_recall` is **never computed** -- the `ContextRecall` metric
  class is never imported, instantiated, or requested from RAGAS. Every
  item's `context_recall` is `None`, with a fixed
  `errors["context_recall"]` reason (never a fabricated score, never
  silently dropped from the schema).
- `context_precision` still uses `reference = response` internally,
  but this is verified (by direct source comparison) to reproduce
  RAGAS's own official reference-free `ContextPrecisionWithoutReference`
  formulation field-for-field -- documented as "the reference-free
  formulation," never claimed as independent ground truth.
- Aggregation excludes `context_recall` from its own denominator when
  unavailable (producing `None`, never `0.0` or a divide-by-zero), and
  does not affect the other three metrics' aggregates.

See `app/services/ragas_adapter.py`'s module docstring for the full
reasoning, including why switching `context_precision` to the genuine
reference-free RAGAS API was considered and rejected (it requires an
incompatible, modern instructor-based LLM wrapper protocol).

**Not live-tested:** no Ollama is reachable in this sandbox (same
`curl localhost:11434` connection-refused result as Task 6.1). The real
RAGAS adapter's wrapper classes are unit-tested against fake clients;
`ragas.evaluate()` itself has never been executed here. The 50-item/
60-second performance requirement has NOT been benchmarked -- only a
timeout *configuration* value is tested, not real throughput.

**Dependency fix:** `ragas==0.4.3` fails to import against the latest
`langchain-community` (0.4.2) in this environment
(`ModuleNotFoundError: langchain_community.chat_models.vertexai`).
Pinned to `langchain-community<0.4` (resolved to 0.3.31) in
`requirements.txt` -- the smallest fix, verified not to affect any other
dependency or the pre-existing 503-test baseline.

## Task 9.2 / P18: Low-Faithfulness Flagging

`EvaluationItemResult.low_faithfulness_flag: bool` is computed once per
item by `EvaluationPipeline` (never by RAGAS, never triggering a second
LLM call) using the existing `Settings.faithfulness_flag_threshold`
(default 0.5, established in Task 1.1 -- not duplicated).

- **Strict comparison:** `faithfulness < threshold`. Exactly `0.5` is
  **not** flagged.
- **Missing faithfulness** (an execution failure, `metrics.faithfulness
  is None`) is **never** flagged as low -- an absent score is not the
  same claim as a low score. The existing `errors["faithfulness"]`
  failure representation from Task 9.1 is completely unaffected.
- **Independent of other metrics:** only `faithfulness` drives the
  flag; `answer_relevancy`/`context_precision`/`context_recall` never
  affect it, and the flag never affects `context_recall`'s own
  structural-unavailability behavior (Task 9.1 remediation, unchanged).
- **Per-item only:** no aggregate-level flag was added --
  `EvaluationAggregate`'s schema is unchanged from Task 9.1.
- **Public evaluation input contract unchanged:** still exactly
  `{query, response, contexts}` -- no `reference`/`ground_truth` field
  was added anywhere.

Exposed automatically in `POST /api/v1/evaluate`'s response via the
existing `EvaluationItemResult` model (no new API endpoint, no schema
redesign).

## Task 10.1: Health & Observability

**`GET /health`** reports four named components (Requirement 9): `rag`,
`vector_store`, `redis`, `llm`. Each dependency check is a single,
lightweight, read-only call:
- `vector_store`: `Qdrant.get_collections()` (no collection provisioning).
- `redis`: a real Redis `PING`.
- `llm`: `GET {ollama_url}/api/tags` (lists local models -- never a real
  generation call).

`rag` is a **derived rollup**, not an independent probe: it is
`"healthy"` only when `vector_store`, `redis`, **and** `llm` are all
healthy, because `RAGService.handle_query()`'s actual implementation
requires all three (it calls `ConversationManager.append_turn()`
unconditionally before retrieval or generation are even attempted, so a
real query fails end-to-end if any one of the three is down).

**Fixed during this task's own review:** an earlier version of this
rollup reported `rag` as unconditionally `"healthy"` whenever the route
executed at all -- which, since none of `RAGService`'s components open a
network connection at construction time, could never actually be
anything else, making the field tautological and non-diagnostic in
every real failure scenario. Caught by re-deriving the field from first
principles (reading `RAGService.handle_query()`'s actual call order)
rather than trusting the existing implementation, and fixed with 6 new
tests specifically proving the rollup behaves correctly under each
single-dependency-down scenario and the all-down scenario.

Always returns HTTP 200 -- failures are represented in the body
(per-component `"unavailable"` + overall `"degraded"`), a documented
choice since neither official document mandates a status-code contract
and a `503` here risks an orchestrator killing an otherwise-functional
process over one degraded dependency.

**`GET /metrics`** returns real, accumulated query-processing data via a
thread-safe `MetricsCollector` (`app/services/metrics.py`) populated by
`POST /api/v1/query`'s own route handler:
- `query_count`: incremented once per attempt, successful or not.
- `average_latency_seconds`: total wall-clock duration / `query_count`.
- `hit_rate`: reuses the existing `chunks_retrieved > 0` concept
  (Task 7.1/6.1) -- denominator is *successfully completed* queries only
  (a failed query never produced a `chunks_retrieved` value).
- `error_rate`: failed attempts / `query_count`.
- All three derived fields are `None` (never `0.0`, never a
  `ZeroDivisionError`) when `query_count == 0`, matching this project's
  established convention (Task 9.1's `EvaluationAggregate`).

Metrics recording is wrapped so a bug in the collector itself can never
turn a successful query into a failed HTTP response. The query-timing
log line records only duration/success/hit/error-type -- never the
query text, answer text, or retrieved documents.

## Task 10.2 / P19: Health Degradation Accuracy

Formalizes Property 19 with a full degradation matrix
(`tests/test_health_properties.py`) over the existing, already-correct
Task 10.1 `GET /health` implementation. **No production code changed**
-- inspection confirmed the existing logic already satisfies every P19
requirement; this task adds the missing test coverage.

- **Exhaustive matrix:** one parametrized test covers all 2^3 = 8
  healthy/unavailable combinations of (Qdrant, Redis, LLM), independently
  verifying each component's status, the derived `rag` rollup, and the
  overall status against plain boolean logic.
- **Pairwise failures** (exactly two of three down) -- the specific gap
  Task 10.1's own tests didn't enumerate (they covered each single
  failure and all-three-down, but not two-at-a-time).
- **Exception resilience** extended to Redis and LLM raising individually
  (Task 10.1 only exercised Qdrant raising) plus mixed raise+false
  combinations.
- **A Hypothesis-based property test of `_check_component` itself**,
  proving that for arbitrary exception types and messages, it can never
  produce `"healthy"` -- directly addresses "no health check may
  silently swallow a real failure and convert it to healthy."

28 new tests, all passing on the first run against the unmodified Task
10.1 implementation -- confirming, not just asserting, that the existing
health logic was already correct.

## Docker Deployment (Task 11.1)

**IMPORTANT, HONESTLY STATED LIMITATION:** the sandbox this was authored
in has no `docker` binary installed, and installing one was attempted
and failed (the sandbox's package mirror does not serve `docker.io`).
Every file below was reviewed carefully against the actual application
source (entrypoint, dependencies, filesystem paths, real `Settings`
fields) and validated wherever a non-Docker method existed (YAML syntax
parsing, real `Settings` construction from Docker-shaped environment
variables, running the real `app.api.main:app` object directly) -- but
`docker build`/`docker compose up` themselves were never executed. See
this task's own implementation report for the exact, itemized
verified/unverified split.

**CORRECTIVE FIX (post-verification):** real Docker runtime
verification on a Windows machine with Docker available found the
production image failed on the first real `POST /api/v1/query` with
`PermissionError: [Errno 13] Permission denied: '/home/appuser'` during
`SentenceTransformer(...)` initialization. Root cause:
`useradd --no-create-home` still leaves `appuser`'s HOME pointing at a
`/home/appuser` that's never created and can't be created under
root-owned `/home`; `huggingface_hub` (sentence-transformers'
underlying cache library) resolves its model cache from `~` when
`HF_HOME` isn't set. Fixed by setting `HOME=/app` and explicit
`HF_HOME`/`SENTENCE_TRANSFORMERS_HOME`/`TRANSFORMERS_CACHE` environment
variables pointing at a pre-created, appuser-owned
`/app/.cache/huggingface` directory -- container still runs fully
non-root, no application code was touched. 4 new tests pin this down
(`tests/test_deployment.py`).

### 1. Prerequisites
Docker Engine with Compose v2 (`docker compose`, not the standalone
`docker-compose` v1 binary). No other local tooling is required --
Python/pip are only needed for pre-Docker development.

### 2. Build command
```
docker compose build
```
(or `docker build -t team4b-api:latest .` directly). Multi-stage build:
a discarded `builder` stage compiles/installs Python dependencies into a
venv; the final `runtime` stage copies only that venv plus the
application source -- no compilers or build tooling ship in the final
image.

### 3. Startup command
```
docker compose up
```
Requires `QDRANT_URL`, `REDIS_URL`, and `OLLAMA_URL` to be set (via a
`.env` file next to `docker-compose.yml` -- copy `.env.docker.example`
and adjust for your environment). These three fail fast with an
explicit message if left unset, rather than silently defaulting to
`localhost` (which would be wrong for inter-container communication).

For a fully self-contained, isolated development stack (bundles its own
Qdrant/Redis/Ollama, no Team 4A infrastructure or manual env values
needed) use `docker-compose.dev.yml` instead:
```
docker compose -f docker-compose.dev.yml up --build
```

### 4. Environment variables
Every variable below maps directly to a real `app/core/config.py`
`Settings` field -- none were invented for Docker. See
`.env.docker.example` for a fully worked example, and `.env.example`
for the complete list with their non-Docker (plain-Python-process)
defaults.

| Variable | Required in `docker-compose.yml`? | Purpose |
|---|---|---|
| `QDRANT_URL` | Yes (`:?`, no default) | Team 4A's real Qdrant endpoint |
| `REDIS_URL` | Yes (`:?`, no default) | Team 4A's real Redis endpoint |
| `OLLAMA_URL` | Yes (`:?`, no default) | Your Ollama endpoint |
| `QDRANT_COLLECTION_NAME` | No (defaults to `team4b_shared_production_chunks`) | Team 4B's own production collection |
| `EMBEDDING_DIMENSIONS`/`EMBEDDING_DISTANCE`/`EMBEDDING_MODEL_NAME` | No (default to `384`/`Cosine`/`all-MiniLM-L6-v2`) | Must match Team 4A's actual verified Qdrant configuration |
| `OLLAMA_MODEL_NAME` | No (defaults to `llama3`) | |
| `ENVIRONMENT`/`LOG_LEVEL` | No (default `production`/`INFO`) | |

### 5. Service dependencies
Team 4B's own compose file (`docker-compose.yml`) runs **only** the API
container. Qdrant, Redis, and Ollama are treated as external
infrastructure reached via the configured URLs above -- Team 4A already
owns and runs the real, shared Qdrant + Redis stack, and Ollama has
never been something Team 4B "owns." See §12 below for exactly how to
point at Team 4A's real containers.

### 6. Ports
The container always listens on `8000` internally (matches the
Dockerfile's `EXPOSE`/`CMD`). The host-side port is configurable via
`TEAM4B_HOST_PORT` (default `8000`). No database port is published to
the host by this compose file -- there is no database service in it.

### 7. Health check
`GET /health` (Task 10.1) is used directly -- no second health endpoint
was invented. The Dockerfile's own `HEALTHCHECK` deliberately checks
**only** the HTTP status code (`== 200`), never the JSON body's
`status` field. This is intentional: `/health` always returns HTTP 200
by design (Task 10.1/P19 -- downstream degradation is represented in
the response *body*, never via a non-200 status), so a Docker
healthcheck that failed the container whenever any one downstream
dependency was briefly degraded would restart the Team 4B process
itself -- which fixes nothing about an external outage, and would cause
pointless restart loops under exactly the conditions `/health` was
designed to survive gracefully. This `HEALTHCHECK` verifies
container/process **liveness** only; downstream dependency health
remains the responsibility of whoever reads `/health`'s response body.

### 8. Metrics endpoint
`GET /metrics` (Task 10.1) is unchanged and exposed on the same port --
no separate metrics port, no Prometheus/Grafana was introduced (not
required by the official specification).

### 9. Persistence
Only one thing needs persistence on Team 4B's own side: Requirement 8's
timestamped evaluation output (`Settings.evaluation_results_path`,
default `data/evaluation_results.jsonl`) -- mounted via the
`team4b-evaluation-data` named volume at `/app/data`. Qdrant and Redis
persistence is Team 4A's existing, already-verified responsibility
(`4a-service_qdrant_storage`, `4a-service_redis_data`) -- Team 4B's
compose file does not touch, mount, or reference those volumes at all.

### 10. Shutdown
```
docker compose down
```
Stops and removes the Team 4B API container; the named
`team4b-evaluation-data` volume persists across this (use `docker
compose down -v` to also remove it, if genuinely intended). This never
touches Team 4A's containers/volumes, which this compose project has no
knowledge of.

### 11. Troubleshooting
- **Container exits immediately / `/health` unreachable:** check
  `docker compose logs team4b-api` for a Python traceback at import
  time (most likely a missing/misconfigured required environment
  variable -- `QDRANT_URL`/`REDIS_URL`/`OLLAMA_URL` fail fast with an
  explicit message rather than silently defaulting).
- **`/health` returns `"status": "degraded"`:** expected, accurate
  behavior when a downstream dependency (Qdrant/Redis/Ollama) is
  unreachable from inside the container -- read the `components` field
  for exactly which one, and `detail` for why. This is not a Team 4B
  bug; verify the referenced service is actually reachable from inside
  the container's network (not just from the host).
- **Connection refused to Qdrant/Redis/Ollama:** almost always a
  `localhost` value used where a service DNS name or
  `host.docker.internal`/host IP was needed -- see §12 below.

### 12. Team 4A integration assumptions
Team 4A's Qdrant/Redis containers already run in their own Docker
Compose project. Team 4B's compose file does not assume automatic
cross-project service-name resolution (that does not happen by
default). Two supported options, both documented with concrete examples
in `.env.docker.example`:

- **Join Team 4A's Docker network** (recommended when both stacks run
  on the same host) and reference Team 4A's actual container names
  (e.g. `http://4a-service-qdrant-1:6333`) -- verify Team 4A's real
  network/container names on your own machine (`docker network ls`,
  `docker ps`) rather than assuming these exact names.
- **Reach Team 4A's stack via its host-exposed ports** instead (no
  shared network needed) using `host.docker.internal` (Docker Desktop)
  or your host's actual reachable address on Linux.

Team 4A's Compose files, containers, volumes, and the
`team4a_ingested_chunks` collection are never modified, renamed, or
touched by any file in this repository.
