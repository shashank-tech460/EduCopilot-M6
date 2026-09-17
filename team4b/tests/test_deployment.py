"""Focused tests for Task 11.1's deployment configuration.

Scope: BEHAVIORAL checks on the Dockerfile/docker-compose.yml/
docker-compose.dev.yml/.dockerignore content, plus real `Settings`
construction from environment variables shaped exactly like what these
files inject -- not "file exists" trivia. No `docker` binary is
available in this sandbox (confirmed: `which docker` -> not found), so
these tests cannot build or run an actual container; see this task's
report for exactly what could and could not be verified, and how.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    path = _REPO_ROOT / relative_path
    assert path.is_file(), f"expected {relative_path!r} to exist at the repo root"
    return path.read_text()


# ---------------------------------------------------------------------------
# Required files present (a minimal baseline check -- everything else in
# this file tests actual CONTENT/behavior, not just existence)
# ---------------------------------------------------------------------------


class TestRequiredFilesPresent:
    @pytest.mark.parametrize(
        "relative_path",
        ["Dockerfile", ".dockerignore", "docker-compose.yml", "docker-compose.dev.yml", ".env.docker.example"],
    )
    def test_file_exists(self, relative_path: str) -> None:
        assert (_REPO_ROOT / relative_path).is_file()


# ---------------------------------------------------------------------------
# Dockerfile: behavioral content checks
# ---------------------------------------------------------------------------


class TestDockerfileContent:
    def test_uses_a_supported_python_version(self) -> None:
        content = _read("Dockerfile")
        # The application itself requires Python 3.10+ (uses `X | None`
        # union syntax and `from __future__ import annotations`
        # throughout -- confirmed directly against app/core/config.py).
        assert "python:3.12-slim" in content

    def test_is_a_multi_stage_build(self) -> None:
        content = _read("Dockerfile")
        assert content.count("FROM python:3.12-slim") == 2
        assert "AS builder" in content
        assert "AS runtime" in content

    def test_final_stage_runs_as_non_root(self) -> None:
        content = _read("Dockerfile")
        assert "USER appuser" in content
        # The non-root USER directive must be the LAST USER directive in
        # the file (i.e., nothing switches back to root afterward).
        user_lines = [line for line in content.splitlines() if line.strip().startswith("USER ")]
        assert user_lines[-1].strip() == "USER appuser"

    def test_does_not_run_with_reload(self) -> None:
        content = _read("Dockerfile")
        cmd_lines = [line for line in content.splitlines() if line.strip().startswith("CMD ")]
        assert cmd_lines, "expected at least one CMD instruction"
        assert not any("--reload" in line for line in cmd_lines)

    def test_exposes_the_application_port(self) -> None:
        content = _read("Dockerfile")
        assert "EXPOSE 8000" in content

    def test_startup_command_matches_the_real_application_entrypoint(self) -> None:
        content = _read("Dockerfile")
        assert 'CMD ["uvicorn", "app.api.main:app"' in content

    def test_healthcheck_targets_the_real_health_endpoint(self) -> None:
        content = _read("Dockerfile")
        assert "HEALTHCHECK" in content
        assert "/health" in content
        # Must not invent a second, different health path.
        assert "/healthz" not in content
        assert "/livez" not in content

    def test_healthcheck_checks_http_status_only_not_the_json_body(self) -> None:
        # Task 10.1/P19: GET /health always returns HTTP 200, with
        # degradation represented in the response BODY. The Dockerfile's
        # own HEALTHCHECK must not contradict that by treating a 200
        # response with a "degraded" body as a container failure --
        # verified here by confirming the healthcheck's own CMD line (not
        # the surrounding explanatory comments, which legitimately
        # discuss "degraded" in prose) only inspects `.status`, never the
        # response body content.
        content = _read("Dockerfile")
        healthcheck_lines = [
            line for line in content.splitlines() if "HEALTHCHECK" in line or line.strip().startswith("CMD python -c")
        ]
        healthcheck_block = "\n".join(healthcheck_lines)
        assert ".status == 200" in healthcheck_block
        assert "degraded" not in healthcheck_block.lower()
        assert "json" not in healthcheck_block.lower()

    def test_no_obvious_secret_literal_is_baked_in(self) -> None:
        content = _read("Dockerfile").lower()
        for forbidden in ("api_key=sk-", "password=", "secret=", "bearer "):
            assert forbidden not in content

    def test_only_copies_the_actual_application_directories(self) -> None:
        content = _read("Dockerfile")
        # Must not copy tests/ or hidden VCS/env files into the image.
        assert "COPY tests" not in content
        assert "COPY .git" not in content
        assert "COPY .env" not in content

    def test_huggingface_sentence_transformers_cache_is_configured_to_a_writable_path(self) -> None:
        # CORRECTIVE FIX: real Docker runtime verification found
        # `SentenceTransformer(...)` failing with
        # `PermissionError: [Errno 13] Permission denied: '/home/appuser'`
        # on the first real query, because `useradd --no-create-home`
        # leaves appuser's HOME pointing at a `/home/appuser` that is
        # never created and can't be created by a non-root user under
        # root-owned `/home`. Every cache-location environment variable
        # sentence-transformers/huggingface_hub actually consults must
        # point somewhere already writable by appuser instead.
        content = _read("Dockerfile")
        assert "HF_HOME=/app/.cache/huggingface" in content
        assert "SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface" in content
        assert "TRANSFORMERS_CACHE=/app/.cache/huggingface" in content

    def test_home_is_redirected_away_from_the_unwritable_default(self) -> None:
        content = _read("Dockerfile")
        assert "HOME=/app" in content
        # The literal broken path from the real traceback must never
        # appear as a configured VALUE (comments are allowed to
        # reference it when explaining the fix, as this file's own
        # corrective-fix comment does) -- checked against actual
        # instruction lines only, not commentary.
        instruction_lines = [line for line in content.splitlines() if not line.strip().startswith("#")]
        instruction_text = "\n".join(instruction_lines)
        assert "/home/appuser" not in instruction_text

    def test_the_cache_directory_is_created_and_chowned_before_switching_to_the_non_root_user(self) -> None:
        content = _read("Dockerfile")
        lines = content.splitlines()
        mkdir_index = next(i for i, line in enumerate(lines) if "mkdir -p" in line and ".cache/huggingface" in line)
        user_index = next(i for i, line in enumerate(lines) if line.strip() == "USER appuser")
        assert mkdir_index < user_index, "the cache directory must be created/chowned BEFORE switching to appuser"
        # The mkdir line itself must also chown -- not just create the
        # directory as root and leave it root-owned.
        assert "chown" in lines[mkdir_index]

    def test_still_runs_as_non_root_after_the_fix(self) -> None:
        # The corrective fix must not have reintroduced root execution
        # as a shortcut to "fixing" the permission error.
        content = _read("Dockerfile")
        user_lines = [line for line in content.splitlines() if line.strip().startswith("USER ")]
        assert user_lines[-1].strip() == "USER appuser"
        assert "USER root" not in content


# ---------------------------------------------------------------------------
# .dockerignore: behavioral content checks
# ---------------------------------------------------------------------------


class TestDockerignoreContent:
    def test_excludes_version_control_and_caches(self) -> None:
        content = _read(".dockerignore")
        for expected in (".git", "__pycache__", ".pytest_cache", ".mypy_cache"):
            assert expected in content

    def test_excludes_real_env_files_but_not_examples(self) -> None:
        content = _read(".dockerignore")
        assert ".env" in content
        assert "!.env.example" in content

    def test_excludes_tests_directory(self) -> None:
        content = _read(".dockerignore")
        assert "tests" in content.splitlines()


# ---------------------------------------------------------------------------
# docker-compose.yml (production-oriented): behavioral content checks
# ---------------------------------------------------------------------------


class TestProductionComposeFile:
    def _load(self) -> dict:
        with open(_REPO_ROOT / "docker-compose.yml") as f:
            return yaml.safe_load(f)

    def test_yaml_parses(self) -> None:
        data = self._load()
        assert "services" in data

    def test_defines_exactly_the_team4b_api_service(self) -> None:
        data = self._load()
        assert set(data["services"].keys()) == {"team4b-api"}

    def test_does_not_bundle_qdrant_redis_or_ollama_containers(self) -> None:
        # Per this task's explicit architecture: Qdrant/Redis/Ollama are
        # external infrastructure Team 4B connects to via configured
        # URLs, not services this compose file owns/starts.
        data = self._load()
        service_names = set(data["services"].keys())
        assert not any("qdrant" in name for name in service_names)
        assert not any("redis" in name for name in service_names)
        assert not any("ollama" in name for name in service_names)

    def test_required_urls_have_no_silent_localhost_fallback(self) -> None:
        env = self._load()["services"]["team4b-api"]["environment"]
        for key in ("QDRANT_URL", "REDIS_URL", "OLLAMA_URL"):
            value = env[key]
            # Uses the ":?" required-variable syntax (fails fast with a
            # message if unset) rather than ":-http://localhost:...".
            assert ":?" in value
            assert "localhost" not in value

    def test_production_collection_name_default_is_the_approved_one(self) -> None:
        env = self._load()["services"]["team4b-api"]["environment"]
        assert "team4b_shared_production_chunks" in env["QDRANT_COLLECTION_NAME"]
        assert "team4a_ingested_chunks" not in env["QDRANT_COLLECTION_NAME"]

    def test_embedding_configuration_matches_the_approved_contract(self) -> None:
        env = self._load()["services"]["team4b-api"]["environment"]
        assert "384" in env["EMBEDDING_DIMENSIONS"]
        assert "Cosine" in env["EMBEDDING_DISTANCE"]
        assert "all-MiniLM-L6-v2" in env["EMBEDDING_MODEL_NAME"]

    def test_no_container_name_collides_with_team_4a(self) -> None:
        data = self._load()
        service = data["services"]["team4b-api"]
        container_name = service.get("container_name", "")
        assert not container_name.startswith("4a-service")

    def test_volume_names_do_not_collide_with_team_4a_volumes(self) -> None:
        data = self._load()
        volume_names = set(data.get("volumes", {}).keys())
        assert "4a-service_qdrant_storage" not in volume_names
        assert "4a-service_redis_data" not in volume_names
        # And they should be clearly Team-4B-owned.
        assert all(name.startswith("team4b") for name in volume_names)

    def test_does_not_publish_a_database_port_to_the_host(self) -> None:
        # This compose file only runs the API container, so there is no
        # database service to accidentally expose -- verified structurally.
        data = self._load()
        for service_name, service in data["services"].items():
            for port_mapping in service.get("ports", []):
                # The only published port should be the API's own 8000.
                assert port_mapping.endswith(":8000")


# ---------------------------------------------------------------------------
# docker-compose.dev.yml (isolated development stack)
# ---------------------------------------------------------------------------


class TestDevComposeFile:
    def _load(self) -> dict:
        with open(_REPO_ROOT / "docker-compose.dev.yml") as f:
            return yaml.safe_load(f)

    def test_yaml_parses(self) -> None:
        data = self._load()
        assert "services" in data

    def test_bundles_its_own_isolated_dependencies(self) -> None:
        data = self._load()
        service_names = set(data["services"].keys())
        assert {"team4b-dev-api", "team4b-dev-qdrant", "team4b-dev-redis", "team4b-dev-ollama"} == service_names

    def test_service_urls_use_service_dns_names_not_localhost(self) -> None:
        data = self._load()
        env = data["services"]["team4b-dev-api"]["environment"]
        assert "localhost" not in env["QDRANT_URL"]
        assert "localhost" not in env["REDIS_URL"]
        assert "localhost" not in env["OLLAMA_URL"]
        assert "team4b-dev-qdrant" in env["QDRANT_URL"]
        assert "team4b-dev-redis" in env["REDIS_URL"]
        assert "team4b-dev-ollama" in env["OLLAMA_URL"]

    def test_all_names_are_distinct_from_team_4a_and_production_compose(self) -> None:
        data = self._load()
        all_names = set(data["services"].keys()) | set(data.get("volumes", {}).keys())
        for name in all_names:
            assert not name.startswith("4a-service")
            assert not name.startswith("team4b-evaluation")  # the PRODUCTION compose file's volume name


# ---------------------------------------------------------------------------
# .env.docker.example: content checks
# ---------------------------------------------------------------------------


class TestEnvDockerExample:
    def test_contains_no_localhost_for_qdrant_or_redis(self) -> None:
        content = _read(".env.docker.example")
        for line in content.splitlines():
            if line.startswith("QDRANT_URL=") or line.startswith("REDIS_URL="):
                assert "localhost" not in line

    def test_contains_no_obvious_real_secret(self) -> None:
        content = _read(".env.docker.example").lower()
        for forbidden in ("password=", "api_key=sk-", "secret=", "token="):
            assert forbidden not in content

    def test_references_the_approved_production_collection_name(self) -> None:
        content = _read(".env.docker.example")
        assert "team4b_shared_production_chunks" in content


# ---------------------------------------------------------------------------
# REAL behavioral check: Settings actually reads the exact environment
# variables these Docker files inject -- not just static file content.
# ---------------------------------------------------------------------------


class TestSettingsReadsDockerStyleEnvironmentVariables:
    def test_settings_picks_up_docker_compose_style_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Simulates exactly the environment docker-compose.yml would
        # inject into the container (service DNS names, never localhost).
        monkeypatch.setenv("QDRANT_URL", "http://4a-service-qdrant-1:6333")
        monkeypatch.setenv("REDIS_URL", "redis://4a-service-redis-1:6379/0")
        monkeypatch.setenv("OLLAMA_URL", "http://host.docker.internal:11434")
        monkeypatch.setenv("QDRANT_COLLECTION_NAME", "team4b_shared_production_chunks")
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        assert settings.qdrant_url == "http://4a-service-qdrant-1:6333"
        assert settings.redis_url == "redis://4a-service-redis-1:6379/0"
        assert settings.ollama_url == "http://host.docker.internal:11434"
        assert settings.qdrant_collection_name == "team4b_shared_production_chunks"
        assert settings.environment == "production"
        assert settings.log_level == "INFO"

    def test_settings_defaults_remain_the_approved_production_values(self) -> None:
        # Without ANY environment override -- confirms the compose
        # file's own ${VAR:-default} fallbacks match Settings' real
        # defaults, so an operator who omits an optional variable still
        # gets the approved configuration.
        settings = Settings(_env_file=None)  # type: ignore[call-arg]

        assert settings.qdrant_collection_name == "team4b_shared_production_chunks"
        assert settings.embedding_dimensions == 384
        assert settings.embedding_distance == "Cosine"
        assert settings.embedding_model_name == "all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# REAL behavioral check: the actual importable module-level `app` object
# (exactly what `CMD ["uvicorn", "app.api.main:app", ...]` runs) serves
# /health and /metrics -- not a test-local create_app() copy.
# ---------------------------------------------------------------------------


class TestRealEntrypointServesHealthAndMetrics:
    def test_the_real_module_level_app_object_has_health_and_metrics_registered(self) -> None:
        from app.api.main import app as real_app

        openapi_paths = set(real_app.openapi()["paths"].keys())
        assert "/health" in openapi_paths
        assert "/metrics" in openapi_paths

    def test_the_real_module_level_app_object_serves_health_over_http(self) -> None:
        from fastapi.testclient import TestClient

        from app.api.main import app as real_app

        client = TestClient(real_app)
        response = client.get("/health")

        assert response.status_code == 200
        assert "status" in response.json()

    def test_the_real_module_level_app_object_serves_metrics_over_http(self) -> None:
        from fastapi.testclient import TestClient

        from app.api.main import app as real_app

        client = TestClient(real_app)
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "query_count" in response.json()
