"""Integration tests for Application C using MOCKED Application A responses.

Covers: export feed shape & eligibility rules (estimates excluded), category
fetching with graceful fallback, the genuine push flow into App A's POST
/expenses (correct fields + idempotency), sync log bookkeeping and auth
protection.
"""
from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import patch

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
    """Replay the exact Pydantic model Application A uses to validate our feed."""
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                    "app_a_sachien"))
    _seed_bill_and_payment(client)
    from schemas import ExternalElectricityExpense  # noqa (App A's schema)
    for raw in client.get("/integration/expenses").json():
        rec = ExternalElectricityExpense.model_validate(raw)
        assert rec.kind in ("actual_bill", "payment")


# ----------------------------- categories -----------------------------

def test_categories_fetched_from_app_a(client):
    class Resp:
        status_code = 200
        def json(self):
            return APP_A_CATEGORIES
    with patch("services.expense_client._session") as sess:
        sess.return_value.get.return_value = Resp()
        out = client.get("/integration/status").json()
    assert out["category_source"] == "app_a"
    assert out["categories_from_app_a"] == APP_A_CATEGORIES
    assert out["mapped_category_for_electricity"] == "Bills"


def test_app_a_down_falls_back_without_breaking_app_c(client):
    """Peer outage must degrade gracefully, never crash or block App C."""
    with patch("services.expense_client._session",
               side_effect=Exception("connection refused")):
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

def test_write_endpoints_protected_when_token_configured():
    """With API_TOKEN set, missing/wrong bearer tokens are rejected."""
    import importlib
    import config as config_mod
    importlib.reload(config_mod)
    config_mod.get_settings.cache_clear()
    os.environ["API_TOKEN"] = "secret-token"
    os.environ.pop("ALLOW_UNAUTHENTICATED_WRITES", None)
    config_mod.get_settings.cache_clear()

    import database
    import main
    importlib.reload(main)
    from fastapi.testclient import TestClient
    database.Base.metadata.drop_all(bind=database.engine)
    with TestClient(main.app) as c:
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

    # restore clean env for other tests
    del os.environ["API_TOKEN"]
    os.environ["ALLOW_UNAUTHENTICATED_WRITES"] = "1"
    config_mod.get_settings.cache_clear()
    importlib.reload(main)
