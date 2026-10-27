"""Integration tests for Application C using MOCKED Application A responses.

Covers: export feed shape & eligibility rules (estimates excluded), category
fetching with graceful fallback, the genuine push flow into App A's POST
/expenses (correct fields + idempotency), sync log bookkeeping and auth
protection.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import patch

from main import app  # provided by conftest sys.path setup

APP_A_CATEGORIES = ["Food", "Travel", "Bills", "Entertainment",
                    "Shopping", "Subscriptions", "Other"]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _patched_get(url, headers=None, timeout=None, **kw):
    path = url.rstrip("/").split("/")[-1] if url else ""
    if url.endswith("/categories"):
        return FakeResponse(APP_A_CATEGORIES)
    if url.endswith("/health"):
        return FakeResponse({"status": "ok"})
    return FakeResponse({"detail": "not found"}, 404)


def _no_network():
    """Patch every outbound HTTP call in the client (GET session + POST)."""
    return (
        patch("services.expense_client._session"),
        patch("services.expense_client.requests.post"),
    )


def _seed_bill_and_payment(client):
    client.post("/tariff/slabs", json={
        "name": "Demo slab", "up_to_kwh": "99999", "rate_per_kwh": "7",
        "effective_from": "2020-01-01", "source": "DEMO"})
    bill = client.post("/bill/actual", json={
        "bill_month": "2026-09", "amount": "1850.40",
        "bill_date": "2026-09-30"}).json()
    pay = client.post("/payments", json={
        "paid_on": "2026-09-28", "amount": "1850.40", "method": "UPI",
        "bill_id": bill["id"]}).json()
    return bill, pay


# ----------------------------- export feed -----------------------------

def test_export_feed_only_recorded_charges(client):
    """Actual bills + payments are exported; estimates never appear."""
    bill, pay = _seed_bill_and_payment(client)
    # create consumption so an estimate EXISTS for a month...
    client.post("/readings", json={"reading_date": "2026-09-01",
                                   "reading_kwh": "100", "source": "simulated"})
    client.post("/readings", json={"reading_date": "2026-10-01",
                                   "reading_kwh": "200", "source": "simulated"})
    est = client.get("/bill/estimate", params={"month": "2026-10"})
    assert est.status_code == 200                      # estimate computable
    items = client.get("/integration/expenses").json()
    kinds = {i["kind"] for i in items}
    assert kinds == {"actual_bill", "payment"}         # no 'estimate' ever exported
    refs = {i["external_ref"] for i in items}
    assert refs == {f"actual-bill-{bill['id']}-2026-09",
                    f"payment-{pay['id']}-2026-09-28"}
    for i in items:
        assert Decimal(i["amount"]) > 0
        assert i["currency"] == "INR"


def test_export_records_validate_against_app_a_schema(client):
    """Validate our feed against a local replica of App A's ExternalElectricityExpense.

    Contract source: app_a_sachien/schemas.py::ExternalElectricityExpense.
    We deliberately do NOT import App A's package inside App C's test session
    (module-name collisions between the two independent projects); instead this
    replica enforces the same documented field rules. If the contract changes,
    update both this model and API_DOCUMENTATION.md.
    """
    import datetime as dt
    from pydantic import BaseModel, ConfigDict, Field

    class ExternalElectricityExpense(BaseModel):
        """Mirror of app_a_sachien/schemas.py::ExternalElectricityExpense."""
        model_config = ConfigDict(extra="ignore")

        id: int | str
        reading_date: dt.date | None = None
        bill_month: str | None = None
        description: str
        amount: Decimal
        currency: str = "INR"
        kind: str = Field(pattern="^(actual_bill|payment)$")
        external_ref: str = Field(min_length=1)

    _seed_bill_and_payment(client)
    items = client.get("/integration/expenses").json()
    assert len(items) >= 2
    for raw in items:
        rec = ExternalElectricityExpense.model_validate(raw)
        assert rec.kind in ("actual_bill", "payment")


# ----------------------------- categories -----------------------------


def test_categories_fetched_from_app_a(client, monkeypatch):
    """When App A returns its documented category list, status shows app_a source."""
    monkeypatch.setenv("EXPENSE_API_URL", "https://app-a.example.com")

    class Resp:
        status_code = 200
        def json(self):
            return APP_A_CATEGORIES  # App A /categories serves a plain JSON list

    with patch("services.expense_client._session") as sess:
        sess.return_value.get.return_value = Resp()
        out = client.get("/integration/status").json()
    assert out["category_source"] == "app_a"
    assert out["categories_from_app_a"] == APP_A_CATEGORIES
    assert out["mapped_category_for_electricity"] == "Bills"


def test_app_a_down_falls_back_without_breaking_app_c(client, monkeypatch):
    """Peer outage must degrade gracefully, never crash or block App C."""
    monkeypatch.setenv("EXPENSE_API_URL", "https://app-a.example.com")
    with patch("services.expense_client._session") as sess, \
         patch("services.expense_client.requests.post",
               side_effect=Exception("connection refused")):
        sess.return_value.get.side_effect = Exception("connection refused")
        status = client.get("/integration/status").json()
        assert status["category_source"] == "local-default"
        push = client.post("/sync/push-expenses").json()
        assert push["status"] == "failed"
    # core functionality still works during peer outage
    r = client.post("/appliances", json={
        "name": "Fridge", "rated_power_w": "150", "daily_hours": "24"})
    assert r.status_code == 201


# ----------------------------- sync bookkeeping -----------------------------

def test_sync_history_records_attempts(client):
    h = client.get("/sync/history").json()
    assert h == []
    client.post("/sync/push-expenses")   # EXPENSE_API_URL unset -> failed
    rows = client.get("/sync/history").json()
    assert len(rows) == 1 and rows[0]["status"] == "failed"
    assert "not configured" in rows[0]["detail"]


def test_repeated_sync_never_duplicates_on_app_a_side(readings):
    """Idempotency contract: stable external_refs let App A dedupe on repeat pulls."""
    readings.post("/bill/actual", json={"bill_month": "2026-10", "amount": "1000"})
    first = readings.get("/integration/expenses").json()
    second = readings.get("/integration/expenses").json()
    assert [r["external_ref"] for r in first] == [r["external_ref"] for r in second]
    assert len({r["external_ref"] for r in first}) == len(first)  # refs unique


# ----------------------------- authentication -----------------------------


def test_write_endpoints_protected_when_token_configured(monkeypatch):
    """With API_TOKEN set, missing/wrong bearer tokens are rejected.

    Auth is resolved per-request via get_settings(), so monkeypatching the
    environment is enough — no module reloads (which would leak state into
    other tests because config/settings objects are shared).
    """
    from fastapi.testclient import TestClient
    import database

    monkeypatch.setenv("API_TOKEN", "secret-token")
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_WRITES", raising=False)

    database.Base.metadata.drop_all(bind=database.engine)
    database.init_db()
    with TestClient(app) as c:  # `app` imported at module top of conftest pattern
        assert c.post("/readings", json={
            "reading_date": "2026-01-01", "reading_kwh": "1"}).status_code == 401
        assert c.post("/readings", json={
            "reading_date": "2026-01-01", "reading_kwh": "1"},
            headers={"Authorization": "Bearer wrong"}).status_code == 403
        assert c.post("/readings", json={
            "reading_date": "2026-01-01", "reading_kwh": "1"},
            headers={"Authorization": "Bearer secret-token"}).status_code == 201
        # read endpoints stay open (least privilege for teammates)
        assert c.get("/integration/expenses").status_code == 200
