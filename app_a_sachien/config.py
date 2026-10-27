"""Application A - Smart Expense & Budget Manager configuration.

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
    APP_NAME = "Smart Expense & Budget Manager"
    APP_VERSION = "1.0.0"
    OWNER = "Sachien N"
    REGISTRATION_NO = "23MID0255"

    # Database: SQLite locally, PostgreSQL in production (Neon / Render).
    DATABASE_URL: str = _env(
        "DATABASE_URL", "sqlite:///./expense_manager.db"
    )

    # Service-to-service authentication (bearer tokens). Set these in the
    # deployment environment; never commit real values.
    API_TOKEN: str = _env("API_TOKEN", "")                # protects write endpoints
    SUBSCRIPTION_API_URL: str = _env("SUBSCRIPTION_API_URL", "")  # Application B public URL
    SUBSCRIPTION_API_TOKEN: str = _env("SUBSCRIPTION_API_TOKEN", "")
    ELECTRICITY_API_URL: str = _env("ELECTRICITY_API_URL", "")   # Application C public URL
    ELECTRICITY_API_TOKEN: str = _env("ELECTRICITY_API_TOKEN", "")

    HTTP_TIMEOUT_SECONDS: float = float(_env("HTTP_TIMEOUT_SECONDS", "10"))
    HTTP_MAX_RETRIES: int = int(_env("HTTP_MAX_RETRIES", "3"))

    # CORS: comma-separated list of allowed frontend origins in production.
    CORS_ORIGINS: list[str] = [
        o.strip()
        for o in _env(
            "CORS_ORIGINS",
            "http://localhost:8501,https://sachien-expense.streamlit.app",
        ).split(",")
        if o.strip()
    ]

    LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")


@lru_cache
def get_settings() -> Settings:
    return Settings()
