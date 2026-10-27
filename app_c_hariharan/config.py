"""Application C - Smart Home Electricity & Bill Manager configuration.

All settings are read from environment variables (never hardcode secrets).
Local development defaults use SQLite; production must use PostgreSQL
(e.g. Neon) via DATABASE_URL.
"""
from __future__ import annotations

import os


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


class Settings:
    APP_NAME = "Smart Home Electricity & Bill Manager"
    APP_VERSION = "1.0.0"
    OWNER = "Hariharan S"
    REGISTRATION_NO = ""  # registration number not provided by owner

    def __init__(self) -> None:
        # Database: SQLite locally, PostgreSQL in production (Neon / Render).
        self.DATABASE_URL: str = _env(
            "DATABASE_URL", "sqlite:///./electricity_manager.db"
        )

        # Service-to-service authentication (bearer tokens). Set these in the
        # deployment environment; never commit real values.
        self.API_TOKEN: str = _env("API_TOKEN", "")              # protects write endpoints
        self.ALLOW_UNAUTHENTICATED_WRITES: bool = _env(
            "ALLOW_UNAUTHENTICATED_WRITES", ""
        ).lower() in ("1", "true", "yes")
        self.EXPENSE_API_URL: str = _env("EXPENSE_API_URL", "")  # Application A public URL
        self.EXPENSE_API_TOKEN: str = _env("EXPENSE_API_TOKEN", "")

        self.HTTP_TIMEOUT_SECONDS: float = float(_env("HTTP_TIMEOUT_SECONDS", "10"))
        self.HTTP_MAX_RETRIES: int = int(_env("HTTP_MAX_RETRIES", "3"))

        # Deviation detection: percentage change vs trailing average that is
        # flagged as significant when comparing a month to the previous window.
        self.DEVIATION_THRESHOLD_PCT: float = float(
            _env("DEVIATION_THRESHOLD_PCT", "25")
        )

        # CORS: comma-separated list of allowed frontend origins in production.
        self.CORS_ORIGINS: list[str] = [
            o.strip()
            for o in _env(
                "CORS_ORIGINS",
                "http://localhost:8503,https://hariharan-electricity.streamlit.app",
            ).split(",")
            if o.strip()
        ]

        self.LOG_LEVEL: str = _env("LOG_LEVEL", "INFO")


def get_settings() -> Settings:
    """Always reads current environment variables (no stale cached config)."""
    return Settings()
