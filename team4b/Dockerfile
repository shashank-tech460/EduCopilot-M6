# Team 4B — Advanced RAG & Semantic Search (Task 11.1)
#
# Multi-stage build: a "builder" stage with build tooling installs
# Python dependencies into a virtualenv; the final "runtime" stage
# copies only that virtualenv and the application source, with no
# compilers/build tooling left in the shipped image.
#
# BASE IMAGE / PYTHON VERSION: python:3.12-slim, not 3.13. The
# reviewer's laptop interpreter (used to run pytest/mypy OUTSIDE this
# container) is reported as Python 3.13, but the container's own
# interpreter is fully self-contained and independent of that -- 3.12
# was chosen deliberately over 3.13 for broader, more mature current
# wheel availability for this project's heavier ML dependency
# (sentence-transformers -> torch), reducing the risk of a dependency
# needing to compile from source during the image build. This codebase
# itself only requires Python 3.10+ (uses `from __future__ import
# annotations` plus `X | None` union syntax throughout) -- confirmed by
# inspecting app/core/config.py and every service module directly, not
# assumed.
#
# CPU-ONLY TORCH: `sentence-transformers` (a runtime dependency, used by
# app/services/embedder.py) pulls in PyTorch as a transitive dependency.
# Installing the default (CUDA-enabled) PyTorch build inside a container
# that only ever runs CPU inference (this application never uses a GPU)
# would needlessly bloat the image by roughly a gigabyte. The CPU-only
# wheel index is used instead -- mirroring Team 4A's own already-
# established "CPU-only PyTorch Docker hardening" practice for the exact
# same dependency, applied here independently (this Dockerfile is not
# shared with, and does not modify, Team 4A's own Dockerfile).
#
# IMPORTANT, HONESTLY STATED LIMITATION: this Dockerfile has been
# reviewed carefully against the actual application source (entrypoint,
# dependencies, filesystem paths) but `docker build`/`docker run` could
# NOT be executed in the sandbox this was authored in -- no `docker`
# binary is installed there at all (confirmed: `which docker` -> not
# found). See this task's report for exactly what was and was not
# verified, and how.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

# build-essential: some transitive dependencies (e.g. grpcio, a
# qdrant-client dependency) may need to compile from source if no
# prebuilt wheel matches the exact platform/Python combination. Present
# only in this discarded builder stage, never in the final image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build

# Copy only dependency manifests first so this (slow) layer is cached
# across rebuilds that only change application source, not dependencies.
COPY requirements.txt ./

# CPU-only PyTorch first (see module-level comment above), then the
# project's own declared runtime dependencies -- exactly what
# requirements.txt lists, nothing manually added outside it.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root runtime user. No login shell, no home-directory surprises --
# just an unprivileged UID/GID to run the application process as.
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --no-create-home appuser

# CORRECTIVE FIX (Task 11.1 post-verification): `useradd --no-create-home`
# still leaves appuser's passwd entry pointing at `/home/appuser` as its
# HOME directory (useradd's own default, per this base image's
# /etc/default/useradd) -- it just never creates that directory on disk.
# `/home` itself is root-owned, so appuser can never create
# `/home/appuser` at runtime. sentence-transformers' underlying
# huggingface_hub library resolves its model cache location from
# `HF_HOME` if set, else falls back to `~/.cache/huggingface` --
# `~` expands via HOME, so with no HF_HOME set this resolved to
# `/home/appuser/.cache/huggingface` and failed with exactly
# `PermissionError: [Errno 13] Permission denied: '/home/appuser'`
# during `SentenceTransformer(...)` initialization on the first real
# `POST /api/v1/query` -- confirmed by real Docker runtime verification
# on Windows, not caught earlier because this sandbox has no `docker`
# binary to run the image at all (see this task's original report).
#
# Fix: give appuser an explicit, writable HOME under the already-chowned
# `/app` tree, and set every cache-location environment variable
# sentence-transformers/huggingface_hub actually consults (HF_HOME
# covers current huggingface_hub versions; TRANSFORMERS_CACHE and
# SENTENCE_TRANSFORMERS_HOME are set too for defense-in-depth against
# older/alternate resolution paths within the same dependency chain) --
# so no library ever needs to touch `/home/appuser` in the first place.
# No embedding/retrieval application code was touched; Embedder (Task
# 3.1) never hardcodes a cache path itself, it only ever constructs
# `SentenceTransformer(settings.embedding_model_name)` and lets the
# library resolve its own cache location from these environment
# variables -- confirmed by re-reading app/services/embedder.py.
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/app \
    HF_HOME=/app/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Only the actual application package + declared dependency manifests +
# the docs this project already ships -- never tests, caches, git
# metadata, or local .env files (see .dockerignore for the exact
# exclusion list).
COPY app ./app
COPY requirements.txt ./
COPY docs ./docs
COPY README.md ./

# Pre-create the evaluation-output directory (Settings.evaluation_results_path
# defaults to "data/evaluation_results.jsonl", relative to the working
# directory) with correct ownership. JSONLEvaluationStore itself already
# creates this directory on first write (mkdir(parents=True,
# exist_ok=True) -- confirmed by reading app/services/evaluation.py
# directly) even without this line, but pre-creating it here makes the
# expected writable path explicit and avoids relying on that fallback.
# For real persistence across container replacement, mount a volume at
# /app/data (see docker-compose.yml).
#
# Also pre-create the Hugging Face/sentence-transformers model cache
# directory referenced by HF_HOME/SENTENCE_TRANSFORMERS_HOME/
# TRANSFORMERS_CACHE above (the corrective fix) -- both directories are
# under /app, so the single recursive chown below covers both; no
# broadened permissions elsewhere, no change to any other path's
# ownership or mode.
RUN mkdir -p /app/data /app/.cache/huggingface && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# HEALTHCHECK deliberately checks ONLY "does the process respond with
# HTTP 200", not "is the JSON body's status == healthy". GET /health
# ALWAYS returns HTTP 200 by design (Task 10.1/P19: downstream
# degradation is represented in the response BODY, never via a non-200
# status), and that is an intentional, already-approved API contract
# this Dockerfile must not silently contradict. If a Docker/orchestrator
# HEALTHCHECK instead failed the container whenever any one downstream
# dependency (Qdrant/Redis/Ollama) was briefly degraded, it would
# restart the Team 4B process itself -- which does nothing to fix an
# external dependency outage, and would cause pointless restart loops
# under exactly the conditions Task 10.1 designed /health to survive
# gracefully. This HEALTHCHECK therefore verifies container/process
# LIVENESS only; downstream dependency health remains the responsibility
# of whoever/whatever reads /health's response body (an operator, a
# dashboard, or a future monitoring task -- not Docker's own
# restart-on-failure mechanism).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0) if urllib.request.urlopen('http://localhost:8000/health', timeout=3).status == 200 else sys.exit(1)"

# No --reload (that is a development-only uvicorn flag and must never
# run in a production container). No debug flags. Deterministic startup
# command, matching exactly how this application already runs outside
# Docker (`uvicorn app.api.main:app`) -- confirmed directly against
# app/api/main.py's own module-level `app` instance, not inferred.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
