"""Environment-backed settings."""

from __future__ import annotations

from civic_alert_relay.config import Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.host == "0.0.0.0"
    assert settings.port == 8080
    assert settings.ingest_enabled is True
    assert settings.usgs_feed == "all_hour"
    assert settings.ingest_interval_seconds == 60
    assert settings.seen_ids_path.endswith("civic-alert-relay-seen.json")
    assert settings.redis_url.startswith("redis://")
    assert settings.redis_channel == "civic-alert-relay:events"
    assert settings.webhook_url == ""
    assert settings.telegram_bot_token == ""
    assert settings.telegram_chat_id == ""
    assert settings.database_url.startswith("postgresql://")


def test_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CAR_HOST", "127.0.0.1")
    monkeypatch.setenv("CAR_PORT", "9090")
    monkeypatch.setenv("CAR_REDIS_URL", "redis://example:6379/2")
    monkeypatch.setenv("CAR_REDIS_CHANNEL", "alerts.custom")
    monkeypatch.setenv("CAR_WEBHOOK_URL", "https://hooks.example/civic")
    monkeypatch.setenv("CAR_TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("CAR_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setenv("CAR_USGS_FEED", "significant_week")
    monkeypatch.setenv("CAR_INGEST_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("CAR_INGEST_ENABLED", "false")
    settings = Settings(_env_file=None)
    assert settings.host == "127.0.0.1"
    assert settings.port == 9090
    assert settings.redis_url == "redis://example:6379/2"
    assert settings.redis_channel == "alerts.custom"
    assert settings.webhook_url == "https://hooks.example/civic"
    assert settings.telegram_bot_token == "tok"
    assert settings.telegram_chat_id == "42"
    assert settings.usgs_feed == "significant_week"
    assert settings.ingest_interval_seconds == 120
    assert settings.ingest_enabled is False
