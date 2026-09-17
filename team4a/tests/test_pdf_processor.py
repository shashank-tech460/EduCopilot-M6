"""Unit tests for Task 2.1: PDFProcessor.

All PDF fixtures are generated locally with PyMuPDF (see pdf_fixtures.py) --
no binary files are committed and no network access is required.
"""

from types import SimpleNamespace

import pytest

from app.models.exceptions import PDFTooLargeError, PDFTooManyPagesError, PDFUnreadableError
from app.models.schemas import PDFSegment
from app.processors.pdf_processor import PDFProcessor
from tests.pdf_fixtures import (
    make_blank_page_pdf,
    make_corrupt_pdf,
    make_encrypted_pdf,
    make_heading_pdf,
    make_image_only_pdf,
    make_mixed_text_and_image_pdf,
    make_multi_level_heading_pdf,
    make_multi_page_pdf,
    make_simple_text_pdf,
)


@pytest.fixture
def processor() -> PDFProcessor:
    return PDFProcessor()


# ---------------------------------------------------------------------------
# 1-2. Basic extraction / multiple pages
# ---------------------------------------------------------------------------


def test_basic_text_extraction(processor, tmp_path):
    path = make_simple_text_pdf(tmp_path / "simple.pdf", ["Hello, this is a test document."])

    segments = processor.process(path)

    assert len(segments) == 1
    assert isinstance(segments[0], PDFSegment)
    assert "Hello, this is a test document." in segments[0].text


def test_multiple_pages_extracted(processor, tmp_path):
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=4)

    segments = processor.process(path)

    assert len(segments) == 4


# ---------------------------------------------------------------------------
# 3-4. Page numbering / page association
# ---------------------------------------------------------------------------


def test_page_numbers_are_one_indexed(processor, tmp_path):
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=3)

    segments = processor.process(path)

    assert [s.page_number for s in segments] == [1, 2, 3]


def test_text_stays_associated_with_correct_page(processor, tmp_path):
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=3)

    segments = processor.process(path)

    for segment in segments:
        assert f"page number {segment.page_number}" in segment.text


# ---------------------------------------------------------------------------
# 5. Reading order
# ---------------------------------------------------------------------------


def test_reading_order_preserved_top_to_bottom(processor, tmp_path):
    path = make_heading_pdf(tmp_path / "heading.pdf")

    segments = processor.process(path)

    text = segments[0].text
    heading_pos = text.find("Chapter One: Introduction")
    first_line_pos = text.find("This is the first line of body text.")
    second_line_pos = text.find("This is the second line of body text.")

    assert heading_pos != -1
    assert first_line_pos != -1
    assert second_line_pos != -1
    assert heading_pos < first_line_pos < second_line_pos


# ---------------------------------------------------------------------------
# 6-7. Heading detection / heading level
# ---------------------------------------------------------------------------


def test_heading_detected_with_larger_font(processor, tmp_path):
    path = make_heading_pdf(tmp_path / "heading.pdf")

    segments = processor.process(path)

    heading_texts = [h.text for h in segments[0].headings]
    assert "Chapter One: Introduction" in heading_texts
    assert "This is the first line of body text." not in heading_texts


def test_heading_levels_assigned_by_relative_font_size(processor, tmp_path):
    path = make_multi_level_heading_pdf(tmp_path / "levels.pdf")

    segments = processor.process(path)
    headings = {h.text: h.level for h in segments[0].headings}

    assert headings.get("Main Title") == 1
    assert headings.get("Subsection A") == 2
    assert all(level >= 1 for level in headings.values())


def test_no_headings_fabricated_for_uniform_font_document(processor, tmp_path):
    path = make_simple_text_pdf(tmp_path / "uniform.pdf", ["Just one plain line of body text."])

    segments = processor.process(path)

    assert segments[0].headings == []


# ---------------------------------------------------------------------------
# 8. Image-only pages
# ---------------------------------------------------------------------------


def test_image_only_page_marked_and_has_empty_text(processor, tmp_path):
    path = make_image_only_pdf(tmp_path / "image_only.pdf")

    segments = processor.process(path)

    assert len(segments) == 1
    assert segments[0].is_image_only is True
    assert segments[0].text == ""


def test_image_only_page_does_not_make_whole_document_unreadable(processor, tmp_path):
    path = make_mixed_text_and_image_pdf(tmp_path / "mixed.pdf")

    segments = processor.process(path)

    assert len(segments) == 3
    assert segments[0].is_image_only is False
    assert "First page has text." in segments[0].text
    assert segments[1].is_image_only is True
    assert segments[1].text == ""
    assert segments[2].is_image_only is False
    assert "Third page has text." in segments[2].text


def test_blank_page_is_not_marked_image_only(processor, tmp_path):
    path = make_blank_page_pdf(tmp_path / "blank.pdf")

    segments = processor.process(path)

    assert segments[0].is_image_only is False
    assert segments[0].text == ""


# ---------------------------------------------------------------------------
# 9-10. Corrupt / password-protected PDFs
# ---------------------------------------------------------------------------


def test_corrupt_pdf_raises_pdf_unreadable_error(processor, tmp_path):
    path = make_corrupt_pdf(tmp_path / "corrupt.pdf")

    with pytest.raises(PDFUnreadableError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "PDFUnreadable"


def test_password_protected_pdf_raises_pdf_unreadable_error(processor, tmp_path):
    path = make_encrypted_pdf(tmp_path / "encrypted.pdf")

    with pytest.raises(PDFUnreadableError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "PDFUnreadable"


def test_unreadable_pdf_error_message_does_not_leak_raw_bytes(processor, tmp_path):
    path = make_corrupt_pdf(tmp_path / "corrupt.pdf")

    with pytest.raises(PDFUnreadableError) as exc_info:
        processor.process(path)

    assert "This is not a real PDF file" not in exc_info.value.message


# ---------------------------------------------------------------------------
# 11-12. Size / page limits
# ---------------------------------------------------------------------------


def test_oversized_pdf_is_rejected_not_as_unreadable(tmp_path):
    tiny_limit_settings = SimpleNamespace(pdf_max_size_mb=0, pdf_max_pages=5000)
    processor = PDFProcessor(settings=tiny_limit_settings)
    path = make_simple_text_pdf(tmp_path / "simple.pdf", ["hello"])

    with pytest.raises(PDFTooLargeError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "PDFTooLarge"
    assert not isinstance(exc_info.value, PDFUnreadableError)


def test_pdf_exceeding_page_limit_is_rejected(tmp_path):
    small_page_limit_settings = SimpleNamespace(pdf_max_size_mb=200, pdf_max_pages=3)
    processor = PDFProcessor(settings=small_page_limit_settings)
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=5)

    with pytest.raises(PDFTooManyPagesError) as exc_info:
        processor.process(path)

    assert exc_info.value.status_code == "PDFTooManyPages"
    assert exc_info.value.detail["actual_pages"] == 5
    assert exc_info.value.detail["max_pages"] == 3


def test_page_limit_rejection_does_not_partially_process(tmp_path):
    small_page_limit_settings = SimpleNamespace(pdf_max_size_mb=200, pdf_max_pages=2)
    processor = PDFProcessor(settings=small_page_limit_settings)
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=3)

    with pytest.raises(PDFTooManyPagesError):
        processor.process(path)


def test_pdf_within_limits_is_accepted(tmp_path):
    settings = SimpleNamespace(pdf_max_size_mb=200, pdf_max_pages=5000)
    processor = PDFProcessor(settings=settings)
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=3)

    segments = processor.process(path)

    assert len(segments) == 3


def test_default_page_limit_of_5000_is_enforced(tmp_path):
    # Exercises the *actual configured default* (not an injected stub) to
    # directly confirm the official 5000-page limit, per Requirement 1.6.
    # Generating 5001 real pages is slow (a few seconds) but worth it for
    # genuine coverage of the default rather than only a stubbed-down limit.
    path = make_multi_page_pdf(tmp_path / "huge.pdf", page_count=5001)
    processor = PDFProcessor()

    with pytest.raises(PDFTooManyPagesError) as exc_info:
        processor.process(path)

    assert exc_info.value.detail["max_pages"] == 5000
    assert exc_info.value.detail["actual_pages"] == 5001


def test_uses_configured_settings_not_hardcoded_defaults():
    from app.config.settings import get_settings

    settings = get_settings()
    processor = PDFProcessor()
    assert processor._settings.pdf_max_size_mb == settings.pdf_max_size_mb
    assert processor._settings.pdf_max_pages == settings.pdf_max_pages


# ---------------------------------------------------------------------------
# 13. Minimal/empty valid PDF
# ---------------------------------------------------------------------------


def test_minimal_blank_pdf_processes_without_error(processor, tmp_path):
    path = make_blank_page_pdf(tmp_path / "blank.pdf")

    segments = processor.process(path)

    assert len(segments) == 1
    assert segments[0].page_number == 1
    assert segments[0].text == ""
    assert segments[0].headings == []
    assert segments[0].is_image_only is False


# ---------------------------------------------------------------------------
# 14. Output matches the existing PDFSegment contract
# ---------------------------------------------------------------------------


def test_output_is_list_of_pdf_segment_instances(processor, tmp_path):
    path = make_multi_page_pdf(tmp_path / "multi.pdf", page_count=2)

    segments = processor.process(path)

    assert isinstance(segments, list)
    for segment in segments:
        assert isinstance(segment, PDFSegment)
        payload = segment.model_dump()
        assert set(payload.keys()) == {"text", "page_number", "headings", "is_image_only"}


# ---------------------------------------------------------------------------
# File-like input (for later Task 10.1 API integration)
# ---------------------------------------------------------------------------


def test_accepts_seekable_file_like_object(processor, tmp_path):
    path = make_simple_text_pdf(tmp_path / "simple.pdf", ["hello from a file-like object"])

    with open(path, "rb") as f:
        segments = processor.process(f)

    assert len(segments) == 1
    assert "hello from a file-like object" in segments[0].text
