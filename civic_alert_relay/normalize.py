"""Turn raw feed items into the internal event model.

TODO(#2): define a shared event schema (source, time, location, magnitude /
severity, raw id) and dedupe on a stable key.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

STATUS = "stub"


def log_ready() -> None:
    """Record that normalization is still a placeholder."""

    log.info("normalize: stub (see issue #2)")


def status() -> str:
    """Return the normalize subsystem state for ``/healthz``."""

    return STATUS
