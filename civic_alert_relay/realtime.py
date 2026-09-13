"""Long-lived WebSocket so dashboards can follow the live event feed.

TODO(#4): accept WebSocket clients and forward normalized events from the
Redis fan-out (or an in-process bus while that is still a stub).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

STATUS = "stub"


def log_ready() -> None:
    """Record that the WebSocket path is still a placeholder."""

    log.info("realtime: stub (see issue #4)")


def status() -> str:
    """Return the realtime subsystem state for ``/healthz``."""

    return STATUS
