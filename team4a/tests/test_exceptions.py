"""Unit tests for Task 1.2: Team 4A exception hierarchy."""

import pytest

from app.models.exceptions import (
    PDFUnreadableError,
    Team4AError,
    TranscriptionError,
    TranscriptUnavailableError,
    VideoInaccessibleError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnreadableError,
)


@pytest.mark.parametrize(
    "exc_cls,expected_status_code",
    [
        (PDFUnreadableError, "PDFUnreadable"),
        (TranscriptUnavailableError, "TranscriptUnavailable"),
        (VideoInaccessibleError, "VideoInaccessible"),
        (VideoUnreadableError, "VideoUnreadable"),
        (VideoTooLargeError, "VideoTooLarge"),
        (VideoTooLongError, "VideoTooLong"),
        (TranscriptionError, "TranscriptionFailed"),
    ],
)
def test_status_codes_match_official_requirements(exc_cls, expected_status_code):
    exc = exc_cls("something went wrong")
    assert exc.status_code == expected_status_code
    assert isinstance(exc, Team4AError)
    assert isinstance(exc, Exception)


def test_exception_carries_message_and_optional_detail():
    exc = PDFUnreadableError("PDF is password-protected", detail={"file_path": "/tmp/x.pdf"})
    assert exc.message == "PDF is password-protected"
    assert exc.detail == {"file_path": "/tmp/x.pdf"}
    assert str(exc) == "PDF is password-protected"


def test_exception_requires_non_empty_message():
    with pytest.raises(ValueError):
        PDFUnreadableError("")


def test_to_error_detail_shape():
    exc = VideoInaccessibleError("video is private", detail={"url": "https://youtu.be/x"})
    error_detail = exc.to_error_detail()

    assert error_detail == {
        "error_type": "VideoInaccessibleError",
        "status_code": "VideoInaccessible",
        "message": "video is private",
        "detail": {"url": "https://youtu.be/x"},
    }


def test_detail_defaults_to_empty_dict():
    exc = TranscriptUnavailableError("no transcript available")
    assert exc.detail == {}
