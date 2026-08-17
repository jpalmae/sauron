from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .consumer import run_consumer
from .db import close_db, get_session_factory, init_db
from .metrics import MetricsMiddleware
from .routers import (
    auth,
    branding,
    cameras,
    corridors,
    events,
    kpis,
    notifications,
    push,
    reports,
    search,
    streams,
)
from .ws import router as ws_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    await init_db()
    from .auth import ensure_bootstrap_admin

    async with get_session_factory()() as session:
        await ensure_bootstrap_admin(session)
        if settings.seed_cameras_path:
            from .seed import seed_cameras

            await seed_cameras(session, settings.seed_cameras_path)
    consumer_task: asyncio.Task | None = None
    if settings.consumer_enabled:
        consumer_task = asyncio.create_task(run_consumer(app))
    yield
    if consumer_task is not None:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Sauron API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(cameras.router, prefix="/api/v1")
    app.include_router(events.router, prefix="/api/v1")
    app.include_router(kpis.router, prefix="/api/v1")
    app.include_router(corridors.router, prefix="/api/v1")
    app.include_router(notifications.router, prefix="/api/v1")
    app.include_router(push.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")
    app.include_router(streams.router, prefix="/api/v1")
    app.include_router(branding.router, prefix="/api/v1")
    app.include_router(ws_router)

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok"}

    return app


app = create_app()
