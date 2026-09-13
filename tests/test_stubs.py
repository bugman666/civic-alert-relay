"""Placeholder modules stay explicitly stubbed until later issues land."""

from __future__ import annotations

from civic_alert_relay import fanout, ingest, normalize, realtime
from civic_alert_relay.config import Settings


def test_stub_status() -> None:
    assert ingest.status() == "stub"
    assert normalize.status() == "stub"
    assert fanout.status() == "stub"
    assert realtime.status() == "stub"


def test_stub_log_ready_does_not_raise() -> None:
    settings = Settings(_env_file=None)
    ingest.log_ready(settings)
    normalize.log_ready()
    fanout.log_ready(settings)
    realtime.log_ready()
