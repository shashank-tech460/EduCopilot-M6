"""Production Hardening Task 6: request-ID/correlation and API request logging.

A small, dedicated ASGI middleware -- kept separate from app/api/routes.py
and app/api/health.py so neither of those (the five official ingestion
endpoints, and the health/readiness endpoints) needs any code change at
all to gain request logging; it is applied once, at the app-assembly
level (app/main.py).

Purely observational: adds one response header (`X-Request-ID`) and
emits one log line per request. Never changes a status code, a response
body, or any validation/business-logic outcome.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.logging_config import request_id_var

logger = logging.getLogger("app.request")

#: Successful health/readiness checks are expected to happen frequently
#: (e.g. every few seconds from a Docker/Kubernetes probe) and are not
#: interesting on their own -- Requirement 9 asks that these not be
#: logged at INFO level. A failing readiness check (>=400) is still
#: logged at INFO/WARNING via the normal path below, since that IS
#: operationally interesting.
_QUIET_PATHS = frozenset({"/health", "/readyz"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming_request_id = request.headers.get("x-request-id")
        req_id = incoming_request_id if incoming_request_id else str(uuid.uuid4())
        token = request_id_var.set(req_id)

        start = time.monotonic()
        try:
            response = await call_next(request)
            duration_ms = round((time.monotonic() - start) * 1000, 2)
            response.headers["X-Request-ID"] = req_id

            is_quiet = request.url.path in _QUIET_PATHS and response.status_code < 400
            level = logging.DEBUG if is_quiet else logging.INFO
            logger.log(
                level,
                "request handled",
                extra={
                    "http_method": request.method,
                    "http_path": request.url.path,
                    "http_status": response.status_code,
                    "duration_ms": duration_ms,
                    "request_id": req_id,
                },
            )
            return response
        finally:
            request_id_var.reset(token)
