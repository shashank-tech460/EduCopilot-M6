"""app.api package marker.

Task 10.1: app/api/routes.py implements the API boundary (request
validation, file saving, job-record bookkeeping) and dispatches each job
to the real Celery task (Task 10.2 Integration Fix).

Production Hardening Task 4: app/api/health.py implements the separate
operational health/readiness boundary (GET /health, GET /readyz).

CIRCULAR IMPORT FIX (found via a real Docker worker startup failure --
`celery -A app.celery_app worker` exited immediately with
`ImportError: cannot import name '_cleanup_upload' from partially
initialized module 'app.tasks'`): this file previously eagerly imported
`router` (from app.api.routes) and `health_router` (from app.api.health)
at package-init time. Nothing in this codebase ever consumed those
package-level re-exports -- app/main.py, every test file, and every
other consumer imports `router`/`health_router` directly from their own
submodules (`from app.api.routes import router`,
`from app.api.health import router as health_router`), never via
`from app.api import router`/`from app.api import health_router`
(verified directly: zero such imports exist anywhere in app/ or tests/).

Those eager, unused imports were nonetheless the exact root cause of the
cycle: `app/tasks.py` imports `app.api.job_store` (a *submodule* of this
package) for `JobStore`/`RedisJobStore`. Importing any submodule of a
package for the first time forces Python to run that package's
`__init__.py` first -- which, before this fix, immediately imported
`app.api.health`, which imports `app.api.routes`, which imports back
`from app.tasks import _cleanup_upload, ...`. When the entry point is
`celery -A app.celery_app worker` (not any test, which happens to import
`app.api.routes` or `app.tasks` in an order that never triggers this
exact first-touch sequence), `app.tasks` is still mid-import at that
point -- paused at its own `app.api.job_store` import line, long before
`_cleanup_upload`/`process_pdf`/etc. are defined further down the file --
so the import of those names from the *partially initialized* app.tasks
module fails.

This package intentionally does not re-export anything: every consumer
already imports directly from the submodule it needs, so removing the
eager, unused imports here breaks the cycle without changing any actual
import statement anywhere else in the codebase.
"""
