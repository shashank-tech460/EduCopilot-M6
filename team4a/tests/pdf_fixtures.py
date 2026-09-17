"""Locally-generated PDF fixtures for Task 2.1 tests.

All fixtures are built at test time with PyMuPDF itself -- no binary PDF
files are committed to the repo, and no network access is required.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf as fitz


def make_simple_text_pdf(path: Path, pages: list[str]) -> Path:
    """One page per string in `pages`, each with a single line of body text."""

    doc = fitz.open()
    for text in pages:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def make_heading_pdf(path: Path) -> Path:
    """A page with a large-font heading followed by two smaller body lines."""

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One: Introduction", fontsize=22)
    page.insert_text((72, 110), "This is the first line of body text.", fontsize=12)
    page.insert_text((72, 130), "This is the second line of body text.", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def make_multi_level_heading_pdf(path: Path) -> Path:
    """A page with two distinct heading sizes (level 1 and level 2) plus body text."""

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 60), "Main Title", fontsize=24)
    page.insert_text((72, 100), "Subsection A", fontsize=16)
    page.insert_text((72, 130), "Body text explaining subsection A in detail here.", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path


def make_image_only_pdf(path: Path) -> Path:
    """A single page containing only an inserted image, no text."""

    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(pix.irect, (200, 30, 30))
    page.insert_image(fitz.Rect(72, 72, 172, 172), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return path


def make_mixed_text_and_image_pdf(path: Path) -> Path:
    """Page 1: text only. Page 2: image only. Page 3: text only."""

    doc = fitz.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "First page has text.", fontsize=12)

    page2 = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(pix.irect, (30, 200, 30))
    page2.insert_image(fitz.Rect(72, 72, 172, 172), pixmap=pix)

    page3 = doc.new_page()
    page3.insert_text((72, 72), "Third page has text.", fontsize=12)

    doc.save(str(path))
    doc.close()
    return path


def make_blank_page_pdf(path: Path) -> Path:
    """A single, entirely blank page: no text, no images."""

    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def make_encrypted_pdf(path: Path, owner_pw: str = "owner-pw", user_pw: str = "user-pw") -> Path:
    """A password-protected PDF that cannot be opened without a password."""

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "secret content", fontsize=12)
    doc.save(
        str(path),
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw=owner_pw,
        user_pw=user_pw,
        permissions=int(fitz.PDF_PERM_ACCESSIBILITY),
    )
    doc.close()
    return path


def make_corrupt_pdf(path: Path) -> Path:
    """A file with a .pdf extension that is not valid PDF data at all."""

    path.write_bytes(b"This is not a real PDF file, just plain text bytes.")
    return path


def make_multi_page_pdf(path: Path, page_count: int) -> Path:
    """`page_count` pages, each labeled with its own 1-indexed page number."""

    doc = fitz.open()
    for i in range(1, page_count + 1):
        page = doc.new_page()
        page.insert_text((72, 72), f"This is page number {i}.", fontsize=12)
    doc.save(str(path))
    doc.close()
    return path
