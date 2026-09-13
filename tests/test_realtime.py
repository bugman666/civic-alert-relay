"""WebSocket live event stream (#4)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from civic_alert_relay.app import create_app
from civic_alert_relay.config import Settings
from civic_alert_relay.normalize import normalize_usgs_feed
from civic_alert_relay.realtime import encode_event, hello_message
from tests.usgs_sample import SAMPLE_FEATURE, sample_feed


def _app(tmp_path=None):
    settings = Settings(
        host="127.0.0.1",
        ingest_enabled=False,
        seen_ids_path="" if tmp_path is None else str(tmp_path / "seen.json"),
        redis_url="",
        webhook_url="",
        _env_file=None,
    )
    return create_app(settings)


def test_encode_event_matches_http_listing() -> None:
    event = normalize_usgs_feed(sample_feed())[0]
    frame = encode_event(event)
    assert frame["type"] == "event"
    assert frame["event"] == event.model_dump(mode="json")
    assert frame["event"]["id"] == "usgs:us6000abcd"


def test_hello_message() -> None:
    hello = hello_message()
    assert hello["type"] == "hello"
    assert hello["service"] == "civic-alert-relay"
    assert hello["path"] == "/ws/events"


def test_ws_connect_receive_event_disconnect(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        status = client.get("/realtime/status")
        assert status.status_code == 200
        assert status.json() == {"path": "/ws/events", "clients": 0}

        with client.websocket_connect("/ws/events") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["path"] == "/ws/events"
            assert client.get("/realtime/status").json()["clients"] == 1

            events = normalize_usgs_feed(sample_feed(SAMPLE_FEATURE))
            emitted = app.state.ingest.accept(events)
            assert [e.id for e in emitted] == ["usgs:us6000abcd"]

            frame = ws.receive_json()
            assert frame["type"] == "event"
            assert frame["event"]["id"] == "usgs:us6000abcd"
            assert frame["event"]["magnitude"] == 5.2
            assert frame["event"]["place"] == "10 km W of Example"

        assert client.get("/realtime/status").json()["clients"] == 0


def test_ws_multiple_clients_then_one_disconnects(tmp_path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/events") as first:
            with client.websocket_connect("/ws/events") as second:
                assert first.receive_json()["type"] == "hello"
                assert second.receive_json()["type"] == "hello"
                assert client.get("/realtime/status").json()["clients"] == 2

                app.state.ingest.accept(normalize_usgs_feed(sample_feed()))
                assert first.receive_json()["event"]["id"] == "usgs:us6000abcd"
                assert second.receive_json()["event"]["id"] == "usgs:us6000abcd"

            assert client.get("/realtime/status").json()["clients"] == 1
            app.state.ingest.accept(
                normalize_usgs_feed(sample_feed({"type": "Feature", "id": "us6000efgh",
                                                "properties": SAMPLE_FEATURE["properties"],
                                                "geometry": SAMPLE_FEATURE["geometry"]}))
            )
            leftover = first.receive_json()
            assert leftover["event"]["id"] == "usgs:us6000efgh"


def test_healthz_reports_realtime_ok() -> None:
    with TestClient(_app()) as client:
        body = client.get("/healthz").json()
        assert body["realtime"] == "ok"
        assert body["fanout"] == "ok"
