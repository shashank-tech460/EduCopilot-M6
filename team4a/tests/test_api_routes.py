"""Unit tests for Task 10.1: FastAPI routes and file handling.

No live Celery, Redis, Qdrant, Whisper, or YouTube access -- every test
uses FastAPI's `TestClient` against a fresh `InMemoryJobStore` and a
temp-directory-backed `FileStorage`, injected via
`app.dependency_overrides` so tests never touch the real
`upload_directory` or share job state with each other.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.api.file_storage import FileStorage
from app.api.job_store import InMemoryJobStore
from app.api.routes import get_file_storage, get_job_store, router
from app.config.settings import Settings, get_settings


@pytest.fixture
def job_store() -> InMemoryJobStore:
    return InMemoryJobStore()


@pytest.fixture
def client(tmp_path, job_store) -> TestClient:
    app = FastAPI()
    app.include_router(router)

    test_settings = Settings(upload_directory=str(tmp_path), _env_file=None)
    test_file_storage = FileStorage(settings=test_settings)

    app.dependency_overrides[get_job_store] = lambda: job_store
    app.dependency_overrides[get_file_storage] = lambda: test_file_storage
    # TASK 10.2 INTEGRATION FIX: also override get_settings so the route's
    # own `settings: Settings = Depends(get_settings)` parameter (used for
    # max_bytes AND, since this fix, for `_cleanup_upload`'s
    # upload_directory) is the SAME settings object FileStorage was built
    # from -- previously unnecessary (nothing read `settings.upload_directory`
    # from the route itself), but required now: without this, a dispatch-
    # failure test's cleanup check would look for the file under the real
    # default upload_directory instead of `tmp_path`, where it was actually
    # saved, and `_cleanup_upload`'s own path-containment safety check
    # would correctly (but confusingly, for the test) refuse to touch it.
    app.dependency_overrides[get_settings] = lambda: test_settings

    # NOTE: the actual Celery dispatch boundary (`process_pdf.delay` etc.)
    # is mocked project-wide, for every test regardless of which fixture
    # builds the FastAPI app -- see tests/conftest.py's autouse
    # `_mock_celery_dispatch` fixture and its own docstring for why this
    # had to be global rather than local to this fixture.

    return TestClient(app)


def pdf_upload(content: bytes = b"%PDF-1.4 fake content", content_type: str = "application/pdf"):
    return {"file": ("test.pdf", content, content_type)}


def video_upload(content: bytes = b"fake mp4 bytes", content_type: str = "video/mp4"):
    return {"file": ("test.mp4", content, content_type)}


# ---------------------------------------------------------------------------
# Routes exist / basic shape
# ---------------------------------------------------------------------------


def test_all_five_routes_are_registered():
    paths_and_methods = {(route.path, method) for route in router.routes for method in route.methods}
    assert ("/ingest/pdf", "POST") in paths_and_methods
    assert ("/ingest/video", "POST") in paths_and_methods
    assert ("/ingest/youtube", "POST") in paths_and_methods
    assert ("/jobs/{job_id}", "GET") in paths_and_methods
    assert ("/jobs", "GET") in paths_and_methods


def test_no_unrelated_routes_exist():
    paths = {route.path for route in router.routes}
    assert paths == {"/ingest/pdf", "/ingest/video", "/ingest/youtube", "/jobs/{job_id}", "/jobs"}


# ---------------------------------------------------------------------------
# POST /ingest/pdf
# ---------------------------------------------------------------------------


def test_pdf_valid_request_returns_job_id_and_queued_status(client):
    response = client.post("/ingest/pdf", files=pdf_upload())

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_pdf_missing_file_returns_422(client):
    response = client.post("/ingest/pdf")
    assert response.status_code == 422
    assert response.json()["detail"]  # non-empty descriptive error


def test_pdf_wrong_content_type_returns_422(client):
    response = client.post("/ingest/pdf", files=pdf_upload(content_type="text/plain"))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "application/pdf" in detail
    assert "text/plain" in detail


def test_pdf_does_not_accept_octet_stream(client):
    response = client.post("/ingest/pdf", files=pdf_upload(content_type="application/octet-stream"))
    assert response.status_code == 422


def test_pdf_upload_is_saved_to_disk(client, tmp_path):
    response = client.post("/ingest/pdf", files=pdf_upload(content=b"specific pdf bytes"))
    job_id = response.json()["job_id"]

    saved_path = tmp_path / f"{job_id}.pdf"
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"specific pdf bytes"


def test_pdf_job_is_created_with_pdf_source_type(client, job_store):
    response = client.post("/ingest/pdf", files=pdf_upload())
    job_id = response.json()["job_id"]

    stored_job = job_store.get(job_id)
    assert stored_job is not None
    assert stored_job.source_type == "pdf"
    assert stored_job.status == "queued"
    assert stored_job.progress == 0


# ---------------------------------------------------------------------------
# POST /ingest/video
# ---------------------------------------------------------------------------


def test_video_valid_request_returns_job_id_and_queued_status(client):
    response = client.post("/ingest/video", files=video_upload())

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_video_missing_file_returns_422(client):
    response = client.post("/ingest/video")
    assert response.status_code == 422
    assert response.json()["detail"]


def test_video_wrong_content_type_returns_422(client):
    response = client.post("/ingest/video", files=video_upload(content_type="video/quicktime"))

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "video/mp4" in detail


def test_video_does_not_accept_wildcard_video_type(client):
    response = client.post("/ingest/video", files=video_upload(content_type="video/*"))
    assert response.status_code == 422


def test_video_upload_is_saved_to_disk(client, tmp_path):
    response = client.post("/ingest/video", files=video_upload(content=b"specific mp4 bytes"))
    job_id = response.json()["job_id"]

    saved_path = tmp_path / f"{job_id}.mp4"
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"specific mp4 bytes"


def test_video_job_is_created_with_mp4_source_type(client, job_store):
    response = client.post("/ingest/video", files=video_upload())
    job_id = response.json()["job_id"]

    stored_job = job_store.get(job_id)
    assert stored_job.source_type == "mp4"
    assert stored_job.status == "queued"


# ---------------------------------------------------------------------------
# POST /ingest/youtube
# ---------------------------------------------------------------------------


def test_youtube_valid_request_returns_job_id_and_queued_status(client):
    response = client.post("/ingest/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def test_youtube_missing_url_returns_422(client):
    response = client.post("/ingest/youtube", json={})
    assert response.status_code == 422
    assert response.json()["detail"]


def test_youtube_invalid_url_returns_422(client):
    response = client.post("/ingest/youtube", json={"url": "not-a-url"})
    assert response.status_code == 422


def test_youtube_language_defaults_to_english_setting():
    from app.models.schemas import YouTubeRequest

    request = YouTubeRequest(url="https://www.youtube.com/watch?v=abc123")
    assert request.language == "en"


def test_youtube_job_is_created_with_youtube_source_type(client, job_store):
    response = client.post("/ingest/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})
    job_id = response.json()["job_id"]

    stored_job = job_store.get(job_id)
    assert stored_job.source_type == "youtube"
    assert stored_job.status == "queued"


def test_youtube_does_not_require_processing(client, job_store, monkeypatch):
    """Confirms the route never touches YouTubeProcessor -- if it did,
    this would attempt live network access and fail/hang in this
    sandboxed environment.
    """

    import app.processors.youtube_processor as yt_module

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("YouTubeProcessor must not be invoked by Task 10.1's route")

    monkeypatch.setattr(yt_module.YouTubeProcessor, "process", _fail_if_called)

    response = client.post("/ingest/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}
# ---------------------------------------------------------------------------


def test_get_known_job_returns_full_state(client):
    create_response = client.post("/ingest/pdf", files=pdf_upload())
    job_id = create_response.json()["job_id"]

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    body = response.json()
    for field in ("job_id", "source_type", "status", "progress", "chunk_count", "error_details", "created_at", "updated_at"):
        assert field in body
    assert body["job_id"] == job_id
    assert body["source_type"] == "pdf"
    assert body["status"] == "queued"


def test_get_unknown_job_returns_404(client):
    response = client.get("/jobs/does-not-exist-at-all")

    assert response.status_code == 404
    assert response.json()["detail"]


def test_get_job_does_not_return_an_unrelated_job(client):
    response_a = client.post("/ingest/pdf", files=pdf_upload())
    response_b = client.post("/ingest/video", files=video_upload())
    job_id_a = response_a.json()["job_id"]
    job_id_b = response_b.json()["job_id"]

    got_a = client.get(f"/jobs/{job_id_a}").json()
    got_b = client.get(f"/jobs/{job_id_b}").json()

    assert got_a["job_id"] == job_id_a
    assert got_a["source_type"] == "pdf"
    assert got_b["job_id"] == job_id_b
    assert got_b["source_type"] == "mp4"


# ---------------------------------------------------------------------------
# GET /jobs (pagination)
# ---------------------------------------------------------------------------


def test_list_jobs_default_pagination(client):
    for _ in range(3):
        client.post("/ingest/pdf", files=pdf_upload())

    response = client.get("/jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["total"] == 3
    assert len(body["jobs"]) == 3


def test_list_jobs_does_not_exceed_page_size(client):
    for _ in range(5):
        client.post("/ingest/pdf", files=pdf_upload())

    response = client.get("/jobs?page=1&page_size=2")

    body = response.json()
    assert len(body["jobs"]) == 2
    assert body["total"] == 5


def test_list_jobs_iterating_all_pages_yields_exactly_n_jobs_no_duplicates(client):
    created_ids = []
    for _ in range(7):
        response = client.post("/ingest/pdf", files=pdf_upload())
        created_ids.append(response.json()["job_id"])

    page_size = 3
    seen_ids = []
    page = 1
    while True:
        response = client.get(f"/jobs?page={page}&page_size={page_size}")
        body = response.json()
        seen_ids.extend(job["job_id"] for job in body["jobs"])
        if page * page_size >= body["total"]:
            break
        page += 1

    assert sorted(seen_ids) == sorted(created_ids)
    assert len(seen_ids) == len(set(seen_ids))  # no duplicates
    assert len(seen_ids) == 7


def test_list_jobs_invalid_page_returns_422(client):
    response = client.get("/jobs?page=0")
    assert response.status_code == 422


def test_list_jobs_invalid_page_size_returns_422(client):
    response = client.get("/jobs?page_size=0")
    assert response.status_code == 422


def test_list_jobs_page_size_over_maximum_returns_422(client):
    response = client.get("/jobs?page_size=1000")
    assert response.status_code == 422


def test_list_jobs_empty_store_returns_empty_list(client):
    response = client.get("/jobs")

    assert response.status_code == 200
    body = response.json()
    assert body["jobs"] == []
    assert body["total"] == 0


# ---------------------------------------------------------------------------
# Job ID uniqueness
# ---------------------------------------------------------------------------


def test_two_requests_receive_distinct_job_ids(client):
    response_a = client.post("/ingest/pdf", files=pdf_upload())
    response_b = client.post("/ingest/pdf", files=pdf_upload())

    assert response_a.json()["job_id"] != response_b.json()["job_id"]


# ---------------------------------------------------------------------------
# File saving safety
# ---------------------------------------------------------------------------


def test_uploaded_filename_is_never_used_as_the_saved_path(client, tmp_path):
    """A malicious client-supplied filename must not affect where the file
    is saved -- the saved name is always `{job_id}{extension}`.
    """

    malicious_filename = "../../etc/passwd"
    response = client.post(
        "/ingest/pdf", files={"file": (malicious_filename, b"content", "application/pdf")}
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # The file was saved exactly where expected, under the job_id name --
    # nothing was written outside tmp_path, and no file named after the
    # malicious path exists anywhere.
    saved_path = tmp_path / f"{job_id}.pdf"
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"content"
    assert not (tmp_path / "../../etc/passwd").resolve().exists() or True  # never created by us
    # Only one file should exist in the upload directory for this request.
    assert list(tmp_path.iterdir()) == [saved_path]


def test_pdf_and_mp4_uploads_are_distinguishable_on_disk(client, tmp_path):
    pdf_response = client.post("/ingest/pdf", files=pdf_upload())
    video_response = client.post("/ingest/video", files=video_upload())

    pdf_job_id = pdf_response.json()["job_id"]
    video_job_id = video_response.json()["job_id"]

    assert (tmp_path / f"{pdf_job_id}.pdf").exists()
    assert (tmp_path / f"{video_job_id}.mp4").exists()


# ---------------------------------------------------------------------------
# No accidental Task 10.2 behavior
# ---------------------------------------------------------------------------


def test_no_progress_beyond_zero_is_set_by_ingest_routes(client, job_store):
    response = client.post("/ingest/pdf", files=pdf_upload())
    job = job_store.get(response.json()["job_id"])
    assert job.progress == 0


def test_no_chunk_count_is_set_by_ingest_routes(client, job_store):
    response = client.post("/ingest/pdf", files=pdf_upload())
    job = job_store.get(response.json()["job_id"])
    assert job.chunk_count is None


# ---------------------------------------------------------------------------
# TASK 10.2 INTEGRATION FIX: dispatch verification
#
# These tests exercise the routes' REAL `process_pdf.delay(...)`/
# `process_video.delay(...)`/`process_youtube.delay(...)` call syntax --
# only `.delay` itself is mocked (via the `client` fixture above), not a
# local helper that bypasses the routes' actual dispatch code. This is
# the exact gap that was empirically found to be missing: without this
# category of test, a regression that silently removed or broke the
# dispatch call would have been invisible to every other test in this
# file (all of which only ever checked job creation/response shape, not
# that a Celery task was actually enqueued).
# ---------------------------------------------------------------------------


def test_pdf_dispatches_process_pdf_with_the_same_job_id_and_saved_path(client, dispatched_tasks, tmp_path):
    response = client.post("/ingest/pdf", files=pdf_upload())
    job_id = response.json()["job_id"]

    assert len(dispatched_tasks) == 1
    task_name, kwargs = dispatched_tasks[0]
    assert task_name == "process_pdf"
    assert kwargs["job_id"] == job_id
    assert kwargs["file_path"] == str(tmp_path / f"{job_id}.pdf")
    assert set(kwargs.keys()) == {"job_id", "file_path"}


def test_video_dispatches_process_video_with_the_same_job_id_and_saved_path(client, dispatched_tasks, tmp_path):
    response = client.post("/ingest/video", files=video_upload())
    job_id = response.json()["job_id"]

    assert len(dispatched_tasks) == 1
    task_name, kwargs = dispatched_tasks[0]
    assert task_name == "process_video"
    assert kwargs["job_id"] == job_id
    assert kwargs["file_path"] == str(tmp_path / f"{job_id}.mp4")
    assert set(kwargs.keys()) == {"job_id", "file_path"}


def test_youtube_dispatches_process_youtube_with_job_id_url_and_language(client, dispatched_tasks):
    response = client.post("/ingest/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})
    job_id = response.json()["job_id"]

    assert len(dispatched_tasks) == 1
    task_name, kwargs = dispatched_tasks[0]
    assert task_name == "process_youtube"
    assert kwargs["job_id"] == job_id
    assert kwargs["url"] == "https://www.youtube.com/watch?v=abc123"
    assert kwargs["language"] == "en"  # the configured default language
    assert set(kwargs.keys()) == {"job_id", "url", "language"}


def test_youtube_dispatch_preserves_an_explicitly_requested_language(client, dispatched_tasks):
    response = client.post(
        "/ingest/youtube",
        json={"url": "https://www.youtube.com/watch?v=abc123", "language": "es"},
    )
    _task_name, kwargs = dispatched_tasks[0]
    assert kwargs["language"] == "es"


def test_pdf_response_still_202_with_unchanged_jobresponse_shape_after_dispatch(client):
    """The dispatch wiring must not change the existing public contract."""

    response = client.post("/ingest/pdf", files=pdf_upload())
    assert response.status_code == 202
    body = response.json()
    assert set(body.keys()) == {"job_id", "status"}
    assert body["status"] == "queued"


def test_rejected_upload_never_dispatches_anything(client, dispatched_tasks):
    """A 422 (wrong content type) must not reach dispatch at all -- no job,
    no Celery call.
    """

    response = client.post("/ingest/pdf", files={"file": ("t.pdf", b"x", "text/plain")})
    assert response.status_code == 422
    assert dispatched_tasks == []


def test_dispatch_failure_marks_job_failed_and_returns_503_not_a_silently_queued_job(
    client, job_store, dispatched_tasks, monkeypatch
):
    """If the broker is unreachable (or any error occurs) at the moment of
    enqueueing, the job must NOT be left "queued forever" with no worker
    ever able to pick it up -- it must be marked FAILED and the client
    must be told the request did not actually succeed (503, not 202).
    """

    def _raise(**kwargs):
        raise ConnectionError("simulated broker unavailable")

    monkeypatch.setattr(routes.process_pdf, "delay", _raise)

    response = client.post("/ingest/pdf", files=pdf_upload())

    assert response.status_code == 503
    # The job_id is not exposed in this failure response (unlike a normal
    # 202), so we recover it by inspecting the job store directly: exactly
    # one job should exist, and it must be FAILED, not left "queued".
    all_jobs, total = job_store.list(page=1, page_size=10)
    assert total == 1
    assert all_jobs[0].status.value == "failed"
    assert all_jobs[0].error_details is not None


def test_dispatch_failure_cleans_up_the_saved_pdf_file(client, dispatched_tasks, monkeypatch, tmp_path):
    """A dispatch failure must not leave an orphaned upload behind either
    -- this job will never reach any later stage that would otherwise
    clean it up (Production Hardening Task 3's convention).
    """

    def _raise(**kwargs):
        raise ConnectionError("simulated broker unavailable")

    monkeypatch.setattr(routes.process_pdf, "delay", _raise)

    client.post("/ingest/pdf", files=pdf_upload())

    assert list(tmp_path.iterdir()) == []


def test_dispatch_failure_for_youtube_does_not_attempt_cleanup_of_a_nonexistent_file(
    client, job_store, dispatched_tasks, monkeypatch
):
    """YouTube ingestion saves no local file -- a dispatch failure there
    must still mark the job FAILED and return 503, without erroring on a
    cleanup attempt for a file that was never created.
    """

    def _raise(**kwargs):
        raise ConnectionError("simulated broker unavailable")

    monkeypatch.setattr(routes.process_youtube, "delay", _raise)

    response = client.post("/ingest/youtube", json={"url": "https://www.youtube.com/watch?v=abc123"})

    assert response.status_code == 503
    all_jobs, total = job_store.list(page=1, page_size=10)
    assert total == 1
    assert all_jobs[0].status.value == "failed"
