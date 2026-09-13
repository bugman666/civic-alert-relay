"""USGS GeoJSON → HazardEvent."""

from __future__ import annotations

from civic_alert_relay.ingest import feed_url
from civic_alert_relay.normalize import (
    SOURCE_USGS,
    normalize_usgs_feature,
    normalize_usgs_feed,
)
from civic_alert_relay.config import Settings
from tests.usgs_sample import MALFORMED_FEATURE, OLDER_FEATURE, SAMPLE_FEATURE, sample_feed


def test_normalize_usgs_feature_fields() -> None:
    event = normalize_usgs_feature(SAMPLE_FEATURE)
    assert event is not None
    assert event.id == "usgs:us6000abcd"
    assert event.source == SOURCE_USGS
    assert event.source_id == "us6000abcd"
    assert event.magnitude == 5.2
    assert event.mag_type == "mb"
    assert event.place == "10 km W of Example"
    assert event.title == "M 5.2 - 10 km W of Example"
    assert event.latitude == 35.2
    assert event.longitude == -120.5
    assert event.depth_km == 10.0
    assert event.url.endswith("/us6000abcd")
    assert event.detail_url is not None
    assert event.event_type == "earthquake"
    assert event.tsunami == 0
    assert event.significance == 416
    assert event.time is not None
    assert event.time.year == 2023
    assert event.time.tzinfo is not None


def test_normalize_skips_feature_without_id() -> None:
    assert normalize_usgs_feature(MALFORMED_FEATURE) is None


def test_normalize_feed_orders_oldest_first() -> None:
    events = normalize_usgs_feed(sample_feed(SAMPLE_FEATURE, OLDER_FEATURE))
    assert [e.source_id for e in events] == ["ci11111111", "us6000abcd"]


def test_normalize_single_feature_payload() -> None:
    events = normalize_usgs_feed(SAMPLE_FEATURE)
    assert len(events) == 1
    assert events[0].source_id == "us6000abcd"


def test_normalize_empty_or_junk() -> None:
    assert normalize_usgs_feed({"type": "FeatureCollection", "features": []}) == []
    assert normalize_usgs_feed({"type": "FeatureCollection", "features": "nope"}) == []
    assert normalize_usgs_feed({"type": "FeatureCollection", "features": [1, None]}) == []


def test_id_fallback_from_net_and_code() -> None:
    event = normalize_usgs_feature(
        {
            "type": "Feature",
            "properties": {
                "net": "ak",
                "code": "123",
                "mag": 3.0,
                "time": 1_700_000_000_000,
                "place": "somewhere",
            },
            "geometry": {"type": "Point", "coordinates": [1, 2]},
        }
    )
    assert event is not None
    assert event.id == "usgs:ak123"


def test_feed_url_from_short_name() -> None:
    settings = Settings(usgs_feed="significant_week", usgs_feed_url="", _env_file=None)
    assert feed_url(settings).endswith("/summary/significant_week.geojson")


def test_feed_url_override() -> None:
    settings = Settings(
        usgs_feed="all_hour",
        usgs_feed_url="https://example.test/custom.geojson",
        _env_file=None,
    )
    assert feed_url(settings) == "https://example.test/custom.geojson"
