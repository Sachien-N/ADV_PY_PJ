"""Pytest configuration: isolated in-memory SQLite database per test session."""
from __future__ import annotations

import os
import sys

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["ALLOW_UNAUTHENTICATED_WRITES"] = "1"
os.environ["API_TOKEN"] = ""
os.environ["SUBSCRIPTION_API_URL"] = ""
os.environ["ELECTRICITY_API_URL"] = ""

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import database  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def client():
    # Fresh tables for every test (in-memory engine shared per module run).
    database.Base.metadata.drop_all(bind=database.engine)
    database.init_db()
    with TestClient(app) as c:
        yield c
