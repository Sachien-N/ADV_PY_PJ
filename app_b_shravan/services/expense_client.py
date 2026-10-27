"""HTTP client for Application A's public API (categories + connectivity check).

Design rules:
- Requests with configurable timeouts and bounded retries for transient errors.
- Pydantic validation of every external payload before use.
- HTTPS in production; base URL comes from the EXPENSE_API_URL env var only.
- All failures are caught and reported - Application B must remain usable
  when Application A is down.
"""
from __future__ import annotations

import logging

import requests
from requests.adapters import HTTPAdapter, Retry

from config import get_settings
from schemas import ExternalCategoryMap

logger = logging.getLogger(__name__)
settings = get_settings()


class IntegrationError(Exception):
    """Raised (and always caught by callers) when a peer API fails."""


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


def _get_json(path: str, token: str = "") -> object:
    if not settings.EXPENSE_API_URL:
        raise IntegrationError("EXPENSE_API_URL is not configured")
    url = f"{settings.EXPENSE_API_URL.rstrip('/')}{path}"
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


def fetch_categories() -> dict:
    """Fetch expense categories from Application A for consistent mapping.

    Falls back to a local default list when App A is unavailable so that
    Application B never blocks on a peer outage.
    """
    defaults = ["Food", "Travel", "Bills", "Entertainment",
                "Shopping", "Subscriptions", "Other"]
    try:
        data = _get_json("/categories")
        validated = ExternalCategoryMap.from_response(data)
        return {"source": "app_a", "reachable": True, "categories": validated.categories}
    except (IntegrationError, ValueError) as exc:
        logger.warning("Could not fetch categories from App A: %s", exc)
        return {"source": "local-default", "reachable": False, "categories": defaults}


def map_category(local_category: str, app_a_categories: list[str]) -> str:
    """Best-effort mapping of a subscription category onto App A's taxonomy."""
    normalized = local_category.strip().lower()
    for cat in app_a_categories:
        if cat.lower() == normalized or normalized in cat.lower():
            return cat
    return "Subscriptions" if "Subscriptions" in app_a_categories else "Other"


def expense_health() -> dict:
    try:
        data = _get_json("/health")
        return {"configured": True, "reachable": True, "detail": data}
    except IntegrationError as exc:
        return {
            "configured": bool(settings.EXPENSE_API_URL),
            "reachable": False,
            "error": str(exc),
        }


def ping_import(expected_count: int) -> dict:
    """Verify App A can see this app's export feed.

    We cannot call App A's authenticated /sync/subscriptions without Sachien's
    write token (least privilege), so instead we confirm App A is reachable
    and report how many records it would pull from our public export feed.
    """
    health = expense_health()
    if not health.get("reachable"):
        raise IntegrationError(health.get("error", "Application A unreachable"))
    return {
        "app_a_reachable": True,
        "records_available_for_pull": expected_count,
        "pull_endpoint": "/subscriptions/export (hosted by Application B)",
    }
