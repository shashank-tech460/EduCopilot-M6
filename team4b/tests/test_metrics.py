"""Focused tests for Task 10.1's MetricsCollector.

Scope: unit tests for query count, average latency, hit rate, error
rate, zero-query behavior, and thread safety. No HTTP/API layer here --
`tests/test_api.py` covers `GET /metrics` and `POST /api/v1/query`'s
recording behavior through actual HTTP requests.
"""

from __future__ import annotations

import threading

import pytest

from app.services.metrics import MetricsCollector, MetricsSnapshot


class TestZeroQueryBehavior:
    def test_query_count_is_zero_initially(self):
        collector = MetricsCollector()

        snapshot = collector.snapshot()

        assert snapshot.query_count == 0

    def test_average_latency_is_none_with_no_queries(self):
        collector = MetricsCollector()

        assert collector.snapshot().average_latency_seconds is None

    def test_hit_rate_is_none_with_no_queries(self):
        collector = MetricsCollector()

        assert collector.snapshot().hit_rate is None

    def test_error_rate_is_none_with_no_queries(self):
        collector = MetricsCollector()

        assert collector.snapshot().error_rate is None

    def test_snapshot_never_raises_with_zero_queries(self):
        collector = MetricsCollector()

        # No ZeroDivisionError, no exception of any kind.
        snapshot = collector.snapshot()
        assert isinstance(snapshot, MetricsSnapshot)


class TestQueryCount:
    def test_count_increases_for_successful_queries(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.2, succeeded=True, hit=True)

        assert collector.snapshot().query_count == 2

    def test_count_increases_for_failed_queries_too(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)

        assert collector.snapshot().query_count == 1

    def test_count_reflects_a_mix_of_success_and_failure(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=False)

        assert collector.snapshot().query_count == 3


class TestAverageLatency:
    def test_average_of_a_single_query(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.5, succeeded=True, hit=True)

        assert collector.snapshot().average_latency_seconds == pytest.approx(0.5)

    def test_average_of_multiple_queries(self):
        collector = MetricsCollector()

        for duration in (0.1, 0.2, 0.3):
            collector.record_query(duration_seconds=duration, succeeded=True, hit=True)

        # Independent oracle, computed directly here.
        expected = (0.1 + 0.2 + 0.3) / 3
        assert collector.snapshot().average_latency_seconds == pytest.approx(expected)

    def test_failed_queries_latency_still_counts_toward_the_average(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=1.0, succeeded=True, hit=True)
        collector.record_query(duration_seconds=3.0, succeeded=False, hit=False)

        # Documented semantics: average latency reflects total processing
        # time regardless of outcome.
        assert collector.snapshot().average_latency_seconds == pytest.approx(2.0)


class TestHitRate:
    def test_all_hits(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)

        assert collector.snapshot().hit_rate == pytest.approx(1.0)

    def test_all_misses(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=False)

        assert collector.snapshot().hit_rate == pytest.approx(0.0)

    def test_mixed_hits_and_misses(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=False)

        assert collector.snapshot().hit_rate == pytest.approx(0.5)

    def test_failed_queries_are_excluded_from_the_hit_rate_denominator(self):
        # Documented semantics: hit_rate is computed over COMPLETED
        # (successful) queries only -- a failed query never produced a
        # chunks_retrieved value, so it cannot count as a hit OR a miss.
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)

        # Independent oracle: 1 hit out of 1 COMPLETED query = 1.0, not
        # 1 out of 2 total queries (which would be 0.5).
        assert collector.snapshot().hit_rate == pytest.approx(1.0)

    def test_hit_rate_is_none_when_every_query_failed(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)

        # Zero completed queries -> undefined hit rate -> None, not 0.0.
        assert collector.snapshot().hit_rate is None


class TestErrorRate:
    def test_no_errors(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)

        assert collector.snapshot().error_rate == pytest.approx(0.0)

    def test_all_errors(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)

        assert collector.snapshot().error_rate == pytest.approx(1.0)

    def test_mixed_errors(self):
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)

        # Independent oracle: 2 errors out of 4 total queries.
        assert collector.snapshot().error_rate == pytest.approx(0.5)

    def test_error_rate_denominator_is_total_queries_not_completed_only(self):
        # Distinguishes error_rate's denominator (ALL query attempts)
        # from hit_rate's denominator (only completed/successful ones).
        collector = MetricsCollector()

        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        collector.record_query(duration_seconds=0.1, succeeded=False, hit=False)

        # Independent oracle: 1 error out of 3 TOTAL queries = 1/3, not
        # 1 out of 2 completed queries.
        assert collector.snapshot().error_rate == pytest.approx(1 / 3)


class TestSnapshotConsistency:
    def test_snapshot_is_a_point_in_time_read_not_a_live_view(self):
        collector = MetricsCollector()
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)

        snapshot_one = collector.snapshot()
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)
        snapshot_two = collector.snapshot()

        assert snapshot_one.query_count == 1
        assert snapshot_two.query_count == 2  # snapshot_one is unaffected by the later record

    def test_snapshot_is_immutable(self):
        collector = MetricsCollector()
        collector.record_query(duration_seconds=0.1, succeeded=True, hit=True)

        snapshot = collector.snapshot()

        with pytest.raises(Exception):
            snapshot.query_count = 999  # type: ignore[misc]


class TestThreadSafety:
    def test_concurrent_recording_from_multiple_threads_produces_the_correct_total_count(self):
        collector = MetricsCollector()
        thread_count = 8
        records_per_thread = 50

        def record_many() -> None:
            for _ in range(records_per_thread):
                collector.record_query(duration_seconds=0.01, succeeded=True, hit=True)

        threads = [threading.Thread(target=record_many) for _ in range(thread_count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # If recording were not properly synchronized, concurrent
        # increments could race and undercount -- this proves they don't.
        assert collector.snapshot().query_count == thread_count * records_per_thread

    def test_concurrent_recording_with_mixed_outcomes_stays_consistent(self):
        collector = MetricsCollector()

        def record_success() -> None:
            for _ in range(50):
                collector.record_query(duration_seconds=0.01, succeeded=True, hit=True)

        def record_failure() -> None:
            for _ in range(50):
                collector.record_query(duration_seconds=0.01, succeeded=False, hit=False)

        threads = [threading.Thread(target=record_success) for _ in range(4)] + [
            threading.Thread(target=record_failure) for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = collector.snapshot()
        assert snapshot.query_count == 400
        assert snapshot.error_rate == pytest.approx(0.5)
