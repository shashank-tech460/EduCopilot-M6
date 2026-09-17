"""Focused tests for Phase 4B's reranking layer
(app/services/reranker.py).

Scope: `CrossEncoderReranker` against a fake `CrossEncoderModelProtocol`
(never a real model -- no download, no network, no GPU/CPU model load in
this test file). Fixtures are deliberately subject-agnostic (generic
"topic A"/"topic B" text, plus a couple of genuinely multilingual
strings) -- never phrased around the OS/DBMS evaluation benchmark's own
questions, per this phase's explicit "do not optimize for the 75
benchmark queries" instruction.
"""

from __future__ import annotations

from typing import Sequence

import pytest

from app.core.config import Settings
from app.models.retrieval import RetrievalResult
from app.services.reranker import CrossEncoderReranker, RerankerUnavailableError, _sigmoid


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


class FakeCrossEncoderModel:
    """Deterministic stand-in for a real sentence-transformers
    `CrossEncoder`: returns a caller-supplied score per (query, text)
    pair, looked up by the candidate text -- so tests control exactly
    what "relevance" means without any real model.
    """

    def __init__(self, scores_by_text: dict[str, float], default: float = 0.0) -> None:
        self._scores_by_text = scores_by_text
        self._default = default
        self.calls: list[Sequence[tuple[str, str]]] = []

    def predict(self, sentence_pairs: Sequence[tuple[str, str]]):
        self.calls.append(list(sentence_pairs))
        return [self._scores_by_text.get(text, self._default) for _query, text in sentence_pairs]


class RaisingCrossEncoderModel:
    def predict(self, sentence_pairs: Sequence[tuple[str, str]]):
        raise RuntimeError("simulated model failure")


def _result(chunk_id: str, text: str, metadata: dict | None = None) -> RetrievalResult:
    return RetrievalResult(chunk_id=chunk_id, text=text, relevance_score=0.5, metadata=metadata or {})


class TestRerankOrdering:
    def test_reorders_candidates_by_model_score_descending(self):
        model = FakeCrossEncoderModel({"low relevance text": -2.0, "high relevance text": 4.0, "mid relevance text": 1.0})
        candidates = [
            _result("c-low", "low relevance text"),
            _result("c-high", "high relevance text"),
            _result("c-mid", "mid relevance text"),
        ]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("some query", candidates, top_k=3)

        assert [r.chunk_id for r in results] == ["c-high", "c-mid", "c-low"]

    def test_relevance_score_is_sigmoid_normalized_into_zero_one(self):
        model = FakeCrossEncoderModel({"a": 10.0, "b": -10.0})
        candidates = [_result("a", "a"), _result("b", "b")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=2)

        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0
        assert dict((r.chunk_id, r.relevance_score) for r in results)["a"] > 0.99
        assert dict((r.chunk_id, r.relevance_score) for r in results)["b"] < 0.01

    def test_deterministic_tie_break_by_chunk_id_ascending(self):
        model = FakeCrossEncoderModel({}, default=0.0)  # every candidate ties
        candidates = [_result("c-zebra", "x"), _result("c-alpha", "y"), _result("c-mike", "z")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=3)

        assert [r.chunk_id for r in results] == ["c-alpha", "c-mike", "c-zebra"]

    def test_same_input_produces_same_output_every_call(self):
        model = FakeCrossEncoderModel({"x": 1.0, "y": 2.0, "z": 0.5})
        candidates = [_result("cx", "x"), _result("cy", "y"), _result("cz", "z")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        first = reranker.rerank("q", candidates, top_k=3)
        second = reranker.rerank("q", candidates, top_k=3)

        assert [r.chunk_id for r in first] == [r.chunk_id for r in second]
        assert [r.relevance_score for r in first] == [r.relevance_score for r in second]


class TestCandidatePoolEdgeCases:
    def test_empty_candidates_returns_empty_list_without_calling_the_model(self):
        model = FakeCrossEncoderModel({})
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", [], top_k=5)

        assert results == []
        assert model.calls == []

    def test_fewer_candidates_than_top_k_returns_all_of_them_ranked(self):
        model = FakeCrossEncoderModel({"a": 1.0, "b": 3.0})
        candidates = [_result("a", "a"), _result("b", "b")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=10)

        assert len(results) == 2
        assert results[0].chunk_id == "b"

    def test_top_k_truncates_to_the_requested_size(self):
        model = FakeCrossEncoderModel({"a": 3.0, "b": 2.0, "c": 1.0})
        candidates = [_result("a", "a"), _result("b", "b"), _result("c", "c")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=2)

        assert [r.chunk_id for r in results] == ["a", "b"]

    def test_duplicate_chunk_ids_are_preserved_not_silently_dropped(self):
        """Deduplication is not this class's job (Task 7: ranking is a
        separate layer from evidence selection/dedup) -- it must not
        silently drop what it was given."""

        model = FakeCrossEncoderModel({}, default=0.0)
        candidates = [_result("dup", "first copy"), _result("dup", "second copy")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=2)

        assert len(results) == 2
        assert {r.text for r in results} == {"first copy", "second copy"}


class TestEvidenceIntegrity:
    """Task 5: the reranker must improve ordering, never manufacture,
    duplicate-invent, or mutate evidence."""

    def test_never_returns_a_chunk_id_not_present_in_the_input(self):
        model = FakeCrossEncoderModel({"a": 1.0, "b": 2.0})
        candidates = [_result("a", "a"), _result("b", "b")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=5)

        assert {r.chunk_id for r in results} <= {"a", "b"}

    def test_text_is_never_modified(self):
        original_text = "the exact original chunk text, untouched"
        model = FakeCrossEncoderModel({original_text: 5.0})
        candidates = [_result("c1", original_text)]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=1)

        assert results[0].text == original_text

    def test_metadata_is_preserved_unchanged(self):
        metadata = {"document_id": "doc-1", "workspace_id": "ws-1", "ingestion_generation": 3, "page_number": 12}
        model = FakeCrossEncoderModel({"text": 1.0})
        candidates = [_result("c1", "text", metadata=metadata)]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=1)

        assert results[0].metadata == metadata

    def test_result_count_never_exceeds_input_count(self):
        model = FakeCrossEncoderModel({"a": 1.0})
        candidates = [_result("a", "a")]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("q", candidates, top_k=100)

        assert len(results) == 1


class TestMultilingualText:
    """Task 6: the reranker's interface must operate on arbitrary text
    with no language-specific branching -- verified here with genuinely
    multilingual (English + Devanagari) fixtures, generic/subject-neutral
    content only.
    """

    def test_handles_devanagari_query_and_candidates_without_error(self):
        hindi_relevant = "यह एक उदाहरण वाक्य है जो प्रासंगिक जानकारी देता है।"
        hindi_irrelevant = "यह पूरी तरह से असंबंधित विषय के बारे में है।"
        model = FakeCrossEncoderModel({hindi_relevant: 3.0, hindi_irrelevant: -3.0})
        candidates = [_result("hi-1", hindi_relevant), _result("hi-2", hindi_irrelevant)]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("यह किस बारे में है?", candidates, top_k=2)

        assert [r.chunk_id for r in results] == ["hi-1", "hi-2"]

    def test_handles_mixed_english_and_hindi_candidates_in_one_call(self):
        english_text = "This is generic English content about topic A."
        hindi_text = "यह विषय के बारे में सामान्य हिंदी सामग्री है।"
        model = FakeCrossEncoderModel({english_text: 2.0, hindi_text: 5.0})
        candidates = [_result("en", english_text), _result("hi", hindi_text)]
        reranker = CrossEncoderReranker(settings=_settings(), model=model)

        results = reranker.rerank("topic A", candidates, top_k=2)

        assert [r.chunk_id for r in results] == ["hi", "en"]
        query_used = model.calls[0][0][0]
        assert query_used == "topic A"


class TestFailureHandling:
    """Task 9's fallback policy lives in HybridRetriever (see
    test_hybrid_retriever.py); this class only verifies the reranker
    itself fails LOUDLY (never silently) so that caller can implement
    that policy at all.
    """

    def test_model_predict_exception_raises_reranker_unavailable_error(self):
        reranker = CrossEncoderReranker(settings=_settings(), model=RaisingCrossEncoderModel())

        with pytest.raises(RerankerUnavailableError):
            reranker.rerank("q", [_result("a", "a")], top_k=1)

    def test_reranker_unavailable_error_message_names_the_model(self):
        reranker = CrossEncoderReranker(
            settings=_settings(reranker_model_name="some/specific-model"), model=RaisingCrossEncoderModel()
        )

        with pytest.raises(RerankerUnavailableError, match="some/specific-model"):
            reranker.rerank("q", [_result("a", "a")], top_k=1)

    def test_does_not_raise_for_empty_candidates_even_with_a_failing_model(self):
        reranker = CrossEncoderReranker(settings=_settings(), model=RaisingCrossEncoderModel())

        assert reranker.rerank("q", [], top_k=5) == []


class TestSigmoidHelper:
    def test_sigmoid_of_zero_is_one_half(self):
        assert _sigmoid(0.0) == pytest.approx(0.5)

    def test_sigmoid_is_bounded_in_unit_interval_for_extreme_inputs(self):
        assert 0.0 < _sigmoid(50.0) <= 1.0
        assert 0.0 <= _sigmoid(-50.0) < 1.0

    def test_sigmoid_is_monotonically_increasing(self):
        assert _sigmoid(-1.0) < _sigmoid(0.0) < _sigmoid(1.0)
