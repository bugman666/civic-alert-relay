"""Health check and service index."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civic_alert_relay import __version__
from civic_alert_relay.app import create_app
from civic_alert_relay.config import Settings


def _client() -> TestClient:
    settings = Settings(
        host="127.0.0.1",
        port=8080,
        ingest_enabled=False,
        seen_ids_path="",
        redis_url="",
        webhook_url="",
        _env_file=None,
    )
    return TestClient(create_app(settings))


def test_healthz_ok() -> None:
    with _client() as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "civic-alert-relay"
    assert body["version"] == __version__
    assert body["ingest"] == "ok"
    assert body["normalize"] == "ok"
    assert body["fanout"] == "ok"
    assert body["realtime"] == "ok"


def test_root_points_at_healthz() -> None:
    with _client() as client:
        response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "civic-alert-relay"
    assert body["health"] == "/healthz"
    assert body["events"] == "/events"
    assert body["ingest"] == "/ingest/status"
    assert body["fanout"] == "/fanout/status"
    assert body["realtime"] == "/realtime/status"
    assert body["ws"] == "/ws/events"
