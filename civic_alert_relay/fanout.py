"""Publish normalized events and deliver them to outbound channels.

TODO(#3): publish on Redis Pub/Sub; deliver via Webhook and/or Telegram Bot
as the first concrete channel. WebPush stays later.
"""

from __future__ import annotations

import logging

from civic_alert_relay.config import Settings

log = logging.getLogger(__name__)

STATUS = "stub"


def log_ready(settings: Settings) -> None:
    """Record that fan-out is still a placeholder."""

    log.info("fanout: stub (see issue #3); redis_url=%s", settings.redis_url)


def status() -> str:
    """Return the fan-out subsystem state for ``/healthz``."""

    return STATUS
