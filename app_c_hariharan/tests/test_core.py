"""Core unit/API tests: CRUD, validation, tariff math, analysis, exports."""
from __future__ import annotations

from decimal import Decimal


# ----------------------------- health & docs -----------------------------

def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["owner"] == "Hariharan S"


def test_swagger_docs_available(client):
    assert client.get("/docs").status_code == 200


# ----------------------------- appliances -----------------------------

def test_appliance_crud_and_monthly_kwh(client):
    r = client.post("/appliances", json={
        "name": "Ceiling Fan", "category": "Cooling",
        "rated_power_w": "75", "daily_hours": "10", "quantity": 2})
    assert r.status_code == 201
    ap = r.json()
    # 75W * 10h * 30.42d * 2 / 1000 = 45.63 kWh/month
    assert Decimal(ap["monthly_kwh"]) == Decimal("45.630")

    assert client.post("/appliances", json={
        "name": "Ceiling Fan", "rated_power_w": "75",
        "daily_hours": "10"}).status_code == 409          # duplicate name

    upd = client.put(f"/appliances/{ap['id']}", json={"daily_hours": "5"})
    assert upd.status_code == 200
    assert Decimal(upd.json()["monthly_kwh"]) == Decimal("22.815")

    assert client.delete(f"/appliances/{ap['id']}").status_code == 204
    assert client.get(f"/appliances/{ap['id']}").status_code == 404


def test_appliance_validation_errors(client):
    bad = {"name": "Heater", "rated_power_w": "-100", "daily_hours": "25"}
    assert client.post("/appliances", json=bad).status_code == 422


# ----------------------------- meter readings -----------------------------

def test_reading_lifecycle_and_delta(tariffed):
    assert tariffed.post("/readings", json={
        "reading_date": "2026-09-01", "reading_kwh": "1000",
        "source": "manual"}).status_code == 201
    dup = tariffed.post("/readings", json={
        "reading_date": "2026-09-01", "reading_kwh": "1100", "source": "manual"})
    assert dup.status_code == 409                          # unique date
    rollback = tariffed.post("/readings", json={
        "reading_date": "2026-10-01", "reading_kwh": "900", "source": "manual"})
    assert rollback.status_code == 422                     # meter rollback rejected
    r = tariffed.post("/readings", json={
        "reading_date": "2026-10-01", "reading_kwh": "1180", "source": "manual"})
    assert Decimal(r.json()["consumption_since_prev_kwh"]) == Decimal("180.000")


def test_reading_source_label_enforced(client):
    r = client.post("/readings", json={
        "reading_date": "2026-09-01", "reading_kwh": "10", "source": "guessed"})
    assert r.status_code == 422   # only 'manual' or 'simulated' allowed


# ----------------------------- tariff calculations -----------------------------

def test_tiered_slab_energy_charge(tariffed):
    # 250 units: 200 @ 6.50 + 50 @ 8.00 = 1300 + 400 = 1700
    r = tariffed.get("/bill/estimate", params={"units": "250"})
    est = r.json()
    assert Decimal(est["energy_charge"]) == Decimal("1700.00")
    assert Decimal(est["estimated_total"]) == Decimal("1700.00")
    assert est["is_estimate"] is True
    assert "not an official bill" in est["disclaimer"]


def test_fixed_and_per_kwh_charges(tariffed):
    tariffed.post("/tariff/charges", json={
        "name": "Fixed service charge", "amount": "50", "charge_type": "fixed"})
    tariffed.post("/tariff/charges", json={
        "name": "Fuel surcharge", "amount": "0.10", "charge_type": "per_kwh"})
    est = tariffed.get("/bill/estimate", params={"units": "100"}).json()
    # energy 100*6.5=650 ; charges 50 + 0.10*100=60 ; total 710
    assert Decimal(est["energy_charge"]) == Decimal("650.00")
    assert Decimal(est["additional_charges"]) == Decimal("60.00")
    assert Decimal(est["estimated_total"]) == Decimal("710.00")


def test_estimate_requires_month_or_units(tariffed):
    assert tariffed.get("/bill/estimate").status_code == 422
    missing = tariffed.get("/bill/estimate", params={"month": "2027-01"})
    assert missing.status_code == 404   # no readings for that month


# ----------------------------- consumption analysis -----------------------------

def test_consumption_series(readings):
    items = readings.get("/consumption").json()["items"]
    assert [i["month"] for i in items] == ["2026-09", "2026-10", "2026-11"]
    assert Decimal(items[1]["units_kwh"]) == Decimal("150.000")


def test_deviation_detection_with_threshold(readings):
    a = readings.get("/consumption/analysis").json()
    assert a["sufficient_history"] is True
    assert a["threshold_pct"] == 25.0
    sep, oct_, nov = a["months"]
    assert sep["deviation_pct"] is None        # no prior history to compare
    assert oct_["deviation_pct"] == 50.0       # 150 vs trailing avg 100 -> +50%
    assert oct_["significant"] is True         # >= 25% threshold
    assert nov["deviation_pct"] == -60.0       # 50 vs trailing avg (100+150)/2=125
    assert nov["significant"] is True          # |−60%| >= 25%


def test_short_history_reports_insufficient(client, tariffed):
    tariffed.post("/readings", json={"reading_date": "2026-09-01",
                                     "reading_kwh": "100", "source": "manual"})
    tariffed.post("/readings", json={"reading_date": "2026-10-01",
                                     "reading_kwh": "150", "source": "manual"})
    a = tariffed.get("/consumption/analysis").json()
    assert a["sufficient_history"] is False
    assert a["message"] is not None


# ----------------------------- bills & payments -----------------------------

def test_actual_bill_unique_month_and_demo_label(tariffed):
    r = tariffed.post("/bill/actual", json={
        "bill_month": "2026-09", "amount": "1600", "source_label": "demo"})
    assert r.status_code == 201
    assert r.json()["source_label"] == "demo"
    assert tariffed.post("/bill/actual", json={
        "bill_month": "2026-09", "amount": "1500"}).status_code == 409
    assert tariffed.post("/bill/actual", json={
        "bill_month": "2026-13", "amount": "1500"}).status_code == 422  # bad month
    assert tariffed.post("/bill/actual", json={
        "bill_month": "2026-10", "amount": "-5"}).status_code == 422    # negative


def test_payment_requires_existing_bill(tariffed):
    r = tariffed.post("/payments", json={
        "paid_on": "2026-09-20", "amount": "1600", "method": "UPI",
        "bill_id": 999})
    assert r.status_code == 422
    bill = tariffed.post("/bill/actual", json={
        "bill_month": "2026-09", "amount": "1600"}).json()
    ok = tariffed.post("/payments", json={
        "paid_on": "2026-09-20", "amount": "1600", "bill_id": bill["id"]})
    assert ok.status_code == 201


def test_estimated_vs_actual_comparison(readings):
    readings.post("/bill/actual", json={
        "bill_month": "2026-10", "amount": "1300", "source_label": "demo"})
    rows = {r["month"]: r for r in readings.get("/bill/comparison").json()["items"]}
    oct_row = rows["2026-10"]
    # Oct consumption = 150 kWh, entirely within slab 1 (0-200 @ 6.50) => 975.00
    assert Decimal(oct_row["estimated_total"]) == Decimal("975.00")
    assert Decimal(oct_row["actual_amount"]) == Decimal("1300.00")
    assert Decimal(oct_row["difference"]) == Decimal("325.00")   # actual - estimated


# ----------------------------- exports -----------------------------

def test_csv_exports(readings):
    csv_text = readings.get("/export/readings.csv").text
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("id,reading_date")
    assert len(lines) == 5   # header + 4 readings
    rep = readings.get("/export/bill-report.csv").text
    assert "estimated_total" in rep.splitlines()[0]


# ----------------------------- persistence -----------------------------

def test_records_persist_across_sessions(readings):
    """Same engine/session factory: data written via API is readable after
    the request session ends (DB-level persistence, not process-local)."""
    from database import SessionLocal
    import models
    db = SessionLocal()
    try:
        assert db.query(models.MeterReading).count() == 4
    finally:
        db.close()
