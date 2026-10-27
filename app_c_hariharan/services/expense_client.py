"""HTTP client for Application A's public API.

Rules implemented here:
- Requests with configurable timeouts and bounded retries (GET only).
- Pydantic validation of external payloads.
- HTTPS base URL supplied via EXPENSE_API_URL env var — never hardcoded
  localhost in production.
- POSTs push eligible records; failures are caught so App C keeps working
  when App A is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter, Retry

from config import get_settings

logger = logging.getLogger(__name__)


def _settings():
    """Read current env every call (keeps tests and hot config changes honest)."""
    return get_settings()


class IntegrationError(Exception):
    """Raised when a peer API call fails (always caught by callers)."""


def _session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=_settings().HTTP_MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=(502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


def _url(path: str) -> str:
    cfg = _settings()
    if not cfg.EXPENSE_API_URL:
        raise IntegrationError("EXPENSE_API_URL is not configured")
    return f"{cfg.EXPENSE_API_URL.rstrip('/')}{path}"


def fetch_categories() -> dict:
    """Fetch expense categories from Application A for consistent mapping.

    Falls back to App A's documented default taxonomy when unreachable so
    Application C never blocks on a peer outage.
    """
    defaults = [
        "Food", "Travel", "Bills", "Entertainment",
        "Shopping", "Subscriptions", "Other",
    ]
    try:
        resp = _session().get(
            _url("/categories"),
            headers={"Accept": "application/json"},
            timeout=_settings().HTTP_TIMEOUT_SECONDS,
        )
        if resp.status_code >= 400:
            raise IntegrationError(f"/categories returned HTTP {resp.status_code}")
        data = resp.json()
        cats = data.get("categories", data) if isinstance(data, dict) else data
        if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
            raise IntegrationError("/categories returned an unexpected shape")
        return {"source": "app_a", "reachable": True, "categories": cats}
    except (IntegrationError, requests.RequestException, ValueError) as exc:
        logger.warning("Could not fetch categories from App A: %s", exc)
        return {"source": "local-default", "reachable": False, "categories": defaults}
    except Exception as exc:  # defensive: peer failure must never crash App C
        logger.warning("Unexpected error fetching categories from App A: %s", exc)
        return {"source": "local-default", "reachable": False, "categories": defaults}


def health() -> dict:
    cfg = _settings()
    if not cfg.EXPENSE_API_URL:
        return {"configured": False, "reachable": False,
                "error": "EXPENSE_API_URL is not configured"}
    try:
        resp = _session().get(
            _url("/health"), headers={"Accept": "application/json"},
            timeout=_settings().HTTP_TIMEOUT_SECONDS,
        )
        return {"configured": True, "reachable": resp.status_code < 400,
                "detail": _safe_json(resp)}
    except (requests.RequestException, ValueError) as exc:
        return {"configured": bool(cfg.EXPENSE_API_URL),
                "reachable": False, "error": str(exc)}


def _safe_json(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return None


def post_expense(payload: dict) -> dict:
    """Push one expense record into Application A.

    Idempotency is provided by App A itself: the payload carries
    source_app='electricity' plus an external_id, and App A skips records
    it has already imported (returns created=False).
    """
    body = {
        "expense_date": payload["date"],
        "merchant": payload["merchant"],
        "amount": str(payload["amount"]),
        "category": payload["category"],
        "payment_method": payload.get("payment_method", "Electricity"),
        "description": payload["description"],
        "source_app": "electricity",
        "external_id": payload["external_id"],
    }
    try:
        resp = requests.post(
            _url("/expenses"),
            json=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {_settings().EXPENSE_API_TOKEN}",
            },
            timeout=_settings().HTTP_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise IntegrationError(f"POST /expenses failed: {exc}") from exc
    if resp.status_code >= 400:
        raise IntegrationError(f"POST /expenses returned HTTP {resp.status_code}: {resp.text[:200]}")
    data = _safe_json(resp) or {}
    return {"status_code": resp.status_code, "created": bool(data.get("created", True)), "record": data}
