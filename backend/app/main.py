"""StructuraSense AI — FastAPI application entry point."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api.v1 import api_router
from app.config import get_settings
from app.db import get_database
from app.migrate import upgrade_to_head
from app.services.inference import get_model_registry

log = logging.getLogger("structurasense")


def bootstrap() -> None:
    """Migrate schema, sync model registry and (optionally) seed demo data."""
    settings = get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    if settings.auto_migrate:
        upgrade_to_head(get_database().url)
    db = get_database().session()
    try:
        from app.services.alert_engine import ensure_default_rules

        ensure_default_rules(db)
        get_model_registry().sync_db(db)
        if settings.seed_demo_data:
            from app.seed.seed import seed_demo

            seed_demo(db)
        db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    await asyncio.to_thread(bootstrap)
    stop = asyncio.Event()
    task = None
    s = get_settings()
    if s.background_enabled:
        from app.background import run_loop

        task = asyncio.create_task(run_loop(s.background_interval_s, stop))
    from app.services.mqtt_bridge import bridge

    bridge.start()
    yield
    bridge.stop()
    stop.set()
    if task:
        await task


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="StructuraSense AI API",
        version="0.1.0",
        description="Structural-health-monitoring and digital-twin backend. Review priorities are not certified structural assessments.",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/docs")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error. See server logs."})

    return app


app = create_app()
