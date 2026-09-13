"""HTTP front door: process health and a short service index."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from civic_alert_relay import __version__, fanout, ingest, normalize, realtime
from civic_alert_relay.config import Settings, get_settings

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="civic-alert-relay: %(levelname)s %(name)s: %(message)s",
    )
    log.info("listening on %s:%s (v%s)", settings.host, settings.port, __version__)
    ingest.log_ready(settings)
    normalize.log_ready()
    fanout.log_ready(settings)
    realtime.log_ready()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application (used by tests and the process entry)."""

    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="Civic Alert Relay",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = settings

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "civic-alert-relay",
                "version": __version__,
                "health": "/healthz",
                "docs": "https://github.com/bugman666/civic-alert-relay",
            }
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "service": "civic-alert-relay",
                "version": __version__,
                "ingest": ingest.status(),
                "normalize": normalize.status(),
                "fanout": fanout.status(),
                "realtime": realtime.status(),
            }
        )

    return app


app = create_app()
