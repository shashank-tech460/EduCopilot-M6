"""Focused tests for Task 7.2's response assembly.

Scope: unit tests for `to_source_attribution` and
`assemble_query_response` -- mapping, ordering, and deduplication
behavior with concrete examples. Property-based verification of
P9-P12/P15 lives in `tests/test_response_assembly_properties.py`;
P16/P17 (RetrievalConfig validation and override isolation) live in
`tests/test_rag_service_properties.py`. This file does not claim any of
those properties are complete.
"""

from __future__ import annotations

import pytest

from app.models.query import QueryResponse, SourceAttribution
from app.models.retrieval import RetrievalResult
from app.services.rag_service import RAGServiceResult
from app.services.response_assembly import assemble_query_response, to_source_attribution


def _pdf_result(
    chunk_id: str, score: float, document_id: str = "job-1", page_number: int = 1, section_heading: str | None = "Intro"
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        relevance_score=score,
        metadata={
            "document_id": document_id,
            "document_title": "notes.pdf",
            "source_type": "document",
            "page_number": page_number,
            "section_heading": section_heading,
        },
    )


def _video_result(
    chunk_id: str, score: float, document_id: str = "job-2", start_timestamp: float = 0.0, end_timestamp: float = 5.0
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        text=f"text for {chunk_id}",
        relevance_score=score,
        metadata={
            "document_id": document_id,
            "document_title": "How RAG Works",
            "source_type": "video",
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
        },
    )


def _rag_result(
    retrieval_results: list[RetrievalResult], answer: str = "the answer", session_id: str = "s1"
) -> RAGServiceResult:
    return RAGServiceResult(
        answer=answer,
        session_id=session_id,
        retrieval_results=retrieval_results,
        retrieval_metadata={"chunks_retrieved": len(retrieval_results), "search_mode": "hybrid"},
    )


# ---------------------------------------------------------------------------
# to_source_attribution: mapping
# ---------------------------------------------------------------------------


class TestToSourceAttributionMapping:
    def test_pdf_result_maps_document_fields(self):
        result = _pdf_result("c1", 0.9, page_number=7, section_heading="Setup")

        attribution = to_source_attribution(result)

        assert attribution.document_id == "job-1"
        assert attribution.document_title == "notes.pdf"
        assert attribution.chunk_id == "c1"
        assert attribution.relevance_score == 0.9
        assert attribution.page_number == 7
        assert attribution.section_heading == "Setup"
        assert attribution.start_timestamp is None
        assert attribution.end_timestamp is None

    def test_video_result_maps_timestamp_fields(self):
        result = _video_result("v1", 0.8, start_timestamp=10.0, end_timestamp=25.0)

        attribution = to_source_attribution(result)

        assert attribution.document_id == "job-2"
        assert attribution.document_title == "How RAG Works"
        assert attribution.start_timestamp == 10.0
        assert attribution.end_timestamp == 25.0
        assert attribution.page_number is None
        assert attribution.section_heading is None

    def test_missing_section_heading_maps_to_none(self):
        result = _pdf_result("c1", 0.5, section_heading=None)

        attribution = to_source_attribution(result)

        assert attribution.section_heading is None

    def test_no_metadata_fabricated_beyond_what_is_present(self):
        result = _pdf_result("c1", 0.5)

        attribution = to_source_attribution(result)

        assert isinstance(attribution, SourceAttribution)
        # exactly the official fields, nothing invented
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

    def test_missing_document_id_raises_clearly(self):
        result = RetrievalResult(chunk_id="c1", text="t", relevance_score=0.5, metadata={"document_title": "t"})

        with pytest.raises(ValueError):
            to_source_attribution(result)

    def test_missing_document_title_raises_clearly(self):
        result = RetrievalResult(chunk_id="c1", text="t", relevance_score=0.5, metadata={"document_id": "d1"})

        with pytest.raises(ValueError):
            to_source_attribution(result)


# ---------------------------------------------------------------------------
# assemble_query_response: ordering
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_results_sorted_by_relevance_score_descending(self):
        results = [
            _pdf_result("low", 0.2, page_number=1),
            _pdf_result("high", 0.9, page_number=2),
            _pdf_result("mid", 0.5, page_number=3),
        ]

        response = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in response.source_attributions] == ["high", "mid", "low"]

    def test_already_sorted_input_remains_sorted(self):
        results = [
            _pdf_result("a", 0.9, page_number=1),
            _pdf_result("b", 0.5, page_number=2),
            _pdf_result("c", 0.1, page_number=3),
        ]

        response = assemble_query_response(_rag_result(results))

        assert [a.relevance_score for a in response.source_attributions] == [0.9, 0.5, 0.1]

    def test_tied_scores_broken_deterministically_by_chunk_id(self):
        results = [_pdf_result("zebra", 0.5, page_number=1), _pdf_result("apple", 0.5, page_number=2)]

        response = assemble_query_response(_rag_result(results))

        assert [a.chunk_id for a in response.source_attributions] == ["apple", "zebra"]

    def test_empty_results_produce_empty_attributions(self):
        response = assemble_query_response(_rag_result([]))

        assert response.source_attributions == []


# ---------------------------------------------------------------------------
# assemble_query_response: deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_same_document_and_page_deduplicated(self):
        results = [
            _pdf_result("c1", 0.9, document_id="job-1", page_number=3),
            _pdf_result("c2", 0.5, document_id="job-1", page_number=3),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 1
        assert response.source_attributions[0].chunk_id == "c1"  # higher-relevance one kept

    def test_same_document_different_pages_not_deduplicated(self):
        results = [
            _pdf_result("c1", 0.9, document_id="job-1", page_number=3),
            _pdf_result("c2", 0.5, document_id="job-1", page_number=4),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 2

    def test_same_video_and_timestamp_range_deduplicated(self):
        results = [
            _video_result("v1", 0.9, document_id="job-2", start_timestamp=10.0, end_timestamp=20.0),
            _video_result("v2", 0.4, document_id="job-2", start_timestamp=10.0, end_timestamp=20.0),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 1
        assert response.source_attributions[0].chunk_id == "v1"

    def test_same_video_different_timestamp_ranges_not_deduplicated(self):
        results = [
            _video_result("v1", 0.9, document_id="job-2", start_timestamp=10.0, end_timestamp=20.0),
            _video_result("v2", 0.4, document_id="job-2", start_timestamp=30.0, end_timestamp=40.0),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 2

    def test_different_documents_same_page_number_not_deduplicated(self):
        results = [
            _pdf_result("c1", 0.9, document_id="job-1", page_number=1),
            _pdf_result("c2", 0.5, document_id="job-2", page_number=1),
        ]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 2

    def test_mixed_document_and_video_sources_not_cross_deduplicated(self):
        results = [_pdf_result("c1", 0.9, document_id="job-1", page_number=1), _video_result("v1", 0.5, document_id="job-1")]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 2

    def test_deduplication_by_chunk_id_alone_is_not_used(self):
        # Same document_id + page_number but DIFFERENT chunk_id must
        # still be deduplicated -- proving the key is not merely
        # chunk_id (which would never collide, since chunk_ids are
        # always unique).
        results = [_pdf_result("chunk-a", 0.9, page_number=5), _pdf_result("chunk-b", 0.3, page_number=5)]

        response = assemble_query_response(_rag_result(results))

        assert len(response.source_attributions) == 1


# ---------------------------------------------------------------------------
# assemble_query_response: QueryResponse assembly
# ---------------------------------------------------------------------------


class TestQueryResponseAssembly:
    def test_answer_and_session_id_pass_through(self):
        response = assemble_query_response(_rag_result([_pdf_result("c1", 0.5)], answer="42", session_id="my-session"))

        assert response.answer == "42"
        assert response.session_id == "my-session"

    def test_retrieval_metadata_passes_through_unmodified(self):
        rag_result = _rag_result([_pdf_result("c1", 0.5)])

        response = assemble_query_response(rag_result)

        assert response.retrieval_metadata == rag_result.retrieval_metadata

    def test_result_is_a_valid_query_response_instance(self):
        response = assemble_query_response(_rag_result([_pdf_result("c1", 0.5)]))

        assert isinstance(response, QueryResponse)

    def test_result_serializes_via_pydantic_without_error(self):
        response = assemble_query_response(_rag_result([_pdf_result("c1", 0.5), _video_result("v1", 0.4)]))

        serialized = response.model_dump()
        assert serialized["answer"] == response.answer
        assert len(serialized["source_attributions"]) == 2

    def test_no_unexpected_fields_in_serialized_response(self):
        response = assemble_query_response(_rag_result([_pdf_result("c1", 0.5)]))

        assert set(response.model_dump().keys()) == {"answer", "session_id", "source_attributions", "retrieval_metadata"}


class TestCanonicalDocumentIdentityInCitations:
    """MVP M3 correction, item 7: citation/source attribution receives
    the canonical document_id (Team 4C's File._id), never job_id, once
    `normalize_payload`'s upstream fix is in effect -- this test
    constructs the RetrievalResult directly with a clearly-canonical
    (non-job-id-shaped) document_id to prove the citation pipeline has
    no assumption baked in about the OLD job_id-as-document_id semantic.
    """

    def test_source_attribution_receives_the_canonical_document_id_not_job_id(self):
        result = RetrievalResult(
            chunk_id="c1",
            text="body",
            relevance_score=0.9,
            metadata={
                "document_id": "file-123",  # canonical Team 4C File._id -- NOT job-shaped
                "document_title": "notes.pdf",
                "source_type": "document",
                "page_number": 3,
            },
        )

        attribution = to_source_attribution(result)

        assert attribution.document_id == "file-123"
        assert "job" not in attribution.document_id  # never accidentally job_id-shaped
