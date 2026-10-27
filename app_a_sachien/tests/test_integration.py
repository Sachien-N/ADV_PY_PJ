"""Integration tests for Application A using MOCKED peer APIs.

Covers: idempotent sync, duplicate prevention, graceful degradation when a
peer API is down, invalid-response handling, and auth protection.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from unittest.mock import patch

SUB_EXPORT = {
    "items": [
        {"id": 1, "service_name": "Netflix", "amount": "649.00", "currency": "INR",
         "billing_frequency": "monthly", "monthly_equivalent": "649.00",
         "next_renewal": "2026-11-01", "status": "active", "category": "Entertainment"},
        {"id": 2, "service_name": "Adobe CC", "amount": "3600.00", "currency": "INR",
         "billing_frequency": "annual", "monthly_equivalent": "300.00",
         "next_renewal": "2027-03-15", "status": "active", "category": "Other"},
    ]
}

ELEC_EXPENSES = {
    "items": [
        {"id": 10, "bill_month": "2026-09", "description": "Actual electricity bill Sep 2026",
         "amount": "1850.40", "currency": "INR", "kind": "actual_bill",
         "external_ref": "bill-10", "reading_date": "2026-09-30"},
        {"id": 11, "bill_month": "2026-09", "description": "Bill payment Sep 2026",
         "amount": "1850.40", "currency": "INR", "kind": "payment",
         "external_ref": "pay-11", "reading_date": "2026-09-30"},
    ]
}


def _sync_all(client):
    return client.post("/sync/subscriptions").json(), client.post("/sync/electricity").json()


def test_sync_subscriptions_imports_and_idempotent(client):
    with patch("services.api_client._get_json", return_value=SUB_EXPORT):
        r1 = client.post("/sync/subscriptions")
        assert r1.status_code == 200
        body = r1.json()
        assert body["status"] == "success" and body["records_imported"] == 2

        # second sync must not create duplicates
        r2 = client.post("/sync/subscriptions")
        assert r2.json()["records_imported"] == 0
        assert r2.json()["records_skipped"] == 2

        expenses = client.get("/expenses", params={"source": "app_b"}).json()
        assert expenses["total"] == 2
        netflix = [e for e in expenses["items"] if e["merchant"] == "Netflix"][0]
        assert float(netflix["amount"]) == 649.00
        assert netflix["category"] == "Subscriptions"
        assert netflix["external_id"] == "sub-1"
        assert netflix["last_synced_at"] is not None


def test_sync_updates_budget_summary(client):
    with patch("services.api_client._get_json", return_value=SUB_EXPORT):
        client.post("/sync/subscriptions")
    client.post("/budgets", json={"month": "2026-11", "category": "Subscriptions",
                                  "limit_amount": "1000.00"})
    summary = client.get("/summary", params={"month": "2026-11"}).json()
    sub = next(b for b in summary["budgets"] if b["category"] == "Subscriptions")
    assert float(sub["spent"]) == 649.00  # Netflix renews 2026-11-01
    assert float(summary["external_sources"]["app_b"]) == 649.00


def test_sync_electricity_only_eligible_records(client):
    with patch("services.api_client._get_json", return_value=ELEC_EXPENSES):
        r = client.post("/sync/electricity")
        assert r.json()["records_imported"] == 2
        # repeat -> no duplicates
        r2 = client.post("/sync/electricity")
        assert r2.json()["records_imported"] == 0
        items = client.get("/expenses", params={"source": "app_c"}).json()["items"]
        assert len(items) == 2
        refs = {i["external_id"] for i in items}
        assert refs == {"bill-10", "pay-11"}


def test_peer_api_down_app_remains_functional(client):
    from services.api_client import IntegrationError

    with patch("services.api_client._get_json", side_effect=IntegrationError("timeout")):
        r = client.post("/sync/subscriptions")
        assert r.status_code == 200  # graceful failure, not 5xx
        body = r.json()
        assert body["status"] == "failed"
        assert "timeout" in body["message"]
    # core functionality unaffected
    assert client.post("/expenses", json={
        "expense_date": "2026-10-01", "merchant": "Test", "amount": "10.00",
        "category": "Other"}).status_code == 201


def test_invalid_external_payload_records_skipped(client):
    bad = {"items": [{"id": 1}, {"id": 2, "service_name": "Good", "amount": "10.00",
                      "billing_frequency": "monthly", "monthly_equivalent": "10.00",
                      "status": "active"}]}
    with patch("services.api_client._get_json", return_value=bad):
        r = client.post("/sync/subscriptions")
        assert r.json()["records_imported"] == 1  # malformed record skipped safely


def test_integration_status_reports_unconfigured_peers(client):
    r = client.get("/integration/status")
    assert r.status_code == 200
    js = r.json()
    assert js["subscription_api"]["reachable"] is False
    assert js["electricity_api"]["reachable"] is False


def test_auth_required_for_writes_when_token_set():
    """With API_TOKEN configured, unauthenticated writes must be rejected."""
    import importlib
    import config as config_mod

    old_env = dict(__import__("os").environ)
    try:
        __import__("os").environ["API_TOKEN"] = "secret-token"
        __import__("os").environ["ALLOW_UNAUTHENTICATED_WRITES"] = ""
        importlib.reload(config_mod)
        for mod_name in ("api.auth", "main"):
            importlib.reload(importlib.import_module(mod_name))
        from fastapi.testclient import TestClient
        import main as main_mod

        with TestClient(main_mod.app) as c:
            assert c.post("/expenses", json={
                "expense_date": "2026-10-01", "merchant": "X", "amount": "5.00",
                "category": "Other"}).status_code == 401
            assert c.post("/expenses", json={
                "expense_date": "2026-10-01", "merchant": "X", "amount": "5.00",
                "category": "Other"},
                headers={"Authorization": "Bearer secret-token"}).status_code == 201
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        importlib.reload(config_mod)
        for mod_name in ("api.auth", "main"):
            importlib.reload(importlib.import_module(mod_name))


import os  # noqa: E402
