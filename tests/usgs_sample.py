"""Minimal USGS GeoJSON fixtures for ingest tests."""

from __future__ import annotations

SAMPLE_FEATURE = {
    "type": "Feature",
    "id": "us6000abcd",
    "properties": {
        "mag": 5.2,
        "place": "10 km W of Example",
        "time": 1_700_000_000_000,
        "updated": 1_700_000_001_000,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us6000abcd",
        "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/us6000abcd.geojson",
        "magType": "mb",
        "type": "earthquake",
        "title": "M 5.2 - 10 km W of Example",
        "tsunami": 0,
        "sig": 416,
        "status": "reviewed",
        "net": "us",
        "code": "6000abcd",
    },
    "geometry": {"type": "Point", "coordinates": [-120.5, 35.2, 10.0]},
}

OLDER_FEATURE = {
    "type": "Feature",
    "id": "ci11111111",
    "properties": {
        "mag": 2.1,
        "place": "5 km N of Older",
        "time": 1_699_000_000_000,
        "updated": 1_699_000_000_500,
        "url": "https://earthquake.usgs.gov/earthquakes/eventpage/ci11111111",
        "detail": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/ci11111111.geojson",
        "magType": "ml",
        "type": "earthquake",
        "title": "M 2.1 - 5 km N of Older",
        "tsunami": 0,
        "sig": 68,
        "status": "automatic",
    },
    "geometry": {"type": "Point", "coordinates": [-117.1, 34.0, 3.4]},
}

MALFORMED_FEATURE = {
    "type": "Feature",
    "properties": {"mag": 1.0, "place": "no id"},
    "geometry": {"type": "Point", "coordinates": [0, 0, 0]},
}


def sample_feed(*features: dict) -> dict:
    items = list(features) if features else [SAMPLE_FEATURE]
    return {
        "type": "FeatureCollection",
        "metadata": {
            "generated": 1_700_000_002_000,
            "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson",
            "title": "USGS Magnitude 1.0+ Earthquakes, Past Hour",
            "status": 200,
            "count": len(items),
        },
        "features": items,
    }
