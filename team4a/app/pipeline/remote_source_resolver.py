"""Phase 2C-R (CORRECTED) -- secure `file_url` -> local temp file
retrieval, for the canonical `POST /v1/ingest` route's `pdf`/`mp4`
branches ONLY.

YouTube is explicitly OUT OF SCOPE for this module -- see
app/processors/youtube_processor.py's own, separate, already-tested host
validation. This module must never be used for YouTube URLs.

============================================================
CORRECTION: REQUEST-LOCAL IP PINNING (no global monkeypatch)
============================================================

The previous version of this module monkeypatched the PROCESS-GLOBAL
function `urllib3.util.connection.create_connection` for the duration of
each call. That is unsafe under concurrency: Team 4A can serve concurrent
`/v1/ingest` requests, and a single mutable global function is shared
mutable state -- two concurrent calls patching and un-patching the same
global function race with each other, and a request could observe (or
even connect through) another request's pinned IP.

This is corrected below by never touching any global/module-level
state at all. Each call constructs its own, request-local
`urllib3.HTTPConnectionPool`/`HTTPSConnectionPool` object, with the
VALIDATED IP passed directly as that pool's own `host` argument -- the
pool itself dials that exact address; there is no shared function to
race on, no global to restore, and no window where two concurrent
requests could observe each other's pinned destination. The original
hostname is preserved separately, for the `Host` header and (for HTTPS)
TLS SNI/certificate-hostname verification via `assert_hostname`/
`server_hostname`.

This module now calls `urllib3` directly (not `requests`) for exactly
this reason: `requests`' own `Session`/`HTTPAdapter` architecture does
not expose a clean, per-call way to substitute the pool's connect target
without either global monkeypatching (rejected above) or subclassing
`HTTPAdapter` in version-fragile ways. Working directly against
`urllib3` (a dependency `requests` itself sits on, so nothing new is
introduced beneath the surface) is the smallest, most direct mechanism
that satisfies "the smallest appropriate transport mechanism" without
introducing global state.

============================================================
CONCURRENCY SAFETY
============================================================

Every mutable object this function touches -- the `HTTPConnectionPool`,
the destination file, the byte counters -- is local to that single call's
stack frame. No class attribute, module attribute, or other shared
object is ever written to. Proven, not merely asserted, by
`test_concurrent_requests_do_not_cross_contaminate_destinations` in
tests/test_remote_source_resolver.py: two real threads, each resolving a
DIFFERENT validated IP, running genuinely concurrently, asserting each
thread's actual connection used its OWN pinned IP throughout.

============================================================
PROXY / ENVIRONMENT SECURITY
============================================================

Raw `urllib3.HTTPConnectionPool`/`HTTPSConnectionPool` objects,
constructed directly as this module does (never via `urllib3.ProxyManager`
or any `_proxy=` argument), NEVER read `HTTP_PROXY`/`HTTPS_PROXY`/
`ALL_PROXY` or any other environment variable to decide where to connect
-- that behavior belongs exclusively to `requests.Session`'s own
`trust_env`-gated environment-proxy resolution, which this module does
not use at all, by construction, not by an opt-out flag. Verified
directly by `test_environment_proxy_variables_do_not_change_the_actual_destination`.

============================================================
CONTENT-TYPE POLICY (corrected)
============================================================

`Content-Type` is NEVER authoritative -- magic-byte validation after
download is the sole authoritative content check, always performed
regardless of what `Content-Type` claims. A missing `Content-Type`, or
the generic `application/octet-stream` (a common, legitimate object-
storage default), is NOT rejected -- only a `Content-Type` that is
CLEARLY, categorically wrong for the requested `file_type` (e.g.
`text/html` for a pdf/mp4 request) is rejected early, as a cheap
optimization; even that early check is advisory, never a substitute for
the magic-byte check that always runs afterward.

============================================================
TRUSTED-ORIGIN POLICY (exact match only, deliberately)
============================================================

`file_url_trusted_origins_json` must contain EXACT hostnames -- no
substring/suffix matching, ever. If a trusted origin legitimately
resolves to a private-range address, that address is not rejected for
being private -- only origin-membership gates trust; a cloud-metadata
address is rejected regardless of origin trust.

============================================================
MULTI-ADDRESS DNS POLICY
============================================================

When `getaddrinfo` returns multiple candidates, this module selects the
FIRST candidate, in the order the resolver returned them, that is not a
cloud-metadata address -- deterministic, computed exactly once. That
single selected address is what the request-local pool is constructed
with; there is no second, independent resolution downstream of that
selection.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import socket
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import urllib3
import urllib3.exceptions

from app.config.settings import Settings
from app.models.schemas import SourceType

logger = logging.getLogger(__name__)

_TEMP_SUBDIR_NAME = "remote-ingest"
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024
_HEADER_SNIFF_BYTES = 16

_PDF_MAGIC = b"%PDF-"

_METADATA_ADDRESSES = {"169.254.169.254", "fd00:ec2::254"}

_CLEARLY_WRONG_CONTENT_TYPE_PREFIXES = ("text/html", "text/plain", "application/json", "application/xml")


class TrustedOriginError(RuntimeError):
    """Raised for every SSRF-policy rejection."""


class RemoteFetchError(RuntimeError):
    """Raised for every network-level failure."""


class ContentValidationError(RuntimeError):
    """Raised when downloaded content's magic bytes don't match file_type."""


def _is_cloud_metadata_address(ip_obj) -> bool:
    return str(ip_obj) in _METADATA_ADDRESSES or (ip_obj.version == 4 and ip_obj.is_link_local)


def _looks_like_pdf(header: bytes) -> bool:
    return header.startswith(_PDF_MAGIC)


def _looks_like_mp4(header: bytes) -> bool:
    return len(header) >= 8 and header[4:8] == b"ftyp"


def _is_clearly_wrong_content_type(declared_content_type: str, expected_prefix: str) -> bool:
    normalized = declared_content_type.split(";")[0].strip().lower()
    if not normalized or normalized == "application/octet-stream" or normalized.startswith(expected_prefix):
        return False
    return normalized.startswith(_CLEARLY_WRONG_CONTENT_TYPE_PREFIXES)


def load_trusted_origins(raw: str) -> set[str]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TrustedOriginError("file_url_trusted_origins_json is not valid JSON") from exc
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise TrustedOriginError("file_url_trusted_origins_json must be a JSON array of strings")
    return set(parsed)


def _resolve_candidates(hostname: str, port: int) -> list[str]:
    try:
        addrinfo = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise RemoteFetchError("DNS resolution failed for a trusted origin") from exc
    return [sockaddr[0] for *_rest, sockaddr in addrinfo]


def _select_validated_ip(candidates: list[str]) -> str:
    for candidate_ip in candidates:
        ip_obj = ipaddress.ip_address(candidate_ip)
        if _is_cloud_metadata_address(ip_obj):
            continue
        return candidate_ip
    raise RemoteFetchError("No usable (non-metadata) address resolved for this trusted origin")


def _validate_url(file_url: str, trusted_origins: set[str], require_https: bool) -> tuple[str, str, int, str]:
    parsed = urlsplit(file_url)

    if parsed.scheme not in ("http", "https"):
        raise TrustedOriginError("Unsupported URL scheme")
    if require_https and parsed.scheme != "https":
        raise TrustedOriginError("Only https is permitted by the current policy")

    if parsed.username is not None or parsed.password is not None:
        raise TrustedOriginError("Credentials embedded in the URL are not permitted")

    hostname = parsed.hostname
    if not hostname:
        raise TrustedOriginError("URL has no hostname")

    if hostname not in trusted_origins:
        raise TrustedOriginError("Host is not an explicitly configured trusted origin")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path_and_query = parsed.path or "/"
    if parsed.query:
        path_and_query = f"{path_and_query}?{parsed.query}"

    return parsed.scheme, hostname, port, path_and_query


def _open_pinned_pool(
    scheme: str,
    validated_ip: str,
    port: int,
    hostname: str,
    connect_timeout: float,
    read_timeout: float,
) -> "urllib3.HTTPConnectionPool":
    """Constructs a brand-new, request-local connection pool dialing
    EXACTLY `validated_ip`. Never stored outside the caller's stack
    frame; never shared across calls; touches no global state.
    """

    timeout = urllib3.Timeout(connect=connect_timeout, read=read_timeout)
    if scheme == "https":
        return urllib3.HTTPSConnectionPool(
            validated_ip,
            port=port,
            timeout=timeout,
            retries=False,
            maxsize=1,
            assert_hostname=hostname,
            server_hostname=hostname,
            cert_reqs="CERT_REQUIRED",
        )
    return urllib3.HTTPConnectionPool(validated_ip, port=port, timeout=timeout, retries=False, maxsize=1)


def resolve_pdf_or_mp4_source(file_url: str, file_type: SourceType, settings: Settings) -> Path:
    """Securely retrieves `file_url` (already validated to be `pdf` or
    `mp4`) to a uniquely-named temporary local file, and returns its
    path. See module docstring for the full security design.
    """

    if file_type not in (SourceType.PDF, SourceType.MP4):
        raise ValueError(
            "resolve_pdf_or_mp4_source only supports pdf/mp4 -- YouTube must be routed directly to "
            "YouTubeProcessor.process(), never through this resolver"
        )

    trusted_origins = load_trusted_origins(settings.file_url_trusted_origins_json)
    scheme, hostname, port, path_and_query = _validate_url(file_url, trusted_origins, settings.file_url_require_https)

    candidates = _resolve_candidates(hostname, port)
    validated_ip = _select_validated_ip(candidates)

    max_bytes = (
        settings.pdf_max_size_mb * 1024 * 1024
        if file_type is SourceType.PDF
        else settings.video_max_size_gb * 1024**3
    )
    expected_content_type_prefix = "application/pdf" if file_type is SourceType.PDF else "video/mp4"
    extension = ".pdf" if file_type is SourceType.PDF else ".mp4"

    temp_dir = Path(settings.upload_directory) / _TEMP_SUBDIR_NAME
    temp_dir.mkdir(parents=True, exist_ok=True)
    destination = temp_dir / f"{uuid.uuid4().hex}{extension}"

    logger.info(
        "Resolving remote file_url for canonical ingestion",
        extra={"hostname": hostname, "file_type": file_type.value},
    )

    pool = _open_pinned_pool(
        scheme, validated_ip, port, hostname, settings.file_url_connect_timeout_seconds, settings.file_url_read_timeout_seconds
    )
    try:
        try:
            response = pool.request(
                "GET",
                path_and_query,
                headers={"Host": hostname},
                preload_content=False,
                redirect=False,
                retries=False,
            )
        except urllib3.exceptions.HTTPError as exc:
            raise RemoteFetchError(f"Request to trusted origin failed: {exc}") from exc

        try:
            if 300 <= response.status < 400:
                raise RemoteFetchError("Redirects are not permitted by the current policy")
            if response.status != 200:
                raise RemoteFetchError(f"Trusted origin returned an unexpected status: {response.status}")

            declared_content_type = response.headers.get("content-type", "")
            if _is_clearly_wrong_content_type(declared_content_type, expected_content_type_prefix):
                raise ContentValidationError(
                    f"Declared Content-Type {declared_content_type!r} is clearly incompatible with {expected_content_type_prefix!r}"
                )

            bytes_written = 0
            header_bytes = b""
            started_at = time.monotonic()

            try:
                with open(destination, "wb") as destination_file:
                    for chunk in response.stream(_DOWNLOAD_CHUNK_BYTES):
                        if time.monotonic() - started_at > settings.file_url_total_timeout_seconds:
                            raise RemoteFetchError("Overall download timeout exceeded")
                        if not chunk:
                            continue
                        bytes_written += len(chunk)
                        if bytes_written > max_bytes:
                            raise RemoteFetchError(f"Download exceeds the maximum allowed size of {max_bytes} bytes")
                        if len(header_bytes) < _HEADER_SNIFF_BYTES:
                            header_bytes += chunk[: _HEADER_SNIFF_BYTES - len(header_bytes)]
                        destination_file.write(chunk)
            except urllib3.exceptions.HTTPError as exc:
                raise RemoteFetchError(f"Connection failed while streaming the response: {exc}") from exc

            if file_type is SourceType.PDF and not _looks_like_pdf(header_bytes):
                raise ContentValidationError("Downloaded content does not match the expected PDF file signature")
            if file_type is SourceType.MP4 and not _looks_like_mp4(header_bytes):
                raise ContentValidationError("Downloaded content does not match the expected MP4 file signature")

        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            response.release_conn()
    finally:
        pool.close()

    return destination
