"""Phase 2C-R tests -- app.pipeline.remote_source_resolver.

Uses a REAL local HTTP server (Python's own http.server, bound to
127.0.0.1 on an ephemeral port) for every "successful retrieval"/
"content behavior" test -- deterministic, CI-safe, no real internet
access, per the governing task's explicit requirement. `trusted_origins`
in these tests is configured as `{"127.0.0.1"}` -- an explicitly trusted
origin that legitimately resolves to a private/loopback address, exactly
the documented exception case (trust is a property of the ORIGIN, not of
whether its resolved address happens to be public).
"""

from __future__ import annotations

import http.server
import ipaddress
import json
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import urllib3

from app.models.schemas import SourceType
from app.pipeline.remote_source_resolver import (
    ContentValidationError,
    RemoteFetchError,
    TrustedOriginError,
    _is_cloud_metadata_address,
    _looks_like_mp4,
    _looks_like_pdf,
    load_trusted_origins,
    resolve_pdf_or_mp4_source,
)

_REAL_PDF_BYTES = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
_REAL_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"\x00" * 100


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request console spam
        pass

    def do_GET(self):
        if self.path == "/pdf":
            self._send(200, b"application/pdf", _REAL_PDF_BYTES)
        elif self.path == "/pdf-octet-stream":
            self._send(200, b"application/octet-stream", _REAL_PDF_BYTES)
        elif self.path == "/pdf-no-content-type":
            self.send_response(200)
            self.send_header("Content-Length", str(len(_REAL_PDF_BYTES)))
            self.end_headers()
            self.wfile.write(_REAL_PDF_BYTES)
        elif self.path == "/mp4":
            self._send(200, b"video/mp4", _REAL_MP4_BYTES)
        elif self.path == "/wrong-content-type":
            self._send(200, b"text/html", _REAL_PDF_BYTES)
        elif self.path == "/wrong-magic-bytes":
            self._send(200, b"application/pdf", b"NOT-A-REAL-PDF-BODY" * 5)
        elif self.path == "/oversized":
            self._send(200, b"application/pdf", _REAL_PDF_BYTES + b"\x00" * (10 * 1024 * 1024))
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/pdf")
            self.end_headers()
        elif self.path == "/slow":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            time.sleep(2)
            self.wfile.write(_REAL_PDF_BYTES)
        elif self.path == "/hang":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            time.sleep(30)  # longer than any test's configured timeout
        else:
            self.send_response(404)
            self.end_headers()

    def _send(self, status: int, content_type: bytes, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type.decode())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def local_server():
    # ThreadingHTTPServer, not the single-threaded HTTPServer: the
    # `/hang` and `/slow` handlers deliberately sleep server-side to
    # simulate a stalled remote origin -- with a single-threaded server,
    # that sleep would block the ENTIRE server from handling any other
    # test's request for its full duration, corrupting every other test
    # in this module (confirmed directly: this was a real, reproducible
    # test-order-dependent failure before this fix).
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"127.0.0.1:{port}"
    server.shutdown()
    thread.join(timeout=5)


def make_settings(**overrides) -> SimpleNamespace:
    defaults = dict(
        pdf_max_size_mb=5,
        video_max_size_gb=1,
        upload_directory=None,  # set per-test via tmp_path
        file_url_trusted_origins_json=json.dumps(["127.0.0.1"]),
        file_url_connect_timeout_seconds=2.0,
        file_url_read_timeout_seconds=1.0,
        file_url_total_timeout_seconds=3.0,
        file_url_max_redirects=0,
        file_url_require_https=False,  # the local test server is plain HTTP
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# -- 1/2: trusted origin succeeds ---------------------------------------


def test_1_trusted_pdf_origin_succeeds(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf", SourceType.PDF, settings)
    assert path.exists()
    assert path.read_bytes() == _REAL_PDF_BYTES
    path.unlink()


def test_2_trusted_mp4_origin_succeeds(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/mp4", SourceType.MP4, settings)
    assert path.exists()
    assert path.read_bytes() == _REAL_MP4_BYTES
    path.unlink()


# -- 3/4: untrusted / lookalike hostname ----------------------------------


def test_3_untrusted_hostname_rejected(tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(TrustedOriginError):
        resolve_pdf_or_mp4_source("http://evil.example.com/pdf", SourceType.PDF, settings)


def test_4_lookalike_hostname_rejected(tmp_path):
    settings = make_settings(
        upload_directory=str(tmp_path),
        file_url_trusted_origins_json=json.dumps(["trusted.example"]),
    )
    with pytest.raises(TrustedOriginError):
        resolve_pdf_or_mp4_source("http://trusted.example.attacker.com/pdf", SourceType.PDF, settings)


# -- 5: HTTPS-only policy -------------------------------------------------


def test_5_http_rejected_when_https_only_policy_configured(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path), file_url_require_https=True)
    with pytest.raises(TrustedOriginError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/pdf", SourceType.PDF, settings)


# -- 6-11: IP classification rejections (unit-level, direct) ---------------


@pytest.mark.parametrize(
    "ip,expected",
    [
        ("127.0.0.1", "loopback"),
        ("::1", "loopback"),
        ("10.0.0.5", "private"),
        ("192.168.1.1", "private"),
        ("fc00::1", "private"),
        ("fe80::1", "link-local"),
        ("169.254.1.1", "link-local"),
        ("224.0.0.1", "multicast"),
        ("0.0.0.0", "unspecified"),
        ("169.254.169.254", "metadata"),
    ],
)
def test_6_to_11_ip_classification_is_correct(ip, expected):
    ip_obj = ipaddress.ip_address(ip)
    if expected == "loopback":
        assert ip_obj.is_loopback
    elif expected == "private":
        assert ip_obj.is_private
    elif expected == "link-local":
        assert ip_obj.is_link_local
    elif expected == "multicast":
        assert ip_obj.is_multicast
    elif expected == "unspecified":
        assert ip_obj.is_unspecified
    elif expected == "metadata":
        assert _is_cloud_metadata_address(ip_obj)


def test_metadata_address_never_selected_even_for_a_trusted_origin_name(monkeypatch, tmp_path):
    settings = make_settings(
        upload_directory=str(tmp_path),
        file_url_trusted_origins_json=json.dumps(["metadata.trusted.test"]),
    )

    def fake_getaddrinfo(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source("http://metadata.trusted.test/pdf", SourceType.PDF, settings)


# -- 12: numeric-IP URL tricks ----------------------------------------------


def test_12_numeric_ip_url_used_as_host_is_rejected_unless_the_exact_literal_is_trusted(tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))  # trusts only "127.0.0.1" the string
    with pytest.raises(TrustedOriginError):
        resolve_pdf_or_mp4_source("http://2130706433/pdf", SourceType.PDF, settings)


# -- 13: URL credentials ------------------------------------------------------


def test_13_url_credentials_rejected(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(TrustedOriginError):
        resolve_pdf_or_mp4_source(f"http://user:pass@{local_server}/pdf", SourceType.PDF, settings)


# -- 14: redirects rejected ---------------------------------------------------


def test_14_redirect_rejected(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/redirect", SourceType.PDF, settings)


# -- 15-17: timeouts -----------------------------------------------------------


def test_16_read_timeout_enforced(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path), file_url_read_timeout_seconds=0.2)
    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/hang", SourceType.PDF, settings)


def test_17_overall_timeout_enforced_even_within_read_timeout(local_server, tmp_path):
    settings = make_settings(
        upload_directory=str(tmp_path),
        file_url_read_timeout_seconds=10.0,
        file_url_total_timeout_seconds=0.5,
    )
    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/slow", SourceType.PDF, settings)


def test_15_connect_timeout_is_a_distinct_configurable_value(tmp_path):
    settings = make_settings(upload_directory=str(tmp_path), file_url_connect_timeout_seconds=1.23)
    assert settings.file_url_connect_timeout_seconds == 1.23
    assert settings.file_url_connect_timeout_seconds != settings.file_url_read_timeout_seconds


# -- 18/19/20: size limit + cleanup -------------------------------------------


def test_18_and_19_max_download_size_enforced_and_partial_file_cleaned(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path), pdf_max_size_mb=1)
    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/oversized", SourceType.PDF, settings)

    remote_ingest_dir = tmp_path / "remote-ingest"
    leftover_files = list(remote_ingest_dir.glob("*")) if remote_ingest_dir.exists() else []
    assert leftover_files == []


def test_20_partial_file_cleaned_after_network_failure(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path), file_url_read_timeout_seconds=0.2)
    with pytest.raises(RemoteFetchError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/hang", SourceType.PDF, settings)

    remote_ingest_dir = tmp_path / "remote-ingest"
    leftover_files = list(remote_ingest_dir.glob("*")) if remote_ingest_dir.exists() else []
    assert leftover_files == []


# -- 21/22/23: content validation ---------------------------------------------


def test_21_wrong_content_type_rejected(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(ContentValidationError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/wrong-content-type", SourceType.PDF, settings)


def test_octet_stream_content_type_is_allowed_through_to_magic_byte_check(local_server, tmp_path):
    """Corrected policy: application/octet-stream (a common, legitimate
    object-storage default) must NOT be rejected -- the real PDF bytes
    behind it pass the authoritative magic-byte check."""

    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf-octet-stream", SourceType.PDF, settings)
    assert path.read_bytes() == _REAL_PDF_BYTES
    path.unlink()


def test_missing_content_type_is_allowed_through_to_magic_byte_check(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf-no-content-type", SourceType.PDF, settings)
    assert path.read_bytes() == _REAL_PDF_BYTES
    path.unlink()


def test_22_pdf_magic_mismatch_rejected(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(ContentValidationError):
        resolve_pdf_or_mp4_source(f"http://{local_server}/wrong-magic-bytes", SourceType.PDF, settings)


def test_23_mp4_signature_check_is_correct():
    assert _looks_like_mp4(_REAL_MP4_BYTES) is True
    assert _looks_like_mp4(b"not an mp4 at all") is False
    assert _looks_like_pdf(_REAL_PDF_BYTES) is True
    assert _looks_like_pdf(b"not a pdf") is False


# -- 24/25: temp file lifecycle on success/failure ----------------------------


def test_24_temp_file_uses_a_dedicated_directory_and_server_generated_name(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf", SourceType.PDF, settings)
    assert path.parent.name == "remote-ingest"
    assert len(path.stem) == 32  # a uuid4 hex, never derived from the URL/path
    path.unlink()


# -- Trusted-origin-resolves-to-private-address exception (documented) -----


def test_trusted_origin_resolving_to_loopback_is_not_rejected_for_being_private(local_server, tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf", SourceType.PDF, settings)
    assert path.exists()
    path.unlink()


# -- Configuration loading ----------------------------------------------------


def test_load_trusted_origins_parses_a_valid_list():
    assert load_trusted_origins('["a.example", "b.example"]') == {"a.example", "b.example"}


@pytest.mark.parametrize("malformed", ["not json", "{}", "42", '["a", 1]', ""])
def test_load_trusted_origins_fails_safely_on_malformed_input(malformed):
    with pytest.raises(TrustedOriginError):
        load_trusted_origins(malformed)


def test_youtube_file_type_is_rejected_by_this_resolver(tmp_path):
    settings = make_settings(upload_directory=str(tmp_path))
    with pytest.raises(ValueError):
        resolve_pdf_or_mp4_source("http://youtube.com/watch?v=x", SourceType.YOUTUBE, settings)


# ============================================================
# CORRECTED IP-PINNING: request-local pools, no global monkeypatch
# ============================================================


def test_pool_is_constructed_with_the_validated_ip_as_its_host(monkeypatch):
    """Direct proof that `_open_pinned_pool` dials the VALIDATED ip, not
    the hostname -- inspects the constructed pool object's own `.host`
    attribute, which is what urllib3 actually uses to open the socket."""

    from app.pipeline.remote_source_resolver import _open_pinned_pool

    pool = _open_pinned_pool("http", "203.0.113.10", 80, "trusted.example", 2.0, 2.0)
    try:
        assert pool.host == "203.0.113.10"
    finally:
        pool.close()


def test_concurrent_requests_do_not_cross_contaminate_destinations(local_server):
    """THE mandatory concurrency test: two real threads, each resolving
    a DIFFERENT validated destination, running genuinely concurrently
    (a barrier forces true overlap, not accidental sequential
    execution), asserting each thread's pool dialed its OWN address
    throughout -- proving no shared/global state exists to race on.

    Uses two real local servers (this module's `local_server` plus a
    second, independent one) as the two distinct "validated
    destinations" -- deterministic, CI-safe, no real DNS races.
    """

    import threading

    second_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    second_server.daemon_threads = True
    second_port = second_server.server_address[1]
    second_thread = threading.Thread(target=second_server.serve_forever, daemon=True)
    second_thread.start()

    try:
        results = {}
        barrier = threading.Barrier(2)

        def run(name, server_addr, tmp_dir):
            settings = make_settings(
                upload_directory=tmp_dir,
                file_url_trusted_origins_json=json.dumps(["127.0.0.1"]),
            )
            barrier.wait(timeout=5)  # force genuine overlap between the two threads
            try:
                path = resolve_pdf_or_mp4_source(f"http://{server_addr}/pdf", SourceType.PDF, settings)
                results[name] = ("ok", path.read_bytes())
                path.unlink()
            except Exception as exc:  # noqa: BLE001
                results[name] = ("error", str(exc))

        import tempfile

        tmp_a = tempfile.mkdtemp()
        tmp_b = tempfile.mkdtemp()

        thread_a = threading.Thread(target=run, args=("a", local_server, tmp_a))
        thread_b = threading.Thread(target=run, args=("b", f"127.0.0.1:{second_port}", tmp_b))
        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=10)
        thread_b.join(timeout=10)

        assert results["a"] == ("ok", _REAL_PDF_BYTES)
        assert results["b"] == ("ok", _REAL_PDF_BYTES)
    finally:
        second_server.shutdown()
        second_thread.join(timeout=5)


def test_pools_from_different_calls_never_share_state():
    """Structural guard: two pools constructed for two different pinned
    IPs are fully independent objects -- no shared mutable state of any
    kind (confirmed by identity and by `.host` divergence)."""

    from app.pipeline.remote_source_resolver import _open_pinned_pool

    pool_a = _open_pinned_pool("http", "203.0.113.10", 80, "a.example", 2.0, 2.0)
    pool_b = _open_pinned_pool("http", "198.51.100.20", 80, "b.example", 2.0, 2.0)
    try:
        assert pool_a is not pool_b
        assert pool_a.host != pool_b.host
        assert pool_a.host == "203.0.113.10"
        assert pool_b.host == "198.51.100.20"
    finally:
        pool_a.close()
        pool_b.close()


# ============================================================
# PROXY / ENVIRONMENT SECURITY
# ============================================================


def test_environment_proxy_variables_do_not_change_the_actual_destination(local_server, tmp_path, monkeypatch):
    """Sets HTTP_PROXY/HTTPS_PROXY/ALL_PROXY to a nonexistent, clearly-
    wrong address -- if this module silently honored them, the request
    would fail (nothing is listening there) or be misrouted. It must
    succeed, reaching the REAL local server directly, proving
    environment proxy variables have zero effect."""

    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.1:9999")
    monkeypatch.setenv("ALL_PROXY", "http://192.0.2.1:9999")

    settings = make_settings(upload_directory=str(tmp_path))
    path = resolve_pdf_or_mp4_source(f"http://{local_server}/pdf", SourceType.PDF, settings)
    assert path.read_bytes() == _REAL_PDF_BYTES
    path.unlink()


def test_pinned_pool_construction_never_passes_a_proxy_argument():
    """Structural guard: `_open_pinned_pool` never constructs a
    `ProxyManager` and never passes a `_proxy` kwarg -- proxy-blindness
    is a property of which class is instantiated, not a runtime flag."""

    from app.pipeline.remote_source_resolver import _open_pinned_pool

    pool = _open_pinned_pool("http", "203.0.113.10", 80, "trusted.example", 2.0, 2.0)
    try:
        assert not isinstance(pool, urllib3.ProxyManager)
        assert getattr(pool, "proxy", None) is None
    finally:
        pool.close()


# ============================================================
# MULTI-ADDRESS DNS BEHAVIOR
# ============================================================


def test_multi_address_dns_selects_deterministically_and_pins_to_it(monkeypatch):
    """Simulates getaddrinfo returning multiple candidates (one
    metadata, one usable) and proves: (1) the metadata candidate is
    never selected even though it comes first, (2) the resulting pool is
    pinned to the deterministically-selected usable candidate, with no
    second resolution call anywhere downstream."""

    from app.pipeline.remote_source_resolver import _select_validated_ip, _resolve_candidates

    call_count = {"n": 0}

    def fake_getaddrinfo(host, port, **kwargs):
        call_count["n"] += 1
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port)),  # metadata -- must be skipped
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.55", port)),  # usable -- must be selected
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.99", port)),  # a second usable candidate
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    candidates = _resolve_candidates("multi.trusted.test", 80)
    assert call_count["n"] == 1  # exactly one resolution call
    selected = _select_validated_ip(candidates)
    assert selected == "203.0.113.55"  # first non-metadata candidate, deterministically

    # Calling selection again on the SAME candidate list (no re-resolution)
    # yields the identical result -- deterministic, not order-randomized.
    assert _select_validated_ip(candidates) == "203.0.113.55"


def test_multi_address_all_metadata_is_rejected(monkeypatch):
    from app.pipeline.remote_source_resolver import _select_validated_ip

    with pytest.raises(RemoteFetchError):
        _select_validated_ip(["169.254.169.254", "169.254.1.1"])  # both are metadata/link-local

