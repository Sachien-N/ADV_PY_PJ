"""Core tests: CRUD, validation, costs, renewals, tags, auth, persistence."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

import database
from main import app
from fastapi.testclient import TestClient


# --------------------------- Health & basic CRUD ---------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["app"] == "subscription-tracker"


def test_create_get_update_delete(client, sample):
    sid = sample["id"]
    got = client.get(f"/subscriptions/{sid}")
    assert got.status_code == 200
    assert got.json()["service_name"] == "Netflix"

    upd = client.put(f"/subscriptions/{sid}", json={"status": "paused"})
    assert upd.status_code == 200 and upd.json()["status"] == "paused"

    assert client.delete(f"/subscriptions/{sid}").status_code == 204
    assert client.get(f"/subscriptions/{sid}").status_code == 404


def test_get_missing_404(client):
    assert client.get("/subscriptions/9999").status_code == 404


def test_list_pagination_and_filters(client, sample):
    client.post("/subscriptions", json={
        "service_name": "Spotboy", "amount": "119", "billing_frequency": "monthly",
        "start_date": "2026-05-01", "category": "Music", "tags": "audio",
    })
    lst = client.get("/subscriptions", params={"page": 1, "page_size": 1}).json()
    assert lst["total"] == 2 and len(lst["items"]) == 1
    music = client.get("/subscriptions", params={"category": "Music"}).json()
    assert music["total"] == 1
    search = client.get("/subscriptions", params={"search": "spot"}).json()
    assert search["items"][0]["service_name"] == "Spotboy"


# --------------------------- Validation errors ---------------------------

@pytest.mark.parametrize("payload,field", [
    ({"service_name": "", "amount": "100", "start_date": "2026-01-01"}, "name"),
    ({"service_name": "X", "amount": "-5", "start_date": "2026-01-01"}, "amount"),
    ({"service_name": "X", "amount": "100", "start_date": "2026-01-01",
      "billing_frequency": "weekly"}, "frequency"),
    ({"service_name": "X", "amount": "100", "start_date": "2026-01-01",
      "status": "deleted"}, "status"),
    ({"service_name": "X", "amount": "100",
      "start_date": (dt.date.today() + dt.timedelta(days=30)).isoformat()}, "future start"),
])
def test_invalid_payloads_422(client, payload, field):
    r = client.post("/subscriptions", json=payload)
    assert r.status_code == 422, f"{field} should be rejected"


def test_duplicate_subscription_409(client, sample):
    # `sample` creates the first Netflix subscription; this POST is the duplicate.
    r = client.post("/subscriptions", json={
        "service_name": "Netflix", "amount": "499", "billing_frequency": "monthly",
        "start_date": "2026-01-15",
    })
    assert r.status_code == 409


# --------------------------- Cost calculations ---------------------------

def test_monthly_equivalent_and_annual(client, sample):
    client.post("/subscriptions", json={
        "service_name": "Prime", "amount": "1799", "billing_frequency": "annual",
        "start_date": "2026-01-01", "category": "Entertainment",
    })
    totals = client.get("/total").json()
    # 499 monthly + 1799/12 = 149.92 monthly-equivalent
    assert Decimal(totals["monthly_total"]) == Decimal("648.92")
    assert Decimal(totals["annual_total"]) == Decimal("7787.04")
    assert Decimal(totals["by_category"]["Entertainment"]) == Decimal("648.92")


def test_cancelled_not_counted_in_total(client, sample):
    client.put(f"/subscriptions/{sample['id']}", json={"status": "cancelled"})
    totals = client.get("/total").json()
    assert totals["active_count"] == 0
    assert Decimal(totals["monthly_total"]) == Decimal("0.00")


@pytest.mark.parametrize("freq,amount,expected", [
    ("monthly", "600", "600.00"),
    ("quarterly", "600", "200.00"),
    ("half-yearly", "600", "100.00"),
    ("annual", "600", "50.00"),
])
def test_frequencies(client, freq, amount, expected):
    r = client.post("/subscriptions", json={
        "service_name": f"Svc-{freq}", "amount": amount,
        "billing_frequency": freq, "start_date": "2026-01-01",
    })
    assert r.status_code == 201
    from schemas import monthly_equivalent
    assert monthly_equivalent(Decimal(amount), freq) == Decimal(expected)


# --------------------------- Renewal date handling ---------------------------

def test_next_renewal_auto_computed(client, sample):
    # Today is >= 2026-10-27 in CI; monthly renewal from Jan-15 must be the 15th
    renewal = dt.date.fromisoformat(sample["next_renewal"])
    assert renewal > dt.date.today()
    assert renewal.day == 15


def test_renewal_month_end_clamping():
    from schemas import add_months
    assert add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert add_months(dt.date(2024, 1, 31), 1) == dt.date(2024, 2, 29)


def test_upcoming_renewals_windows(client, sample):
    client.post("/subscriptions", json={
        "service_name": "Soon", "amount": "99", "billing_frequency": "monthly",
        "start_date": "2026-01-01",
        "next_renewal": (dt.date.today() + dt.timedelta(days=5)).isoformat(),
    })
    d7 = client.get("/renewals", params={"days": 7}).json()
    d30 = client.get("/renewals", params={"days": 30}).json()
    assert any(r["service_name"] == "Soon" for r in d7)
    assert len(d30) >= len(d7)
    assert all(r["days_until_renewal"] <= 7 for r in d7)


# --------------------------- Tags & category ---------------------------

def test_tags_endpoint(client, sample):
    tags = client.get("/tags").json()
    assert "video" in tags and "family" in tags


def test_category_detail(client, sample):
    detail = client.get("/category/Entertainment").json()
    assert detail["count"] == 1
    assert Decimal(str(detail["monthly_equivalent_total"])) == Decimal("499.00")


# --------------------------- Authentication ---------------------------

def test_write_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "secret-token")
    from config import Settings
    monkeypatch.setattr(Settings, "API_TOKEN", "secret-token", raising=False)
    monkeypatch.delenv("ALLOW_UNAUTHENTICATED_WRITES", raising=False)
    database.Base.metadata.drop_all(bind=database.engine)
    database.init_db()
    with TestClient(app) as c:
        r = c.post("/subscriptions", json={
            "service_name": "NoAuth", "amount": "10", "start_date": "2026-01-01"})
        assert r.status_code == 401
        ok = c.post("/subscriptions", json={
            "service_name": "NoAuth", "amount": "10", "start_date": "2026-01-01"},
            headers={"Authorization": "Bearer secret-token"})
        assert ok.status_code == 201


# --------------------------- Persistence ---------------------------

def test_records_persist_across_sessions(client, sample):
    """Same engine, new session: data remains (mirrors restart persistence)."""
    from sqlalchemy.orm import Session
    with Session(database.engine) as s:
        from models import Subscription
        assert s.query(Subscription).count() == 1
