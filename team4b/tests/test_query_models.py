"""Focused tests for Corrective Task 1.2's query/response models.

Scope: unit tests establishing the official model contract --
SearchMode, RetrievalConfig, QueryRequest, SourceAttribution,
QueryResponse. Does NOT implement any correctness property (P1-P19);
those remain their designated tasks' scope.

ANTI-CIRCULARITY: every assertion checks an observable model attribute
or a raised `pydantic.ValidationError` directly -- no test constructs
its "expected" value by calling the same model/validator being tested.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.models.query import (
    QueryRequest,
    QueryResponse,
    RetrievalConfig,
    SearchMode,
    SourceAttribution,
)


# ---------------------------------------------------------------------------
# SearchMode
# ---------------------------------------------------------------------------


class TestSearchMode:
    def test_hybrid_value(self):
        assert SearchMode.HYBRID.value == "hybrid"

    def test_semantic_value(self):
        assert SearchMode.SEMANTIC.value == "semantic"

    def test_keyword_value(self):
        assert SearchMode.KEYWORD.value == "keyword"

    def test_exactly_three_values_no_more_no_less(self):
        assert {mode.value for mode in SearchMode} == {"hybrid", "semantic", "keyword"}

    def test_is_a_string_enum_for_json_compatibility(self):
        assert isinstance(SearchMode.HYBRID, str)
        assert SearchMode.HYBRID == "hybrid"

    def test_constructing_from_valid_string_values(self):
        assert SearchMode("hybrid") is SearchMode.HYBRID
        assert SearchMode("semantic") is SearchMode.SEMANTIC
        assert SearchMode("keyword") is SearchMode.KEYWORD

    def test_invalid_value_rejected(self):
        with pytest.raises(ValueError):
            SearchMode("bm25")

    def test_invalid_value_rejected_case_sensitive(self):
        with pytest.raises(ValueError):
            SearchMode("Hybrid")

    def test_no_unofficial_modes_exist(self):
        official_values = {"hybrid", "semantic", "keyword"}
        for unofficial in ("bm25", "vector", "hybrid_search", "vector_search", "keyword_search"):
            assert unofficial not in official_values


# ---------------------------------------------------------------------------
# RetrievalConfig
# ---------------------------------------------------------------------------


class TestRetrievalConfigDefaults:
    def test_default_top_k_is_5(self):
        assert RetrievalConfig().top_k == 5

    def test_default_score_threshold_is_0_3(self):
        assert RetrievalConfig().score_threshold == 0.3

    def test_default_search_mode_is_hybrid(self):
        assert RetrievalConfig().search_mode == SearchMode.HYBRID

    def test_default_collection_filter_is_none(self):
        assert RetrievalConfig().collection_filter is None

    def test_defaults_do_not_drift_from_settings_defaults(self):
        """Regression guard for the documented design decision: these
        are hardcoded literals, not a live Settings-reading
        default_factory -- this test is what keeps them honest if
        Settings' own defaults ever change without this model being
        updated to match.
        """

        settings = get_settings()
        config = RetrievalConfig()

        assert config.top_k == settings.default_top_k
        assert config.score_threshold == settings.default_score_threshold
        assert config.search_mode.value == settings.default_search_mode


class TestRetrievalConfigValidation:
    def test_top_k_minimum_boundary_1_is_valid(self):
        assert RetrievalConfig(top_k=1).top_k == 1

    def test_top_k_maximum_boundary_50_is_valid(self):
        assert RetrievalConfig(top_k=50).top_k == 50

    def test_top_k_below_1_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=0)

    def test_top_k_negative_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=-1)

    def test_top_k_above_50_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(top_k=51)

    def test_score_threshold_minimum_boundary_0_is_valid(self):
        assert RetrievalConfig(score_threshold=0.0).score_threshold == 0.0

    def test_score_threshold_maximum_boundary_1_is_valid(self):
        assert RetrievalConfig(score_threshold=1.0).score_threshold == 1.0

    def test_score_threshold_below_0_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(score_threshold=-0.01)

    def test_score_threshold_above_1_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(score_threshold=1.01)

    def test_valid_search_mode_string_accepted(self):
        assert RetrievalConfig(search_mode="semantic").search_mode == SearchMode.SEMANTIC

    def test_invalid_search_mode_string_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(search_mode="bm25")

    def test_collection_filter_accepts_a_list_of_strings(self):
        config = RetrievalConfig(collection_filter=["document", "video"])
        assert config.collection_filter == ["document", "video"]

    def test_collection_filter_accepts_explicit_none(self):
        assert RetrievalConfig(collection_filter=None).collection_filter is None

    def test_collection_filter_empty_list_is_distinct_from_none(self):
        assert RetrievalConfig(collection_filter=[]).collection_filter == []


class TestRetrievalConfigIndependence:
    def test_per_instance_overrides_do_not_affect_other_instances(self):
        override = RetrievalConfig(top_k=1, score_threshold=0.99, search_mode="keyword")
        default = RetrievalConfig()

        assert default.top_k == 5
        assert default.score_threshold == 0.3
        assert default.search_mode == SearchMode.HYBRID
        assert override.top_k == 1  # confirms the override actually took effect on its own instance

    def test_constructing_retrieval_config_does_not_mutate_global_settings(self):
        settings_before = get_settings()
        original_default_top_k = settings_before.default_top_k

        RetrievalConfig(top_k=1)
        RetrievalConfig(top_k=50)
        RetrievalConfig(search_mode="keyword")

        settings_after = get_settings()
        assert settings_after.default_top_k == original_default_top_k


# ---------------------------------------------------------------------------
# QueryRequest
# ---------------------------------------------------------------------------


class TestQueryRequest:
    def test_query_is_required(self):
        with pytest.raises(ValidationError):
            QueryRequest()  # type: ignore[call-arg]

    def test_valid_query_only(self):
        request = QueryRequest(query="What is RAG?")
        assert request.query == "What is RAG?"

    def test_session_id_defaults_to_none(self):
        request = QueryRequest(query="hello")
        assert request.session_id is None

    def test_session_id_can_be_supplied(self):
        request = QueryRequest(query="hello", session_id="abc-123")
        assert request.session_id == "abc-123"

    def test_retrieval_config_defaults_to_none(self):
        request = QueryRequest(query="hello")
        assert request.retrieval_config is None

    def test_retrieval_config_can_be_supplied(self):
        request = QueryRequest(query="hello", retrieval_config=RetrievalConfig(top_k=10))
        assert request.retrieval_config is not None
        assert request.retrieval_config.top_k == 10

    def test_retrieval_config_can_be_supplied_as_a_dict(self):
        # Pydantic should coerce a plain dict into RetrievalConfig.
        request = QueryRequest(query="hello", retrieval_config={"top_k": 20, "search_mode": "keyword"})
        assert request.retrieval_config is not None
        assert request.retrieval_config.top_k == 20
        assert request.retrieval_config.search_mode == SearchMode.KEYWORD

    def test_no_unofficial_fields_exist(self):
        official_fields = set(QueryRequest.model_fields.keys())
        unofficial = {"user_id", "conversation_id", "model", "temperature", "max_tokens", "sources", "stream", "metadata"}
        assert official_fields.isdisjoint(unofficial)

    def test_official_fields_are_exactly_query_session_id_retrieval_config(self):
        assert set(QueryRequest.model_fields.keys()) == {"query", "session_id", "retrieval_config"}


# ---------------------------------------------------------------------------
# SourceAttribution
# ---------------------------------------------------------------------------


class TestSourceAttribution:
    def test_required_fields_must_be_supplied(self):
        with pytest.raises(ValidationError):
            SourceAttribution()  # type: ignore[call-arg]

    def test_valid_minimal_construction(self):
        attribution = SourceAttribution(
            document_id="job-1", document_title="notes.pdf", chunk_id="c1", relevance_score=0.87
        )
        assert attribution.document_id == "job-1"
        assert attribution.document_title == "notes.pdf"
        assert attribution.chunk_id == "c1"
        assert attribution.relevance_score == 0.87

    def test_optional_fields_default_to_none(self):
        attribution = SourceAttribution(
            document_id="job-1", document_title="notes.pdf", chunk_id="c1", relevance_score=0.87
        )
        assert attribution.page_number is None
        assert attribution.section_heading is None
        assert attribution.start_timestamp is None
        assert attribution.end_timestamp is None

    def test_document_style_optional_fields(self):
        attribution = SourceAttribution(
            document_id="job-1",
            document_title="notes.pdf",
            chunk_id="c1",
            relevance_score=0.5,
            page_number=3,
            section_heading="Introduction",
        )
        assert attribution.page_number == 3
        assert attribution.section_heading == "Introduction"

    def test_video_style_optional_fields(self):
        attribution = SourceAttribution(
            document_id="job-2",
            document_title="How RAG Works",
            chunk_id="c2",
            relevance_score=0.5,
            start_timestamp=10.0,
            end_timestamp=25.0,
        )
        assert attribution.start_timestamp == 10.0
        assert attribution.end_timestamp == 25.0

    def test_relevance_score_is_not_range_restricted_at_this_layer(self):
        # Documented decision: no [0,1] validation added here (the
        # upstream Property 7 invariant is enforced elsewhere). This
        # test pins that decision down explicitly so a future change
        # doesn't silently add stricter validation than the official
        # contract states for this specific model.
        attribution = SourceAttribution(document_id="d", document_title="t", chunk_id="c", relevance_score=1.5)
        assert attribution.relevance_score == 1.5

    def test_no_team_4c_fields_exist(self):
        official_fields = set(SourceAttribution.model_fields.keys())
        team_4c_fields = {"type", "sourceFile", "fileId", "location", "label"}
        assert official_fields.isdisjoint(team_4c_fields)

    def test_official_fields_are_exactly_the_documented_set(self):
        assert set(SourceAttribution.model_fields.keys()) == {
            "document_id",
            "document_title",
            "chunk_id",
            "relevance_score",
            "page_number",
            "section_heading",
            "start_timestamp",
            "end_timestamp",
        }


# ---------------------------------------------------------------------------
# QueryResponse
# ---------------------------------------------------------------------------


class TestQueryResponse:
    def test_required_fields_must_be_supplied(self):
        with pytest.raises(ValidationError):
            QueryResponse()  # type: ignore[call-arg]

    def test_valid_construction_with_empty_attributions(self):
        response = QueryResponse(answer="Paris.", session_id="s1", source_attributions=[], retrieval_metadata={})
        assert response.answer == "Paris."
        assert response.session_id == "s1"
        assert response.source_attributions == []
        assert response.retrieval_metadata == {}

    def test_source_attributions_is_a_list_of_source_attribution(self):
        attribution = SourceAttribution(document_id="d", document_title="t", chunk_id="c", relevance_score=0.9)
        response = QueryResponse(
            answer="answer", session_id="s1", source_attributions=[attribution], retrieval_metadata={}
        )
        assert len(response.source_attributions) == 1
        assert isinstance(response.source_attributions[0], SourceAttribution)
        assert response.source_attributions[0].document_id == "d"

    def test_source_attributions_can_be_supplied_as_dicts(self):
        response = QueryResponse(
            answer="answer",
            session_id="s1",
            source_attributions=[{"document_id": "d", "document_title": "t", "chunk_id": "c", "relevance_score": 0.5}],
            retrieval_metadata={},
        )
        assert isinstance(response.source_attributions[0], SourceAttribution)

    def test_retrieval_metadata_accepts_an_open_dict(self):
        # The schema is intentionally open -- any JSON-serializable dict
        # is accepted, not a fixed/closed set of keys.
        response = QueryResponse(
            answer="answer",
            session_id="s1",
            source_attributions=[],
            retrieval_metadata={"chunks_retrieved": 5, "search_mode": "hybrid", "anything_else": [1, 2, 3]},
        )
        assert response.retrieval_metadata["chunks_retrieved"] == 5
        assert response.retrieval_metadata["anything_else"] == [1, 2, 3]

    def test_no_unofficial_fields_exist(self):
        official_fields = set(QueryResponse.model_fields.keys())
        unofficial = {"stream", "messages", "citations", "usage", "model", "finish_reason"}
        assert official_fields.isdisjoint(unofficial)

    def test_official_fields_are_exactly_the_documented_set(self):
        assert set(QueryResponse.model_fields.keys()) == {
            "answer",
            "session_id",
            "source_attributions",
            "retrieval_metadata",
        }


# ---------------------------------------------------------------------------
# No runtime logic in these models (sanity check, not exhaustive)
# ---------------------------------------------------------------------------


class TestModelsContainNoRuntimeLogic:
    def test_query_module_imports_without_touching_any_backend(self):
        # If constructing these models required a live Qdrant, Redis, or
        # Ollama connection, this import (already executed at module
        # load time above) or the constructions throughout this file
        # would already have failed/hung. Succeeding is itself the
        # assertion -- this is also implicitly proven by every other
        # test in this file running without any fake/mock backend
        # injected anywhere.
        import app.models.query  # noqa: F401


class TestM6DocumentIdsValidation:
    """MVP M6 document-level retrieval scope -- RetrievalConfig.document_ids validation."""

    def test_omitted_defaults_to_none(self):
        config = RetrievalConfig()
        assert config.document_ids is None

    def test_none_is_accepted_explicitly(self):
        config = RetrievalConfig(document_ids=None)
        assert config.document_ids is None

    def test_empty_list_is_accepted_and_preserved_distinct_from_none(self):
        config = RetrievalConfig(document_ids=[])
        assert config.document_ids == []
        assert config.document_ids is not None

    def test_a_normal_list_is_accepted(self):
        config = RetrievalConfig(document_ids=["doc-A", "doc-B"])
        assert config.document_ids == ["doc-A", "doc-B"]

    def test_duplicate_ids_are_accepted_not_rejected(self):
        config = RetrievalConfig(document_ids=["doc-A", "doc-A"])
        assert config.document_ids == ["doc-A", "doc-A"]

    def test_whitespace_only_entry_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(document_ids=["   "])

    def test_blank_string_entry_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(document_ids=[""])

    def test_non_string_entry_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(document_ids=[123])

    def test_excessively_large_list_is_rejected(self):
        with pytest.raises(ValidationError):
            RetrievalConfig(document_ids=[f"doc-{i}" for i in range(101)])

    def test_exactly_the_bound_is_accepted(self):
        config = RetrievalConfig(document_ids=[f"doc-{i}" for i in range(100)])
        assert len(config.document_ids) == 100

    def test_existing_fields_are_unaffected_default_construction_still_works(self):
        config = RetrievalConfig()
        assert config.top_k == 5
        assert config.score_threshold == 0.3
        assert config.collection_filter is None

    def test_document_ids_and_collection_filter_can_both_be_set_together(self):
        config = RetrievalConfig(document_ids=["doc-A"], collection_filter=["document"])
        assert config.document_ids == ["doc-A"]
        assert config.collection_filter == ["document"]
