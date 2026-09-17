"""Focused tests for Task 9.1's EvaluationPipeline, plus Task 9.2's P18
(low-faithfulness flagging) property/example tests.

Scope: unit tests for batch validation, per-item evaluation, partial
metric failure handling, aggregation (with independently-computed
oracles), ordering, and persistence -- against `FakeRagasEvaluator` and
`InMemoryEvaluationStore`/a real `JSONLEvaluationStore` writing to a
temp file. No live RAGAS, LLM, or embedding execution anywhere in this
file. The `TestP18*` classes at the end of this file implement Task
9.2's Property 18 (faithfulness < 0.5 flagging); everything above them
remains Task 9.1 scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config import Settings
from app.models.evaluation import EvaluationItem
from app.services.evaluation import (
    BatchTooLargeError,
    EvaluationPersistenceError,
    EvaluationPipeline,
    InMemoryEvaluationStore,
    JSONLEvaluationStore,
)
from tests.fakes import FakeRagasEvaluator


def _settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def _pipeline(
    evaluator: FakeRagasEvaluator | None = None,
    store: InMemoryEvaluationStore | None = None,
    clock: Any = None,
    **settings_overrides: Any,
) -> tuple[EvaluationPipeline, FakeRagasEvaluator, InMemoryEvaluationStore]:
    evaluator = evaluator or FakeRagasEvaluator()
    store = store or InMemoryEvaluationStore()
    pipeline = EvaluationPipeline(
        evaluator=evaluator, store=store, settings=_settings(**settings_overrides), clock=clock
    )
    return pipeline, evaluator, store


def _item(query: str = "q", response: str = "r", contexts: list[str] | None = None) -> EvaluationItem:
    return EvaluationItem(query=query, response=response, contexts=contexts if contexts is not None else ["context"])


# ---------------------------------------------------------------------------
# Evaluation input / batch size
# ---------------------------------------------------------------------------


class TestBatchSizeValidation:
    def test_empty_batch_is_accepted(self):
        pipeline, evaluator, _store = _pipeline()

        response = pipeline.evaluate_batch([])

        assert response.results == []
        assert evaluator.calls == []  # RAGAS never invoked for zero items

    def test_single_item_batch(self):
        pipeline, _evaluator, _store = _pipeline()

        response = pipeline.evaluate_batch([_item()])

        assert len(response.results) == 1

    def test_batch_of_49_is_accepted(self):
        pipeline, _evaluator, _store = _pipeline()

        response = pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(49)])

        assert len(response.results) == 49

    def test_batch_of_50_is_accepted(self):
        pipeline, _evaluator, _store = _pipeline()

        response = pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(50)])

        assert len(response.results) == 50

    def test_batch_of_51_is_rejected(self):
        pipeline, evaluator, _store = _pipeline()

        with pytest.raises(BatchTooLargeError):
            pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(51)])

        assert evaluator.calls == []  # validation happens before evaluation

    def test_max_batch_size_is_configurable(self):
        pipeline, evaluator, _store = _pipeline(evaluation_batch_max_size=5)

        with pytest.raises(BatchTooLargeError):
            pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(6)])

        assert evaluator.calls == []

    def test_default_max_batch_size_is_50(self):
        assert _settings().evaluation_batch_max_size == 50


# ---------------------------------------------------------------------------
# Four metrics -- success and per-metric identification
# ---------------------------------------------------------------------------


class TestFourMetrics:
    def test_three_metrics_computed_context_recall_structurally_unavailable_on_success(self):
        # UPDATED (Task 9.1 remediation): context_recall is no longer a
        # normal successful numeric metric by default -- it is
        # structurally unavailable under the official
        # query/response/contexts-only contract (see
        # app/services/ragas_adapter.py's module docstring). This test
        # replaces the old assumption that all four metrics succeed by
        # default; it does not simply delete the coverage.
        pipeline, _evaluator, _store = _pipeline()

        response = pipeline.evaluate_batch([_item()])

        result = response.results[0]
        assert result.metrics.faithfulness is not None
        assert result.metrics.answer_relevancy is not None
        assert result.metrics.context_precision is not None
        assert result.metrics.context_recall is None
        assert "context_recall" in result.errors

    def test_each_metric_value_is_independently_readable(self):
        evaluator = FakeRagasEvaluator(
            default_metrics={"faithfulness": 0.1, "answer_relevancy": 0.2, "context_precision": 0.3, "context_recall": 0.4}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        metrics = pipeline.evaluate_batch([_item()]).results[0].metrics

        assert metrics.faithfulness == 0.1
        assert metrics.answer_relevancy == 0.2
        assert metrics.context_precision == 0.3
        assert metrics.context_recall == 0.4


class TestPartialMetricFailureIsolation:
    def test_one_failed_metric_does_not_remove_other_successful_metrics(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: (
                    {"faithfulness": 0.82, "answer_relevancy": None, "context_precision": 0.76, "context_recall": 0.71},
                    {"answer_relevancy": "simulated metric failure"},
                )
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.metrics.faithfulness == 0.82
        assert result.metrics.answer_relevancy is None  # failed, not fabricated as 0.0
        assert result.metrics.context_precision == 0.76
        assert result.metrics.context_recall == 0.71
        assert "answer_relevancy" in result.errors

    def test_failed_metric_is_never_silently_converted_to_zero(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: ({"faithfulness": None, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": 0.5}, {"faithfulness": "err"})
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.metrics.faithfulness is None
        assert result.metrics.faithfulness != 0.0

    def test_failed_item_is_not_discarded_from_results(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                1: ({"faithfulness": None, "answer_relevancy": None, "context_precision": None, "context_recall": None}, {"faithfulness": "err", "answer_relevancy": "err", "context_precision": "err", "context_recall": "err"})
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="q0"), _item(query="q1"), _item(query="q2")])

        assert len(response.results) == 3  # the fully-failed item 1 is still present
        assert response.results[1].query == "q1"


# ---------------------------------------------------------------------------
# Aggregation -- independent oracles
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_correct_per_metric_mean(self):
        evaluator = FakeRagasEvaluator()
        overrides = {
            i: ({"faithfulness": v, "answer_relevancy": v, "context_precision": v, "context_recall": v}, {})
            for i, v in enumerate([0.2, 0.4, 0.6, 0.8])
        }
        evaluator = FakeRagasEvaluator(per_item_overrides=overrides)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(4)])

        # Independent oracle -- computed directly here, not via any pipeline helper.
        expected_mean = sum([0.2, 0.4, 0.6, 0.8]) / 4
        assert response.aggregate.faithfulness == pytest.approx(expected_mean)
        assert response.aggregate.answer_relevancy == pytest.approx(expected_mean)

    def test_failed_metrics_excluded_from_aggregate_denominator(self):
        overrides = {
            0: ({"faithfulness": 0.9, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": 0.5}, {}),
            1: ({"faithfulness": None, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": 0.5}, {"faithfulness": "err"}),
        }
        evaluator = FakeRagasEvaluator(per_item_overrides=overrides)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="q0"), _item(query="q1")])

        # Independent oracle: only item 0's faithfulness (0.9) counts --
        # item 1's failure is excluded from the denominator, not
        # averaged in as 0.0 (which would give 0.45, not 0.9).
        assert response.aggregate.faithfulness == pytest.approx(0.9)

    def test_all_failed_metric_produces_none_aggregate_not_zero(self):
        overrides = {
            i: ({"faithfulness": None, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": 0.5}, {"faithfulness": "err"})
            for i in range(3)
        }
        evaluator = FakeRagasEvaluator(per_item_overrides=overrides)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(3)])

        assert response.aggregate.faithfulness is None
        assert response.aggregate.faithfulness != 0.0

    def test_empty_batch_produces_all_none_aggregate(self):
        pipeline, _e, _store = _pipeline()

        response = pipeline.evaluate_batch([])

        assert response.aggregate.faithfulness is None
        assert response.aggregate.answer_relevancy is None
        assert response.aggregate.context_precision is None
        assert response.aggregate.context_recall is None


# ---------------------------------------------------------------------------
# Order preservation
# ---------------------------------------------------------------------------


class TestOrderPreservation:
    def test_results_preserve_original_input_order(self):
        pipeline, _e, _store = _pipeline()
        items = [_item(query=f"q{i}") for i in range(10)]

        response = pipeline.evaluate_batch(items)

        assert [r.query for r in response.results] == [f"q{i}" for i in range(10)]

    def test_results_are_not_sorted_by_score(self):
        overrides = {
            0: ({"faithfulness": 0.1, "answer_relevancy": 0.1, "context_precision": 0.1, "context_recall": 0.1}, {}),
            1: ({"faithfulness": 0.9, "answer_relevancy": 0.9, "context_precision": 0.9, "context_recall": 0.9}, {}),
            2: ({"faithfulness": 0.5, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": 0.5}, {}),
        }
        evaluator = FakeRagasEvaluator(per_item_overrides=overrides)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="low"), _item(query="high"), _item(query="mid")])

        assert [r.query for r in response.results] == ["low", "high", "mid"]  # input order, not score order


# ---------------------------------------------------------------------------
# Timestamp / persistence
# ---------------------------------------------------------------------------


class TestTimestampAndPersistence:
    def test_timestamp_exists(self):
        pipeline, _e, _store = _pipeline()

        response = pipeline.evaluate_batch([_item()])

        assert response.evaluated_at is not None

    def test_timestamp_is_timezone_aware(self):
        pipeline, _e, _store = _pipeline()

        response = pipeline.evaluate_batch([_item()])

        assert response.evaluated_at.tzinfo is not None

    def test_injected_clock_controls_the_timestamp(self):
        fixed_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        pipeline, _e, _store = _pipeline(clock=lambda: fixed_time)

        response = pipeline.evaluate_batch([_item()])

        assert response.evaluated_at == fixed_time

    def test_result_is_persisted_to_the_store(self):
        pipeline, _e, store = _pipeline()

        response = pipeline.evaluate_batch([_item()])

        assert store.saved == [response]

    def test_empty_batch_is_still_persisted(self):
        pipeline, _e, store = _pipeline()

        pipeline.evaluate_batch([])

        assert len(store.saved) == 1

    def test_jsonl_store_writes_a_valid_json_line(self, tmp_path: Path):
        file_path = tmp_path / "results.jsonl"
        store = JSONLEvaluationStore(file_path)
        pipeline = EvaluationPipeline(evaluator=FakeRagasEvaluator(), store=store, settings=_settings())

        pipeline.evaluate_batch([_item()])

        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        import json

        parsed = json.loads(lines[0])
        assert "evaluated_at" in parsed
        assert len(parsed["results"]) == 1

    def test_jsonl_store_appends_multiple_batches(self, tmp_path: Path):
        file_path = tmp_path / "results.jsonl"
        store = JSONLEvaluationStore(file_path)
        pipeline = EvaluationPipeline(evaluator=FakeRagasEvaluator(), store=store, settings=_settings())

        pipeline.evaluate_batch([_item(query="batch1")])
        pipeline.evaluate_batch([_item(query="batch2")])

        lines = file_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_persistence_failure_is_visible_not_swallowed(self, tmp_path: Path):
        # Point the store at a path whose parent cannot be created
        # (a file where a directory is expected), forcing a real OSError.
        blocking_file = tmp_path / "blocking"
        blocking_file.write_text("x")
        impossible_path = blocking_file / "subdir" / "results.jsonl"
        store = JSONLEvaluationStore(impossible_path)
        pipeline = EvaluationPipeline(evaluator=FakeRagasEvaluator(), store=store, settings=_settings())

        with pytest.raises(EvaluationPersistenceError):
            pipeline.evaluate_batch([_item()])


class TestTotalEvaluatorFailure:
    """ADDED IN TASK 9.1 (discovered while writing the API-level tests):
    `FakeRagasEvaluator(raise_error=...)` existed in tests/fakes.py but
    was never actually exercised at the pipeline level -- this closes
    that gap and pins down `EvaluationExecutionError`'s exact behavior.
    """

    def test_total_evaluator_failure_raises_evaluation_execution_error(self):
        from app.services.evaluation import EvaluationExecutionError

        evaluator = FakeRagasEvaluator(raise_error=RuntimeError("ragas/LLM backend unreachable"))
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        with pytest.raises(EvaluationExecutionError):
            pipeline.evaluate_batch([_item()])

    def test_total_evaluator_failure_preserves_original_exception(self):
        from app.services.evaluation import EvaluationExecutionError

        original = RuntimeError("backend down")
        evaluator = FakeRagasEvaluator(raise_error=original)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        with pytest.raises(EvaluationExecutionError) as exc_info:
            pipeline.evaluate_batch([_item()])

        assert exc_info.value.last_error is original

    def test_total_evaluator_failure_does_not_persist_a_partial_result(self):
        evaluator = FakeRagasEvaluator(raise_error=RuntimeError("down"))
        pipeline, _e, store = _pipeline(evaluator=evaluator)

        with pytest.raises(Exception):
            pipeline.evaluate_batch([_item()])

        assert store.saved == []  # nothing persisted for a totally-failed batch

    def test_empty_batch_never_reaches_the_evaluator_so_cannot_trigger_total_failure(self):
        evaluator = FakeRagasEvaluator(raise_error=RuntimeError("would fail if called"))
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([])  # should not raise

        assert response.results == []


class TestContextRecallStructuralUnavailability:
    """Task 9.1 remediation: context_recall must be represented as
    structurally unavailable (None + a fixed reason), never fabricated,
    never silently dropped from the schema, and must not contaminate
    other metrics' aggregates or be treated as an execution failure.

    These tests exercise the GENERIC `EvaluationPipeline`/aggregation
    logic (which is agnostic to *why* a metric is None) against a
    `FakeRagasEvaluator` configured to mirror the corrected real
    `RagasEvaluationAdapter`'s actual behavior -- proving the pipeline
    correctly propagates and aggregates that behavior, not proving the
    adapter itself (that's `tests/test_ragas_adapter.py`'s job).
    """

    def test_context_recall_is_none_by_default(self):
        pipeline, _e, _store = _pipeline()  # default FakeRagasEvaluator

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.metrics.context_recall is None

    def test_context_recall_unavailability_reason_is_present_in_errors(self):
        pipeline, _e, _store = _pipeline()

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert "context_recall" in result.errors
        assert "reference" in result.errors["context_recall"].lower()

    def test_context_recall_never_becomes_zero(self):
        pipeline, _e, _store = _pipeline()

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.metrics.context_recall != 0.0
        assert result.metrics.context_recall is None

    def test_context_recall_field_remains_in_the_schema_not_dropped(self):
        pipeline, _e, _store = _pipeline()

        result = pipeline.evaluate_batch([_item()]).results[0]

        # The field exists and is explicitly None -- not omitted from
        # the model, not renamed, not removed from the four-metric contract.
        assert "context_recall" in type(result.metrics).model_fields

    def test_aggregate_context_recall_is_none_when_all_items_unavailable(self):
        pipeline, _e, _store = _pipeline()  # every item: context_recall structurally unavailable by default

        response = pipeline.evaluate_batch([_item(query=f"q{i}") for i in range(5)])

        # Independent oracle: with every item's context_recall being
        # None, there are zero successful values, so the mean is
        # undefined -- must be None, never 0.0 and never a ZeroDivisionError.
        assert response.aggregate.context_recall is None

    def test_other_metric_aggregates_are_unaffected_by_context_recall_unavailability(self):
        pipeline, _e, _store = _pipeline()
        items = [_item(query=f"q{i}") for i in range(3)]

        response = pipeline.evaluate_batch(items)

        # Independent oracle: the default fake returns fixed
        # faithfulness=0.9/answer_relevancy=0.85/context_precision=0.8
        # for every item, regardless of context_recall's unavailability.
        assert response.aggregate.faithfulness == pytest.approx(0.9)
        assert response.aggregate.answer_relevancy == pytest.approx(0.85)
        assert response.aggregate.context_precision == pytest.approx(0.8)

    def test_context_recall_unavailability_is_not_reported_as_an_execution_failure(self):
        # An execution failure raises EvaluationExecutionError and aborts
        # the whole batch (see TestTotalEvaluatorFailure). Structural
        # unavailability of context_recall must NOT raise at all -- the
        # batch completes normally with a 200-equivalent successful response.
        pipeline, _e, _store = _pipeline()

        response = pipeline.evaluate_batch([_item()])  # must not raise

        assert len(response.results) == 1

    def test_mixed_batch_with_some_items_having_a_hypothetical_recall_value(self):
        # Exercises the GENERIC aggregation math (not real adapter
        # behavior) against a scenario where context_recall happens to
        # be available for some items and not others -- proving the
        # existing exclude-from-denominator logic still works correctly
        # for this specific metric, same as any other.
        overrides = {
            0: ({"faithfulness": 0.9, "answer_relevancy": 0.9, "context_precision": 0.9, "context_recall": 0.6}, {}),
            1: (
                {"faithfulness": 0.9, "answer_relevancy": 0.9, "context_precision": 0.9, "context_recall": None},
                {"context_recall": "structurally unavailable"},
            ),
        }
        evaluator = FakeRagasEvaluator(per_item_overrides=overrides)
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="q0"), _item(query="q1")])

        # Independent oracle: only item 0's 0.6 counts.
        assert response.aggregate.context_recall == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# No cross-contamination with other services
# ---------------------------------------------------------------------------


class TestNoCrossContamination:
    def test_evaluation_does_not_mutate_global_settings(self):
        from app.core.config import get_settings

        settings_before = get_settings()
        original_batch_size = settings_before.default_top_k

        pipeline, _e, _store = _pipeline()
        pipeline.evaluate_batch([_item()])

        settings_after = get_settings()
        assert settings_after.default_top_k == original_batch_size

    def test_evaluation_module_does_not_import_ragas_directly(self):
        import inspect

        import app.services.evaluation as evaluation_module

        source = inspect.getsource(evaluation_module)
        assert "import ragas" not in source
        assert "from ragas" not in source


# ---------------------------------------------------------------------------
# Task 9.2 / P18: low-faithfulness flagging
# ---------------------------------------------------------------------------


class TestP18BelowThreshold:
    def test_faithfulness_zero_is_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.0, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True

    def test_faithfulness_point_one_is_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.1, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True

    def test_faithfulness_just_under_half_is_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.499999, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True


class TestP18ExactBoundary:
    def test_faithfulness_exactly_half_is_not_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.5, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False


class TestP18AboveThreshold:
    def test_faithfulness_just_over_half_is_not_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.500001, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False

    def test_faithfulness_point_seven_five_is_not_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.75, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False

    def test_faithfulness_one_is_not_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 1.0, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False


class TestP18MissingFaithfulness:
    def test_faithfulness_none_due_to_execution_failure_is_not_flagged(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: (
                    {"faithfulness": None, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None},
                    {"faithfulness": "RAGAS did not return a value for this metric (see adapter logs)."},
                )
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False

    def test_faithfulness_none_preserves_the_original_error_representation(self):
        # The existing execution-failure representation (metrics.faithfulness
        # is None + errors["faithfulness"] explains why) must remain
        # completely intact -- P18 only ADDS a flag, it never removes or
        # alters the existing failure semantics.
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: (
                    {"faithfulness": None, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None},
                    {"faithfulness": "simulated execution failure"},
                )
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.metrics.faithfulness is None
        assert result.errors["faithfulness"] == "simulated execution failure"
        assert result.low_faithfulness_flag is False


class TestP18OtherMetricsDoNotAffectTheFlag:
    def test_high_other_metrics_do_not_prevent_flagging_low_faithfulness(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: ({"faithfulness": 0.4, "answer_relevancy": 1.0, "context_precision": 1.0, "context_recall": None}, {})
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True

    def test_low_other_metrics_do_not_trigger_flagging_when_faithfulness_is_high(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: ({"faithfulness": 0.9, "answer_relevancy": 0.0, "context_precision": 0.0, "context_recall": None}, {})
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is False

    def test_context_recall_structural_unavailability_is_unrelated_to_the_flag(self):
        # Uses the DEFAULT fake (context_recall always structurally
        # unavailable) with a low faithfulness override -- proving the
        # two features are completely independent of one another.
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.2, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {"context_recall": "independent reference answer required"})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True  # faithfulness flagging still works
        assert result.metrics.context_recall is None  # context_recall still unavailable, unaffected
        assert "context_recall" in result.errors


class TestP18ThresholdSource:
    def test_default_threshold_is_0_5(self):
        assert _settings().faithfulness_flag_threshold == 0.5

    def test_threshold_is_configurable_not_hardcoded(self):
        # Proves the flag genuinely reads Settings.faithfulness_flag_threshold
        # rather than a hardcoded 0.5 literal duplicated in this module.
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.2, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator, faithfulness_flag_threshold=0.1)

        result = pipeline.evaluate_batch([_item()]).results[0]

        # 0.2 is BELOW the official default (0.5) but ABOVE this
        # custom, lower threshold (0.1) -- so it must NOT be flagged
        # under this configuration.
        assert result.low_faithfulness_flag is False

    def test_raising_the_threshold_flags_previously_unflagged_scores(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": 0.6, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator, faithfulness_flag_threshold=0.9)

        result = pipeline.evaluate_batch([_item()]).results[0]

        assert result.low_faithfulness_flag is True  # 0.6 < 0.9


class TestP18Ordering:
    def test_flag_does_not_affect_result_ordering(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: ({"faithfulness": 0.9, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {}),
                1: ({"faithfulness": 0.1, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {}),
                2: ({"faithfulness": 0.9, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {}),
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="q0"), _item(query="q1"), _item(query="q2")])

        assert [r.query for r in response.results] == ["q0", "q1", "q2"]  # original order preserved
        assert [r.low_faithfulness_flag for r in response.results] == [False, True, False]


class TestP18AggregateUnaffected:
    def test_aggregate_model_has_no_new_flag_field(self):
        # Task 9.2's scope is per-item flagging only -- EvaluationAggregate
        # itself must remain exactly as Task 9.1 defined it.
        from app.models.evaluation import EvaluationAggregate

        assert set(EvaluationAggregate.model_fields.keys()) == {
            "faithfulness",
            "answer_relevancy",
            "context_precision",
            "context_recall",
        }

    def test_aggregate_faithfulness_value_is_unaffected_by_flagging(self):
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: ({"faithfulness": 0.2, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {}),
                1: ({"faithfulness": 0.8, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {}),
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator)

        response = pipeline.evaluate_batch([_item(query="q0"), _item(query="q1")])

        # Independent oracle: mean of 0.2 and 0.8, computed here directly.
        assert response.aggregate.faithfulness == pytest.approx(0.5)


class TestP18PropertyBased:
    """Hypothesis-based property test: for every generated faithfulness
    score in [0,1], the flag must equal exactly (score < threshold) --
    tested through the externally-observable EvaluationPipeline result,
    never by importing/calling `_is_low_faithfulness` as its own oracle
    for a DIFFERENT computation (the assertion below independently
    recomputes the expected boolean via a plain Python comparison).
    """

    @given(faithfulness_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
    @settings(max_examples=100, deadline=None)
    def test_flag_equals_score_less_than_threshold_for_arbitrary_scores(self, faithfulness_score: float) -> None:
        threshold = 0.5
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: (
                    {
                        "faithfulness": faithfulness_score,
                        "answer_relevancy": 0.5,
                        "context_precision": 0.5,
                        "context_recall": None,
                    },
                    {},
                )
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator, faithfulness_flag_threshold=threshold)

        result = pipeline.evaluate_batch([_item()]).results[0]

        # Independent oracle: a bare Python comparison, computed fresh
        # here, not via any pipeline/model helper.
        expected_flag = faithfulness_score < threshold
        assert result.low_faithfulness_flag == expected_flag

    @given(
        threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        faithfulness_score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100, deadline=None)
    def test_flag_equals_score_less_than_arbitrary_configured_threshold(
        self, threshold: float, faithfulness_score: float
    ) -> None:
        evaluator = FakeRagasEvaluator(
            per_item_overrides={
                0: (
                    {
                        "faithfulness": faithfulness_score,
                        "answer_relevancy": 0.5,
                        "context_precision": 0.5,
                        "context_recall": None,
                    },
                    {},
                )
            }
        )
        pipeline, _e, _store = _pipeline(evaluator=evaluator, faithfulness_flag_threshold=threshold)

        result = pipeline.evaluate_batch([_item()]).results[0]

        expected_flag = faithfulness_score < threshold
        assert result.low_faithfulness_flag == expected_flag

    @given(
        offset=st.floats(min_value=1e-9, max_value=1e-3, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=50, deadline=None)
    def test_values_immediately_around_the_boundary(self, offset: float) -> None:
        # Explicitly targets values very close to 0.5 on both sides,
        # per the task's emphasis on the exact boundary.
        threshold = 0.5

        just_below = threshold - offset
        evaluator_below = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": just_below, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline_below, _e, _store = _pipeline(evaluator=evaluator_below, faithfulness_flag_threshold=threshold)
        assert pipeline_below.evaluate_batch([_item()]).results[0].low_faithfulness_flag is True

        just_above = threshold + offset
        evaluator_above = FakeRagasEvaluator(
            per_item_overrides={0: ({"faithfulness": just_above, "answer_relevancy": 0.5, "context_precision": 0.5, "context_recall": None}, {})}
        )
        pipeline_above, _e2, _store2 = _pipeline(evaluator=evaluator_above, faithfulness_flag_threshold=threshold)
        assert pipeline_above.evaluate_batch([_item()]).results[0].low_faithfulness_flag is False
