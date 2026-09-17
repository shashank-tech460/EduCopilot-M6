"""Team 4A PDF_Processor.

Location and class name match the official design document exactly:
    "app/processors/pdf_processor.py ... class PDFProcessor"

Implements Requirements 1.1-1.6:
    1.1 Extract all text content preserving reading order and structural
        hierarchy.
    1.2 Associate each text segment with its 1-indexed source page number.
    1.3 Extract heading text and heading level as structural metadata.
    1.4 Raise PDFUnreadable for password-protected/corrupt PDFs.
    1.5 Mark image-only pages and skip text extraction for them.
    1.6 Support PDFs up to 200MB / 5000 pages; reject anything larger.

Does not implement chunking, embedding, metadata enrichment, or Qdrant
publication -- those belong to later tasks (6.1, 7.1, 8.1, 8.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, BinaryIO, Union

import pymupdf as fitz  # `import fitz` in the design doc; pymupdf is the
# current, non-deprecated import name for the same library/API (fitz is
# retained as an alias by the package itself). See Task 2.1 report.

from app.config.settings import Settings, get_settings
from app.models.exceptions import PDFTooLargeError, PDFTooManyPagesError, PDFUnreadableError
from app.models.schemas import Heading, PDFSegment

#: Accepted inputs: a filesystem path, or a seekable binary file-like object
#: (e.g. a FastAPI UploadFile's `.file`, wired up in Task 10.1).
PDFSource = Union[str, Path, BinaryIO]

#: A line's largest font size must be at least this multiple of the
#: document's body-text font size to be considered a heading candidate.
_HEADING_SIZE_RATIO = 1.15

#: Headings are short lines, not paragraphs. Longer lines at a larger font
#: size are treated as body text (e.g. an emphasized pull-quote), not a
#: heading, to keep the heuristic conservative and deterministic.
_HEADING_MAX_WORDS = 12

_BYTES_PER_MB = 1024 * 1024


class PDFProcessor:
    """Extracts page-level, structure-preserving segments from a PDF.

    Heading detection is a deterministic, PyMuPDF-layout-based heuristic
    (font size relative to the document's body-text size), not a hardcoded
    keyword list, per Task 2.1 section 8. If a PDF carries too little
    layout information to distinguish headings from body text, none are
    fabricated -- `PDFSegment.headings` is simply empty for that content.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, source: PDFSource) -> list[PDFSegment]:
        """Extract one PDFSegment per page from `source`.

        Args:
            source: A file path, or a seekable binary file-like object
                positioned anywhere (it is read from the start and restored
                afterwards).

        Raises:
            PDFTooLargeError: if the input exceeds `settings.pdf_max_size_mb`.
            PDFUnreadableError: if the PDF is corrupt/malformed, or is
                password-protected and cannot be opened as given.
            PDFTooManyPagesError: if the document exceeds
                `settings.pdf_max_pages`.
        """

        self._validate_size(source)
        doc = self._open(source)
        try:
            self._validate_not_encrypted(doc)
            self._validate_page_count(doc)
            return self._extract_segments(doc)
        finally:
            doc.close()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_size(self, source: PDFSource) -> None:
        size_bytes = self._size_of(source)
        max_bytes = self._settings.pdf_max_size_mb * _BYTES_PER_MB
        if size_bytes > max_bytes:
            raise PDFTooLargeError(
                f"PDF exceeds the maximum allowed size of {self._settings.pdf_max_size_mb}MB",
                detail={
                    "max_size_mb": self._settings.pdf_max_size_mb,
                    "actual_size_bytes": size_bytes,
                },
            )

    @staticmethod
    def _size_of(source: PDFSource) -> int:
        if isinstance(source, (str, Path)):
            return Path(source).stat().st_size

        # Seekable file-like object: measure without losing position.
        original_position = source.tell()
        source.seek(0, 2)  # SEEK_END
        size = source.tell()
        source.seek(original_position)
        return size

    def _open(self, source: PDFSource) -> "fitz.Document":
        try:
            if isinstance(source, (str, Path)):
                return fitz.open(str(source))
            source.seek(0)
            return fitz.open(stream=source.read(), filetype="pdf")
        except Exception as exc:
            # PyMuPDF raises varying exception types (e.g. FileDataError,
            # RuntimeError) for malformed/corrupt input; all are classified
            # uniformly as PDFUnreadable per Requirement 1.4. The original
            # exception is chained (`from exc`) for local debugging, but its
            # message is not echoed back -- avoids leaking raw parser
            # internals in the error surfaced to API/job-status consumers.
            raise PDFUnreadableError("Cannot open PDF file: it is malformed or corrupt") from exc

    @staticmethod
    def _validate_not_encrypted(doc: "fitz.Document") -> None:
        if doc.is_encrypted:
            raise PDFUnreadableError("PDF is password-protected and cannot be read without a password")

    def _validate_page_count(self, doc: "fitz.Document") -> None:
        if doc.page_count > self._settings.pdf_max_pages:
            raise PDFTooManyPagesError(
                f"PDF exceeds the maximum allowed page count of {self._settings.pdf_max_pages}",
                detail={
                    "max_pages": self._settings.pdf_max_pages,
                    "actual_pages": doc.page_count,
                },
            )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    def _extract_segments(self, doc: "fitz.Document") -> list[PDFSegment]:
        # Single PyMuPDF pass per page: gather body-font-size samples and
        # heading candidates together, so the document is only parsed once.
        pages_raw: list[dict[str, Any]] = []
        weighted_sizes: dict[float, int] = {}

        for page in doc:
            lines, heading_candidates, page_weighted_sizes = self._parse_page(page)
            for size, weight in page_weighted_sizes.items():
                weighted_sizes[size] = weighted_sizes.get(size, 0) + weight
            pages_raw.append(
                {
                    "lines": lines,
                    "heading_candidates": heading_candidates,
                    "has_images": len(page.get_images()) > 0,
                }
            )

        base_font_size = self._body_font_size(weighted_sizes)
        level_by_size = self._heading_levels(pages_raw, base_font_size)

        segments: list[PDFSegment] = []
        for page_number, page_data in enumerate(pages_raw, start=1):
            segments.append(
                self._build_segment(page_number, page_data, base_font_size, level_by_size)
            )
        return segments

    @staticmethod
    def _parse_page(
        page: "fitz.Page",
    ) -> tuple[list[str], list[tuple[str, float, int]], dict[float, int]]:
        """Parse one page's text in reading order.

        Returns:
            lines: page text, one entry per non-empty line, in reading order
                (blocks sorted top-to-bottom then left-to-right; PyMuPDF
                preserves left-to-right span order within a line).
            heading_candidates: (line_text, max_font_size, word_count) for
                every non-empty line, to be filtered into true headings once
                the document-wide body font size is known.
            weighted_sizes: {font_size: total_character_count}, used to
                estimate the document's body-text size (see
                `_body_font_size`).
        """

        info = page.get_text("dict")
        text_blocks = [b for b in info.get("blocks", []) if b.get("type") == 0]
        # Preserve reading order: top-to-bottom, then left-to-right, rather
        # than relying on raw block order (which is extraction order, not
        # necessarily layout order).
        text_blocks.sort(key=lambda b: (round(b["bbox"][1], 1), round(b["bbox"][0], 1)))

        lines: list[str] = []
        heading_candidates: list[tuple[str, float, int]] = []
        weighted_sizes: dict[float, int] = {}

        for block in text_blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                line_text = "".join(span.get("text", "") for span in spans).strip()
                if not line_text:
                    continue

                lines.append(line_text)
                sizes_in_line = []
                for span in spans:
                    span_text = span.get("text", "")
                    stripped = span_text.strip()
                    if not stripped:
                        continue
                    size = round(span.get("size", 0.0), 1)
                    sizes_in_line.append(size)
                    # Weight by character count, not line count: a short,
                    # large-font heading must not outvote a long paragraph
                    # of small-font body text when estimating the body size.
                    weighted_sizes[size] = weighted_sizes.get(size, 0) + len(stripped)

                max_size = max(sizes_in_line, default=0.0)
                word_count = len(line_text.split())
                heading_candidates.append((line_text, max_size, word_count))

        return lines, heading_candidates, weighted_sizes

    @staticmethod
    def _body_font_size(weighted_sizes: dict[float, int]) -> float:
        """Estimate the document's body-text font size.

        The body size is the font size with the most total characters set
        in it (character-weighted, not just "most frequent line/span"), so
        a document with a few short, large-font headings and much longer
        paragraphs of smaller body text correctly identifies the smaller
        size as the body text. Ties break on the smaller size, since body
        text is the more conservative assumption.
        """

        if not weighted_sizes:
            return 0.0
        return max(weighted_sizes.items(), key=lambda item: (item[1], -item[0]))[0]

    @classmethod
    def _heading_levels(
        cls, pages_raw: list[dict[str, Any]], base_font_size: float
    ) -> dict[float, int]:
        """Map each distinct heading font size to a 1-indexed level.

        Levels are assigned document-wide (not per page) so the same font
        size always maps to the same heading level throughout the PDF: the
        largest heading font size is level 1, the next distinct size is
        level 2, and so on.
        """

        if base_font_size <= 0:
            return {}

        heading_sizes: set[float] = set()
        for page_data in pages_raw:
            for _text, size, word_count in page_data["heading_candidates"]:
                if size >= base_font_size * _HEADING_SIZE_RATIO and word_count <= _HEADING_MAX_WORDS:
                    heading_sizes.add(size)

        return {size: level for level, size in enumerate(sorted(heading_sizes, reverse=True), start=1)}

    @staticmethod
    def _build_segment(
        page_number: int,
        page_data: dict[str, Any],
        base_font_size: float,
        level_by_size: dict[float, int],
    ) -> PDFSegment:
        text = "\n".join(page_data["lines"])
        is_image_only = len(text.strip()) == 0 and page_data["has_images"]

        headings: list[Heading] = []
        if base_font_size > 0:
            for line_text, size, word_count in page_data["heading_candidates"]:
                level = level_by_size.get(size)
                if level is not None:
                    headings.append(Heading(text=line_text, level=level))

        return PDFSegment(
            text="" if is_image_only else text,
            page_number=page_number,
            headings=headings,
            is_image_only=is_image_only,
        )
