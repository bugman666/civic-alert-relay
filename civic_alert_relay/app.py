"""HTTP front door: process health, ingest / fan-out status, recent events, and WebSocket."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

from civic_alert_relay import __version__, fanout, ingest, normalize, realtime
from civic_alert_relay.config import Settings, get_settings
from civic_alert_relay.fanout import FanoutService
from civic_alert_relay.ingest import IngestService
from civic_alert_relay.realtime import EventHub, WS_PATH

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="civic-alert-relay: %(levelname)s %(name)s: %(message)s",
    )
    log.info("listening on %s:%s (v%s)", settings.host, settings.port, __version__)
    normalize.log_ready()
    fanout.configure(app.state.fanout)
    fanout.log_ready(settings)
    realtime.configure(app.state.realtime)
    app.state.realtime.start()
    realtime.log_ready()
    app.state.fanout.start()
    await app.state.ingest.start()
    yield
    await app.state.ingest.stop()
    app.state.fanout.stop()
    fanout.configure(None)
    app.state.realtime.stop()
    realtime.configure(None)


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
    app.state.ingest = IngestService(settings)
    app.state.fanout = FanoutService(settings)
    app.state.realtime = EventHub()

    @app.get("/", include_in_schema=False)
    def root() -> JSONResponse:
        return JSONResponse(
            {
                "service": "civic-alert-relay",
                "version": __version__,
                "health": "/healthz",
                "events": "/events",
                "ingest": "/ingest/status",
                "fanout": "/fanout/status",
                "realtime": "/realtime/status",
                "ws": WS_PATH,
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

    @app.get("/events", include_in_schema=False)
    def events() -> JSONResponse:
        items = [event.model_dump(mode="json") for event in app.state.ingest.recent_events()]
        return JSONResponse({"count": len(items), "events": items})

    @app.get("/ingest/status", include_in_schema=False)
    def ingest_status() -> JSONResponse:
        return JSONResponse(app.state.ingest.snapshot())

    @app.get("/fanout/status", include_in_schema=False)
    def fanout_status() -> JSONResponse:
        return JSONResponse(app.state.fanout.snapshot())

    @app.get("/realtime/status", include_in_schema=False)
    def realtime_status() -> JSONResponse:
        return JSONResponse(app.state.realtime.snapshot())

    @app.websocket(WS_PATH)
    async def ws_events(websocket: WebSocket) -> None:
        await realtime.handle_client(websocket, app.state.realtime)

    return app


app = create_app()
