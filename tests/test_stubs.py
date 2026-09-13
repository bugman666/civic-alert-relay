"""Fan-out and WebSocket stay stubbed; ingest/normalize are live for #2."""

from __future__ import annotations

from civic_alert_relay import fanout, ingest, normalize, realtime
from civic_alert_relay.config import Settings


def test_status_after_ingest_slice() -> None:
    assert ingest.status() == "ok"
    assert normalize.status() == "ok"
    assert fanout.status() == "stub"
    assert realtime.status() == "stub"


def test_log_ready_does_not_raise() -> None:
    settings = Settings(ingest_enabled=False, _env_file=None)
    ingest.log_ready(settings)
    normalize.log_ready()
    fanout.log_ready(settings)
    realtime.log_ready()


def test_fanout_publish_is_still_a_stub() -> None:
    fanout.publish(object())
