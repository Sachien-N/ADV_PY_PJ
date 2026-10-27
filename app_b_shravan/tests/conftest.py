"""Pytest configuration: isolated in-memory SQLite database per test."""
from __future__ import annotations

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ALLOW_UNAUTHENTICATED_WRITES"] = "1"
os.environ["API_TOKEN"] = ""
os.environ["EXPENSE_API_URL"] = ""

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
def sample(client):
    """Create and return one monthly Netflix subscription payload result."""
    resp = client.post("/subscriptions", json={
        "service_name": "Netflix", "amount": "499.00",
        "billing_frequency": "monthly", "start_date": "2026-01-15",
        "category": "Entertainment", "tags": "video, family",
    })
    assert resp.status_code == 201
    return resp.json()
