"""Meter readings, consumption analytics and estimated bills."""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
import schemas
from api.auth import require_token
from config import get_settings
from database import get_db
from services import consumption, tariff

router = APIRouter(tags=["readings & consumption"])
settings = get_settings()


def _with_delta(db: Session, r: models.MeterReading) -> schemas.ReadingOut:
    prev = db.scalar(
        select(models.MeterReading)
        .where(models.MeterReading.reading_date < r.reading_date)
        .order_by(models.MeterReading.reading_date.desc())
        .limit(1)
    )
    out = schemas.ReadingOut.model_validate(r)
    if prev is not None:
        delta = Decimal(r.reading_kwh) - Decimal(prev.reading_kwh)
        out.consumption_since_prev_kwh = delta if delta >= 0 else Decimal("0")
    return out


@router.get("/readings", response_model=list[schemas.ReadingOut])
def list_readings(
    start: dt.date | None = Query(default=None),
    end: dt.date | None = Query(default=None),
    source: str | None = Query(default=None, pattern="^(manual|simulated)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(models.MeterReading).order_by(models.MeterReading.reading_date.desc())
    if start:
        stmt = stmt.where(models.MeterReading.reading_date >= start)
    if end:
        stmt = stmt.where(models.MeterReading.reading_date <= end)
    if source:
        stmt = stmt.where(models.MeterReading.source == source)
    rows = list(db.scalars(stmt.limit(limit)))
    return [_with_delta(db, r) for r in reversed(rows)]


@router.post("/readings", response_model=schemas.ReadingOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_reading(payload: schemas.ReadingCreate, db: Session = Depends(get_db)):
    exists = db.scalar(
        select(models.MeterReading).where(
            models.MeterReading.reading_date == payload.reading_date
        )
    )
    if exists:
        raise HTTPException(409, f"A reading for {payload.reading_date} already exists")
    last = db.scalar(
        select(models.MeterReading)
        .where(models.MeterReading.reading_date < payload.reading_date)
        .order_by(models.MeterReading.reading_date.desc())
        .limit(1)
    )
    if last and payload.reading_kwh < Decimal(last.reading_kwh):
        raise HTTPException(
            422, "Reading is lower than the previous reading (meter rollback); "
                 "record it with a note via an edit instead."
        )
    r = models.MeterReading(**payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return _with_delta(db, r)


@router.delete("/readings/{reading_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_reading(reading_id: int, db: Session = Depends(get_db)):
    r = db.get(models.MeterReading, reading_id)
    if not r:
        raise HTTPException(404, "Reading not found")
    db.delete(r)
    db.commit()


@router.get("/consumption")
def consumption_summary(months: int = Query(default=6, ge=1, le=24),
                        db: Session = Depends(get_db)) -> dict:
    """Monthly consumed units derived from consecutive meter readings."""
    series = consumption.monthly_consumption(db)[-months:]
    return {"items": series, "unit": "kWh"}


@router.get("/consumption/analysis", response_model=schemas.ConsumptionAnalysis)
def consumption_trend(db: Session = Depends(get_db)):
    """Six-month analysis with configurable deviation threshold."""
    return consumption.consumption_analysis(db)


@router.get("/consumption/by-appliance")
def consumption_by_appliance(db: Session = Depends(get_db)) -> dict:
    items = [
        {
            "id": ap.id,
            "name": ap.name,
            "category": ap.category,
            "rated_power_w": str(ap.rated_power_w),
            "daily_hours": str(ap.daily_hours),
            "quantity": ap.quantity,
            "monthly_kwh": str(tariff.appliance_monthly_kwh(ap)),
        }
        for ap in db.scalars(
            select(models.Appliance).where(models.Appliance.active.is_(True))
            .order_by(models.Appliance.name)
        )
    ]
    total = sum(Decimal(i["monthly_kwh"]) for i in items) if items else Decimal("0")
    return {"items": items, "total_monthly_kwh": str(total.quantize(Decimal("0.001")))}


@router.get("/bill/estimate", response_model=schemas.EstimateOut)
@router.post("/bill/estimate", response_model=schemas.EstimateOut)
def estimate_bill(
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    units: Decimal | None = Query(default=None, gt=Decimal("0")),
    db: Session = Depends(get_db),
):
    """Estimated bill for a month's recorded consumption, or explicit units."""
    if units is not None:
        est = tariff.estimate_bill(db, units)
        return schemas.EstimateOut(month=month or dt.date.today().isoformat()[:7], **est)
    if month:
        est = consumption.estimate_for_month(db, month)
        if not est:
            raise HTTPException(404, f"No consumption data for {month}; add meter readings first.")
        return schemas.EstimateOut(**est)
    raise HTTPException(422, "Provide either 'month' (with readings) or 'units'.")


@router.get("/bill/comparison")
def bill_comparison(db: Session = Depends(get_db)) -> dict:
    """Estimated vs actual per month. Difference = actual - estimated."""
    return {"items": consumption.compare_bills(db)}


@router.get("/export/readings.csv")
def export_readings(db: Session = Depends(get_db)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "reading_date", "reading_kwh", "source", "note"])
    for r in db.scalars(select(models.MeterReading).order_by(models.MeterReading.reading_date)):
        writer.writerow([r.id, r.reading_date, r.reading_kwh, r.source, r.note or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=readings.csv"},
    )


@router.get("/export/bill-report.csv")
def export_bill_report(db: Session = Depends(get_db)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["month", "estimated_total", "actual_amount", "difference", "actual_source_label"])
    for row in consumption.compare_bills(db):
        writer.writerow([
            row["month"],
            row["estimated_total"] if row["estimated_total"] is not None else "",
            row["actual_amount"] if row["actual_amount"] is not None else "",
            row["difference"] if row["difference"] is not None else "",
            row["source_label"] or "",
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bill_report.csv"},
    )
