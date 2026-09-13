"""Fan-out: Redis publish, webhook POST, skip when a channel is unset."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx
from fastapi.testclient import TestClient

from civic_alert_relay import fanout
from civic_alert_relay.app import create_app
from civic_alert_relay.config import Settings
from civic_alert_relay.fanout import FanoutService, event_payload, telegram_text
from civic_alert_relay.ingest import IngestService
from civic_alert_relay.normalize import normalize_usgs_feed
from tests.usgs_sample import SAMPLE_FEATURE, sample_feed


class FakeRedis:
    """Stand-in for redis.Redis.publish used by unit tests."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.closed = False

    def publish(self, channel: str, message: str) -> int:
        self.messages.append((channel, message))
        return 1

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


class WebhookReceiver:
    """Local HTTP server that records POSTed JSON (httptest-style)."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self._server = HTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                recorder.requests.append(
                    {
                        "path": self.path,
                        "body": json.loads(raw.decode("utf-8")) if raw else None,
                        "content_type": self.headers.get("Content-Type"),
                    }
                )
                self.send_response(204)
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/hook"

    def __enter__(self) -> WebhookReceiver:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=2)
        self._server.server_close()


def _event():
    events = normalize_usgs_feed(sample_feed(SAMPLE_FEATURE))
    assert len(events) == 1
    return events[0]


def _settings(**kwargs) -> Settings:
    defaults = dict(
        ingest_enabled=False,
        seen_ids_path="",
        redis_url="",
        webhook_url="",
        telegram_bot_token="",
        telegram_chat_id="",
        _env_file=None,
    )
    defaults.update(kwargs)
    return Settings(**defaults)


def test_publish_path_uses_redis_channel() -> None:
    bus = FakeRedis()
    settings = _settings(
        redis_url="redis://example:6379/0",
        redis_channel="alerts.test",
    )
    service = FanoutService(settings, redis_client=bus)
    event = _event()

    service.publish(event)

    assert len(bus.messages) == 1
    channel, raw = bus.messages[0]
    assert channel == "alerts.test"
    body = json.loads(raw)
    assert body["id"] == "usgs:us6000abcd"
    assert body["magnitude"] == 5.2
    assert body["place"] == "10 km W of Example"
    assert service.redis_ok == 1
    assert service.published == 1


def test_webhook_delivery_posts_normalized_json() -> None:
    event = _event()
    with WebhookReceiver() as hook:
        settings = _settings(webhook_url=hook.url, webhook_timeout_seconds=2)
        service = FanoutService(settings)
        service.publish(event)

    assert len(hook.requests) == 1
    posted = hook.requests[0]
    assert posted["path"] == "/hook"
    assert posted["body"]["id"] == event.id
    assert posted["body"]["source"] == "usgs"
    assert posted["body"]["magnitude"] == 5.2
    assert service.webhook_ok == 1


def test_skip_webhook_when_unset() -> None:
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(204)

    settings = _settings(webhook_url="")
    service = FanoutService(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    service.publish(_event())

    assert hits["n"] == 0
    assert service.webhook_ok == 0
    assert service.published == 1


def test_skip_redis_when_url_unset() -> None:
    bus = FakeRedis()
    settings = _settings(redis_url="")
    # Injecting a client must still be a no-op when the URL is empty.
    service = FanoutService(settings, redis_client=bus)
    service.publish(_event())
    assert bus.messages == []
    assert service.redis_ok == 0


def test_telegram_skipped_unless_token_and_chat() -> None:
    hits: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hits.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    only_token = FanoutService(
        _settings(telegram_bot_token="tok", telegram_chat_id=""),
        http=http,
    )
    only_token.publish(_event())
    assert hits == []

    both = FanoutService(
        _settings(telegram_bot_token="tok", telegram_chat_id="123"),
        http=http,
    )
    event = _event()
    both.publish(event)
    assert len(hits) == 1
    assert hits[0].endswith("/bottok/sendMessage")
    assert both.telegram_ok == 1
    text = telegram_text(event)
    assert "M 5.2" in text
    assert "10 km W of Example" in text


def test_ingest_first_seen_reaches_redis_and_webhook() -> None:
    bus = FakeRedis()
    event = _event()
    with WebhookReceiver() as hook:
        settings = _settings(
            redis_url="redis://example:6379/0",
            redis_channel="civic-alert-relay:events",
            webhook_url=hook.url,
            webhook_timeout_seconds=2,
        )
        service = FanoutService(settings, redis_client=bus)
        fanout.configure(service)
        try:
            ingest = IngestService(settings)
            first = ingest.accept(normalize_usgs_feed(sample_feed()))
            second = ingest.accept(normalize_usgs_feed(sample_feed()))
        finally:
            fanout.configure(None)
            service.stop()

    assert [e.id for e in first] == ["usgs:us6000abcd"]
    assert second == []
    assert len(bus.messages) == 1
    assert json.loads(bus.messages[0][1])["id"] == event.id
    assert len(hook.requests) == 1
    assert hook.requests[0]["body"]["id"] == event.id


def test_webhook_error_does_not_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    settings = _settings(webhook_url="http://example.test/hook")
    service = FanoutService(
        settings,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    service.publish(_event())
    assert service.webhook_ok == 0
    assert service.last_error
    assert service.published == 1


def test_event_payload_skips_plain_object() -> None:
    assert event_payload(object()) is None


def test_fanout_status_endpoint() -> None:
    settings = _settings(host="127.0.0.1", redis_url="", webhook_url="")
    with TestClient(create_app(settings)) as client:
        response = client.get("/fanout/status")
    assert response.status_code == 200
    body = response.json()
    assert body["redis_enabled"] is False
    assert body["webhook_enabled"] is False
    assert body["telegram_enabled"] is False
    assert body["published"] == 0
