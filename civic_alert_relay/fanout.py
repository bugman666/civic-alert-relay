"""Publish normalized events on Redis and deliver them to outbound channels.

First-seen events from ingest are JSON-encoded, published on a Redis Pub/Sub
channel, then POSTed to a webhook and/or sent through a Telegram bot when those
are configured. Each hop is skipped when its setting is empty; failures are
logged and do not stop ingest. WebSocket is a separate in-process path.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import redis

from civic_alert_relay import __version__
from civic_alert_relay.config import Settings
from civic_alert_relay.normalize import HazardEvent

log = logging.getLogger(__name__)

STATUS = "ok"
DEFAULT_CHANNEL = "civic-alert-relay:events"
USER_AGENT = (
    f"civic-alert-relay/{__version__} "
    "(https://github.com/bugman666/civic-alert-relay)"
)
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

_service: FanoutService | None = None


def configure(service: FanoutService | None) -> None:
    """Install the process-wide service used by :func:`publish`."""

    global _service
    _service = service


def current() -> FanoutService | None:
    """Return the service installed by :func:`configure`, if any."""

    return _service


def log_ready(settings: Settings) -> None:
    """Record which fan-out hops are enabled."""

    redis_url = (settings.redis_url or "").strip()
    channel = (settings.redis_channel or "").strip() or DEFAULT_CHANNEL
    webhook = (settings.webhook_url or "").strip()
    telegram = _telegram_on(settings)
    log.info(
        "fanout: redis=%s channel=%s webhook=%s telegram=%s",
        redis_url or "(disabled)",
        channel if redis_url else "-",
        webhook or "(disabled)",
        "on" if telegram else "(disabled)",
    )


def status() -> str:
    """Return the fan-out subsystem state for ``/healthz``."""

    return STATUS


def publish(event: object) -> None:
    """Receive a newly seen event from ingest and fan it out."""

    service = _service
    if service is None:
        ident = getattr(event, "id", event)
        log.debug("fanout: drop %s (service not started)", ident)
        return
    service.publish(event)


class FanoutService:
    """Redis Pub/Sub plus webhook / Telegram delivery."""

    def __init__(
        self,
        settings: Settings,
        *,
        redis_client: Any = None,
        http: httpx.Client | None = None,
    ) -> None:
        self.settings = settings
        self._redis = redis_client
        self._owns_redis = redis_client is None
        self._http = http
        self._owns_http = http is None
        self.published = 0
        self.redis_ok = 0
        self.webhook_ok = 0
        self.telegram_ok = 0
        self.last_error: str | None = None

    @property
    def channel(self) -> str:
        return (self.settings.redis_channel or "").strip() or DEFAULT_CHANNEL

    def redis_enabled(self) -> bool:
        return bool((self.settings.redis_url or "").strip())

    def webhook_enabled(self) -> bool:
        return bool((self.settings.webhook_url or "").strip())

    def telegram_enabled(self) -> bool:
        return _telegram_on(self.settings)

    def snapshot(self) -> dict[str, Any]:
        """Config and last-delivery counters, for ``GET /fanout/status``."""

        return {
            "redis_enabled": self.redis_enabled(),
            "redis_channel": self.channel if self.redis_enabled() else None,
            "webhook_enabled": self.webhook_enabled(),
            "telegram_enabled": self.telegram_enabled(),
            "published": self.published,
            "redis_ok": self.redis_ok,
            "webhook_ok": self.webhook_ok,
            "telegram_ok": self.telegram_ok,
            "last_error": self.last_error,
        }

    def start(self) -> None:
        if (self.webhook_enabled() or self.telegram_enabled()) and self._http is None:
            self._http = self._build_http()

    def stop(self) -> None:
        if self._owns_redis and self._redis is not None:
            try:
                close = getattr(self._redis, "close", None)
                if callable(close):
                    close()
            except Exception:
                pass
            self._redis = None
        if self._owns_http and self._http is not None:
            self._http.close()
            self._http = None

    def publish(self, event: object) -> None:
        payload = event_payload(event)
        if payload is None:
            return
        self._publish_redis(payload)
        self._deliver_webhook(payload)
        self._deliver_telegram(event, payload)
        self.published += 1

    def _build_http(self) -> httpx.Client:
        timeout = max(0.5, float(self.settings.webhook_timeout_seconds))
        return httpx.Client(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def _http_client(self) -> httpx.Client:
        if self._http is None:
            self._http = self._build_http()
        return self._http

    def _connect_redis(self) -> Any | None:
        url = (self.settings.redis_url or "").strip()
        if not url:
            return None
        try:
            client = redis.Redis.from_url(
                url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=True,
            )
            client.ping()
            return client
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("fanout: redis unavailable (%s); publish skipped", exc)
            return None

    def _redis_client(self) -> Any | None:
        if not self.redis_enabled():
            return None
        if self._redis is None:
            self._redis = self._connect_redis()
        return self._redis

    def _publish_redis(self, payload: dict[str, Any]) -> None:
        if not self.redis_enabled():
            log.debug("fanout: redis unset; skip %s", payload.get("id"))
            return
        try:
            client = self._redis_client()
            if client is None:
                return
            client.publish(self.channel, json.dumps(payload, ensure_ascii=False))
            self.redis_ok += 1
        except Exception as exc:
            self.last_error = str(exc)
            if self._owns_redis:
                self._redis = None
            log.warning("fanout: redis publish failed: %s", exc)

    def _deliver_webhook(self, payload: dict[str, Any]) -> None:
        url = (self.settings.webhook_url or "").strip()
        if not url:
            log.debug("fanout: webhook unset; skip %s", payload.get("id"))
            return
        try:
            response = self._http_client().post(url, json=payload)
            response.raise_for_status()
            self.webhook_ok += 1
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("fanout: webhook failed: %s", exc)

    def _deliver_telegram(self, event: object, payload: dict[str, Any]) -> None:
        if not self.telegram_enabled():
            return
        token = (self.settings.telegram_bot_token or "").strip()
        chat_id = (self.settings.telegram_chat_id or "").strip()
        text = telegram_text(event, payload)
        url = TELEGRAM_API.format(token=token)
        try:
            response = self._http_client().post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            self.telegram_ok += 1
        except Exception as exc:
            self.last_error = str(exc)
            log.warning("fanout: telegram failed: %s", exc)


def event_payload(event: object) -> dict[str, Any] | None:
    """JSON-ready dict for Redis and the webhook, or None if not an event."""

    if isinstance(event, HazardEvent):
        return event.model_dump(mode="json")
    dump = getattr(event, "model_dump", None)
    if callable(dump):
        raw = dump(mode="json")
        if isinstance(raw, dict):
            return raw
    ident = getattr(event, "id", event)
    log.debug("fanout: skip non-event %s", ident)
    return None


def telegram_text(event: object, payload: dict[str, Any] | None = None) -> str:
    """Short plain-text body for Telegram ``sendMessage``."""

    if isinstance(event, HazardEvent):
        mag = f"M {event.magnitude}" if event.magnitude is not None else "Alert"
        kind = event.event_type or "hazard"
        place = event.place or event.title or event.id
        lines = [f"{mag} {kind}", place]
        if event.url:
            lines.append(event.url)
        return "\n".join(lines)
    body = payload or {}
    return str(body.get("title") or body.get("place") or body.get("id") or "alert")


def _telegram_on(settings: Settings) -> bool:
    return bool(
        (settings.telegram_bot_token or "").strip()
        and (settings.telegram_chat_id or "").strip()
    )
