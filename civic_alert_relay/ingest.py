"""Poll the USGS earthquake GeoJSON feed and emit newly seen events."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx

from civic_alert_relay import __version__, fanout
from civic_alert_relay.config import Settings
from civic_alert_relay.normalize import (
    HazardEvent,
    SeenIdSet,
    normalize_usgs_feed,
    select_new,
)

log = logging.getLogger(__name__)

STATUS = "ok"

USGS_FEED_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
DEFAULT_FEED = "all_hour"
USER_AGENT = (
    f"civic-alert-relay/{__version__} "
    "(https://github.com/bugman666/civic-alert-relay)"
)


def feed_url(settings: Settings) -> str:
    """Resolve the USGS GeoJSON URL from settings."""

    override = (settings.usgs_feed_url or "").strip()
    if override:
        return override
    name = (settings.usgs_feed or DEFAULT_FEED).strip() or DEFAULT_FEED
    if name.endswith(".geojson") or name.startswith("http://") or name.startswith("https://"):
        return name
    return f"{USGS_FEED_BASE}/{name}.geojson"


def log_ready(settings: Settings) -> None:
    """Record that the ingest loop is configured."""

    if not settings.ingest_enabled:
        log.info("ingest: disabled (CAR_INGEST_ENABLED=false)")
        return
    log.info(
        "ingest: polling %s every %ss; seen_ids=%s",
        feed_url(settings),
        settings.ingest_interval_seconds,
        settings.seen_ids_path or "(memory)",
    )


def status() -> str:
    """Return the ingest subsystem state for ``/healthz``."""

    return STATUS


class IngestService:
    """Background poller plus the recent-event buffer used by HTTP listings."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        path = (settings.seen_ids_path or "").strip() or None
        self.seen = SeenIdSet(path)
        self.recent: deque[HazardEvent] = deque(maxlen=settings.recent_event_limit)
        self.url = feed_url(settings)
        self.last_attempt_at: datetime | None = None
        self.last_ok_at: datetime | None = None
        self.last_error: str | None = None
        self.last_fetched = 0
        self.last_emitted = 0
        self.last_duplicates = 0
        self.polls = 0
        self._task: asyncio.Task[None] | None = None
        self._client: httpx.AsyncClient | None = None
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def recent_events(self) -> list[HazardEvent]:
        """Newest-first copy of events emitted since this process started."""

        return list(reversed(self.recent))

    def snapshot(self) -> dict[str, Any]:
        """Last poll outcome and loop state, for ``GET /ingest/status``."""

        return {
            "enabled": self.settings.ingest_enabled,
            "running": self.running,
            "feed_url": self.url,
            "interval_seconds": self.settings.ingest_interval_seconds,
            "seen_ids_path": (self.settings.seen_ids_path or "").strip() or None,
            "seen_count": len(self.seen),
            "recent_count": len(self.recent),
            "polls": self.polls,
            "last_attempt_at": _iso(self.last_attempt_at),
            "last_ok_at": _iso(self.last_ok_at),
            "last_error": self.last_error,
            "last_fetched": self.last_fetched,
            "last_emitted": self.last_emitted,
            "last_duplicates": self.last_duplicates,
        }

    def accept(self, events: list[HazardEvent]) -> list[HazardEvent]:
        """Dedupe, keep first-seen items, and hand them to fan-out."""

        emitted = select_new(events, self.seen)
        for event in emitted:
            self.recent.append(event)
            fanout.publish(event)
        return emitted

    async def fetch_feed(self, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        http = client or self._client
        if http is None:
            raise RuntimeError("ingest HTTP client is not started")
        response = await http.get(self.url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("USGS feed did not return a JSON object")
        return payload

    async def poll_once(self, client: httpx.AsyncClient | None = None) -> list[HazardEvent]:
        """One fetch → normalize → dedupe cycle. Safe to call from tests."""

        self.last_attempt_at = _utcnow()
        self.polls += 1
        payload = await self.fetch_feed(client)
        events = normalize_usgs_feed(payload)
        emitted = self.accept(events)
        self.last_fetched = len(events)
        self.last_emitted = len(emitted)
        self.last_duplicates = len(events) - len(emitted)
        self.last_error = None
        self.last_ok_at = self.last_attempt_at
        if emitted:
            log.info(
                "ingest: %s new / %s fetched (%s duplicates)",
                len(emitted),
                len(events),
                self.last_duplicates,
            )
        else:
            log.debug(
                "ingest: no new events (%s fetched, %s already seen)",
                len(events),
                self.last_duplicates,
            )
        return emitted

    async def start(self) -> None:
        log_ready(self.settings)
        if not self.settings.ingest_enabled:
            return
        self._stopping = False
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._task = asyncio.create_task(self._loop(), name="usgs-ingest")

    async def stop(self) -> None:
        self._stopping = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        client = self._client
        self._client = None
        if client is not None:
            await client.aclose()

    async def _loop(self) -> None:
        interval = max(1, int(self.settings.ingest_interval_seconds))
        while not self._stopping:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.last_error = str(exc)
                log.warning("ingest: poll failed: %s", exc)
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()
