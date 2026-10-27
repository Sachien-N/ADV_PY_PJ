"""Pytest configuration: isolated in-memory SQLite database per test."""
from __future__ import annotations

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ALLOW_UNAUTHENTICATED_WRITES"] = "1"
os.environ["API_TOKEN"] = ""
os.environ["EXPENSE_API_URL"] = ""
os.environ["DEVIATION_THRESHOLD_PCT"] = "25"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client():
    database.Base.metadata.drop_all(bind=database.engine)
    database.init_db()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def tariffed(client):
    """Two demo slabs: 0-200 kWh @ 6.50, 200+ @ 8.00 (DEMO INPUT, not official)."""
    client.post("/tariff/slabs", json={
        "name": "Demo slab 1", "up_to_kwh": "200", "rate_per_kwh": "6.5",
        "effective_from": "2020-01-01", "source": "DEMO INPUT for tests"})
    client.post("/tariff/slabs", json={
        "name": "Demo slab 2", "up_to_kwh": "99999", "rate_per_kwh": "8.0",
        "effective_from": "2020-01-01", "source": "DEMO INPUT for tests"})
    return client


@pytest.fixture()
def readings(tariffed):
    """Four monthly simulated readings -> Sep/Oct/Nov consumption series."""
    for d, k in [("2026-08-01", "1000"), ("2026-09-01", "1100"),
                 ("2026-10-01", "1250"), ("2026-11-01", "1300")]:
        r = tariffed.post("/readings", json={
            "reading_date": d, "reading_kwh": k, "source": "simulated"})
        assert r.status_code == 201, r.text
    return tariffed
