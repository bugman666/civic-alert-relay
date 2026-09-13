"""Ingest / normalize / fan-out / realtime are all live."""

from __future__ import annotations

from civic_alert_relay import fanout, ingest, normalize, realtime
from civic_alert_relay.config import Settings


def test_status_after_realtime_and_fanout() -> None:
    assert ingest.status() == "ok"
    assert normalize.status() == "ok"
    assert fanout.status() == "ok"
    assert realtime.status() == "ok"


def test_log_ready_does_not_raise() -> None:
    settings = Settings(ingest_enabled=False, redis_url="", webhook_url="", _env_file=None)
    ingest.log_ready(settings)
    normalize.log_ready()
    fanout.log_ready(settings)
    realtime.log_ready()
