"""Integration tests: export feed, App A client behaviour with mocks,
category mapping, graceful degradation and cross-application sync check."""
from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest
import requests

import services.expense_client as expense_client
from schemas import ExternalCategoryMap


# --------------------------- Export feed contract ---------------------------

def test_export_only_eligible(client, sample):
    client.post("/subscriptions", json={
        "service_name": "Dead", "amount": "100", "billing_frequency": "monthly",
        "start_date": "2026-01-01",
    })
    client.put(f"/subscriptions/2", json={"status": "cancelled"})
    items = client.get("/subscriptions/export").json()["items"]
    names = [i["service_name"] for i in items]
    assert "Netflix" in names and "Dead" not in names


def test_export_matches_app_a_validator(client, sample):
    """The exported payload must validate against Application A's schema shape."""
    item = client.get("/subscriptions/export").json()["items"][0]
    # Mirror of App A's ExternalSubscription required fields:
    for field in ("id", "service_name", "amount", "currency",
                  "billing_frequency", "monthly_equivalent", "next_renewal",
                  "status", "category"):
        assert field in item
    assert Decimal(item["monthly_equivalent"]) == Decimal("499.00")


def test_paused_still_shared(client, sample):
    client.put(f"/subscriptions/{sample['id']}", json={"status": "paused"})
    items = client.get("/subscriptions/export").json()["items"]
    assert len(items) == 1 and items[0]["status"] == "paused"


# --------------------------- Category fetch from App A (mocked) ---------------------------

def test_fetch_categories_success(monkeypatch):
    class FakeResp:
        status_code = 200
        def json(self):
            return ["Food", "Travel", "Bills", "Entertainment",
                    "Shopping", "Subscriptions", "Other"]
    monkeypatch.setattr(expense_client.settings, "EXPENSE_API_URL",
                        "https://fake-app-a.example")
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: FakeResp())
    result = expense_client.fetch_categories()
    assert result["source"] == "app_a" and len(result["categories"]) == 7


def test_fetch_categories_invalid_json(monkeypatch):
    class BadResp:
        status_code = 200
        def json(self):
            return {"not": "a list"}
    monkeypatch.setattr(expense_client.settings, "EXPENSE_API_URL",
                        "https://fake-app-a.example")
    monkeypatch.setattr(requests.Session, "get", lambda *a, **k: BadResp())
    result = expense_client.fetch_categories()
    # Invalid response -> graceful fallback, never a crash:
    assert result["source"] == "local-default"


def test_fetch_categories_timeout_degrades_gracefully(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("simulated timeout")
    monkeypatch.setattr(expense_client.settings, "EXPENSE_API_URL",
                        "https://fake-app-a.example")
    monkeypatch.setattr(requests.Session, "get", boom)
    result = expense_client.fetch_categories()
    assert result["reachable"] is False
    assert "Subscriptions" in result["categories"]


def test_integration_status_without_app_a(client):
    """App B remains fully functional when EXPENSE_API_URL is unset."""
    r = client.get("/integration/status")
    assert r.status_code == 200
    body = r.json()
    assert body["expense_api"]["configured"] is False
    # Falls back to the default taxonomy so the UI still works:
    assert "Subscriptions" in body["categories_from_app_a"]


def test_push_fails_gracefully_when_app_a_down(client, sample):
    r = client.post("/sync/push-expenses")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert "not configured" in body["message"] or "unreachable" in body["message"].lower()
    history = client.get("/sync/history").json()
    assert history[0]["status"] == "failed"


# --------------------------- Category mapping ---------------------------

def test_map_category():
    cats = ["Food", "Travel", "Bills", "Entertainment",
            "Shopping", "Subscriptions", "Other"]
    assert expense_client.map_category("entertainment", cats) == "Entertainment"
    assert expense_client.map_category("Music", cats) == "Subscriptions"
    assert expense_client.map_category("Cloud Storage", cats) == "Subscriptions"


def test_external_category_map_validates_list():
    m = ExternalCategoryMap.from_response(["A", "B"])
    assert m.categories == ["A", "B"]
    with pytest.raises(ValueError):
        ExternalCategoryMap.from_response({"wrong": True})


# --------------------------- Cross-application end-to-end (subprocess) ----------

CROSS_APP_SCRIPT = r"""
import os, sys

os.environ["ALLOW_UNAUTHENTICATED_WRITES"] = "1"
os.environ["API_TOKEN"] = ""
os.environ["EXPENSE_API_URL"] = ""

app_b_dir, app_a_dir = sys.argv[1], sys.argv[2]

# --- Load Application B under module alias package "bapp" ---
sys.path.insert(0, app_b_dir)
from fastapi.testclient import TestClient
import main as b_main  # App B backend
cb = TestClient(b_main.app)
with cb:
    r = cb.post("/subscriptions", json={
        "service_name": "Disney+", "amount": "299",
        "billing_frequency": "monthly", "start_date": "2026-06-01",
        "category": "Entertainment"})
    assert r.status_code == 201, r.text
    feed = cb.get("/subscriptions/export").json()
    assert feed["items"][0]["service_name"] == "Disney+"
    renewal_month = feed["items"][0]["next_renewal"][:7]

    # --- Load Application A in a fresh interpreter (separate DB/process-free
    #     but isolated modules): run it inline here with its own sys.path ---
    for name in list(sys.modules):
        if name in ("main", "config", "database", "models", "schemas", "services",
                    "api") or name.startswith(("services.", "api.")):
            del sys.modules[name]
    sys.path.remove(app_b_dir)
    sys.path.insert(0, app_a_dir)
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    import main as a_main
    import config as a_config
    import database as a_database
    from sqlalchemy.pool import StaticPool
    a_database.engine = a_database.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    a_database.SessionLocal.configure(bind=a_database.engine)
    a_database.Base.metadata.create_all(bind=a_database.engine)
    ca = TestClient(a_main.app)
    with ca:
        # Bridge App A's HTTP client to App B's TestClient (mocked external service)
        import services.api_client as a_api
        class Bridge:
            def get(self, url, **kw):
                resp = cb.get("/" + url.split("://", 1)[1].split("/", 1)[1])
                class R: pass
                R.status_code = resp.status_code
                R.json = resp.json
                return R
        a_api._session = lambda: Bridge()
        cfg = a_config.get_settings()
        cfg.SUBSCRIPTION_API_URL = "https://fake-b"

        # Step 3: import into A
        s1 = ca.post("/sync/subscriptions").json()
        assert s1["status"] == "success" and s1["records_imported"] == 1, s1

        # Step 4: budget summary reflects it
        summ = ca.get("/summary", params={"month": renewal_month}).json()
        subs = [c for c in summ["by_category"] if c["category"] == "Subscriptions"]
        from decimal import Decimal
        assert subs and Decimal(str(subs[0]["total"])) == Decimal("299.00"), summ

        # Step 5: re-sync -> no duplicate
        s2 = ca.post("/sync/subscriptions").json()
        assert s2["records_imported"] == 0 and s2["records_skipped"] == 1, s2
        exp = ca.get("/expenses", params={"source": "app_b"}).json()
        assert exp["total"] == 1, exp

        # Categories flow: App A exposes categories used by B/C mapping
        cats = ca.get("/categories").json()
        assert "Subscriptions" in cats
print("CROSS-APP OK")
"""


def test_cross_app_sync_no_duplicates(tmp_path):
    """Workflow steps 1-5 across the two independent backends with a mocked
    HTTP bridge (no network). Runs each app's real FastAPI code."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app_b_dir = root
    app_a_dir = os.path.abspath(os.path.join(root, "..", "app_a_sachien"))
    script = tmp_path / "cross_app.py"
    script.write_text(CROSS_APP_SCRIPT)
    result = subprocess.run(
        [sys.executable, str(script), app_b_dir, app_a_dir],
        capture_output=True, text=True, timeout=120,
    )
    assert "CROSS-APP OK" in result.stdout, (result.stdout, result.stderr)
