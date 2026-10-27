"""Idempotent synchronization of external records into Application A.

Rules:
- Dedupe on (source, external_id) enforced by a DB unique constraint;
  re-syncing never creates duplicates.
- Imported records are flagged with their source and last sync time;
  manual records are NEVER overwritten automatically.
- If a peer API is unavailable the function reports failure but does not
  raise - Application A keeps working.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Expense, SyncLog
from services import api_client
from services.api_client import IntegrationError

logger = logging.getLogger(__name__)


def _last_success(db: Session, source_app: str) -> dt.datetime | None:
    log = db.scalars(
        select(SyncLog)
        .where(SyncLog.source_app == source_app, SyncLog.status == "success")
        .order_by(SyncLog.ran_at.desc())
        .limit(1)
    ).first()
    return log.ran_at if log else None


def _existing(db: Session, source: str, external_id: str) -> Expense | None:
    return db.scalars(
        select(Expense).where(Expense.source == source, Expense.external_id == external_id)
    ).first()


def _record_log(db: Session, source_app: str, status: str, imported: int,
                skipped: int, message: str | None) -> dt.datetime | None:
    db.add(SyncLog(source_app=source_app, status=status,
                   records_imported=imported, records_skipped=skipped, message=message))
    db.commit()
    return _last_success(db, source_app)


def sync_subscriptions(db: Session) -> dict:
    """Import eligible recurring subscription costs from Application B."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        subs = api_client.fetch_subscriptions()
    except IntegrationError as exc:
        msg = str(exc)
        logger.warning("Subscription sync failed: %s", msg)
        last = _record_log(db, "app_b", "failed", 0, 0, msg)
        return {"source_app": "app_b", "status": "failed",
                "records_imported": 0, "records_skipped": 0,
                "message": msg, "last_successful_sync": last}

    imported = skipped = 0
    for sub in subs:
        ext_id = f"sub-{sub.id}"
        existing = _existing(db, "app_b", ext_id)
        if existing:
            # Update only synced fields of previously-imported records;
            # manual expenses are untouched because they have different keys.
            existing.amount = sub.monthly_equivalent
            existing.merchant = sub.service_name
            existing.last_synced_at = now
            skipped += 1
        else:
            db.add(Expense(
                expense_date=sub.next_renewal or now.date(),
                merchant=sub.service_name,
                amount=sub.monthly_equivalent,
                currency=sub.currency or "INR",
                category="Subscriptions",
                payment_method="Subscription",
                description=(
                    f"Auto-imported monthly-equivalent of {sub.billing_frequency} "
                    f"subscription from Subscription Tracker (id {sub.id})"
                ),
                source="app_b",
                external_id=ext_id,
                last_synced_at=now,
            ))
            imported += 1
    db.commit()
    last = _record_log(db, "app_b", "success", imported, skipped, None)
    return {"source_app": "app_b", "status": "success",
            "records_imported": imported, "records_skipped": skipped,
            "message": None, "last_successful_sync": last}


def sync_electricity(db: Session) -> dict:
    """Import eligible electricity expenses (actual bills / payments) from C."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        records = api_client.fetch_electricity_expenses()
    except IntegrationError as exc:
        msg = str(exc)
        logger.warning("Electricity sync failed: %s", msg)
        last = _record_log(db, "app_c", "failed", 0, 0, msg)
        return {"source_app": "app_c", "status": "failed",
                "records_imported": 0, "records_skipped": 0,
                "message": msg, "last_successful_sync": last}

    imported = skipped = 0
    for rec in records:
        ext_id = rec.external_ref
        existing = _existing(db, "app_c", ext_id)
        if existing:
            existing.amount = rec.amount
            existing.last_synced_at = now
            skipped += 1
        else:
            expense_date = rec.reading_date or (
                dt.date(int(rec.bill_month[:4]), int(rec.bill_month[5:7]), 1)
                if rec.bill_month else now.date()
            )
            db.add(Expense(
                expense_date=expense_date,
                merchant="Home Electricity",
                amount=rec.amount,
                currency=rec.currency or "INR",
                category="Bills",
                payment_method="Electricity",
                description=f"{rec.description} [source: Electricity Manager]",
                source="app_c",
                external_id=ext_id,
                last_synced_at=now,
            ))
            imported += 1
    db.commit()
    last = _record_log(db, "app_c", "success", imported, skipped, None)
    return {"source_app": "app_c", "status": "success",
            "records_imported": imported, "records_skipped": skipped,
            "message": None, "last_successful_sync": last}
