"""Task 7.2 -- official RAGService/RetrievalConfig correctness properties.

    P16 RetrievalConfig validation (invalid config never reaches the retriever)
    P17 Config override isolation

These test BEHAVIOR through `RAGService.handle_query(, workspace_id="ws-1")` and
`RetrievalConfig`'s own Pydantic validation -- the actual public
surfaces -- using a recording/raising fake retriever, per the task's
explicit instructions. Reuses the existing `FakeHybridRetriever`,
`FakeConversationManager`, `FakeLLMGenerator` from
`tests/test_rag_service.py` rather than duplicating them.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.query import RetrievalConfig, SearchMode
from app.services.rag_service import RAGService
from tests.test_rag_service import FakeConversationManager, FakeHybridRetriever, FakeLLMGenerator, _chunk

_HYP = hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def _service() -> tuple[RAGService, FakeHybridRetriever, FakeConversationManager, FakeLLMGenerator]:
    retriever = FakeHybridRetriever(results=[_chunk("c1", "context")])
    conversation = FakeConversationManager()
    llm = FakeLLMGenerator()
    service = RAGService(hybrid_retriever=retriever, conversation_manager=conversation, llm_generator=llm)  # type: ignore[arg-type]
    return service, retriever, conversation, llm


# ===========================================================================
# P16: RetrievalConfig validation -- invalid configuration never executes a query
#
# "For any invalid RetrievalConfig, construction SHALL raise a
#  validation error and the retriever SHALL NOT be invoked." (Validates
#  Requirement 7.1/7.3)
# ===========================================================================


class TestPropertySixteenRetrievalConfigValidation:
    @_HYP
    @given(top_k=st.integers(max_value=0))
    def test_top_k_at_or_below_zero_rejected_before_any_query_executes(self, top_k: int) -> None:
        _service_instance, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=top_k)

        assert retriever.calls == []  # never even reached because construction itself failed

    @_HYP
    @given(top_k=st.integers(min_value=51, max_value=10_000))
    def test_top_k_above_fifty_rejected_before_any_query_executes(self, top_k: int) -> None:
        _service_instance, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=top_k)

        assert retriever.calls == []

    @_HYP
    @given(threshold=st.floats(max_value=-0.0001, allow_nan=False))
    def test_negative_score_threshold_rejected_before_any_query_executes(self, threshold: float) -> None:
        _service_instance, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            RetrievalConfig(score_threshold=threshold)

        assert retriever.calls == []

    @_HYP
    @given(threshold=st.floats(min_value=1.0001, max_value=1000.0, allow_nan=False))
    def test_score_threshold_above_one_rejected_before_any_query_executes(self, threshold: float) -> None:
        _service_instance, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            RetrievalConfig(score_threshold=threshold)

        assert retriever.calls == []

    @_HYP
    @given(mode=st.text(min_size=1, max_size=20).filter(lambda s: s not in ("hybrid", "semantic", "keyword")))
    def test_invalid_search_mode_rejected_before_any_query_executes(self, mode: str) -> None:
        _service_instance, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            RetrievalConfig(search_mode=mode)  # type: ignore[arg-type] # intentionally invalid input under test

        assert retriever.calls == []

    def test_valid_boundary_top_k_one_executes_successfully(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q", session_id="s1", retrieval_config=RetrievalConfig(top_k=1), workspace_id="ws-1")

        assert retriever.calls[0]["top_k"] == 1

    def test_valid_boundary_top_k_fifty_executes_successfully(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q", session_id="s1", retrieval_config=RetrievalConfig(top_k=50), workspace_id="ws-1")

        assert retriever.calls[0]["top_k"] == 50

    def test_valid_boundary_threshold_zero_executes_successfully(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q", session_id="s1", retrieval_config=RetrievalConfig(score_threshold=0.0), workspace_id="ws-1")

        assert retriever.calls[0]["score_threshold"] == 0.0

    def test_valid_boundary_threshold_one_executes_successfully(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q", session_id="s1", retrieval_config=RetrievalConfig(score_threshold=1.0), workspace_id="ws-1")

        assert retriever.calls[0]["score_threshold"] == 1.0

    def test_invalid_config_cannot_be_smuggled_through_handle_query(self) -> None:
        """Explicit end-to-end proof: since `RetrievalConfig` cannot be
        constructed with an invalid value at all, there is no code path
        by which `RAGService.handle_query(, workspace_id="ws-1")` could ever be called with
        one -- the property holds structurally, not just by convention.
        """

        service, retriever, _conv, _llm = _service()

        with pytest.raises(ValidationError):
            bad_config = RetrievalConfig(top_k=999)
            service.handle_query("q", session_id="s1", retrieval_config=bad_config, workspace_id="ws-1")  # never reached

        assert retriever.calls == []


# ===========================================================================
# P17: Config override isolation
#
# "For any sequence of queries with different (or absent) RetrievalConfig
#  overrides, each query SHALL be executed with exactly its own
#  configuration, no override SHALL leak into another request, and
#  global Settings/defaults SHALL remain unchanged throughout."
#  (Validates Requirement 7.2)
# ===========================================================================


class TestPropertySeventeenConfigOverrideIsolation:
    def test_three_request_example_from_task_brief(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query(
            "A", session_id="s-a", retrieval_config=RetrievalConfig(top_k=2, score_threshold=0.8, search_mode=SearchMode.SEMANTIC), workspace_id="ws-1"
        )
        service.handle_query(
            "B", session_id="s-b", retrieval_config=RetrievalConfig(top_k=10, score_threshold=0.1, search_mode=SearchMode.KEYWORD), workspace_id="ws-1"
        )
        service.handle_query("C", session_id="s-c", workspace_id="ws-1")  # no override -- defaults

        call_a, call_b, call_c = retriever.calls[0], retriever.calls[1], retriever.calls[2]

        assert call_a["top_k"] == 2 and call_a["score_threshold"] == 0.8 and call_a["search_mode"] == "semantic"
        assert call_b["top_k"] == 10 and call_b["score_threshold"] == 0.1 and call_b["search_mode"] == "keyword"
        assert call_c["top_k"] == 5 and call_c["score_threshold"] == 0.3 and call_c["search_mode"] == "hybrid"

    @_HYP
    @given(
        configs=st.lists(
            st.one_of(
                st.none(),
                st.builds(
                    RetrievalConfig,
                    top_k=st.integers(min_value=1, max_value=50),
                    score_threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
                    search_mode=st.sampled_from([SearchMode.HYBRID, SearchMode.SEMANTIC, SearchMode.KEYWORD]),
                ),
            ),
            min_size=2,
            max_size=10,
        )
    )
    def test_each_generated_request_receives_exactly_its_own_configuration(
        self, configs: list[RetrievalConfig | None]
    ) -> None:
        service, retriever, _conv, _llm = _service()

        for i, config in enumerate(configs):
            service.handle_query(f"query {i}", session_id=f"session-{i}", retrieval_config=config, workspace_id="ws-1")

        for i, config in enumerate(configs):
            expected = config if config is not None else RetrievalConfig()
            actual_call = retriever.calls[i]
            assert actual_call["top_k"] == expected.top_k
            assert actual_call["score_threshold"] == expected.score_threshold
            assert actual_call["search_mode"] == expected.search_mode.value
            assert actual_call["collection_filter"] == expected.collection_filter

    @_HYP
    @given(
        configs=st.lists(
            st.builds(RetrievalConfig, top_k=st.integers(min_value=1, max_value=50)),
            min_size=2,
            max_size=8,
        )
    )
    def test_global_settings_never_change_across_any_sequence_of_overrides(
        self, configs: list[RetrievalConfig]
    ) -> None:
        settings_before = get_settings()
        original_top_k = settings_before.default_top_k
        original_threshold = settings_before.default_score_threshold
        original_mode = settings_before.default_search_mode

        service, _retriever, _conv, _llm = _service()
        for i, config in enumerate(configs):
            service.handle_query(f"q{i}", session_id=f"s{i}", retrieval_config=config, workspace_id="ws-1")

        settings_after = get_settings()
        assert settings_after.default_top_k == original_top_k
        assert settings_after.default_score_threshold == original_threshold
        assert settings_after.default_search_mode == original_mode

    def test_default_retrieval_config_construction_is_unaffected_by_prior_overrides(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q1", session_id="s1", retrieval_config=RetrievalConfig(top_k=1, score_threshold=0.99), workspace_id="ws-1")

        # A freshly-constructed default RetrievalConfig, AFTER an
        # extreme override was used, must still show the official
        # defaults -- proving overrides never mutated the model's own
        # default values.
        fresh_default = RetrievalConfig()
        assert fresh_default.top_k == 5
        assert fresh_default.score_threshold == 0.3
        assert fresh_default.search_mode == SearchMode.HYBRID

    def test_collection_filter_does_not_leak_between_requests(self) -> None:
        service, retriever, _conv, _llm = _service()

        service.handle_query("q1", session_id="s1", retrieval_config=RetrievalConfig(collection_filter=["document"]), workspace_id="ws-1")
        service.handle_query("q2", session_id="s2", workspace_id="ws-1")  # no override

        assert retriever.calls[0]["collection_filter"] == ["document"]
        assert retriever.calls[1]["collection_filter"] is None  # not leaked from the previous request

    def test_service_behavior_is_deterministic_for_repeated_identical_configs(self) -> None:
        service, retriever, _conv, _llm = _service()
        config = RetrievalConfig(top_k=7, score_threshold=0.6, search_mode=SearchMode.KEYWORD)

        service.handle_query("q1", session_id="s1", retrieval_config=config, workspace_id="ws-1")
        service.handle_query("q2", session_id="s2", retrieval_config=config, workspace_id="ws-1")

        assert retriever.calls[0]["top_k"] == retriever.calls[1]["top_k"] == 7
        assert retriever.calls[0]["search_mode"] == retriever.calls[1]["search_mode"] == "keyword"
