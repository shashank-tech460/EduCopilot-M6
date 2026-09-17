"""Task 10.2 / P19 -- Health degradation accuracy.

Formalizes the official Property 19 test for `GET /health`, building on
Task 10.1's already-implemented health logic:

    app/services/vector_store.py::VectorStoreManager.check_health()
    app/services/conversation.py::ConversationManager.check_health()
    app/services/llm_generator.py::LLMGenerator.check_health()
    app/api/routes.py::get_health() / _check_component()

NO PRODUCTION CODE WAS CHANGED for this task -- inspected directly (not
assumed from the Task 10.1 report) and confirmed the existing
implementation already: checks each component independently (a failure
in one never affects another's reported status); derives `"rag"`
correctly as the logical AND of the other three (already fixed during
Task 10.1's own review); tolerates any check raising via
`_check_component`'s own try/except, which can only ever produce
`"unavailable"`, never `"healthy"`, on any exception; and never
mutates/creates anything (each check is exactly one read-only call).

This file's job is exclusively to PROVE the full degradation matrix P19
requires -- including the pairwise (exactly-two-of-three) failure
combinations Task 10.1's own tests did not yet enumerate -- through the
real `GET /health` HTTP route (reusing `_health_client`/
`_FakeHealthComponent` from `tests/test_api.py`, not a second,
competing test fixture), plus a Hypothesis-based property test of
`_check_component` itself proving NO exception, of any type or message,
can ever produce a `"healthy"` result.
"""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.api.routes import ComponentHealth, _check_component
from tests.test_api import _FakeHealthComponent, _health_client

# ---------------------------------------------------------------------------
# A + full matrix: all 2^3 = 8 healthy/unavailable combinations of
# (vector_store, redis, llm), independently verified against plain
# boolean logic -- never against the production _check_component/get_health
# code itself.
# ---------------------------------------------------------------------------

_ALL_COMBINATIONS = list(itertools.product([True, False], repeat=3))  # (qdrant, redis, llm)


class TestP19FullDegradationMatrix:
    """The exhaustive version of the "P19 degradation matrix" the task
    requests: every one of the 8 possible healthy/unavailable
    combinations of the three real dependencies, checked in one
    parametrized test so no combination can be silently skipped.
    """

    @pytest.mark.parametrize("qdrant_healthy,redis_healthy,llm_healthy", _ALL_COMBINATIONS)
    def test_matrix(self, qdrant_healthy: bool, redis_healthy: bool, llm_healthy: bool) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(healthy=qdrant_healthy),
            redis=_FakeHealthComponent(healthy=redis_healthy),
            llm=_FakeHealthComponent(healthy=llm_healthy),
        )

        response = client.get("/health")

        assert response.status_code == 200  # never changes regardless of degradation (Task 10.1 decision, preserved)

        body = response.json()
        components = body["components"]

        # Independent oracle: exactly what was configured, nothing else
        # -- proves no cross-contamination between components.
        assert (components["vector_store"]["status"] == "healthy") == qdrant_healthy
        assert (components["redis"]["status"] == "healthy") == redis_healthy
        assert (components["llm"]["status"] == "healthy") == llm_healthy

        # "rag" is the logical AND of the three, per RAGService.handle_query()'s
        # actual call order (Task 10.1's documented, verified rollup rule).
        expected_rag_healthy = qdrant_healthy and redis_healthy and llm_healthy
        assert (components["rag"]["status"] == "healthy") == expected_rag_healthy

        # Overall status is "healthy" only when literally everything is.
        expected_overall_healthy = qdrant_healthy and redis_healthy and llm_healthy
        assert (body["status"] == "healthy") == expected_overall_healthy


# ---------------------------------------------------------------------------
# B: single failures (named, human-readable versions of 3 of the 8 matrix
# rows above, for direct citability in review/reporting)
# ---------------------------------------------------------------------------


class TestP19SingleFailuresNamed:
    def test_qdrant_alone_down(self) -> None:
        client, _vs, _redis, _llm = _health_client(vector_store=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["vector_store"]["status"] == "unavailable"
        assert body["components"]["redis"]["status"] == "healthy"
        assert body["components"]["llm"]["status"] == "healthy"
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"

    def test_redis_alone_down(self) -> None:
        client, _vs, _redis, _llm = _health_client(redis=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["redis"]["status"] == "unavailable"
        assert body["components"]["vector_store"]["status"] == "healthy"
        assert body["components"]["llm"]["status"] == "healthy"
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"

    def test_llm_alone_down(self) -> None:
        client, _vs, _redis, _llm = _health_client(llm=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["llm"]["status"] == "unavailable"
        assert body["components"]["vector_store"]["status"] == "healthy"
        assert body["components"]["redis"]["status"] == "healthy"
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# C: multiple (pairwise) failures -- the genuine gap Task 10.1's own tests
# did not enumerate (they covered each single failure and all-three-down,
# but not exactly-two-of-three)
# ---------------------------------------------------------------------------


class TestP19PairwiseFailures:
    def test_qdrant_and_redis_down_llm_stays_healthy(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(healthy=False),
            redis=_FakeHealthComponent(healthy=False),
        )

        body = client.get("/health").json()

        assert body["components"]["vector_store"]["status"] == "unavailable"
        assert body["components"]["redis"]["status"] == "unavailable"
        assert body["components"]["llm"]["status"] == "healthy"  # NOT falsely marked down
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"

    def test_qdrant_and_llm_down_redis_stays_healthy(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(healthy=False),
            llm=_FakeHealthComponent(healthy=False),
        )

        body = client.get("/health").json()

        assert body["components"]["vector_store"]["status"] == "unavailable"
        assert body["components"]["llm"]["status"] == "unavailable"
        assert body["components"]["redis"]["status"] == "healthy"  # NOT falsely marked down
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"

    def test_redis_and_llm_down_qdrant_stays_healthy(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            redis=_FakeHealthComponent(healthy=False),
            llm=_FakeHealthComponent(healthy=False),
        )

        body = client.get("/health").json()

        assert body["components"]["redis"]["status"] == "unavailable"
        assert body["components"]["llm"]["status"] == "unavailable"
        assert body["components"]["vector_store"]["status"] == "healthy"  # NOT falsely marked down
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"

    def test_all_three_down(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(healthy=False),
            redis=_FakeHealthComponent(healthy=False),
            llm=_FakeHealthComponent(healthy=False),
        )

        body = client.get("/health").json()

        assert all(body["components"][name]["status"] == "unavailable" for name in ("vector_store", "redis", "llm"))
        assert body["components"]["rag"]["status"] == "unavailable"
        assert body["status"] == "degraded"


# ---------------------------------------------------------------------------
# D: mixed states -- healthy components must never be reported as
# unavailable merely because a different component failed
# ---------------------------------------------------------------------------


class TestP19MixedStatesDoNotCrossContaminate:
    def test_each_component_check_is_invoked_independently_exactly_once(self) -> None:
        # Structural proof, not just an output check: every check
        # function is called, and called exactly once, regardless of
        # what the OTHER checks report.
        client, vector_store, redis, llm = _health_client(redis=_FakeHealthComponent(healthy=False))

        client.get("/health")

        assert vector_store.check_health_calls == 1
        assert redis.check_health_calls == 1
        assert llm.check_health_calls == 1

    def test_healthy_qdrant_and_llm_are_unaffected_by_a_redis_failure(self) -> None:
        client, _vs, _redis, _llm = _health_client(redis=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["vector_store"]["status"] == "healthy"
        assert body["components"]["llm"]["status"] == "healthy"

    def test_healthy_redis_and_llm_are_unaffected_by_a_qdrant_failure(self) -> None:
        client, _vs, _redis, _llm = _health_client(vector_store=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["redis"]["status"] == "healthy"
        assert body["components"]["llm"]["status"] == "healthy"


# ---------------------------------------------------------------------------
# E: RAG rollup -- already exhaustively covered by TestP19FullDegradationMatrix
# above (every one of the 8 combinations asserts the exact expected "rag"
# value), plus this explicit restatement of the specific claim Task 10.1's
# own review grounded the rollup rule in.
# ---------------------------------------------------------------------------


class TestP19RagRollupGroundedInRealCallOrder:
    def test_rag_unavailable_when_only_redis_is_down_because_append_turn_is_unconditional(self) -> None:
        # RAGService.handle_query() calls ConversationManager.append_turn()
        # (Redis) BEFORE retrieval or generation are even attempted (Task
        # 7.1) -- so a real query fails end-to-end if Redis alone is down,
        # even with Qdrant and Ollama both healthy. "rag" must reflect that.
        client, _vs, _redis, _llm = _health_client(redis=_FakeHealthComponent(healthy=False))

        body = client.get("/health").json()

        assert body["components"]["rag"]["status"] == "unavailable"


# ---------------------------------------------------------------------------
# F: exception resilience across ALL THREE components (Task 10.1's own
# tests only exercised vector_store raising, plus one all-three-raising
# case) -- this fills in redis-raises and llm-raises individually, plus
# mixed raise+false combinations.
# ---------------------------------------------------------------------------


class TestP19ExceptionResilienceAcrossAllComponents:
    def test_redis_check_raising_is_handled_safely(self) -> None:
        client, _vs, _redis, _llm = _health_client(redis=_FakeHealthComponent(raises=ConnectionError("redis down")))

        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["components"]["redis"]["status"] == "unavailable"
        assert body["components"]["vector_store"]["status"] == "healthy"
        assert body["components"]["llm"]["status"] == "healthy"

    def test_llm_check_raising_is_handled_safely(self) -> None:
        client, _vs, _redis, _llm = _health_client(llm=_FakeHealthComponent(raises=TimeoutError("ollama timeout")))

        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["components"]["llm"]["status"] == "unavailable"
        assert body["components"]["vector_store"]["status"] == "healthy"
        assert body["components"]["redis"]["status"] == "healthy"

    def test_mixed_raise_and_returned_false_across_two_components(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(raises=TimeoutError("timeout")),
            redis=_FakeHealthComponent(healthy=False),
        )

        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert body["components"]["vector_store"]["status"] == "unavailable"
        assert body["components"]["redis"]["status"] == "unavailable"
        assert body["components"]["llm"]["status"] == "healthy"

    def test_all_three_raising_simultaneously_with_different_exception_types(self) -> None:
        client, _vs, _redis, _llm = _health_client(
            vector_store=_FakeHealthComponent(raises=ConnectionError("a")),
            redis=_FakeHealthComponent(raises=TimeoutError("b")),
            llm=_FakeHealthComponent(raises=RuntimeError("c")),
        )

        response = client.get("/health")

        assert response.status_code == 200
        body = response.json()
        assert all(component["status"] == "unavailable" for component in body["components"].values())
        assert body["status"] == "degraded"


class TestP19CheckComponentNeverReturnsHealthyOnException:
    """Direct, Hypothesis-based property test of `_check_component` itself
    (the ONE function responsible for turning a raised exception into a
    health result) -- proving, for arbitrary exception types and
    messages, it can NEVER produce `"healthy"`. This complements (does
    not replace) the route-level tests above.
    """

    @given(message=st.text(min_size=0, max_size=200))
    def test_arbitrary_runtime_error_message_always_yields_unavailable(self, message: str) -> None:
        def raising_check() -> bool:
            raise RuntimeError(message)

        result = _check_component(raising_check)

        assert result.status == "unavailable"
        assert result.status != "healthy"

    @given(
        exception_type=st.sampled_from([ConnectionError, TimeoutError, ValueError, RuntimeError, OSError, KeyError])
    )
    def test_arbitrary_exception_type_always_yields_unavailable(self, exception_type: type[Exception]) -> None:
        def raising_check() -> bool:
            raise exception_type("simulated failure")

        result = _check_component(raising_check)

        assert result.status == "unavailable"

    @given(returns_healthy=st.booleans())
    def test_non_raising_check_result_matches_exactly_what_it_returned(self, returns_healthy: bool) -> None:
        def check_fn() -> bool:
            return returns_healthy

        result = _check_component(check_fn)

        assert isinstance(result, ComponentHealth)
        assert (result.status == "healthy") == returns_healthy


# ---------------------------------------------------------------------------
# G: no side effects (Task 10.1 already has one such test; these add
# explicit coverage that the injected fakes -- which implement ONLY
# check_health() -- are never asked to do anything else)
# ---------------------------------------------------------------------------


class TestP19NoSideEffects:
    def test_health_check_fakes_are_never_asked_to_do_anything_beyond_check_health(self) -> None:
        # _FakeHealthComponent implements ONLY check_health(). If the
        # route attempted retrieval, generation, or a Qdrant write
        # through these objects, it would raise AttributeError, which
        # would surface here as a 500 -- succeeding with 200 is itself
        # the proof no such call was attempted.
        client, _vs, _redis, _llm = _health_client()

        response = client.get("/health")

        assert response.status_code == 200

    def test_repeated_health_calls_do_not_change_component_call_counts_unexpectedly(self) -> None:
        # Each GET /health should invoke each check exactly once per
        # request -- not zero (skipped), not more than once (redundant
        # re-checks), across repeated calls.
        client, vector_store, redis, llm = _health_client()

        client.get("/health")
        client.get("/health")
        client.get("/health")

        assert vector_store.check_health_calls == 3
        assert redis.check_health_calls == 3
        assert llm.check_health_calls == 3
