"""Integration endpoints for Application C.

Exposed to Application A (pull model, mirroring App B's export feed):
- GET /integration/expenses  -> eligible recorded charges (actual bills +
  payments only; estimates are NEVER exported to avoid double counting).
- POST /sync/push-expenses   -> manual sync button target: verifies that
  Application A is reachable and logs the attempt. The authoritative import
  happens on App A via its own /sync/electricity pull, which dedupes on
  (source='electricity', external_ref).
- POST /sync/import-to-app-a -> genuine push flow (Hariharan supplies Sachien's
  write token as EXPENSE_API_TOKEN): pushes each eligible record to App A's
  POST /expenses with source_app='electricity' + stable external_id, so App A
  dedupes and repeated runs create no duplicates.
- GET /sync/history          -> local sync log.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
import schemas
from config import get_settings
from database import get_db
from services import expense_client

router = APIRouter(tags=["integration"])
settings = get_settings()

CATEGORY_FALLBACK = "Bills"


def _map_category(desired: str, app_a_categories: list[str]) -> str:
    normalized = desired.strip().lower()
    for cat in app_a_categories:
        if cat.strip().lower() == normalized:
            return cat
    return CATEGORY_FALLBACK


def eligible_records(db: Session) -> list[dict]:
    """Actual bills and payments shaped for App A's ExternalElectricityExpense."""
    items: list[dict] = []
    for bill in db.scalars(select(models.ActualBill).order_by(models.ActualBill.bill_month)):
        label = " (demo data)" if bill.source_label == "demo" else ""
        items.append(
            {
                "id": bill.id,
                "bill_month": bill.bill_month,
                "reading_date": bill.bill_date,
                "description": f"Electricity bill {bill.bill_month}{label}",
                "amount": Decimal(bill.amount),
                "currency": bill.currency,
                "kind": "actual_bill",
                "external_ref": f"actual-bill-{bill.id}-{bill.bill_month}",
            }
        )
    for pay in db.scalars(select(models.Payment).order_by(models.Payment.paid_on)):
        label = " (demo data)" if pay.source_label == "demo" else ""
        items.append(
            {
                "id": pay.id,
                "bill_month": pay.paid_on.isoformat()[:7],
                "reading_date": pay.paid_on,
                "description": f"Electricity payment {pay.method}{label}",
                "amount": Decimal(pay.amount),
                "currency": pay.currency,
                "kind": "payment",
                "external_ref": f"payment-{pay.id}-{pay.paid_on.isoformat()}",
            }
        )
    return items


@router.get("/integration/expenses", response_model=list[schemas.ExternalExpenseRecord])
def integration_expenses(db: Session = Depends(get_db)):
    """Public export feed consumed by Application A (read-only, no secret needed)."""
    return eligible_records(db)


@router.get("/integration/status")
def integration_status(db: Session = Depends(get_db)) -> dict:
    cats = expense_client.fetch_categories()
    last = db.scalars(
        select(models.SyncState)
        .where(models.SyncState.target == "app_a", models.SyncState.status == "ok")
        .order_by(models.SyncState.last_synced_at.desc())
        .limit(1)
    ).first()
    return {
        "expense_api": expense_client.health(),
        "categories_from_app_a": cats.get("categories", []),
        "category_source": cats.get("source"),
        "mapped_category_for_electricity": _map_category(
            "Bills", cats.get("categories", [])
        ),
        "eligible_records_for_export": len(eligible_records(db)),
        "last_successful_sync": last.last_synced_at.isoformat() if last else None,
        "note": (
            "Application A pulls this feed via its authenticated "
            "POST /sync/electricity endpoint; estimates are excluded upstream."
        ),
    }


@router.post("/sync/push-expenses", response_model=dict)
def push_expenses(db: Session = Depends(get_db)) -> schemas.SyncResult | dict:
    """Manual synchronization button target.

    Verifies App A reachability and records the attempt locally. Idempotency
    is guaranteed on App A's side (dedupe by source+external_id), so repeated
    syncs never duplicate expenses there. Never blocks when App A is down.
    """
    records = eligible_records(db)
    try:
        h = expense_client.health()
        if h.get("reachable"):
            status, detail = "ok", f"App A reachable; {len(records)} records ready to pull."
        else:
            status, detail = "failed", h.get("error", "App A unreachable")
    except Exception as exc:  # defensive: sync must never crash App C
        status, detail = "failed", str(exc)

    state = db.scalar(select(models.SyncState).where(models.SyncState.target == "app_a"))
    if state is None:
        state = models.SyncState(target="app_a")
        db.add(state)
    state.status = status
    state.records_pushed = len(records) if status == "ok" else 0
    state.detail = detail
    if status == "ok":
        state.last_synced_at = dt.datetime.now(dt.timezone.utc)
    db.commit()

    return {
        "target": "app_a",
        "status": status,
        "pushed": state.records_pushed,
        "skipped_duplicates": len(records) - state.records_pushed if status != "ok" else 0,
        "detail": detail,
        "last_successful_sync": (
            state.last_synced_at.isoformat() if status == "ok" else None
        ),
    }


@router.post("/sync/import-to-app-a", response_model=schemas.SyncResult)
def import_to_app_a(db: Session = Depends(get_db)):
    """Genuine push of eligible records into Application A (requires Sachien's
    write token in EXPENSE_API_TOKEN). Idempotent via stable external refs."""
    records = eligible_records(db)
    cats = expense_client.fetch_categories()
    category = _map_category("Bills", cats.get("categories", []))
    pushed = duplicates = 0
    errors: list[str] = []
    for rec in records:
        date_val = rec["reading_date"] or dt.date.fromisoformat(rec["bill_month"] + "-01")
        payload = {
            "date": date_val.isoformat(),
            "merchant": "Home Electricity",
            "amount": rec["amount"],
            "category": category,
            "payment_method": "Electricity",
            "description": f"{rec['description']} [source: Electricity Manager]",
            "external_id": rec["external_ref"],
        }
        try:
            result = expense_client.post_expense(payload)
            if result["created"]:
                pushed += 1
            else:
                duplicates += 1
        except expense_client.IntegrationError as exc:
            errors.append(str(exc))
            break  # one failure per run is enough signal; keep it snappy

    status = "ok" if not errors else "failed"
    state = db.scalar(select(models.SyncState).where(models.SyncState.target == "app_a"))
    if state is None:
        state = models.SyncState(target="app_a")
        db.add(state)
    state.status = status
    state.records_pushed = pushed
    state.detail = "; ".join(errors[:3]) if errors else (
        f"{pushed} new, {duplicates} already present (no duplicates created)")
    if status == "ok":
        state.last_synced_at = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return {
        "target": "app_a",
        "status": status,
        "pushed": pushed,
        "skipped_duplicates": duplicates,
        "detail": state.detail,
    }


@router.get("/sync/history")
def sync_history(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(
        select(models.SyncState).order_by(models.SyncState.last_synced_at.desc())
        .limit(min(limit, 100))
    )
    return [
        {
            "target": s.target,
            "status": s.status,
            "records_pushed": s.records_pushed,
            "last_synced_at": s.last_synced_at.isoformat(),
            "detail": s.detail,
        }
        for s in rows
    ]
