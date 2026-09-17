"""Team 4A FastAPI application entry point.

Task 11.1 gap identified during inspection (per that task's own explicit
instruction to check before assuming): no `FastAPI()` instance existed
anywhere in the repository. Task 10.1 deliberately created only an
`APIRouter` (app/api/routes.py) and had its own tests construct a
throwaway `FastAPI()` app around that router for `TestClient` use --
there was never a real, importable application object to run with
`uvicorn`.

This is the smallest possible entry point that fills that gap: it
assembles the existing router into one real `FastAPI` app and adds
nothing else (no new routes, no auth). Run with:

    uvicorn app.main:app --host 0.0.0.0 --port 8000

Production Hardening Task 4 additionally mounts `app.api.health`'s
router (GET /health, GET /readyz) alongside the existing ingestion/job
router -- a separate module and router so the five official ingestion
endpoints in app/api/routes.py remain completely untouched by this
addition.

Production Hardening Task 6 additionally configures structured logging
(app/logging_config.py) and adds `RequestLoggingMiddleware`
(app/api/logging_middleware.py) -- both purely observational, adding a
response header and log lines without changing any endpoint's behavior.
"""

import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.logging_middleware import RequestLoggingMiddleware
from app.api.canonical_ingest import canonical_router
from app.api.routes import router
from app.config.settings import get_settings
from app.logging_config import configure_logging

_settings = get_settings()
configure_logging(_settings.log_level)

_logger = logging.getLogger(__name__)
# Startup log: deliberately safe -- no Redis/Qdrant URLs, no credentials,
# no filesystem secrets. Just enough to confirm the process started and
# what log level it's running at.
_logger.info("Team 4A Ingestion Service starting", extra={"component": "api", "log_level": _settings.log_level})

app = FastAPI(title="Team 4A Ingestion Service")
app.add_middleware(RequestLoggingMiddleware)
app.include_router(router)
app.include_router(health_router)
app.include_router(canonical_router)
