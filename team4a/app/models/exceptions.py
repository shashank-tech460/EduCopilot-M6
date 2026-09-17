"""Team 4A exception hierarchy.

Only the exception types explicitly named in the official Team 4A design
document are defined here:

    app/models/exceptions.py with custom exceptions:
        PDFUnreadableError, TranscriptUnavailableError, VideoInaccessibleError

    Requirements: 1.4, 2.5, 2.6, 3.4, 3.5, 8.2, 8.4

Two conditions described in the requirements — an MP4 with no audio track
(Requirement 2.5, "audio_absent") and a per-segment transcription failure
(Requirement 2.6, "transcription_failed") — are explicitly *non-fatal*: the
spec requires the Video_Processor to continue processing when they occur.
They are therefore represented as data flags on the relevant pipeline models
in `schemas.py` (Task 1.2) rather than as raised exceptions, and are not
included in this module. See the Task 1.2 report for this decision.

Every exception here carries enough structured information (`status_code`,
`message`, optional `detail`) for later layers to convert it into an
`ErrorDetail` (stored on `IngestionJob.error_details`) or into an HTTP error
response, without those later layers needing to know exception internals.
"""

from __future__ import annotations

from typing import Any


class Team4AError(Exception):
    """Base class for all Team 4A ingestion pipeline errors.

    Attributes:
        message: Human-readable description of the failure.
        status_code: Short machine-readable error code matching the value
            named in the official requirements (e.g. "PDFUnreadable").
        detail: Optional extra structured context (e.g. file path, video id)
            useful for logs and API error responses.
    """

    #: Overridden by subclasses to the status code named in the requirements.
    status_code: str = "IngestionError"

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        if not message:
            raise ValueError("message must be a non-empty, descriptive string")
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_error_detail(self) -> dict[str, Any]:
        """Return a plain dict suitable for `IngestionJob.error_details`.

        Kept as a plain dict (rather than importing the `ErrorDetail` model
        from `schemas.py`) to avoid a circular import between the two
        sibling modules; `ErrorDetail.from_exception` in `schemas.py` wraps
        this into the typed model.
        """

        return {
            "error_type": type(self).__name__,
            "status_code": self.status_code,
            "message": self.message,
            "detail": self.detail,
        }

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{type(self).__name__}(status_code={self.status_code!r}, message={self.message!r})"


class PDFUnreadableError(Team4AError):
    """Raised when a PDF is password-protected or structurally corrupted.

    Requirement 1.4: THE PDF_Processor SHALL return an error response with
    a PDFUnreadable status code and a descriptive error message.
    """

    status_code = "PDFUnreadable"


class PDFTooLargeError(Team4AError):
    """Raised when a PDF exceeds the configured maximum file size.

    Requirement 1.6: THE PDF_Processor SHALL support PDF files up to 200MB
    in size. The requirement names no specific status code for this case
    (only Requirement 1.4's "PDFUnreadable" is named), so this is a Task
    2.1 addition — kept distinct from PDFUnreadableError because an
    oversized file is a *valid* PDF that was rejected on size grounds, not
    a corrupt/unreadable one (see Task 2.1 report).
    """

    status_code = "PDFTooLarge"


class PDFTooManyPagesError(Team4AError):
    """Raised when a PDF exceeds the configured maximum page count.

    Requirement 1.6: THE PDF_Processor SHALL support PDFs up to 5000 pages
    in length. As with PDFTooLargeError, no status code is named in the
    requirements for this case; this is a Task 2.1 addition, kept distinct
    from PDFUnreadableError for the same reason.
    """

    status_code = "PDFTooManyPages"


class TranscriptUnavailableError(Team4AError):
    """Raised when a YouTube video has no available transcript.

    Requirement 3.4: THE YouTube_Processor SHALL return an error response
    with a TranscriptUnavailable status code.
    """

    status_code = "TranscriptUnavailable"


class VideoInaccessibleError(Team4AError):
    """Raised when a YouTube URL is invalid, private, or removed.

    Requirement 3.5: THE YouTube_Processor SHALL return an error response
    with a VideoInaccessible status code.
    """

    status_code = "VideoInaccessible"


class VideoUnreadableError(Team4AError):
    """Raised when a local MP4 file is corrupt/malformed and cannot be
    probed or read by ffmpeg/ffprobe.

    Not explicitly named in the requirements document (Requirement 2's
    acceptance criteria cover audio-absence, per-segment transcription
    failure, and size/duration limits, but no corrupt-file status code the
    way Requirement 1.4 names "PDFUnreadable" for PDFs). Added in Task 3.1
    as the smallest justified addition needed to fulfil the task's explicit
    instruction to distinguish "invalid/unreadable video" from size/duration
    rejection and from transcription failure. Named and shaped
    (status_code, message, detail) the same way as PDFUnreadableError for
    consistency.
    """

    status_code = "VideoUnreadable"


class VideoTooLargeError(Team4AError):
    """Raised when an MP4 file exceeds the configured maximum file size.

    Requirement 2.7: THE Video_Processor SHALL support MP4 files up to 2GB
    in size. As with PDFTooLargeError, no status code is named in the
    requirements for this case; added in Task 3.1, kept distinct from
    VideoUnreadableError because an oversized file is a valid video
    rejected on size grounds, not a corrupt one.
    """

    status_code = "VideoTooLarge"


class VideoTooLongError(Team4AError):
    """Raised when an MP4 file exceeds the configured maximum duration.

    Requirement 2.7: THE Video_Processor SHALL support MP4 files up to 4
    hours in duration. As with VideoTooLargeError, no status code is named
    in the requirements for this case; added in Task 3.1.
    """

    status_code = "VideoTooLong"


class TranscriptionError(Team4AError):
    """Raised when transcription fails globally and cannot continue.

    Distinct from a per-segment transcription failure (Requirement 2.6),
    which is represented as data -- `VideoSegment.transcription_failed`
    -- so that other segments can still be returned. This exception is
    for the case where the transcription engine itself cannot produce any
    result at all (e.g. it cannot be loaded), per Task 3.1's instruction
    not to "pretend transcription succeeded" when it fundamentally could
    not run.
    """

    status_code = "TranscriptionFailed"


class EmbeddingDimensionMismatchError(Team4AError):
    """Raised when the loaded embedding model's actual output dimension
    does not match the configured `embedding_dimensions` setting.

    Not explicitly named in the requirements document, but required by
    Task 7.1's explicit instruction that "embedding dimensions
    [must be] configurable/validated according to the project
    configuration" and that "the implementation must not silently return
    vectors with an unexpected dimension" (Property 16). Raised once, the
    first time the model is actually loaded, rather than failing silently
    or emitting wrongly-shaped vectors.
    """

    status_code = "EmbeddingDimensionMismatch"


class UploadTooLargeError(Team4AError):
    """Raised by the upload/API layer (`FileStorage.save`) when an
    incoming PDF/MP4 upload exceeds the configured size limit while it is
    still being streamed to disk.

    Production Hardening Task 2: deliberately distinct from
    `PDFTooLargeError`/`VideoTooLargeError` (Requirement 1.6/2.7), which
    remain the *processor*-level check against a file that is already
    fully and validly saved on disk. This is the earlier, upload-layer
    check -- "defense in depth" means two genuinely separate enforcement
    points are entitled to two distinct, precisely-named failure
    identities, so it's clear from the error alone which layer rejected
    the upload, without changing or replacing the existing processor-level
    checks in any way.
    """

    status_code = "UploadTooLarge"
