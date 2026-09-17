"""Team 4B FastAPI application entry point (Tasks 8.1, 9.1).

Minimal application factory + module-level `app` instance for
`uvicorn app.api.main:app`. Registers Task 8.1's two routes
(`POST /api/v1/query`, `GET /api/v1/sessions/{session_id}/history`) and
Task 9.1's evaluation route (`POST /api/v1/evaluate`) -- no `/health` or
`/metrics` (Task 10.1), and no Docker/deployment configuration (Task
11.1). Those are explicitly out of scope and are not added here as
placeholders.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import router


def create_app() -> FastAPI:
    """Build a fresh FastAPI application with Task 8.1's routes
    registered. A factory function (rather than only a module-level
    `app`) so tests can construct independent app instances and apply
    their own `dependency_overrides` without interference between
    tests.
    """

    application = FastAPI(title="Team 4B — Advanced RAG & Semantic Search")
    application.include_router(router)
    return application


app = create_app()
