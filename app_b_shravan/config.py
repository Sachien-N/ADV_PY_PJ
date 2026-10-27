"""Application B - Subscription Renewal & Cost Tracker configuration.

All settings are read from environment variables (never hardcode secrets).
Local development defaults use SQLite; production must use PostgreSQL
(e.g. Neon) via DATABASE_URL.
"""
from __future__ import annotations

import os
from functools import lru_cache


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class Settings:
    APP_NAME = "Subscription Renewal & Cost Tracker"
    APP_VERSION = "1.0.0"
    OWNER = "Shravan N A"
    REGISTRATION_NO = "23MID0445"

    # Database: SQLite locally, PostgreSQL in production (Neon / Render).
    DATABASE_URL: str = _env(
        "DATABASE_URL", "sqlite:///./subscription_tracker.db"
    )

    # Service-to-service authentication (bearer tokens). Set these in the
    # deployment environment; never commit real values.
    API_TOKEN: str = _env("API_TOKEN", "")                # protects write endpoints
    EXPENSE_API_URL: str = _env("EXPENSE_API_URL", "")    # Application A public URL
    EXPENSE_API_TOKEN: str = _env("EXPENSE_API_TOKEN", "")

    HTTP_TIMEOUT_SECONDS: float = float(_env("HTTP_TIMEOUT_SECONDS", "10"))
    HTTP_MAX_RETRIES: int = int(_env("HTTP_MAX_RETRIES", "3"))

    # CORS: comma-separated list of allowed frontend origins in production.
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in _env(
            "CORS_ORIGINS",
            "http://localhost:8502,https://shravan-subscriptions.streamlit.app",
        ).split(",")
        if o.strip()
    ]

    LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
