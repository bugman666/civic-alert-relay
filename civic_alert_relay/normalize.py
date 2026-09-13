"""Turn USGS GeoJSON items into the internal event model and drop repeats."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)

STATUS = "ok"
SOURCE_USGS = "usgs"


class HazardEvent(BaseModel):
    """Normalized hazard item used by ingest, later fan-out, and HTTP listings."""

    id: str
    source: str
    source_id: str
    time: datetime | None = None
    updated: datetime | None = None
    magnitude: float | None = None
    mag_type: str | None = None
    place: str | None = None
    title: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    depth_km: float | None = None
    url: str | None = None
    detail_url: str | None = None
    event_type: str | None = None
    tsunami: int | None = None
    significance: int | None = None
    status: str | None = None


class SeenIdSet:
    """Remember emitted event ids so a later poll of the same feed is a no-op.

    Ids are kept in memory and, when ``path`` is set, flushed to a small JSON
    file so a process restart does not re-emit the same USGS events.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        max_ids: int = 20_000,
    ) -> None:
        self.path = Path(path) if path else None
        self.max_ids = max_ids
        self._ids: set[str] = set()
        self._order: list[str] = []
        if self.path is not None:
            self._load()

    def __len__(self) -> int:
        return len(self._ids)

    def contains(self, event_id: str) -> bool:
        return event_id in self._ids

    def remember(self, event_id: str) -> bool:
        """Record ``event_id``. Return True if this is the first time we saw it."""

        if event_id in self._ids:
            return False
        self._ids.add(event_id)
        self._order.append(event_id)
        overflow = len(self._order) - self.max_ids
        if overflow > 0:
            for old in self._order[:overflow]:
                self._ids.discard(old)
            del self._order[:overflow]
        self._save()
        return True

    def _load(self) -> None:
        assert self.path is not None
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("seen-id file %s unreadable (%s); starting empty", self.path, exc)
            return
        ids = raw.get("ids") if isinstance(raw, dict) else raw
        if not isinstance(ids, list):
            log.warning("seen-id file %s has unexpected shape; starting empty", self.path)
            return
        for item in ids:
            if isinstance(item, str) and item and item not in self._ids:
                self._ids.add(item)
                self._order.append(item)

    def _save(self) -> None:
        if self.path is None:
            return
        payload = json.dumps({"ids": self._order}, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.warning("could not persist seen ids to %s: %s", self.path, exc)


def log_ready() -> None:
    """Record that USGS GeoJSON normalization is active."""

    log.info("normalize: usgs geojson -> HazardEvent; dedupe by %s:<feed id>", SOURCE_USGS)


def status() -> str:
    """Return the normalize subsystem state for ``/healthz``."""

    return STATUS


def event_id(source: str, source_id: str) -> str:
    """Stable key used for dedupe and listings."""

    return f"{source}:{source_id}"


def normalize_usgs_feature(feature: Mapping[str, Any]) -> HazardEvent | None:
    """Map one USGS GeoJSON Feature to :class:`HazardEvent`, or None if unusable."""

    props = feature.get("properties")
    if not isinstance(props, Mapping):
        props = {}

    source_id = feature.get("id")
    if not source_id:
        net = props.get("net") or ""
        code = props.get("code") or ""
        source_id = f"{net}{code}" if net or code else ""
    if not isinstance(source_id, str) or not source_id.strip():
        return None
    source_id = source_id.strip()

    geometry = feature.get("geometry")
    coords: Any = geometry.get("coordinates") if isinstance(geometry, Mapping) else None
    longitude = latitude = depth_km = None
    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
        longitude = _as_float(coords[0])
        latitude = _as_float(coords[1])
        if len(coords) >= 3:
            depth_km = _as_float(coords[2])

    return HazardEvent(
        id=event_id(SOURCE_USGS, source_id),
        source=SOURCE_USGS,
        source_id=source_id,
        time=_ms_to_dt(props.get("time")),
        updated=_ms_to_dt(props.get("updated")),
        magnitude=_as_float(props.get("mag")),
        mag_type=_as_str(props.get("magType")),
        place=_as_str(props.get("place")),
        title=_as_str(props.get("title")),
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
        url=_as_str(props.get("url")),
        detail_url=_as_str(props.get("detail")),
        event_type=_as_str(props.get("type")),
        tsunami=_as_int(props.get("tsunami")),
        significance=_as_int(props.get("sig")),
        status=_as_str(props.get("status")),
    )


def normalize_usgs_feed(payload: Mapping[str, Any]) -> list[HazardEvent]:
    """Parse a USGS FeatureCollection (or a single Feature) into events.

    Results are oldest-first so a burst of new items is emitted in time order.
    Unparseable features are skipped.
    """

    kind = payload.get("type")
    if kind == "Feature":
        features: Iterable[Any] = (payload,)
    else:
        raw_features = payload.get("features") or []
        if not isinstance(raw_features, list):
            return []
        features = raw_features

    events: list[HazardEvent] = []
    for item in features:
        if not isinstance(item, Mapping):
            continue
        event = normalize_usgs_feature(item)
        if event is not None:
            events.append(event)
    events.sort(key=lambda e: e.time or datetime.min.replace(tzinfo=timezone.utc))
    return events


def select_new(events: Iterable[HazardEvent], seen: SeenIdSet) -> list[HazardEvent]:
    """Return events whose ids have not been recorded yet, and record them."""

    emitted: list[HazardEvent] = []
    for event in events:
        if seen.remember(event.id):
            emitted.append(event)
    return emitted


def _ms_to_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
