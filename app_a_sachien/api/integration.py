"""Integration & synchronization endpoints (Applications B and C)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_token
from config import get_settings
from database import get_db
from models import SyncLog
from services import api_client
from services.sync_service import sync_electricity, sync_subscriptions

router = APIRouter(tags=["integration"])


@router.get("/integration/status")
def integration_status(db: Session = Depends(get_db)) -> dict:
    settings = get_settings()
    last: dict[str, str | None] = {}
    for src in ("app_b", "app_c"):
        log = db.scalars(
            select(SyncLog).where(SyncLog.source_app == src, SyncLog.status == "success")
            .order_by(SyncLog.ran_at.desc()).limit(1)
        ).first()
        last[src] = log.ran_at.isoformat() if log else None
    return {
        "subscription_api": api_client.subscription_health(),
        "electricity_api": api_client.electricity_health(),
        "last_syncs": last,
    }


@router.post("/sync/subscriptions", dependencies=[Depends(require_token)])
def trigger_sync_subscriptions(db: Session = Depends(get_db)) -> dict:
    """Manual synchronization button target - idempotent."""
    return sync_subscriptions(db)


@router.post("/sync/electricity", dependencies=[Depends(require_token)])
def trigger_sync_electricity(db: Session = Depends(get_db)) -> dict:
    return sync_electricity(db)


@router.get("/sync/history")
def sync_history(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    logs = db.scalars(select(SyncLog).order_by(SyncLog.ran_at.desc()).limit(min(limit, 100))).all()
    return [
        {"source_app": l.source_app, "status": l.status,
         "records_imported": l.records_imported, "records_skipped": l.records_skipped,
         "message": l.message, "ran_at": l.ran_at.isoformat() if l.ran_at else None}
        for l in logs
    ]
