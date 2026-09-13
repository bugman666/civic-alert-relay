"""Ingest: first-seen emit, duplicate suppress, mocked USGS poll, HTTP listings."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from civic_alert_relay import fanout
from civic_alert_relay.app import create_app
from civic_alert_relay.config import Settings
from civic_alert_relay.ingest import IngestService
from civic_alert_relay.normalize import SeenIdSet, normalize_usgs_feed, select_new
from tests.usgs_sample import SAMPLE_FEATURE, sample_feed


def test_first_seen_emits_duplicate_suppressed(monkeypatch) -> None:
    published: list[str] = []
    monkeypatch.setattr(fanout, "publish", lambda event: published.append(event.id))

    settings = Settings(ingest_enabled=False, seen_ids_path="", _env_file=None)
    service = IngestService(settings)
    events = normalize_usgs_feed(sample_feed())

    first = service.accept(events)
    second = service.accept(events)

    assert [e.id for e in first] == ["usgs:us6000abcd"]
    assert second == []
    assert published == ["usgs:us6000abcd"]
    assert service.seen.contains("usgs:us6000abcd")
    assert [e.id for e in service.recent_events()] == ["usgs:us6000abcd"]


def test_select_new_then_remember_on_disk(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    events = normalize_usgs_feed(sample_feed())

    first_store = SeenIdSet(path)
    assert select_new(events, first_store) == events
    assert path.is_file()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["ids"] == ["usgs:us6000abcd"]

    second_store = SeenIdSet(path)
    assert second_store.contains("usgs:us6000abcd")
    assert select_new(events, second_store) == []


def test_poll_once_mocked_usgs_then_duplicate() -> None:
    payload = sample_feed()
    url = "https://example.test/all_hour.geojson"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == url
        return httpx.Response(200, json=payload)

    settings = Settings(
        ingest_enabled=False,
        usgs_feed_url=url,
        seen_ids_path="",
        _env_file=None,
    )
    service = IngestService(settings)
    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            first = await service.poll_once(client)
            second = await service.poll_once(client)
            assert [e.source_id for e in first] == ["us6000abcd"]
            assert second == []
            assert service.last_fetched == 1
            assert service.last_emitted == 0
            assert service.last_duplicates == 1
            assert service.last_error is None
            assert service.polls == 2

    asyncio.run(_run())


def test_events_and_ingest_status_endpoints(tmp_path: Path, monkeypatch) -> None:
    published: list[str] = []
    monkeypatch.setattr(fanout, "publish", lambda event: published.append(event.id))

    settings = Settings(
        host="127.0.0.1",
        ingest_enabled=False,
        seen_ids_path=str(tmp_path / "seen.json"),
        usgs_feed_url="https://example.test/all_hour.geojson",
        _env_file=None,
    )
    app = create_app(settings)
    with TestClient(app) as client:
        empty = client.get("/events")
        assert empty.status_code == 200
        assert empty.json() == {"count": 0, "events": []}

        status = client.get("/ingest/status")
        assert status.status_code == 200
        body = status.json()
        assert body["enabled"] is False
        assert body["running"] is False
        assert body["feed_url"] == "https://example.test/all_hour.geojson"
        assert body["polls"] == 0

        events = normalize_usgs_feed(sample_feed(SAMPLE_FEATURE))
        app.state.ingest.accept(events)

        listed = client.get("/events").json()
        assert listed["count"] == 1
        assert listed["events"][0]["id"] == "usgs:us6000abcd"
        assert listed["events"][0]["magnitude"] == 5.2
        assert listed["events"][0]["place"] == "10 km W of Example"

        after = client.get("/ingest/status").json()
        assert after["seen_count"] == 1
        assert after["recent_count"] == 1

    assert published == ["usgs:us6000abcd"]


def test_poll_loop_uses_mocked_client(tmp_path: Path) -> None:
    payload = sample_feed()
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(200, json=payload)

    settings = Settings(
        ingest_enabled=True,
        ingest_interval_seconds=60,
        usgs_feed_url="https://example.test/all_hour.geojson",
        seen_ids_path=str(tmp_path / "seen.json"),
        _env_file=None,
    )
    service = IngestService(settings)

    async def _run() -> None:
        service._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        emitted = await service.poll_once()
        assert len(emitted) == 1
        again = await service.poll_once()
        assert again == []
        await service._client.aclose()

    asyncio.run(_run())
    assert hits["n"] == 2
