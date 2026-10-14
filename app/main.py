import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.middleware.sessions import SessionMiddleware

from .config import Settings
from .database import create_tables, make_engine, make_session_factory
from .instagram import InstagramClient
from .routes import api, auth, webhook
from .security import TokenCipher
from .services import AppContext, cleanup_old_rows, refresh_expiring_tokens

log = logging.getLogger("reeldm")
MAINTENANCE_INTERVAL_SECONDS = 6 * 60 * 60


def run_maintenance(ctx: AppContext) -> None:
    try:
        refreshed = refresh_expiring_tokens(ctx)
        cleanup_old_rows(ctx)
        if refreshed:
            log.info("Refreshed %d Instagram token(s)", refreshed)
    except Exception:  # never let maintenance take the server down
        log.exception("Maintenance run failed")


def create_app(
    settings: Settings | None = None,
    ig: InstagramClient | None = None,
    run_background_jobs: bool = True,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)
    ctx = AppContext(
        settings=settings,
        sessions=make_session_factory(engine),
        ig=ig or InstagramClient(settings),
        cipher=TokenCipher(settings.token_encryption_key),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(create_tables, engine)
        task = None
        if run_background_jobs:

            async def loop():
                while True:
                    await run_in_threadpool(run_maintenance, ctx)
                    await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)

            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        engine.dispose()

    app = FastAPI(title="Reel DM Automation", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.ctx = ctx
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="reeldm_session",
        max_age=30 * 24 * 60 * 60,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        # Turn pydantic's error list into one readable sentence for the UI
        messages = []
        for err in exc.errors():
            field = ".".join(str(p) for p in err.get("loc", [])[1:])
            msg = str(err.get("msg", "Invalid value")).removeprefix("Value error, ")
            messages.append(f"{field}: {msg}" if field else msg)
        return JSONResponse({"detail": "; ".join(messages)}, status_code=422)

    @app.get("/healthz")
    def healthz():
        # Also useful as an uptime-ping target: keeps free hosts awake and the free DB from pausing
        with ctx.sessions() as db:
            db.execute(text("SELECT 1"))
        return {"ok": True}

    app.include_router(auth.router)
    app.include_router(api.router)
    app.include_router(webhook.router)

    # Optionally serve a built ca-frontend from the same origin (single-service deploys, E2E tests).
    # Normally the frontend is hosted separately and proxies /api, /auth and /webhook to this app.
    dist = settings.frontend_dist.resolve() if settings.frontend_dist else None
    if dist and (dist / "index.html").exists():

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.split("/", 1)[0] in {"api", "auth", "webhook"}:
                return JSONResponse({"detail": "Not Found"}, status_code=404)
            file = (dist / path).resolve()
            if path and file.is_file() and file.is_relative_to(dist):
                return FileResponse(file)
            return FileResponse(dist / "index.html")

    return app
