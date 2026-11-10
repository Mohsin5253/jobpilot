import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import account, admin, auth, campus, consent, drafts, events, evidence, extension, google_auth, growth, insights, ledger, matches, notifications, payments, profile, proof_links, public, questions, rights, runs, scam, sources, stats, whatsapp
from app.services.events import hub
from app.services.runs import AgeNotConfirmed
from app.config import settings
from app.db import engine
from app.logging import configure_logging, log


def init_sentry(component: str) -> None:
    """Error reporting (optional): set SENTRY_DSN. Personal data (resumes, emails) is never sent."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.env, send_default_pii=False, traces_sample_rate=0.05, server_name=component)


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_sentry("api")
    worker = None
    if settings.embedded_worker:
        from app.worker import Worker

        worker = Worker()
        await worker.start()
    log.info("api.started", env=settings.env, llm=settings.llm_label, models=settings.models, embedded_worker=bool(worker))
    yield
    if worker:
        await worker.stop()
    await hub.close()
    await engine.dispose()


app = FastAPI(title="JobPilot API", version="1.0.0", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.extension_origin_regex,  # the Chrome autofill extension (token auth, no cookies)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AgeNotConfirmed)
async def age_gate(_: Request, exc: AgeNotConfirmed) -> JSONResponse:
    return JSONResponse({"detail": str(exc), "code": "age_not_confirmed"}, status_code=403)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    structlog.contextvars.bind_contextvars(request_id=request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("api.unhandled", path=request.url.path)
        response = JSONResponse({"detail": "Internal server error", "request_id": request_id}, status_code=500)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["x-request-id"] = request_id
    response.headers["server-timing"] = f"app;dur={elapsed:.1f}"
    response.headers.setdefault("x-content-type-options", "nosniff")
    response.headers.setdefault("cache-control", "no-store")  # API answers are per-user
    if settings.cookie_secure:
        response.headers.setdefault("strict-transport-security", "max-age=63072000; includeSubDomains")
    if request.url.path not in ("/health", "/ready"):
        log.info("api.request", method=request.method, path=request.url.path, status=response.status_code, ms=round(elapsed, 1))
    structlog.contextvars.clear_contextvars()
    return response


for r in (auth.router, google_auth.router, account.router, admin.router, consent.router, extension.router, evidence.router, insights.router, campus.router, whatsapp.router, profile.router, matches.router, drafts.router, questions.router, notifications.router, runs.router, stats.router, events.router, public.router, rights.router, scam.router, proof_links.router, sources.router, payments.router, ledger.router, growth.router):
    app.include_router(r, prefix="/api")


@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
async def ready() -> JSONResponse:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse({"status": "unavailable", "error": type(exc).__name__}, status_code=503)
    return JSONResponse({"status": "ready", "llm": settings.llm_label})
