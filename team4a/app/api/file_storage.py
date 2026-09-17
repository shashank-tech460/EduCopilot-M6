"""Task 10.1 upload file-saving boundary.

Saves POST /ingest/pdf and POST /ingest/video uploads to a local,
configurable directory (`Settings.upload_directory`) so Task 10.2's future
Celery task can locate them by path. Not cloud storage -- the official
spec doesn't define external storage for Team 4A.

Path-traversal / unsafe-filename prevention is structural, not by
sanitizing client input: the saved filename is always
`{job_id}{extension}`, where `job_id` is a server-generated UUID
(`IngestionJob`'s own default factory) and `extension` is one of two
fixed, route-chosen constants (".pdf" or ".mp4") -- the client-supplied
filename is never used to build a filesystem path at all, so there is
nothing for a malicious filename to traverse.

PRODUCTION HARDENING TASK 2: `save()` now enforces the applicable upload
size limit (`pdf_max_size_mb`/`video_max_size_gb`, converted to bytes by
the caller) *while streaming*, as defense in depth alongside the existing
processor-level checks (`PDFProcessor`/`VideoProcessor`, Requirement
1.6/2.7) that run later, against a file already fully and validly on
disk. Two independent layers are intentional:
    1. Here (upload layer): reject before the complete oversized body is
       ever written to disk, so a malicious/oversized upload cannot
       exhaust disk space merely by being submitted.
    2. Processor layer (unchanged, untouched): re-validates the size of
       whatever ends up on disk, as an independent, already-tested
       safeguard against any other path that might create a file bypassing
       this route (e.g. a future non-HTTP ingestion path).
Centralized here (not duplicated between the PDF and video routes) so
both endpoints share exactly the same enforcement code and cannot drift
into different rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

from app.config.settings import Settings, get_settings
from app.models.exceptions import UploadTooLargeError

#: Read/write in bounded chunks so memory use stays flat regardless of
#: upload size -- the file is never held in memory all at once, whether
#: it's ultimately accepted or rejected partway through.
_COPY_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class FileStorage:
    """Saves an uploaded file's content to `settings.upload_directory`."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        Path(self._settings.upload_directory).mkdir(parents=True, exist_ok=True)

    def save(
        self,
        source: BinaryIO,
        job_id: str,
        extension: str,
        max_bytes: int,
        declared_content_length: int | None = None,
    ) -> str:
        """Save `source`'s content under a server-generated name; return the saved path.

        Args:
            source: A readable binary file-like object (e.g. FastAPI's
                `UploadFile.file`).
            job_id: The IngestionJob's own job_id -- used verbatim as the
                base filename since it is already a server-generated UUID,
                never client input.
            extension: A fixed extension chosen by the calling route
                (".pdf" or ".mp4"), not derived from the client's declared
                filename.
            max_bytes: The maximum number of bytes this upload may
                contain, in bytes (the caller converts the configured
                `pdf_max_size_mb`/`video_max_size_gb` setting to bytes,
                since that conversion is source-type-specific and this
                method is source-agnostic).
            declared_content_length: The request's declared
                `Content-Length` header value, if present and parseable
                (the caller is responsible for parsing it; `None` if
                absent or unparseable). Used only as a cheap, early,
                *approximate* pre-check to avoid touching the disk at all
                for obviously oversized uploads -- it is never trusted as
                the authoritative limit, since it can be missing,
                incorrect, or manipulated by the client. The authoritative
                check is the byte-exact running count enforced while
                streaming, below, which applies regardless of what (if
                anything) Content-Length claims.

        Returns:
            The absolute path the file was saved to.

        Raises:
            UploadTooLargeError: if the declared Content-Length clearly
                exceeds `max_bytes`, or if the stream's actual byte count
                exceeds `max_bytes` while being written. In the latter
                case, the partial file written so far is deleted before
                the exception is raised -- no partial/oversized file, and
                no file at all, is left on disk for a rejected upload.
        """

        if declared_content_length is not None and declared_content_length > max_bytes:
            raise UploadTooLargeError(
                f"Upload declares a size of {declared_content_length} bytes, "
                f"exceeding the maximum allowed {max_bytes} bytes",
                detail={"declared_content_length": declared_content_length, "max_bytes": max_bytes},
            )

        destination = Path(self._settings.upload_directory) / f"{job_id}{extension}"
        bytes_written = 0
        try:
            with open(destination, "wb") as destination_file:
                while True:
                    chunk = source.read(_COPY_CHUNK_BYTES)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise UploadTooLargeError(
                            f"Upload exceeds the maximum allowed size of {max_bytes} bytes",
                            detail={"max_bytes": max_bytes, "bytes_read_before_rejection": bytes_written},
                        )
                    destination_file.write(chunk)
        except UploadTooLargeError:
            # Never leave a partial/oversized file on disk for a rejected
            # upload -- no orphaned file, and (since the caller only
            # creates the job record after `save()` returns successfully)
            # no job ever references this path either.
            destination.unlink(missing_ok=True)
            raise
        except BaseException:
            # Any other failure while streaming (e.g. a client disconnect)
            # must not leave a partial file behind either.
            destination.unlink(missing_ok=True)
            raise

        return str(destination)
