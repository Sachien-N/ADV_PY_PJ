"""Core CRUD, validation, budget and persistence tests for Application A."""
from __future__ import annotations

import datetime as dt


def _expense(**over):
    body = {
        "expense_date": "2026-10-05",
        "merchant": "Swiggy",
        "amount": "250.50",
        "category": "Food",
        "payment_method": "UPI",
        "description": "dinner",
    }
    body.update(over)
    return body


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_expense_crud_cycle(client):
    # CREATE
    r = client.post("/expenses", json=_expense())
    assert r.status_code == 201
    eid = r.json()["id"]

    # READ
    r = client.get(f"/expenses/{eid}")
    assert r.status_code == 200
    assert r.json()["merchant"] == "Swiggy"
    assert float(r.json()["amount"]) == 250.50

    # UPDATE
    r = client.put(f"/expenses/{eid}", json={"amount": "300.00", "category": "Other"})
    assert r.status_code == 200
    assert float(r.json()["amount"]) == 300.00

    # DELETE
    assert client.delete(f"/expenses/{eid}").status_code == 204
    assert client.get(f"/expenses/{eid}").status_code == 404


def test_validation_errors(client):
    assert client.post("/expenses", json=_expense(amount="-5")).status_code == 422
    assert client.post("/expenses", json=_expense(category="Invalid")).status_code == 422
    assert client.post("/expenses", json=_expense(expense_date="not-a-date")).status_code == 422
    assert client.post("/expenses", json=_expense(currency="rupees")).status_code == 422
    assert client.get("/expenses/999999").status_code == 404


def test_pagination_and_filters(client):
    for i in range(25):
        client.post("/expenses", json=_expense(merchant=f"Shop{i}", amount="10.00"))
    r = client.get("/expenses", params={"page": 2, "page_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 25 and len(body["items"]) == 10
    r = client.get("/expenses", params={"search": "Shop3"})
    assert r.json()["total"] == 1
    r = client.get("/expenses", params={"category": "Food", "date_from": "2026-10-01",
                                        "date_to": "2026-10-31"})
    assert r.json()["total"] == 25


def test_categorization_rules(client):
    r = client.get("/categorize", params={"merchant": "Netflix India"})
    assert r.json()["category"] == "Subscriptions"
    r = client.get("/categorize", params={"merchant": "Random Emporium"})
    assert r.json()["category"] == "Other"
    # add custom rule then re-check
    r = client.post("/rules", json={"pattern": "emporium", "category": "Shopping"})
    assert r.status_code == 201
    assert client.get("/categorize", params={"merchant": "Random Emporium"}).json()["category"] == "Shopping"


def test_budget_utilization_and_overspending(client):
    client.post("/budgets", json={"month": "2026-10", "category": "Food", "limit_amount": "1000.00"})
    client.post("/expenses", json=_expense(amount="600.00"))
    client.post("/expenses", json=_expense(amount="500.00", merchant="Zomato"))
    r = client.get("/budgets/status", params={"month": "2026-10"})
    st = r.json()["statuses"][0]
    assert float(st["spent"]) == 1100.00
    assert float(st["remaining"]) == -100.00
    assert float(st["utilization_percent"]) == 110.0
    assert st["over_budget"] is True


def test_duplicate_budget_rejected(client):
    payload = {"month": "2026-10", "category": "Food", "limit_amount": "1000.00"}
    assert client.post("/budgets", json=payload).status_code == 201
    assert client.post("/budgets", json=payload).status_code == 409


def test_summary_month(client):
    client.post("/expenses", json=_expense(amount="250.50"))
    client.post("/expenses", json=_expense(amount="100.00", category="Travel", merchant="Uber"))
    r = client.get("/summary", params={"month": "2026-10"})
    assert r.status_code == 200
    body = r.json()
    assert float(body["total_spent"]) == 350.50
    cats = {c["category"]: float(c["total"]) for c in body["by_category"]}
    assert cats == {"Food": 250.50, "Travel": 100.00}
    assert client.get("/summary", params={"month": "2026-13"}).status_code == 422


def test_csv_export_import_roundtrip(client):
    client.post("/expenses", json=_expense())
    csv_resp = client.get("/export/csv")
    assert csv_resp.status_code == 200
    text = csv_resp.text
    assert "Swiggy" in text
    imported = client.post("/import/csv", files={"file": ("e.csv", text.encode(), "text/csv")})
    assert imported.status_code == 200
    assert imported.json()["imported"] >= 1


def test_categories_endpoint_for_peers(client):
    r = client.get("/categories")
    assert r.status_code == 200
    assert "Subscriptions" in r.json() and "Bills" in r.json()
