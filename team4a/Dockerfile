# Team 4A Multi-Modal Data Ingestion -- production image (Task 11.1).
#
# One image is shared by both the "api" and "worker" Compose services
# (see docker-compose.yml); only the container's start command differs.
# This mirrors how the application is actually structured -- there is
# one codebase, one set of dependencies, and Celery tasks import the same
# processors/pipeline modules the API does.

FROM python:3.12-slim

# System dependency: ffmpeg (+ ffprobe, bundled with it).
# Required by app/processors/video_processor.py (Task 3.1) for audio
# extraction, keyframe capture, and media probing, and by openai-whisper
# for audio decoding. `VideoProcessor` already raises a clear RuntimeError
# naming any missing ffmpeg/ffprobe binary rather than failing opaquely
# (see app/processors/video_processor.py:_require_ffmpeg) -- this install
# is what satisfies that requirement inside the container, so the
# application never has to fall back on a host-installed ffmpeg.
# "ffmpeg" is the correct Debian/Ubuntu package name (python:3.12-slim is
# Debian-based), matching what requirements.txt's own comment already
# documents for local (non-container) installs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# PRODUCTION HARDENING TASK 5: dedicated non-root application user/group.
#
# Fixed UID/GID (not auto-assigned) so ownership is deterministic and
# reproducible across rebuilds/hosts -- 10001 is comfortably outside
# Debian's reserved system-account range (< 1000) and isn't used by any
# default account in python:3.12-slim.
#
# `--create-home` is not cosmetic: sentence-transformers (via
# huggingface_hub), openai-whisper, and yt-dlp all default their runtime
# caches to paths under `$HOME/.cache/...` when no HF_HOME/XDG_CACHE_HOME
# override is configured (none is, in this project) -- without a real,
# writable home directory for this user, those libraries would fail to
# create their cache directories the first time they actually run.
# `--shell /usr/sbin/nologin`: this account only ever runs the
# application process (via CMD/the Compose `command:` override) -- it is
# not meant to be logged into interactively.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# PRODUCTION HARDENING TASK 7: force a CPU-only PyTorch install.
#
# Team 4A's official architecture requires CPU inference only (Settings'
# own embedding_device/whisper_device default to "cpu" throughout this
# project; no GPU/CUDA requirement exists anywhere in the Team 4A
# specification). However, neither openai-whisper nor sentence-transformers
# pins a CPU-vs-GPU build of torch -- they simply declare a plain "torch"
# dependency (verified directly against PyPI's JSON API before making
# this change: openai-whisper 20250625 requires "torch" with no version
# constraint at all; sentence-transformers 6.0.1, the version already
# used throughout this project, requires "torch>=2.2"). Left to its
# default resolution, `pip install torch` from PyPI installs the
# GPU-enabled build, which pulls several GB of NVIDIA CUDA/cuBLAS/cuDNN
# wheels neither this application nor its CPU-only inference requirement
# need -- this is exactly what caused a Docker build to crash containerd
# during image export in this environment.
#
# Fix: install a CPU-only torch build from PyTorch's own official CPU
# wheel index *before* installing requirements.txt. pip's resolver, when
# it later processes openai-whisper's/sentence-transformers' own "torch"
# dependency declarations, finds an already-installed version that
# satisfies both constraints (any current CPU wheel is well above 2.2)
# and reuses it rather than resolving/downloading PyPI's default
# CUDA-enabled build. No exact torch version is pinned here (per this
# task's own instruction not to pin arbitrary versions) -- PyTorch's CPU
# index always publishes a current, compatible CPU build for its latest
# stable release.
#
# This is also its own Docker layer, ordered before requirements.txt is
# even copied in, preserving (and slightly improving) the existing
# layer-caching strategy described below: neither an application code
# change nor a requirements.txt change invalidates this layer.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install Python dependencies first (separate layer) so an application
# code change doesn't force a full dependency reinstall on rebuild.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code, owned by the app user (not root) from the moment
# it's copied in.
COPY --chown=app:app app ./app

# Local fallback for Settings.upload_directory; docker-compose.yml
# overrides this via the UPLOAD_DIRECTORY environment variable to point
# at the shared volume both "api" and "worker" mount (see Task 10.1/10.2's
# file-saving contract in app/api/file_storage.py).
#
# IMPORTANT -- named-volume ownership caveat (explicitly flagged, not
# glossed over): Docker initializes a *newly created* named volume's
# contents (including ownership) from whatever already exists at that
# path in the image at first mount. Chowning `/data/uploads` to app:app
# here, before the "uploads" volume is ever created, is what makes a
# *fresh* deployment's volume come up already writable by the app user.
# This does NOT retroactively fix ownership on a volume that was already
# created and populated by an earlier, root-running version of this
# image -- an operator upgrading such an existing deployment would need
# to run a one-time `docker compose run --user root --rm worker chown -R
# app:app /data/uploads` (or equivalent) before switching to this image.
# No such pre-existing volume exists for this project today (Docker has
# never successfully built/run here -- see the Task 5 report), so this
# caveat is documented for future operators rather than acted on now.
RUN mkdir -p /data/uploads \
    && chown -R app:app /app /data

# Switch to the non-root user for everything from here on: no further
# root-owned files are created, and the application itself never runs as
# root.
USER app

# FastAPI port. The worker service does not listen on any port -- this
# EXPOSE only documents the api service's contract.
EXPOSE 8000

# Default command: the API service. docker-compose.yml overrides this
# with the Celery worker command for the "worker" service -- one image,
# two roles, matching how docker-compose.yml uses `build: .` for both.
# Both roles run as the "app" user set above; docker-compose.yml does not
# (and must not) override this back to root for either service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
