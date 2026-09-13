"""Poll or stream open hazard feeds.

TODO(#2): poll USGS (or a similar authoritative feed), pass raw items to
``normalize``, and skip repeats.
"""

from __future__ import annotations

import logging

from civic_alert_relay.config import Settings

log = logging.getLogger(__name__)

STATUS = "stub"


def log_ready(settings: Settings) -> None:
    """Record that the ingest loop is still a placeholder."""

    log.info("ingest: stub (see issue #2); redis_url=%s", settings.redis_url)


def status() -> str:
    """Return the ingest subsystem state for ``/healthz``."""

    return STATUS
