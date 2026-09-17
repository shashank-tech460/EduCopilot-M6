"""Task 7.2 -- official response-assembly correctness properties.

    P9  Source_Attribution validity
    P10 Source_Attribution ordering
    P11 Source-type metadata
    P12 Source_Attribution deduplication
    P15 Response JSON schema completeness

These test BEHAVIOR through `assemble_query_response()` (the actual
public assembly function), using independently-derived oracles and
Hypothesis-generated inputs -- never by importing
`_sort_and_deduplicate`/`_deduplication_key` to compute an "expected"
value (that would just prove the implementation agrees with itself).

P16 (RetrievalConfig validation) and P17 (config override isolation) are
NOT in this file -- they concern `RAGService`/`RetrievalConfig`
behavior, not response assembly, and live in
`tests/test_rag_service_properties.py`.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.models.query import QueryResponse, SourceAttribution
from app.models.retrieval import RetrievalResult
from app.services.rag_service import RAGServiceResult
from app.services.response_assembly import assemble_query_response, to_source_attribution

_HYP = hyp_settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])

# ---------------------------------------------------------------------------
# Shared Hypothesis strategies
# ---------------------------------------------------------------------------

_chunk_id = st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8)
_document_id = st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=8)
_relevance_score = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_page_number = st.integers(min_value=1, max_value=1000)
_timestamp = st.floats(min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False)


def _pdf_result(chunk_id: str, document_id: str, score: float, page_number: int) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        relevance_score=score,
        metadata={
            "document_id": document_id,
            "document_title": f"{document_id}.pdf",
            "source_type": "document",
            "page_number": page_number,
            "section_heading": "Intro",
        },
    )


def _video_result(chunk_id: str, document_id: str, score: float, start: float, end: float) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        relevance_score=score,
        metadata={
            "document_id": document_id,
            "document_title": f"video {document_id}",
            "source_type": "video",
            "start_timestamp": start,
            "end_timestamp": end,
        },
    )


def _rag_result(results: list[RetrievalResult]) -> RAGServiceResult:
    return RAGServiceResult(
        answer="an answer",
        session_id="s1",
        retrieval_results=results,
        retrieval_metadata={"chunks_retrieved": len(results), "search_mode": "hybrid"},
    )


# ===========================================================================
# P9: Source_Attribution validity
#
# "For any Context_Chunk returned by the Hybrid_Retriever, the
#  Source_Attribution assembled from it SHALL be valid and its fields
#  SHALL correspond exactly to that chunk's metadata." (Validates
#  Requirements 3.3, 6.1)
# ===========================================================================


class TestPropertyNineAttributionValidity:
    @_HYP
    @given(
        chunk_id=_chunk_id,
        document_id=_document_id,
        score=_relevance_score,
        page_number=_page_number,
    )
    def test_pdf_attribution_fields_correspond_to_source_metadata(
        self, chunk_id: str, document_id: str, score: float, page_number: int
    ) -> None:
        result = _pdf_result(chunk_id, document_id, score, page_number)

        attribution = to_source_attribution(result)

        assert isinstance(attribution, SourceAttribution)
        assert attribution.chunk_id == chunk_id  # from the RetrievalResult itself, not its metadata
        assert attribution.relevance_score == score
        assert attribution.document_id == document_id
        assert attribution.document_title == f"{document_id}.pdf"
        assert attribution.page_number == page_number

    @_HYP
    @given(
        chunk_id=_chunk_id,
        document_id=_document_id,
        score=_relevance_score,
        start=_timestamp,
        duration=st.floats(min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False),
    )
    def test_video_attribution_fields_correspond_to_source_metadata(
        self, chunk_id: str, document_id: str, score: float, start: float, duration: float
    ) -> None:
        end = start + duration
        result = _video_result(chunk_id, document_id, score, start, end)

        attribution = to_source_attribution(result)

        assert attribution.chunk_id == chunk_id
        assert attribution.relevance_score == score
        assert attribution.document_id == document_id
        assert attribution.start_timestamp == start
        assert attribution.end_timestamp == end

    @_HYP
    @given(
        results=st.lists(
            st.tuples(_chunk_id, _document_id, _relevance_score, _page_number),
            min_size=0,
            max_size=10,
            unique_by=lambda t: t[0],
        )
    )
    def test_every_assembled_attribution_is_a_valid_pydantic_instance(
        self, results: list[tuple[str, str, float, int]]
    ) -> None:
        retrieval_results = [_pdf_result(cid, did, score, page) for cid, did, score, page in results]

        response = assemble_query_response(_rag_result(retrieval_results))

        for attribution in response.source_attributions:
            # Re-validating through Pydantic's own model_validate proves
            # each attribution is genuinely well-formed per the official
            # model, not just a Python object that happens to have the
            # right attribute names.
            SourceAttribution.model_validate(attribution.model_dump())

    def test_missing_required_metadata_fails_clearly_not_silently(self) -> None:
        result = RetrievalResult(chunk_id="c1", text="t", relevance_score=0.5, metadata={})

        with pytest.raises(ValueError):
            to_source_attribution(result)


# ===========================================================================
# P10: Source_Attribution ordering
#
# "For any set of retrieved Context_Chunks, the resulting
#  Source_Attribution list SHALL be ordered by relevance_score in
#  non-increasing order, deterministically." (Validates Requirement 6.2)
# ===========================================================================


class TestPropertyTenOrdering:
    @_HYP
    @given(
        scored_ids=st.lists(st.tuples(_chunk_id, _relevance_score), min_size=0, max_size=15, unique_by=lambda t: t[0])
    )
    def test_output_scores_are_non_increasing(self, scored_ids: list[tuple[str, float]]) -> None:
        results = [_pdf_result(cid, f"doc-{i}", score, i + 1) for i, (cid, score) in enumerate(scored_ids)]

        response = assemble_query_response(_rag_result(results))

        scores = [a.relevance_score for a in response.source_attributions]
        assert scores == sorted(scores, reverse=True)

    @_HYP
    @given(
        scored_ids=st.lists(st.tuples(_chunk_id, _relevance_score), min_size=1, max_size=15, unique_by=lambda t: t[0])
    )
    def test_ordering_is_deterministic_across_repeated_assembly(self, scored_ids: list[tuple[str, float]]) -> None:
        results = [_pdf_result(cid, f"doc-{i}", score, i + 1) for i, (cid, score) in enumerate(scored_ids)]

        first = assemble_query_response(_rag_result(results))
        second = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in first.source_attributions] == [a.chunk_id for a in second.source_attributions]

    def test_empty_results(self) -> None:
        response = assemble_query_response(_rag_result([]))
        assert response.source_attributions == []

    def test_single_result(self) -> None:
        response = assemble_query_response(_rag_result([_pdf_result("c1", "doc1", 0.5, 1)]))
        assert len(response.source_attributions) == 1

    def test_already_ascending_input_gets_reordered_descending(self) -> None:
        results = [_pdf_result("a", "d1", 0.1, 1), _pdf_result("b", "d2", 0.5, 2), _pdf_result("c", "d3", 0.9, 3)]

        response = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in response.source_attributions] == ["c", "b", "a"]

    def test_already_descending_input_stays_descending(self) -> None:
        results = [_pdf_result("a", "d1", 0.9, 1), _pdf_result("b", "d2", 0.5, 2), _pdf_result("c", "d3", 0.1, 3)]

        response = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in response.source_attributions] == ["a", "b", "c"]

    @_HYP
    @given(
        score=_relevance_score,
        chunk_ids=st.lists(_chunk_id, min_size=2, max_size=8, unique=True),
    )
    def test_equal_scores_broken_deterministically_by_chunk_id_ascending(
        self, score: float, chunk_ids: list[str]
    ) -> None:
        results = [_pdf_result(cid, f"doc-{i}", score, i + 1) for i, cid in enumerate(chunk_ids)]

        response = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in response.source_attributions] == sorted(chunk_ids)


# ===========================================================================
# P11: Source-type metadata
#
# "Document-sourced attributions SHALL carry page_number/section_heading
#  and never carry timestamp fields; video-sourced attributions SHALL
#  carry start_timestamp/end_timestamp and never carry page_number."
#  (Validates Requirements 6.3, 6.4)
# ===========================================================================


class TestPropertyElevenSourceTypeMetadata:
    @_HYP
    @given(chunk_id=_chunk_id, document_id=_document_id, score=_relevance_score, page_number=_page_number)
    def test_document_attribution_never_carries_timestamp_fields(
        self, chunk_id: str, document_id: str, score: float, page_number: int
    ) -> None:
        result = _pdf_result(chunk_id, document_id, score, page_number)

        attribution = to_source_attribution(result)

        assert attribution.start_timestamp is None
        assert attribution.end_timestamp is None

    @_HYP
    @given(chunk_id=_chunk_id, document_id=_document_id, score=_relevance_score, start=_timestamp)
    def test_video_attribution_never_carries_page_number_or_section_heading(
        self, chunk_id: str, document_id: str, score: float, start: float
    ) -> None:
        result = _video_result(chunk_id, document_id, score, start, start + 5.0)

        attribution = to_source_attribution(result)

        assert attribution.page_number is None
        assert attribution.section_heading is None

    def test_missing_optional_document_metadata_maps_to_none(self) -> None:
        result = RetrievalResult(
            chunk_id="c1",
            text="t",
            relevance_score=0.5,
            metadata={"document_id": "d1", "document_title": "t.pdf"},  # no page_number/section_heading at all
        )

        attribution = to_source_attribution(result)

        assert attribution.page_number is None
        assert attribution.section_heading is None

    def test_missing_optional_video_metadata_maps_to_none(self) -> None:
        result = RetrievalResult(
            chunk_id="c1",
            text="t",
            relevance_score=0.5,
            metadata={"document_id": "d1", "document_title": "video"},  # no timestamps at all
        )

        attribution = to_source_attribution(result)

        assert attribution.start_timestamp is None
        assert attribution.end_timestamp is None

    @_HYP
    @given(
        pdf_results=st.lists(
            st.tuples(_chunk_id, _document_id, _relevance_score, _page_number),
            min_size=1,
            max_size=5,
            unique_by=lambda t: t[0],
        ),
        video_results=st.lists(
            st.tuples(_chunk_id, _document_id, _relevance_score, _timestamp),
            min_size=1,
            max_size=5,
            unique_by=lambda t: t[0],
        ),
    )
    def test_mixed_batch_keeps_each_sources_metadata_separate(
        self,
        pdf_results: list[tuple[str, str, float, int]],
        video_results: list[tuple[str, str, float, float]],
    ) -> None:
        all_pdf_chunk_ids = {cid for cid, *_ in pdf_results}
        video_results = [(cid, did, score, ts) for cid, did, score, ts in video_results if cid not in all_pdf_chunk_ids]

        retrieval_results = [_pdf_result(cid, did, score, page) for cid, did, score, page in pdf_results]
        retrieval_results += [_video_result(cid, did, score, ts, ts + 1.0) for cid, did, score, ts in video_results]

        response = assemble_query_response(_rag_result(retrieval_results))

        pdf_chunk_ids = {cid for cid, *_ in pdf_results}
        video_chunk_ids = {cid for cid, *_ in video_results}

        for attribution in response.source_attributions:
            if attribution.chunk_id in pdf_chunk_ids:
                assert attribution.start_timestamp is None
                assert attribution.end_timestamp is None
            elif attribution.chunk_id in video_chunk_ids:
                assert attribution.page_number is None


# ===========================================================================
# P12: Source_Attribution deduplication
#
# "Source_Attributions referring to the same document+page (documents)
#  or the same document+timestamp-range (video) SHALL be deduplicated to
#  a single entry; distinct sources SHALL be preserved." (Validates
#  Requirement 6.5)
# ===========================================================================


class TestPropertyTwelveDeduplication:
    @_HYP
    @given(
        document_id=_document_id,
        page_number=_page_number,
        duplicate_count=st.integers(min_value=2, max_value=6),
        scores=st.lists(_relevance_score, min_size=2, max_size=6),
    )
    def test_identical_document_and_page_collapses_to_one(
        self, document_id: str, page_number: int, duplicate_count: int, scores: list[float]
    ) -> None:
        scores = (scores * duplicate_count)[:duplicate_count]  # ensure enough scores
        results = [_pdf_result(f"c{i}", document_id, scores[i], page_number) for i in range(duplicate_count)]

        response = assemble_query_response(_rag_result(results))

        matching = [
            a for a in response.source_attributions if a.document_id == document_id and a.page_number == page_number
        ]
        assert len(matching) == 1

    @_HYP
    @given(
        document_id=_document_id,
        start=_timestamp,
        end=_timestamp,
        duplicate_count=st.integers(min_value=2, max_value=6),
    )
    def test_identical_video_timestamp_range_collapses_to_one(
        self, document_id: str, start: float, end: float, duplicate_count: int
    ) -> None:
        results = [_video_result(f"v{i}", document_id, 0.5, start, end) for i in range(duplicate_count)]

        response = assemble_query_response(_rag_result(results))

        matching = [a for a in response.source_attributions if a.document_id == document_id]
        assert len(matching) == 1

    @_HYP
    @given(
        document_id=_document_id,
        pages=st.lists(_page_number, min_size=2, max_size=8, unique=True),
    )
    def test_distinct_pages_of_same_document_all_survive(self, document_id: str, pages: list[int]) -> None:
        results = [_pdf_result(f"c{i}", document_id, 0.5, page) for i, page in enumerate(pages)]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == len(pages)

    def test_same_document_different_pages_not_deduplicated(self) -> None:
        results = [_pdf_result("c1", "d1", 0.9, 1), _pdf_result("c2", "d1", 0.5, 2)]
        response = assemble_query_response(_rag_result(results))
        assert len(response.source_attributions) == 2

    def test_same_video_different_ranges_not_deduplicated(self) -> None:
        results = [_video_result("v1", "d1", 0.9, 10.0, 20.0), _video_result("v2", "d1", 0.5, 30.0, 40.0)]
        response = assemble_query_response(_rag_result(results))
        assert len(response.source_attributions) == 2

    def test_same_source_different_chunk_ids_still_deduplicates(self) -> None:
        # Explicit anti-"dedup by chunk_id" guard: two DIFFERENT
        # chunk_ids pointing at the same document+page must still
        # collapse to one attribution.
        results = [_pdf_result("chunk-x", "d1", 0.9, 1), _pdf_result("chunk-y", "d1", 0.4, 1)]
        response = assemble_query_response(_rag_result(results))
        assert len(response.source_attributions) == 1

    def test_mixed_pdf_and_video_sources_with_duplicates_in_each(self) -> None:
        results = [
            _pdf_result("c1", "d1", 0.9, 1),
            _pdf_result("c2", "d1", 0.3, 1),  # dup of c1
            _pdf_result("c3", "d1", 0.5, 2),  # distinct page
            _video_result("v1", "d2", 0.8, 10.0, 20.0),
            _video_result("v2", "d2", 0.2, 10.0, 20.0),  # dup of v1
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 3  # c1(kept), c3, v1(kept)

    def test_repeated_duplicates_collapse_to_exactly_one(self) -> None:
        results = [_pdf_result(f"c{i}", "d1", 0.1 * i, 1) for i in range(10)]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 1

    def test_highest_relevance_duplicate_is_the_one_kept(self) -> None:
        results = [
            _pdf_result("low", "d1", 0.1, 1),
            _pdf_result("high", "d1", 0.9, 1),
            _pdf_result("mid", "d1", 0.5, 1),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 1
        assert response.source_attributions[0].chunk_id == "high"


# ===========================================================================
# P15: Response JSON schema completeness
#
# "The final QueryResponse SHALL contain exactly answer, session_id,
#  source_attributions, and retrieval_metadata, and SHALL validate
#  against the official QueryResponse model." (Validates Requirement 4.7)
# ===========================================================================


class TestPropertyFifteenResponseSchema:
    @_HYP
    @given(
        answer=st.text(min_size=0, max_size=200),
        session_id=st.text(alphabet=st.characters(min_codepoint=97, max_codepoint=122), min_size=1, max_size=20),
        results=st.lists(
            st.tuples(_chunk_id, _document_id, _relevance_score, _page_number),
            min_size=0,
            max_size=8,
            unique_by=lambda t: t[0],
        ),
    )
    def test_response_always_validates_against_the_official_model(
        self, answer: str, session_id: str, results: list[tuple[str, str, float, int]]
    ) -> None:
        retrieval_results = [_pdf_result(cid, did, score, page) for cid, did, score, page in results]
        rag_result = RAGServiceResult(
            answer=answer,
            session_id=session_id,
            retrieval_results=retrieval_results,
            retrieval_metadata={"chunks_retrieved": len(retrieval_results)},
        )

        response = assemble_query_response(rag_result)

        # Re-validate through Pydantic's own model_validate_json (a full
        # serialize-then-revalidate round trip), not just isinstance.
        revalidated = QueryResponse.model_validate_json(response.model_dump_json())
        assert revalidated.answer == answer
        assert revalidated.session_id == session_id

    def test_no_unexpected_public_fields_are_introduced(self) -> None:
        response = assemble_query_response(_rag_result([_pdf_result("c1", "d1", 0.5, 1)]))

        assert set(response.model_dump().keys()) == {"answer", "session_id", "source_attributions", "retrieval_metadata"}

    def test_source_attributions_field_is_a_list_of_valid_source_attribution_dicts(self) -> None:
        response = assemble_query_response(
            _rag_result([_pdf_result("c1", "d1", 0.5, 1), _video_result("v1", "d2", 0.4, 1.0, 2.0)])
        )

        serialized = response.model_dump()
        for raw_attribution in serialized["source_attributions"]:
            SourceAttribution.model_validate(raw_attribution)

    def test_empty_source_attributions_still_produces_a_valid_response(self) -> None:
        response = assemble_query_response(_rag_result([]))

        revalidated = QueryResponse.model_validate_json(response.model_dump_json())
        assert revalidated.source_attributions == []
