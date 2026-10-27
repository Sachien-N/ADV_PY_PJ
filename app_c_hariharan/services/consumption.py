"""Consumption analytics for Application C.

- Monthly consumption derived from consecutive meter readings.
- Six-month trailing analysis with configurable deviation threshold.
- Estimated-vs-actual bill comparison. Estimates are always labelled as
  estimates; recorded bills/payments are kept separate.
"""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from config import get_settings
from services import tariff

settings = get_settings()


def month_of(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def monthly_consumption(db: Session) -> list[dict]:
    """Consume = reading(next date) - reading(previous date), grouped by month.

    Requires at least two readings. Negative deltas (meter reset/rollback)
    are ignored rather than silently counted.
    """
    rows = list(
        db.scalars(
            select(models.MeterReading).order_by(models.MeterReading.reading_date)
        )
    )
    per_month: dict[str, Decimal] = {}
    prev: models.MeterReading | None = None
    for r in rows:
        if prev is not None:
            delta = Decimal(r.reading_kwh) - Decimal(prev.reading_kwh)
            if delta >= 0:
                key = month_of(r.reading_date)
                per_month[key] = per_month.get(key, Decimal("0")) + delta
        prev = r
    return [{"month": m, "units_kwh": per_month[m]} for m in sorted(per_month)]


def consumption_analysis(db: Session) -> dict:
    """Analyse up to the last six months; flag significant deviations.

    A month's deviation is measured against the average of the preceding
    months (at least one prior month required to compute a deviation).
    """
    series = monthly_consumption(db)[-6:]
    threshold = settings.DEVIATION_THRESHOLD_PCT
    out: list[dict] = []
    history: list[Decimal] = []
    for item in series:
        units = item["units_kwh"]
        deviation_pct: float | None = None
        significant = False
        if history:
            avg = sum(history, Decimal("0")) / Decimal(len(history))
            if avg > 0:
                deviation_pct = float((units - avg) / avg * Decimal("100"))
                significant = abs(deviation_pct) >= threshold
        out.append(
            {
                "month": item["month"],
                "units_kwh": units,
                "deviation_pct": round(deviation_pct, 2) if deviation_pct is not None else None,
                "significant": significant,
            }
        )
        history.append(units)
    sufficient = len(series) >= 3
    message = (
        None
        if sufficient
        else "Need at least 3 months of readings (>=4 readings) for meaningful six-month analysis."
    )
    trailing_avg = (
        sum([s["units_kwh"] for s in series], Decimal("0")) / Decimal(len(series))
        if series
        else None
    )
    return {
        "months": out,
        "trailing_average_kwh": trailing_avg,
        "threshold_pct": threshold,
        "sufficient_history": sufficient,
        "message": message,
    }


def estimate_for_month(db: Session, month: str) -> dict | None:
    """Estimated bill for one consumed-units month using configured slabs."""
    for item in monthly_consumption(db):
        if item["month"] == month:
            ref = dt.date.fromisoformat(f"{month}-01")
            # use last day of that month as tariff effective reference
            ref = ref.replace(day=calendar.monthrange(ref.year, ref.month)[1])
            est = tariff.estimate_bill(db, item["units_kwh"], on_date=ref)
            return {"month": month, **est}
    return None


def compare_bills(db: Session) -> list[dict]:
    """Match estimated bills against recorded actual bills per month."""
    estimates = {e["month"]: e for e in
                 [estimate_for_month(db, m["month"]) for m in monthly_consumption(db)]
                 if e is not None}
    bills = list(db.scalars(select(models.ActualBill).order_by(models.ActualBill.bill_month)))
    months = sorted(set(estimates) | {b.bill_month for b in bills})
    result: list[dict] = []
    bill_by_month = {b.bill_month: b for b in bills}
    for m in months:
        est = estimates.get(m)
        bill = bill_by_month.get(m)
        est_total = est["estimated_total"] if est else None
        act_total = Decimal(bill.amount) if bill else None
        diff = (
            act_total - est_total
            if (est_total is not None and act_total is not None)
            else None
        )
        result.append(
            {
                "month": m,
                "estimated_total": est_total,
                "actual_amount": act_total,
                "difference": diff,
                "source_label": bill.source_label if bill else None,
            }
        )
    return result
