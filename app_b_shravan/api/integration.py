"""Integration & synchronization endpoints (Application A)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import ExpenseShareLog, Subscription

from services import expense_client
from services.expense_client import IntegrationError

router = APIRouter(tags=["integration"])


def _eligible(db: Session) -> list[Subscription]:
    """Subscriptions eligible for cost sharing: active or paused recurring plans.

    Cancelled/expired subscriptions are NOT shared so Application A never
    counts a dead service. One record per subscription (idempotency key:
    App A dedupes on source='app_b' + external_id='sub-<id>').
    """
    return db.scalars(
        select(Subscription)
        .where(Subscription.status.in_(["active", "paused"]))
        .order_by(Subscription.id)
    ).all()


@router.get("/integration/status")
def integration_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    last = db.scalars(
        select(ExpenseShareLog)
        .where(ExpenseShareLog.target_app == "app_a", ExpenseShareLog.status == "success")
        .order_by(ExpenseShareLog.ran_at.desc())
        .limit(1)
    ).first()
    return {
        "expense_api": expense_client.expense_health(),
        "categories_from_app_a": expense_client.fetch_categories().get(
            "categories", []
        ),
        "eligible_records_for_export": len(_eligible(db)),
        "last_successful_sync": last.ran_at.isoformat() if last else None,
    }


@router.post("/sync/push-expenses")
def push_expenses(db: Session = Depends(get_db)) -> dict:
    """Manual synchronization button target.

    NOTE: Application A pulls from /subscriptions/export; this endpoint lets
    Shravan verify connectivity and record an export attempt in the log. It is
    idempotent on Application A's side (dedupe by source+external_id), so
    repeated pushes never duplicate expenses there.
    """
    exported = len(_eligible(db))
    try:
        result = expense_client.ping_import(expected_count=exported)
        status, message = "success", None
    except IntegrationError as exc:
        status, message = "failed", str(exc)
        result = {}
    db.add(ExpenseShareLog(
        target_app="app_a", status=status,
        records_exported=exported if status == "success" else 0,
        message=message,
    ))
    db.commit()
    last = db.scalars(
        select(ExpenseShareLog)
        .where(ExpenseShareLog.target_app == "app_a", ExpenseShareLog.status == "success")
        .order_by(ExpenseShareLog.ran_at.desc())
        .limit(1)
    ).first()
    return {
        "target_app": "app_a",
        "status": status,
        "records_exported": exported if status == "success" else 0,
        "message": message,
        "last_successful_sync": last.ran_at.isoformat() if last else None,
        "detail": result,
    }


@router.get("/sync/history")
def sync_history(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    logs = db.scalars(
        select(ExpenseShareLog).order_by(ExpenseShareLog.ran_at.desc()).limit(min(limit, 100))
    ).all()
    return [
        {
            "target_app": l.target_app,
            "status": l.status,
            "records_exported": l.records_exported,
            "message": l.message,
            "ran_at": l.ran_at.isoformat() if l.ran_at else None,
        }
        for l in logs
    ]
