"""Team 4B query metrics collector (Task 10.1).

Tracks real query-processing activity for `GET /metrics` (Requirement 9):
total query count, average latency, hit rate, and error rate. Populated
by `POST /api/v1/query`'s own route handler (`app/api/routes.py`) at the
end of every request -- this module contains no route logic itself and
no knowledge of HTTP.

THREAD SAFETY: this project's API routes are synchronous `def` functions
(matching `RAGService`'s own synchronous design, per Task 8.1's own
"async/sync compatibility" decision) -- FastAPI runs sync routes in a
worker thread pool (`starlette.concurrency.run_in_threadpool`), so
concurrent requests can call into this collector from DIFFERENT OS
THREADS simultaneously, not just concurrent asyncio tasks. A plain
`threading.Lock` (not an asyncio lock, which would not protect against
genuine multi-threaded access) guards all mutable state.

METRICS SEMANTICS (documented decisions, since neither official document
defines exact formulas):

  - query_count: incremented once per `POST /api/v1/query` attempt,
    successful or not.
  - average_latency_seconds: total recorded wall-clock duration (from
    just before `RAGService.handle_query()` is called to just after the
    route produces its response or raises) divided by query_count.
    Latency is recorded for BOTH successful and failed attempts, since
    "average latency" is naturally understood as how long the system
    spent processing a request, regardless of outcome.
  - hit_rate: reuses this project's own existing concept of retrieval
    success (Task 7.1's `RAGServiceResult.retrieval_metadata["chunks_retrieved"]`,
    the same field `LLMGenerator`'s insufficient-context shortcut keys
    off of, Task 6.1) -- a query is a "hit" if at least one chunk was
    retrieved (`chunks_retrieved > 0`). The denominator is the number of
    SUCCESSFULLY COMPLETED queries (a failed query never produced a
    `chunks_retrieved` value at all, so it cannot sensibly count as
    either a hit or a miss).
  - error_rate: failed query attempts (any exception propagating out of
    `RAGService.handle_query()`/response assembly, i.e. any request that
    resulted in the route mapping to a 5xx) divided by query_count.

ZERO-QUERY BEHAVIOR: all three derived metrics (average_latency_seconds,
hit_rate, error_rate) are `None`, not `0.0` and not a `ZeroDivisionError`,
when `query_count == 0` -- consistent with this project's own established
convention (Task 9.1's `EvaluationAggregate`: an undefined mean is `None`,
never a fabricated `0.0`).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricsSnapshot:
    """An immutable point-in-time read of the collected metrics."""

    query_count: int
    average_latency_seconds: float | None
    hit_rate: float | None
    error_rate: float | None


class MetricsCollector:
    """Thread-safe accumulator for query count, latency, hits, and
    errors. See module docstring for exact semantics.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._query_count = 0
        self._error_count = 0
        self._completed_count = 0
        self._hit_count = 0
        self._total_latency_seconds = 0.0

    def record_query(self, *, duration_seconds: float, succeeded: bool, hit: bool = False) -> None:
        """Record one completed query attempt.

        `succeeded=False` means the request ultimately failed (mapped to
        a 5xx by the route) -- `hit` is meaningless in that case and is
        ignored for the hit-rate denominator/numerator.
        """

        with self._lock:
            self._query_count += 1
            self._total_latency_seconds += duration_seconds
            if succeeded:
                self._completed_count += 1
                if hit:
                    self._hit_count += 1
            else:
                self._error_count += 1

    def snapshot(self) -> MetricsSnapshot:
        """Return a consistent, immutable read of all metrics at this
        instant. Never raises, never divides by zero -- see module
        docstring's "ZERO-QUERY BEHAVIOR" section.
        """

        with self._lock:
            query_count = self._query_count
            average_latency = (self._total_latency_seconds / query_count) if query_count > 0 else None
            hit_rate = (self._hit_count / self._completed_count) if self._completed_count > 0 else None
            error_rate = (self._error_count / query_count) if query_count > 0 else None

        return MetricsSnapshot(
            query_count=query_count,
            average_latency_seconds=average_latency,
            hit_rate=hit_rate,
            error_rate=error_rate,
        )
