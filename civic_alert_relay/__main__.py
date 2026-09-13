"""Process entry: ``python -m civic_alert_relay`` or ``civic-alert-relay``."""

from __future__ import annotations

import uvicorn

from civic_alert_relay.app import app
from civic_alert_relay.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
