"""Team 4B EvaluationPipeline (Task 9.1).

Implements Requirement 8 (RAGAS Evaluation) EXCEPT the actual RAGAS
metric computation, which is isolated in `app/services/ragas_adapter.py`
behind the `RagasEvaluatorProtocol` this module depends on -- this file
contains zero RAGAS/LLM/embedding imports, and is fully testable with a
fake evaluator (no live Ollama or RAGAS execution required).

APPROVED ARCHITECTURE:

    POST /api/v1/evaluate
            |
            v
      EvaluationPipeline (this module)
            |
            +-- RagasEvaluatorProtocol (app/services/ragas_adapter.py: real RAGAS)
            |
            +-- EvaluationStoreProtocol (this module: JSONL persistence)
            |
            v
      EvaluationResponse

SCOPE NOTE (Task 9.1 only): this module does NOT implement Task 9.2's
Property 18 (faithfulness < 0.5 flagging) -- `Settings.faithfulness_flag_threshold`
exists (Task 1.1) but is never read here. It does NOT retrieve chunks,
query Qdrant, run BM25/embeddings/RRF, call ConversationManager, or
invoke RAGService/LLMGenerator -- evaluation operates exclusively on the
caller-supplied `query`/`response`/`contexts` triples.

BATCH SIZE: `Settings.evaluation_batch_max_size` (default 50, from Task
1.1) is reused, not reinvented. A batch exceeding it raises
`BatchTooLargeError` BEFORE any evaluation is attempted -- no silent
truncation, no hidden splitting into multiple batches.

EMPTY BATCH (documented decision, since neither official document
addresses this explicitly): an empty list is accepted and evaluates to
an empty `results` list with an all-`None` aggregate -- RAGAS is never
invoked for zero items, and no aggregate value is fabricated.

TIMESTAMP: `datetime.now(timezone.utc)` by default -- timezone-aware,
per the explicit instruction to avoid a naive local timestamp. The
clock is injectable (a zero-argument callable) for deterministic tests,
mirroring this project's established pattern (`ConversationManager`'s
injectable clock, Task 4.1).

PARTIAL FAILURE VS. TOTAL FAILURE: a per-metric failure within an
otherwise-successful item never raises -- it's represented via
`EvaluationMetrics`/`errors` (see `app/models/evaluation.py`). A TOTAL
failure of the `evaluate_batch()` call itself (e.g. the evaluator can't
reach its LLM/embeddings backend at all) raises `EvaluationExecutionError`,
mapped by the API layer to a deterministic 5xx -- this is distinct from,
and did not exist before, `BatchTooLargeError`/`EvaluationPersistenceError`.

STRUCTURAL UNAVAILABILITY VS. EXECUTION FAILURE (Task 9.1 remediation):
a third, distinct case exists alongside the two above. `context_recall`
is represented as `None` with a FIXED, CONSTANT `errors["context_recall"]`
message (see `app/services/ragas_adapter.py::CONTEXT_RECALL_UNAVAILABLE_REASON`)
for every single item, unconditionally -- not because RAGAS attempted
the metric and failed (that would be a per-item, per-execution message
that varies), but because the official evaluation contract
(`query`/`response`/`contexts`) never supplies the independent
ground-truth reference RAGAS's `context_recall` requires. This
`EvaluationPipeline` itself performs no special-casing for this --
`RagasEvaluatorProtocol` is opaque to *why* a metric is `None`; the
distinction lives entirely in whether the reason string is the same
fixed constant every time (structural) or a varying, per-attempt message
(execution failure). `context_recall` is never silently dropped from the
result schema -- it remains a real field on `EvaluationMetrics`, always
present, always `None` under the current contract.

P18 -- LOW-FAITHFULNESS FLAGGING (Task 9.2): `EvaluationItemResult.low_faithfulness_flag`
is computed once per item, here, via `_is_low_faithfulness()`, using
`Settings.faithfulness_flag_threshold` (default 0.5, already established
in Task 1.1 -- reused, not duplicated). Strict `<` comparison, never
`<=`: exactly `0.5` is NOT flagged. A `None` faithfulness (an execution
failure -- see "PARTIAL FAILURE VS. TOTAL FAILURE" above) is never
flagged as low -- these are three genuinely distinct states this module
is careful not to conflate: (a) `context_recall`'s structural
unavailability, (b) a per-metric execution failure (any metric, `None`
+ a varying error message), and (c) a successfully-computed faithfulness
score that happens to be low (flagged) versus not low (not flagged).
This computation triggers no second RAGAS/LLM call and does not touch
`RagasEvaluatorProtocol` or its real implementation at all -- it is a
pure, deterministic function of the metrics `evaluate_batch()` already
received. No aggregate-level flag is added (Task 9.2's scope is
per-item flagging only); `EvaluationAggregate` is unchanged.

PERSISTENCE: `JSONLEvaluationStore` appends one JSON line per evaluated
batch to `Settings.evaluation_results_path` (default
`data/evaluation_results.jsonl`) -- the smallest production-sensible
persistence mechanism that doesn't require a new database dependency
(file-backed JSONL, an explicitly-acceptable option per this task's own
instructions). A write failure raises `EvaluationPersistenceError`
rather than being silently swallowed, so persistence failures remain
visible to the API layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence

from app.core.config import Settings, get_settings
from app.models.evaluation import (
    EvaluationAggregate,
    EvaluationItem,
    EvaluationItemResult,
    EvaluationMetrics,
    EvaluationResponse,
)

_METRIC_NAMES: tuple[str, ...] = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


def _is_low_faithfulness(faithfulness: float | None, threshold: float) -> bool:
    """P18 (Task 9.2): `True` only when `faithfulness` was successfully
    computed AND is strictly below `threshold`. Strict comparison --
    `faithfulness == threshold` is NOT flagged. `None` (an execution
    failure, or any other reason no value exists) is never flagged as
    low faithfulness -- an absent score is not the same claim as a low
    score, and conflating them would misrepresent a failure as a
    successful-but-poor evaluation.
    """

    return faithfulness is not None and faithfulness < threshold


class BatchTooLargeError(ValueError):
    """Raised when an evaluation batch exceeds `Settings.evaluation_batch_max_size`."""


class EvaluationPersistenceError(Exception):
    """Raised when persisting an evaluation result fails. Not swallowed
    -- propagates so the API layer can surface it as a 5xx."""

    def __init__(self, message: str, *, last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


class EvaluationExecutionError(Exception):
    """Raised when the evaluator itself fails unexpectedly -- e.g. the
    underlying RAGAS/LLM/embeddings stack is unreachable or raises for
    any reason during `evaluate_batch()`.

    Distinct from `BatchTooLargeError` (a request-validation failure,
    raised before evaluation is even attempted) and
    `EvaluationPersistenceError` (a storage failure, raised after
    evaluation succeeded). Also distinct from a per-metric failure
    within an otherwise-successful item -- those are represented via
    `EvaluationMetrics`/`errors` per the partial-failure contract and
    never raise at all; this is specifically for a TOTAL failure of the
    `evaluate_batch()` call itself (e.g. the evaluator can't even reach
    its LLM/embeddings backend). Mirrors this project's established
    `VectorStoreUnavailableError`/`LLMUnavailableError` pattern (Tasks
    2.1/6.1) for the same kind of failure at a different backend.
    """

    def __init__(self, message: str, *, last_error: Exception | None = None) -> None:
        super().__init__(message)
        self.last_error = last_error


# ---------------------------------------------------------------------------
# Injectable evaluator boundary (mirrors this project's established
# Protocol + lazy-real-implementation pattern: QdrantClientProtocol,
# LLMClientProtocol, RedisClientProtocol)
# ---------------------------------------------------------------------------


class RagasEvaluatorProtocol(Protocol):
    """The minimal interface EvaluationPipeline needs from a RAGAS
    evaluator. Returns, for each input item in the SAME order, a
    (metrics, errors) pair: computed metric values (`None` for anything
    that failed) and a dict of metric-name -> failure-reason for exactly
    the metrics that failed.
    """

    def evaluate_batch(
        self, items: Sequence[EvaluationItem]
    ) -> list[tuple[EvaluationMetrics, dict[str, str]]]: ...


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class EvaluationStoreProtocol(Protocol):
    def save(self, response: EvaluationResponse) -> None: ...


class JSONLEvaluationStore:
    """Appends one JSON line per evaluated batch to a file. See module
    docstring for why this mechanism was chosen."""

    def __init__(self, file_path: str | Path) -> None:
        self._file_path = Path(file_path)

    def save(self, response: EvaluationResponse) -> None:
        try:
            self._file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._file_path, "a", encoding="utf-8") as handle:
                handle.write(response.model_dump_json() + "\n")
        except OSError as exc:
            raise EvaluationPersistenceError(
                f"Failed to persist evaluation result to {self._file_path}", last_error=exc
            ) from exc


class InMemoryEvaluationStore:
    """A store that keeps results in a process-local list.

    Explicitly NOT presented as durable storage (the official
    requirement asks for persistence, and an in-memory list is not
    durable across process restarts) -- provided only as a convenient,
    honestly-named test double. `JSONLEvaluationStore` is the actual
    persistence mechanism used by the real dependency wiring.
    """

    def __init__(self) -> None:
        self.saved: list[EvaluationResponse] = []

    def save(self, response: EvaluationResponse) -> None:
        self.saved.append(response)


# ---------------------------------------------------------------------------
# EvaluationPipeline
# ---------------------------------------------------------------------------


class EvaluationPipeline:
    def __init__(
        self,
        evaluator: RagasEvaluatorProtocol,
        store: EvaluationStoreProtocol,
        settings: Settings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._evaluator = evaluator
        self._store = store
        self._settings = settings or get_settings()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def evaluate_batch(self, items: Sequence[EvaluationItem]) -> EvaluationResponse:
        """Validate, evaluate, aggregate, persist, and return the result
        for `items`, in their original order.

        Raises `BatchTooLargeError` before any evaluation is attempted
        if `len(items)` exceeds `Settings.evaluation_batch_max_size`.
        Raises `EvaluationPersistenceError` if the result cannot be
        persisted (the API layer's own choice is to treat this as a
        failed request, since Requirement 8 requires timestamped storage
        as part of the contract).
        """

        max_batch_size = self._settings.evaluation_batch_max_size
        if len(items) > max_batch_size:
            raise BatchTooLargeError(
                f"Evaluation batch of {len(items)} items exceeds the maximum of {max_batch_size}."
            )

        if not items:
            response = EvaluationResponse(results=[], aggregate=EvaluationAggregate(), evaluated_at=self._clock())
            self._store.save(response)
            return response

        try:
            metrics_and_errors = self._evaluator.evaluate_batch(items)
        except Exception as exc:  # noqa: BLE001 -- any total evaluator failure is reported uniformly
            raise EvaluationExecutionError("Evaluation batch failed", last_error=exc) from exc

        threshold = self._settings.faithfulness_flag_threshold
        item_results = [
            EvaluationItemResult(
                query=item.query,
                response=item.response,
                contexts=list(item.contexts),
                metrics=metrics,
                errors=errors,
                low_faithfulness_flag=_is_low_faithfulness(metrics.faithfulness, threshold),
            )
            for item, (metrics, errors) in zip(items, metrics_and_errors)
        ]

        aggregate = self._compute_aggregate(item_results)
        response = EvaluationResponse(results=item_results, aggregate=aggregate, evaluated_at=self._clock())
        self._store.save(response)
        return response

    @staticmethod
    def _compute_aggregate(item_results: list[EvaluationItemResult]) -> EvaluationAggregate:
        aggregate_values: dict[str, float | None] = {}
        for metric_name in _METRIC_NAMES:
            successful_values = [
                value for result in item_results if (value := getattr(result.metrics, metric_name)) is not None
            ]
            aggregate_values[metric_name] = (
                sum(successful_values) / len(successful_values) if successful_values else None
            )
        return EvaluationAggregate(**aggregate_values)
