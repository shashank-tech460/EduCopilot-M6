"""EduCopilot M6 Phase 2 -- multilingual embedding evaluation harness.

PURPOSE: determine, with a repeatable and evidence-based benchmark,
whether the current production embedding model (`Settings.embedding_model_name`,
`all-MiniLM-L6-v2` by default) is adequate for the product's multilingual
requirement (English / Hindi-Devanagari / Hinglish content and queries,
in every combination), and compare it against a genuinely multilingual
candidate model. See `docs/EDUCOPILOT_MASTER_HANDOFF.md` Sections 11-14
for the product requirement and decision rule this harness serves.

THIS SCRIPT IS EVALUATION-ONLY. It never modifies the canonical
production collection, never changes the production embedding model,
and never modifies HybridRetriever/RRF/citation/generation-authority
logic. It re-embeds a COPY of real canonical chunk text/metadata into
its own uniquely-named temporary Qdrant collections (one per model
under evaluation), then measures pure semantic (vector-only) retrieval
quality directly, deliberately bypassing BM25/RRF/generation-authority
so that embedding-model quality and score-threshold effects can be
isolated from every other retrieval component -- confounding them would
make it impossible to answer this phase's actual question.

SAFETY GUARANTEES (enforced in code, not only documented):
  - `assert_safe_write_target()` is called before every write-capable
    operation this script performs (collection creation via
    `VectorStoreManager.upsert_batch`'s automatic `ensure_collection()`,
    and the optional `--cleanup` deletion) and raises
    `CanonicalCollectionWriteRefusedError` if the target collection name
    matches `Settings.canonical_qdrant_collection_name` (case-insensitive).
  - The canonical collection is only ever touched through
    `VectorStoreManager.scroll_all_chunks()` / `get_collection()` --
    both read-only.
  - Temporary collections are left in place by default (never silently
    deleted) so results remain inspectable after the run; `--cleanup`
    opts in to deleting them.
  - No `.env`/`.env.local` file is read or written by this script beyond
    the normal `Settings` loading every other Team 4B component already
    does.

GROUND TRUTH: this harness NEVER invents relevance judgments. It only
computes Recall@k/MRR when given an explicit, human-authored ground
truth file via `--ground-truth`. See `GROUND_TRUTH_SCHEMA_DOC` below for
the required schema. Without `--ground-truth`, the script still runs
end-to-end (environment validation, dimension discovery, re-embedding,
indexing, and raw retrieval) so its plumbing can be exercised and timed,
but explicitly reports retrieval-quality metrics as NOT_COMPUTED rather
than fabricating them.

USAGE:
    python scripts/phase2_multilingual_embedding_evaluation.py \\
        --ground-truth data/phase2_ground_truth.json \\
        --output data/phase2_evaluation_report.json

    python scripts/phase2_multilingual_embedding_evaluation.py --print-schema
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings, get_settings  # noqa: E402
from app.models.retrieval import RetrievalResult  # noqa: E402
from app.services.embedder import Embedder  # noqa: E402
from app.services.vector_store import ContextChunk, RealQdrantClient, VectorStoreManager  # noqa: E402

logger = logging.getLogger("phase2_multilingual_embedding_evaluation")

RECALL_KS: tuple[int, ...] = (1, 3, 5, 10)
DEFAULT_CANDIDATE_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
PHASE2_COLLECTION_PREFIX = "phase2_eval_"
_VALID_LANGUAGES = frozenset({"english", "hindi", "hinglish"})


# ===========================================================================
# Safety: refuse to ever write to the canonical production collection
# ===========================================================================


class CanonicalCollectionWriteRefusedError(Exception):
    """Raised whenever this harness is about to create, write to, or
    delete a collection whose name matches the canonical production
    collection. This is a hard stop -- Requirement 6 (this task's own
    STRICT SAFETY RULES) permits no code path that bypasses it."""


def assert_safe_write_target(collection_name: str, canonical_collection_name: str) -> None:
    """The one function every write-capable code path in this script
    calls first. Comparison is case-insensitive and whitespace-trimmed
    so a stray environment/config typo cannot slip past a naive exact
    match."""

    if collection_name.strip().lower() == canonical_collection_name.strip().lower():
        raise CanonicalCollectionWriteRefusedError(
            f"Refusing to write to/delete {collection_name!r}: it matches the canonical "
            f"production collection ({canonical_collection_name!r}). This evaluation harness "
            "may only write to its own uniquely-named temporary collections."
        )


def make_temp_collection_name(model_name: str, run_id: str) -> str:
    """A clearly-named, collision-resistant temporary collection name,
    e.g. `phase2_eval_all_minilm_l6_v2_a1b2c3d4`. Never equal to the
    canonical collection name for any real model_name/run_id combination
    -- `assert_safe_write_target` is still called as a second,
    independent guard rather than trusting this naming scheme alone."""

    slug = "".join(ch if ch.isalnum() else "_" for ch in model_name.strip().lower()).strip("_")
    return f"{PHASE2_COLLECTION_PREFIX}{slug}_{run_id}"


# ===========================================================================
# Ground truth (Requirement: never invented by this script)
# ===========================================================================

GROUND_TRUTH_SCHEMA_DOC = """\
Ground truth file format: a JSON array of objects, each with:

  query_id            (str, required, unique)  stable identifier for this query
  query               (str, required)          the literal query text
  query_language      (str, required)          one of: "english", "hindi", "hinglish"
  source_language     (str, required)          one of: "english", "hindi", "hinglish"
                                                 -- the language of the expected relevant content
  workspace_id        (str, required)          the REAL workspace_id the expected chunks belong to
                                                 (mandatory -- Team 4B enforces workspace isolation
                                                 on every search; this harness reproduces that)
  relevant_chunk_ids  (list[str], required, non-empty)
                                                 REAL chunk_id values from the canonical
                                                 `educopilot_chunks` collection -- never invented
  source_type         (str, optional)          "pdf" | "youtube" | "mp4" -- descriptive only,
                                                 not used to constrain retrieval
  subject             (str, optional)          free-text subject/topic label, for reporting only

Example:

[
  {
    "query_id": "q1",
    "query": "What is process scheduling?",
    "query_language": "english",
    "source_language": "english",
    "workspace_id": "6a8de2d7e43679cbe2ee243d",
    "relevant_chunk_ids": ["<real-chunk-id-1>", "<real-chunk-id-2>"],
    "source_type": "pdf",
    "subject": "operating systems"
  }
]

Every `relevant_chunk_ids` value MUST be a chunk_id that actually exists
in the canonical `educopilot_chunks` collection, and every relevance
judgment must be made by a human who has actually read the query and the
candidate chunk's text -- this harness has no mechanism to verify
relevance itself and will not attempt to.
"""


class GroundTruthValidationError(Exception):
    """Raised on any structurally invalid ground truth file -- fails
    clearly and refuses to guess at a corrected interpretation, per this
    task's explicit instruction not to pretend metrics are valid without
    real labels."""


@dataclass(frozen=True)
class GroundTruthEntry:
    query_id: str
    query: str
    query_language: str
    source_language: str
    workspace_id: str
    relevant_chunk_ids: frozenset[str]
    source_type: str | None = None
    subject: str | None = None


def load_ground_truth(path: Path) -> list[GroundTruthEntry]:
    """Load and strictly validate a human-authored ground truth file.
    Raises `GroundTruthValidationError` with a specific, actionable
    message on any structural problem rather than silently skipping bad
    entries or guessing intent."""

    if not path.exists():
        raise GroundTruthValidationError(f"Ground truth file not found: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GroundTruthValidationError(f"Ground truth file {path} is not valid JSON: {exc}") from exc

    if not isinstance(raw, list):
        raise GroundTruthValidationError(
            f"Ground truth file {path} must contain a JSON array of entry objects.\n\n{GROUND_TRUTH_SCHEMA_DOC}"
        )

    entries: list[GroundTruthEntry] = []
    seen_query_ids: set[str] = set()

    for index, item in enumerate(raw):
        location = f"entry #{index}"
        if not isinstance(item, dict):
            raise GroundTruthValidationError(f"{location}: expected a JSON object, got {type(item).__name__}.")

        query_id = item.get("query_id")
        if not isinstance(query_id, str) or not query_id.strip():
            raise GroundTruthValidationError(f"{location}: 'query_id' must be a non-empty string.")
        if query_id in seen_query_ids:
            raise GroundTruthValidationError(f"{location}: duplicate query_id {query_id!r}.")
        seen_query_ids.add(query_id)

        query = item.get("query")
        if not isinstance(query, str) or not query.strip():
            raise GroundTruthValidationError(f"{location} ({query_id}): 'query' must be a non-empty string.")

        query_language = item.get("query_language")
        if query_language not in _VALID_LANGUAGES:
            raise GroundTruthValidationError(
                f"{location} ({query_id}): 'query_language' must be one of {sorted(_VALID_LANGUAGES)}, "
                f"got {query_language!r}."
            )

        source_language = item.get("source_language")
        if source_language not in _VALID_LANGUAGES:
            raise GroundTruthValidationError(
                f"{location} ({query_id}): 'source_language' must be one of {sorted(_VALID_LANGUAGES)}, "
                f"got {source_language!r}."
            )

        workspace_id = item.get("workspace_id")
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise GroundTruthValidationError(f"{location} ({query_id}): 'workspace_id' must be a non-empty string.")

        relevant_chunk_ids = item.get("relevant_chunk_ids")
        if (
            not isinstance(relevant_chunk_ids, list)
            or not relevant_chunk_ids
            or not all(isinstance(cid, str) and cid.strip() for cid in relevant_chunk_ids)
        ):
            raise GroundTruthValidationError(
                f"{location} ({query_id}): 'relevant_chunk_ids' must be a non-empty list of non-empty strings."
            )

        source_type = item.get("source_type")
        if source_type is not None and not isinstance(source_type, str):
            raise GroundTruthValidationError(f"{location} ({query_id}): 'source_type' must be a string or absent.")

        subject = item.get("subject")
        if subject is not None and not isinstance(subject, str):
            raise GroundTruthValidationError(f"{location} ({query_id}): 'subject' must be a string or absent.")

        entries.append(
            GroundTruthEntry(
                query_id=query_id,
                query=query,
                query_language=query_language,
                source_language=source_language,
                workspace_id=workspace_id,
                relevant_chunk_ids=frozenset(relevant_chunk_ids),
                source_type=source_type,
                subject=subject,
            )
        )

    if not entries:
        raise GroundTruthValidationError(f"Ground truth file {path} contained zero entries.")

    return entries


def validate_ground_truth_chunk_ids_exist(entries: list[GroundTruthEntry], known_chunk_ids: set[str]) -> list[str]:
    """Cross-check every `relevant_chunk_ids` value against chunk_ids
    actually present in the copied canonical data. Returns a list of
    human-readable problem descriptions (empty if all valid) -- the
    caller decides whether this is fatal, since a ground truth file
    scoped to a different workspace subset than was copied is a
    legitimate (if probably unintended) situation to surface rather than
    a hard crash."""

    problems: list[str] = []
    for entry in entries:
        missing = entry.relevant_chunk_ids - known_chunk_ids
        if missing:
            problems.append(
                f"query_id={entry.query_id!r}: relevant_chunk_ids not found in copied canonical data: {sorted(missing)}"
            )
    return problems


# ===========================================================================
# Environment validation (Requirements 10-11: fail clearly, never silently)
# ===========================================================================


@dataclass
class EnvironmentCheckResult:
    qdrant_reachable: bool
    canonical_collection_exists: bool
    canonical_point_count: int
    errors: list[str]

    @property
    def ok(self) -> bool:
        return self.qdrant_reachable and self.canonical_collection_exists and self.canonical_point_count > 0


def validate_environment(client: RealQdrantClient, settings: Settings) -> EnvironmentCheckResult:
    errors: list[str] = []

    try:
        collections = {collection.name for collection in client.get_collections().collections}
    except Exception as exc:  # noqa: BLE001
        return EnvironmentCheckResult(
            qdrant_reachable=False,
            canonical_collection_exists=False,
            canonical_point_count=0,
            errors=[f"Qdrant unreachable at {settings.qdrant_url!r}: {exc}"],
        )

    canonical_name = settings.canonical_qdrant_collection_name
    if canonical_name not in collections:
        errors.append(f"Canonical collection {canonical_name!r} does not exist in this Qdrant instance.")
        return EnvironmentCheckResult(True, False, 0, errors)

    info = client.get_collection(collection_name=canonical_name)
    point_count = int(getattr(info, "points_count", 0) or 0)
    if point_count == 0:
        errors.append(f"Canonical collection {canonical_name!r} exists but has zero points.")

    return EnvironmentCheckResult(True, True, point_count, errors)


class ModelUnavailableError(Exception):
    """Raised when an embedding model cannot be loaded (not cached
    locally AND not downloadable in this environment, or any other
    load-time failure). Callers must report this clearly and skip that
    model rather than inventing results for it, per this task's explicit
    instruction."""


def discover_model_dimension(model_name: str) -> int:
    """Load `model_name` and read its ACTUAL output dimension --
    Requirement: never hardcode/assume a dimension, including for the
    documented 384-dimensional candidate. Raises `ModelUnavailableError`
    with the underlying cause if the model cannot be loaded at all
    (e.g. not cached and no network access to huggingface.co)."""

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(model_name)
        dimension = model.get_sentence_embedding_dimension()
    except Exception as exc:  # noqa: BLE001
        raise ModelUnavailableError(f"Could not load embedding model {model_name!r}: {exc}") from exc

    if dimension is None:
        raise ModelUnavailableError(f"Model {model_name!r} loaded but reported no embedding dimension.")

    return int(dimension)


# ===========================================================================
# Canonical data copy (read-only) and re-embedding/indexing (write, to a
# per-model temporary collection only)
# ===========================================================================


def copy_canonical_chunks(
    reader: VectorStoreManager,
    canonical_collection_name: str,
    workspace_ids: set[str] | None = None,
) -> list[RetrievalResult]:
    """Read-only copy of real canonical chunk text/metadata via the
    existing, unmodified `VectorStoreManager.scroll_all_chunks()`.
    Never writes anything. `workspace_ids`, when given, scopes the copy
    to exactly those workspaces (Requirement 8: scope evaluation data
    correctly)."""

    chunks = reader.scroll_all_chunks(collection_name=canonical_collection_name)
    if workspace_ids is not None:
        chunks = [chunk for chunk in chunks if chunk.metadata.get("workspace_id") in workspace_ids]
    return chunks


@dataclass
class IndexingTiming:
    embedding_seconds: float
    indexing_seconds: float
    chunk_count: int


def embed_and_index_chunks(
    chunks: list[RetrievalResult],
    embedder: Embedder,
    vector_store: VectorStoreManager,
) -> IndexingTiming:
    """Re-embed a copy of real chunk text (never Team 4A's/production's
    own stored vectors -- those never leave the canonical collection)
    and upsert into `vector_store`'s own configured collection, which
    the caller has already verified is a safe temporary target via
    `assert_safe_write_target()`. Embedding and indexing latency are
    timed and returned SEPARATELY (Requirement 13)."""

    texts = [chunk.text for chunk in chunks]

    embedding_start = time.perf_counter()
    vectors = embedder.embed_queries(texts) if texts else []
    embedding_seconds = time.perf_counter() - embedding_start

    context_chunks = [
        ContextChunk(chunk_id=chunk.chunk_id, text=chunk.text, embedding=vector, metadata=dict(chunk.metadata))
        for chunk, vector in zip(chunks, vectors)
    ]

    indexing_start = time.perf_counter()
    if context_chunks:
        vector_store.upsert_batch(context_chunks)
    indexing_seconds = time.perf_counter() - indexing_start

    return IndexingTiming(embedding_seconds=embedding_seconds, indexing_seconds=indexing_seconds, chunk_count=len(chunks))


# ===========================================================================
# Query-time semantic retrieval (deliberately semantic-only: no BM25, no
# RRF, no generation-authority filtering -- this phase isolates embedding
# quality and threshold effects, not the full production pipeline)
# ===========================================================================


@dataclass
class QueryOutcome:
    query_id: str
    threshold: float
    latency_seconds: float
    ranked_chunk_ids: list[str]
    ranked_scores: list[float]


def run_query(
    vector_store: VectorStoreManager,
    embedder: Embedder,
    entry: GroundTruthEntry,
    top_k: int,
    score_threshold: float,
    temp_collection_name: str,
) -> QueryOutcome:
    start = time.perf_counter()
    query_vector = embedder.embed_query(entry.query)
    results = vector_store.search_similar(
        query_vector=query_vector,
        top_k=top_k,
        score_threshold=score_threshold,
        workspace_id=entry.workspace_id,
        collection_name=temp_collection_name,
    )
    elapsed = time.perf_counter() - start
    return QueryOutcome(
        query_id=entry.query_id,
        threshold=score_threshold,
        latency_seconds=elapsed,
        ranked_chunk_ids=[result.chunk_id for result in results],
        ranked_scores=[result.relevance_score for result in results],
    )


# ===========================================================================
# Metrics -- only ever computed against a real, human-authored ground
# truth file. Never invented.
# ===========================================================================


def recall_at_k(ranked_chunk_ids: Sequence[str], relevant: frozenset[str], k: int) -> float:
    """Fraction of `relevant` chunk_ids present in the top-k ranked
    results. 0.0 if `relevant` is empty (should not happen -- ground
    truth validation already rejects empty relevant_chunk_ids)."""

    if not relevant:
        return 0.0
    top_k_ids = set(ranked_chunk_ids[:k])
    return len(top_k_ids & relevant) / len(relevant)


def reciprocal_rank(ranked_chunk_ids: Sequence[str], relevant: frozenset[str]) -> float:
    """1/rank of the first relevant chunk_id found in the ranked list
    (1-indexed); 0.0 if none of `ranked_chunk_ids` is relevant."""

    for position, chunk_id in enumerate(ranked_chunk_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / position
    return 0.0


@dataclass
class MetricsSummary:
    query_count: int
    recall_at_k: dict[int, float]
    mrr: float


def summarize(pairs: list[tuple[GroundTruthEntry, QueryOutcome]]) -> MetricsSummary:
    if not pairs:
        return MetricsSummary(query_count=0, recall_at_k={k: 0.0 for k in RECALL_KS}, mrr=0.0)

    recalls: dict[int, list[float]] = {k: [] for k in RECALL_KS}
    reciprocal_ranks: list[float] = []

    for entry, outcome in pairs:
        for k in RECALL_KS:
            recalls[k].append(recall_at_k(outcome.ranked_chunk_ids, entry.relevant_chunk_ids, k))
        reciprocal_ranks.append(reciprocal_rank(outcome.ranked_chunk_ids, entry.relevant_chunk_ids))

    return MetricsSummary(
        query_count=len(pairs),
        recall_at_k={k: sum(values) / len(values) for k, values in recalls.items()},
        mrr=sum(reciprocal_ranks) / len(reciprocal_ranks),
    )


def group_by_language_pair(
    pairs: list[tuple[GroundTruthEntry, QueryOutcome]],
) -> dict[tuple[str, str], list[tuple[GroundTruthEntry, QueryOutcome]]]:
    """Groups by (query_language, source_language) -- e.g. ("hindi",
    "english") is the Hindi-query-against-English-content cell of the
    3x3 matrix. Requirement: report per-language-pair results, not only
    one aggregate number, so a weak cell (e.g. Hindi->English) is
    visible rather than averaged away."""

    groups: dict[tuple[str, str], list[tuple[GroundTruthEntry, QueryOutcome]]] = {}
    for entry, outcome in pairs:
        key = (entry.query_language, entry.source_language)
        groups.setdefault(key, []).append((entry, outcome))
    return groups


# ===========================================================================
# Per-model evaluation orchestration
# ===========================================================================


@dataclass
class ThresholdResult:
    threshold: float
    overall: MetricsSummary
    by_language_pair: dict[str, MetricsSummary]
    latencies_seconds: list[float]
    raw_outcomes: list[QueryOutcome]


@dataclass
class ModelEvaluationResult:
    model_name: str
    role: str  # "baseline" | "candidate"
    dimension: int
    temp_collection_name: str
    chunk_count: int
    embedding_seconds: float
    indexing_seconds: float
    thresholds: list[ThresholdResult]


def evaluate_model(
    *,
    model_name: str,
    role: str,
    base_settings: Settings,
    shared_client: RealQdrantClient,
    chunks: list[RetrievalResult],
    ground_truth: list[GroundTruthEntry],
    top_k: int,
    thresholds: list[float],
    run_id: str,
    dimension_discovery: Any = discover_model_dimension,
    embedder_factory: Any = Embedder,
) -> ModelEvaluationResult:
    """Evaluate exactly one embedding model against the SAME chunks, the
    SAME ground truth, the SAME top_k, and the SAME threshold set as
    every other model this run evaluates (Requirement: fair comparison
    -- the benchmark itself is never changed between models).

    `dimension_discovery` and `embedder_factory` default to the real
    `discover_model_dimension` function and the real `Embedder` class --
    overridable only so this function's own control flow (settings
    construction, safety guard, indexing, querying, metrics) can be
    exercised by focused tests without downloading/loading a real
    sentence-transformers model. Production callers (`main()`) never
    override either.
    """

    dimension = dimension_discovery(model_name)

    temp_collection_name = make_temp_collection_name(model_name, run_id)
    assert_safe_write_target(temp_collection_name, base_settings.canonical_qdrant_collection_name)

    eval_settings = base_settings.model_copy(
        update={
            "embedding_dimensions": dimension,
            "embedding_model_name": model_name,
            "qdrant_collection_name": temp_collection_name,
        }
    )

    embedder = embedder_factory(settings=eval_settings)
    vector_store = VectorStoreManager(settings=eval_settings, qdrant_client=shared_client)

    timing = embed_and_index_chunks(chunks, embedder, vector_store)

    threshold_results: list[ThresholdResult] = []
    for threshold in thresholds:
        outcomes = [
            run_query(vector_store, embedder, entry, top_k, threshold, temp_collection_name) for entry in ground_truth
        ]
        pairs = list(zip(ground_truth, outcomes))
        overall = summarize(pairs)
        by_pair = {
            f"{query_lang}->{source_lang}": summarize(group_pairs)
            for (query_lang, source_lang), group_pairs in group_by_language_pair(pairs).items()
        }
        threshold_results.append(
            ThresholdResult(
                threshold=threshold,
                overall=overall,
                by_language_pair=by_pair,
                latencies_seconds=[outcome.latency_seconds for outcome in outcomes],
                raw_outcomes=outcomes,
            )
        )

    return ModelEvaluationResult(
        model_name=model_name,
        role=role,
        dimension=dimension,
        temp_collection_name=temp_collection_name,
        chunk_count=len(chunks),
        embedding_seconds=timing.embedding_seconds,
        indexing_seconds=timing.indexing_seconds,
        thresholds=threshold_results,
    )


# ===========================================================================
# Cleanup (opt-in only -- design spec item 13: temp collections are left
# in place unless cleanup is explicitly enabled)
# ===========================================================================


def delete_temp_collection(collection_name: str, canonical_collection_name: str, settings: Settings) -> None:
    assert_safe_write_target(collection_name, canonical_collection_name)
    from qdrant_client import QdrantClient

    raw_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key, check_compatibility=False)
    raw_client.delete_collection(collection_name=collection_name)


# ===========================================================================
# Report serialization
# ===========================================================================


def _metrics_to_dict(metrics: MetricsSummary) -> dict[str, Any]:
    return {
        "query_count": metrics.query_count,
        "recall_at_k": {str(k): v for k, v in metrics.recall_at_k.items()},
        "mrr": metrics.mrr,
    }


def _model_result_to_dict(result: ModelEvaluationResult) -> dict[str, Any]:
    return {
        "model_name": result.model_name,
        "role": result.role,
        "dimension": result.dimension,
        "temp_collection_name": result.temp_collection_name,
        "chunk_count": result.chunk_count,
        "embedding_seconds": result.embedding_seconds,
        "indexing_seconds": result.indexing_seconds,
        "thresholds": [
            {
                "threshold": threshold_result.threshold,
                "overall": _metrics_to_dict(threshold_result.overall),
                "by_language_pair": {
                    pair: _metrics_to_dict(metrics) for pair, metrics in threshold_result.by_language_pair.items()
                },
                "latency_seconds": {
                    "mean": (
                        sum(threshold_result.latencies_seconds) / len(threshold_result.latencies_seconds)
                        if threshold_result.latencies_seconds
                        else None
                    ),
                    "min": min(threshold_result.latencies_seconds, default=None),
                    "max": max(threshold_result.latencies_seconds, default=None),
                },
                "raw_outcomes": [
                    {
                        "query_id": outcome.query_id,
                        "latency_seconds": outcome.latency_seconds,
                        "ranked_chunk_ids": outcome.ranked_chunk_ids,
                        "ranked_scores": outcome.ranked_scores,
                    }
                    for outcome in threshold_result.raw_outcomes
                ],
            }
            for threshold_result in result.thresholds
        ],
    }


def print_comparison_table(results: list[ModelEvaluationResult], thresholds: list[float]) -> None:
    for threshold in thresholds:
        print(f"\n=== Threshold = {threshold} ===")
        header = ["model", "dim", "recall@1", "recall@3", "recall@5", "recall@10", "mrr", "mean_latency_s"]
        print(" | ".join(header))
        for result in results:
            threshold_result = next(t for t in result.thresholds if t.threshold == threshold)
            overall = threshold_result.overall
            mean_latency = (
                sum(threshold_result.latencies_seconds) / len(threshold_result.latencies_seconds)
                if threshold_result.latencies_seconds
                else float("nan")
            )
            row = [
                result.model_name,
                str(result.dimension),
                *(f"{overall.recall_at_k[k]:.3f}" for k in RECALL_KS),
                f"{overall.mrr:.3f}",
                f"{mean_latency:.4f}",
            ]
            print(" | ".join(row))

        print("\nPer-language-pair recall@5 / mrr:")
        for result in results:
            threshold_result = next(t for t in result.thresholds if t.threshold == threshold)
            print(f"  {result.model_name}:")
            for pair, metrics in sorted(threshold_result.by_language_pair.items()):
                print(f"    {pair}: n={metrics.query_count} recall@5={metrics.recall_at_k[5]:.3f} mrr={metrics.mrr:.3f}")


# ===========================================================================
# CLI entrypoint
# ===========================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=None,
        help="Path to a human-authored ground truth JSON file (see --print-schema). "
        "If omitted, the harness runs structurally (env checks, indexing, raw retrieval) "
        "but reports retrieval-quality metrics as NOT_COMPUTED rather than inventing them.",
    )
    parser.add_argument("--baseline-model", type=str, default=None, help="Defaults to Settings.embedding_model_name.")
    parser.add_argument("--candidate-model", type=str, default=DEFAULT_CANDIDATE_MODEL)
    parser.add_argument("--top-k", type=int, default=10, help="Retrieval depth (also the max Recall@k evaluated).")
    parser.add_argument(
        "--workspace-id",
        action="append",
        default=None,
        help="Restrict copied canonical chunks to this workspace_id. Repeatable. "
        "Ignored (all workspaces referenced by --ground-truth are used) when a ground truth file is given.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "phase2_evaluation_report.json",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Delete this run's temporary evaluation collections when done. Default: leave them in place.",
    )
    parser.add_argument("--print-schema", action="store_true", help="Print the ground truth file schema and exit.")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.print_schema:
        print(GROUND_TRUTH_SCHEMA_DOC)
        return 0

    settings = get_settings()
    shared_client = RealQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

    env_check = validate_environment(shared_client, settings)
    if not env_check.ok:
        for error in env_check.errors:
            logger.error(error)
        logger.error("Environment validation failed -- refusing to proceed. No results were fabricated.")
        return 1
    logger.info(
        "Environment OK: canonical collection %r has %d points.",
        settings.canonical_qdrant_collection_name,
        env_check.canonical_point_count,
    )

    ground_truth: list[GroundTruthEntry] = []
    ground_truth_available = False
    if args.ground_truth is not None:
        try:
            ground_truth = load_ground_truth(args.ground_truth)
        except GroundTruthValidationError as exc:
            logger.error("Ground truth file invalid: %s", exc)
            return 1
        ground_truth_available = True
        logger.info("Loaded %d ground truth entries from %s.", len(ground_truth), args.ground_truth)
    else:
        logger.warning(
            "No --ground-truth file given. Running in STRUCTURAL mode: indexing and raw retrieval will run, "
            "but Recall@k/MRR will be reported as NOT_COMPUTED -- this harness never invents relevance judgments."
        )

    workspace_ids: set[str] | None
    if ground_truth_available:
        workspace_ids = {entry.workspace_id for entry in ground_truth}
    elif args.workspace_id:
        workspace_ids = set(args.workspace_id)
    else:
        workspace_ids = None

    reader = VectorStoreManager(settings=settings, qdrant_client=shared_client)
    chunks = copy_canonical_chunks(reader, settings.canonical_qdrant_collection_name, workspace_ids)
    if not chunks:
        logger.error("No canonical chunks found for the given scope (workspace_ids=%s). Nothing to evaluate.", workspace_ids)
        return 1
    logger.info("Copied %d real canonical chunks (read-only) for evaluation.", len(chunks))

    if ground_truth_available:
        known_chunk_ids = {chunk.chunk_id for chunk in chunks}
        problems = validate_ground_truth_chunk_ids_exist(ground_truth, known_chunk_ids)
        if problems:
            for problem in problems:
                logger.error(problem)
            logger.error(
                "Ground truth references chunk_ids not present in the copied canonical data -- "
                "refusing to compute metrics against an inconsistent ground truth."
            )
            return 1

    thresholds = sorted({0.0, settings.default_score_threshold})
    logger.info("Evaluating at thresholds: %s", thresholds)

    baseline_model = args.baseline_model or settings.embedding_model_name
    run_id = uuid.uuid4().hex[:10]

    results: list[ModelEvaluationResult] = []
    unavailable: list[tuple[str, str]] = []

    for model_name, role in ((baseline_model, "baseline"), (args.candidate_model, "candidate")):
        logger.info("Evaluating %s model: %s", role, model_name)
        try:
            result = evaluate_model(
                model_name=model_name,
                role=role,
                base_settings=settings,
                shared_client=shared_client,
                chunks=chunks,
                ground_truth=ground_truth,
                top_k=max(args.top_k, max(RECALL_KS)),
                thresholds=thresholds,
                run_id=run_id,
            )
            results.append(result)
            logger.info(
                "%s (%s): dimension=%d, embedding=%.2fs, indexing=%.2fs, collection=%s",
                role,
                model_name,
                result.dimension,
                result.embedding_seconds,
                result.indexing_seconds,
                result.temp_collection_name,
            )
        except ModelUnavailableError as exc:
            logger.error("%s model %r UNAVAILABLE in this environment: %s", role, model_name, exc)
            logger.error("Skipping %s -- reporting this limitation rather than inventing results for it.", model_name)
            unavailable.append((role, model_name))

    report: dict[str, Any] = {
        "run_id": run_id,
        "ground_truth_available": ground_truth_available,
        "ground_truth_file": str(args.ground_truth) if args.ground_truth else None,
        "ground_truth_query_count": len(ground_truth),
        "chunk_count": len(chunks),
        "workspace_ids": sorted(workspace_ids) if workspace_ids else None,
        "top_k": max(args.top_k, max(RECALL_KS)),
        "thresholds": thresholds,
        "canonical_collection": settings.canonical_qdrant_collection_name,
        "canonical_point_count": env_check.canonical_point_count,
        "unavailable_models": [{"role": role, "model_name": name} for role, name in unavailable],
        "models": [_model_result_to_dict(result) for result in results],
    }

    if not ground_truth_available:
        report["metrics_note"] = (
            "NOT_COMPUTED: no --ground-truth file was provided. Recall@k/MRR values above are all 0.0 "
            "by construction (no relevant_chunk_ids to match against) and MUST NOT be read as real "
            "retrieval-quality measurements. Structural results (dimensions, embedding/indexing timing, "
            "raw per-query retrieval latency and ranked chunk_ids) ARE real measurements."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote full report to %s", args.output)

    if results:
        print_comparison_table(results, thresholds)

    if args.cleanup:
        for result in results:
            logger.info("Cleaning up temporary collection %s", result.temp_collection_name)
            delete_temp_collection(result.temp_collection_name, settings.canonical_qdrant_collection_name, settings)

    if unavailable:
        logger.warning(
            "%d model(s) could not be evaluated in this environment: %s",
            len(unavailable),
            ", ".join(name for _, name in unavailable),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
