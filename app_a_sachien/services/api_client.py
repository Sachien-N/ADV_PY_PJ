"""HTTP client for communicating with Application B (Subscriptions) and
Application C (Electricity) public APIs.

Design rules:
- Requests with configurable timeouts and bounded retries for transient errors.
- Pydantic validation of every external payload before touching the database.
- HTTPS in production; base URLs come from environment variables only.
- All failures are caught and reported - Application A must remain usable
  when a peer API is down.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

import requests
from requests.adapters import HTTPAdapter, Retry

from config import get_settings
from schemas import ExternalElectricityExpense, ExternalSubscription

logger = logging.getLogger(__name__)
settings = get_settings()


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=settings.HTTP_MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


class IntegrationError(Exception):
    """Raised (and always caught by callers) when a peer API fails."""


def _get_json(base_url: str, path: str, token: str) -> object:
    if not base_url:
        raise IntegrationError("API base URL is not configured")
    url = f"{base_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = _session().get(url, headers=headers, timeout=settings.HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise IntegrationError(f"Request to {url} failed: {exc}") from exc
    if resp.status_code >= 400:
        raise IntegrationError(f"{url} returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except ValueError as exc:
        raise IntegrationError(f"{url} returned invalid JSON") from exc


# ------------------------- Application B: subscriptions -------------------------

def fetch_subscriptions() -> list[ExternalSubscription]:
    """Fetch recurring subscription costs eligible for expense import."""
    data = _get_json(
        settings.SUBSCRIPTION_API_URL, "/subscriptions/export", settings.SUBSCRIPTION_API_TOKEN
    )
    items = data.get("items", []) if isinstance(data, dict) else data
    result: list[ExternalSubscription] = []
    for raw in items:
        try:
            result.append(ExternalSubscription.model_validate(raw))
        except Exception as exc:  # skip malformed records, keep the rest
            logger.warning("Skipping invalid subscription record: %s", exc)
    return result


def subscription_health() -> dict:
    try:
        data = _get_json(settings.SUBSCRIPTION_API_URL, "/health", "")
        return {"configured": True, "reachable": True, "detail": data}
    except IntegrationError as exc:
        return {"configured": bool(settings.SUBSCRIPTION_API_URL), "reachable": False, "error": str(exc)}


# ------------------------- Application C: electricity -------------------------

def fetch_electricity_expenses() -> list[ExternalElectricityExpense]:
    """Fetch eligible electricity expenses (actual bills/payments only).

    Estimates are excluded by Application C itself so that estimated charges
    are never double-counted or confused with recorded charges.
    """
    data = _get_json(
        settings.ELECTRICITY_API_URL, "/integration/expenses", settings.ELECTRICITY_API_TOKEN
    )
    items = data.get("items", []) if isinstance(data, dict) else data
    result: list[ExternalElectricityExpense] = []
    for raw in items:
        try:
            result.append(ExternalElectricityExpense.model_validate(raw))
        except Exception as exc:
            logger.warning("Skipping invalid electricity record: %s", exc)
    return result


def electricity_health() -> dict:
    try:
        data = _get_json(settings.ELECTRICITY_API_URL, "/health", "")
        return {"configured": True, "reachable": True, "detail": data}
    except IntegrationError as exc:
        return {"configured": bool(settings.ELECTRICITY_API_URL), "reachable": False, "error": str(exc)}
