"""Production Hardening Task 6: centralized, structured logging configuration.

PRIOR STATE (confirmed by inspection before writing this file): no
`logging.basicConfig()` or equivalent existed anywhere in the project --
only two ad hoc `logger = logging.getLogger(__name__)` module loggers
(`app/pipeline/publisher.py`, `app/tasks.py`), both preserved exactly as
they were (their existing call sites are untouched; this module only
adds a shared handler/formatter for the whole logger hierarchy, plus new,
purely additive log statements elsewhere). No diagnostic `print()` calls
existed in application code either.

DESIGN:
    - One JSON-lines formatter (stdlib `json` only -- no new dependency,
      per this task's explicit "prefer standard library" instruction).
      JSON's own string-escaping rules are what make this safe against
      log injection (Requirement 17): a newline, tab, or carriage return
      inside a logged value is escaped to `\\n`/`\\t`/`\\r` *within* the
      JSON string by `json.dumps` itself, never emitted as a literal
      line break that could forge a fake second log line.
    - `request_id`/`job_id` are `contextvars.ContextVar`s, injected into
      *every* log record automatically via a `logging.Filter` -- so any
      log statement anywhere in the codebase, existing or new, picks up
      the current request/job context without needing to pass it
      explicitly, and log statements that predate this task
      automatically gain this context "for free".
    - Key-name and value-shape based redaction (`_redact_extra_fields`)
      is a defense-in-depth layer, not the primary safety mechanism --
      the project's established pattern (Publisher.ping(), the YouTube/
      video/PDF error classifications) is to never let a secret reach a
      log/error call in the first place. This redacts anything that
      *does* reach it anyway (e.g. a field literally named "password",
      or a value shaped like `scheme://user:pass@host`).
    - `configure_logging()` is idempotent: repeated calls (e.g. the API
      and worker both eventually importing this module, or multiple test
      imports) never add a second handler -- a marker attribute on the
      handler is checked first (Requirement 12).
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
from typing import Any

#: Populated by app/api/logging_middleware.py for the duration of one
#: HTTP request; "-" outside of any request context.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

#: Populated by app/tasks.py for the duration of one Celery task
#: invocation; "-" outside of any task context.
job_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("job_id", default="-")

_HANDLER_MARKER = "_team4a_structured_handler"

_SENSITIVE_KEY_HINTS = ("password", "secret", "token", "api_key", "apikey", "credential", "authorization")

#: Matches a URL-shaped string with embedded userinfo credentials, e.g.
#: "redis://user:hunter2@host:6379" -- the exact shape a connection
#: string with an embedded password takes.
_CREDENTIAL_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.\-]*://[^\s/@]+:[^\s/@]+@")

_REDACTED = "[REDACTED]"

#: Standard LogRecord attributes -- excluded when copying "extra" fields
#: into the JSON payload, so only genuinely caller-supplied context
#: fields (job_id, http_status, etc.) are treated as structured extras.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=None, exc_info=None
    ).__dict__.keys()
) | {"message", "asctime", "request_id", "job_id"}


def _redact_value(key: str, value: Any) -> Any:
    """Redact a single extra-field value if its key or shape looks sensitive."""

    key_lower = key.lower()
    if any(hint in key_lower for hint in _SENSITIVE_KEY_HINTS):
        return _REDACTED
    if isinstance(value, str) and _CREDENTIAL_URL_PATTERN.search(value):
        return _REDACTED
    return value


class _JsonFormatter(logging.Formatter):
    """Formats every record as one JSON object per line.

    Always includes timestamp, level, logger name, message, request_id,
    and job_id; merges in any caller-supplied `extra=` fields (redacted
    per `_redact_value`); includes a formatted traceback when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "job_id": getattr(record, "job_id", "-"),
        }

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_ATTRS:
                continue
            payload[key] = _redact_value(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # `default=str` guarantees this never raises on an unexpected
        # extra-field type (e.g. a Path or a custom object) -- a logging
        # call must never itself crash the caller.
        return json.dumps(payload, default=str)


class _ContextFilter(logging.Filter):
    """Injects the current request_id/job_id into every record it sees."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.job_id = job_id_var.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    """Attach one JSON-lines stdout handler to the root logger, once.

    Safe to call multiple times (e.g. from both app/main.py and
    app/celery_app.py, or repeatedly across test imports): if a handler
    from a prior call is already present, only its level is updated --
    no second handler, and therefore no duplicated log lines, is ever
    added (Requirement 12).

    Logs to stdout (not a file) per Requirement 20 -- the container
    platform is expected to collect stdout/stderr; this works identically
    regardless of which user (root or the non-root `app` user from
    Production Hardening Task 5) the process runs as.

    PRODUCTION FIX (found via this task's own explicit "job-aware logs
    contain job_id" test requirement, not a cosmetic change): the
    request_id/job_id context filter is attached to the *root logger*
    itself (`root_logger.addFilter(...)`), not only to this module's own
    handler. A `logging.Filter` attached to a handler only decorates a
    record for *that* handler -- any other handler on the same logger
    (e.g. a second production handler an operator adds later, or
    pytest's own `caplog` capture handler, which attaches independently
    at the logger level) would never see the injected `job_id`/
    `request_id` attributes. Attaching the filter at the logger level
    means the record is decorated exactly once, before any handler runs,
    so every handler -- including ones this module doesn't know about --
    sees the same enriched record.
    """

    resolved_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()

    if not any(isinstance(f, _ContextFilter) for f in root_logger.filters):
        root_logger.addFilter(_ContextFilter())

    existing = next((h for h in root_logger.handlers if getattr(h, _HANDLER_MARKER, False)), None)
    if existing is not None:
        root_logger.setLevel(resolved_level)
        existing.setLevel(resolved_level)
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    setattr(handler, _HANDLER_MARKER, True)
    handler.setFormatter(_JsonFormatter())
    handler.setLevel(resolved_level)

    root_logger.addHandler(handler)
    root_logger.setLevel(resolved_level)
