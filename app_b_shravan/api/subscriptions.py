"""Subscription CRUD, renewals, totals and tags endpoints."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.auth import require_token
from database import get_db
from models import Subscription, _plan_key
from schemas import (
    CostTotals,
    ExportBundle,
    ExportedSubscription,
    RenewalItem,
    SubscriptionCreate,
    SubscriptionList,
    SubscriptionOut,
    SubscriptionUpdate,
    compute_next_renewal,
    monthly_equivalent,
)

router = APIRouter(tags=["subscriptions"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": "subscription-tracker",
        "time": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


@router.get("/subscriptions/export", response_model=ExportBundle)
def export_subscriptions(db: Session = Depends(get_db)) -> ExportBundle:
    """Machine-readable feed consumed by Application A's idempotent sync.

    Eligible = active or paused recurring plans only; cancelled/expired
    subscriptions are never exported so App A cannot count a dead service.
    Idempotency key for App A: source='app_b', external_id='sub-<id>'.
    """
    subs = db.scalars(
        select(Subscription)
        .where(Subscription.status.in_(["active", "paused"]))
        .order_by(Subscription.id)
    ).all()
    items = [
        ExportedSubscription(
            id=s.id, service_name=s.service_name, amount=s.amount,
            currency=s.currency, billing_frequency=s.billing_frequency,
            monthly_equivalent=monthly_equivalent(s.amount, s.billing_frequency),
            next_renewal=s.next_renewal, status=s.status, category=s.category,
        )
        for s in subs
    ]
    return ExportBundle(generated_at=dt.datetime.now(dt.timezone.utc), items=items)


@router.get("/subscriptions", response_model=SubscriptionList)
def list_subscriptions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = None,
    category: str | None = None,
    status: str | None = None,
    frequency: str | None = None,
    tag: str | None = None,
    sort: str = "next_renewal",
    db: Session = Depends(get_db),
):
    stmt = select(Subscription)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(Subscription.service_name.ilike(like), Subscription.notes.ilike(like))
        )
    if category:
        stmt = stmt.where(Subscription.category == category)
    if status:
        stmt = stmt.where(Subscription.status == status)
    if frequency:
        stmt = stmt.where(Subscription.billing_frequency == frequency)
    if tag:
        stmt = stmt.where(Subscription.tags.ilike(f"%{tag}%"))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order_col = getattr(Subscription, sort.lstrip("-"))
    order = order_col.desc() if sort.startswith("-") else order_col.asc()
    items = db.scalars(
        stmt.order_by(order, Subscription.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return SubscriptionList(total=total, page=page, page_size=page_size, items=items)


@router.post("/subscriptions", response_model=SubscriptionOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    plan_val = data.pop("plan", None)
    sub = Subscription(**data)
    # Assign explicitly so the normalization applies even when `plan` is omitted.
    sub.plan = plan_val
    sub.plan_key = _plan_key(plan_val)
    if sub.next_renewal is None:
        sub.next_renewal = compute_next_renewal(sub.start_date, sub.billing_frequency)
    # Application-level duplicate check (portable across SQLite/PostgreSQL):
    # NULL-ability of the raw `plan` column makes the DB UNIQUE constraint
    # unreliable on some backends, so we detect duplicates before inserting.
    dup = db.scalar(
        select(Subscription).where(
            Subscription.service_name == sub.service_name,
            Subscription.plan_key == sub.plan_key,
            Subscription.billing_frequency == sub.billing_frequency,
        )
    )
    if dup:
        raise HTTPException(
            409,
            f"A {sub.billing_frequency} subscription '{sub.service_name}' "
            f"(plan {sub.plan or '-'}) already exists",
        )
    db.add(sub)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            409,
            f"A {sub.billing_frequency} subscription '{sub.service_name}' "
            f"(plan {sub.plan or '-'}) already exists",
        )
    db.refresh(sub)
    return sub


@router.get("/subscriptions/{subscription_id}", response_model=SubscriptionOut)
def get_subscription(subscription_id: int, db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    return sub


@router.put("/subscriptions/{subscription_id}", response_model=SubscriptionOut,
            dependencies=[Depends(require_token)])
def update_subscription(subscription_id: int, payload: SubscriptionUpdate,
                        db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "No fields to update")
    for key, value in data.items():
        setattr(sub, key, value)
    sub.plan_key = _plan_key(sub.plan)
    # If the cycle changed and no explicit renewal date was provided, recompute.
    if ("billing_frequency" in data or "start_date" in data) and \
            "next_renewal" not in data:
        sub.next_renewal = compute_next_renewal(sub.start_date, sub.billing_frequency)
    db.commit()
    db.refresh(sub)
    return sub


@router.delete("/subscriptions/{subscription_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)):
    sub = db.get(Subscription, subscription_id)
    if not sub:
        raise HTTPException(404, "Subscription not found")
    db.delete(sub)
    db.commit()


# --------------------------- Renewals ---------------------------

@router.get("/renewals", response_model=list[RenewalItem])
def upcoming_renewals(
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Active subscriptions renewing within the next `days` days (7/15/30 UI chips)."""
    today = dt.date.today()
    horizon = today + dt.timedelta(days=days)
    subs = db.scalars(
        select(Subscription)
        .where(
            Subscription.status == "active",
            Subscription.next_renewal.is_not(None),
            Subscription.next_renewal <= horizon,
            Subscription.next_renewal >= today,
        )
        .order_by(Subscription.next_renewal)
    ).all()
    return [
        RenewalItem(
            subscription_id=s.id,
            service_name=s.service_name,
            amount=s.amount,
            currency=s.currency,
            billing_frequency=s.billing_frequency,
            next_renewal=s.next_renewal,
            days_until_renewal=(s.next_renewal - today).days,
            status=s.status,
        )
        for s in subs
    ]


# --------------------------- Totals ---------------------------

@router.get("/total", response_model=CostTotals)
def total_costs(db: Session = Depends(get_db)):
    subs = db.scalars(select(Subscription).where(Subscription.status == "active")).all()
    monthly = Decimal("0")
    by_cat: dict[str, Decimal] = {}
    for s in subs:
        m = monthly_equivalent(s.amount, s.billing_frequency)
        monthly += m
        by_cat[s.category] = by_cat.get(s.category, Decimal("0")) + m
    return CostTotals(
        active_count=len(subs),
        monthly_total=monthly.quantize(Decimal("0.01")),
        annual_total=(monthly * 12).quantize(Decimal("0.01")),
        by_category={k: v.quantize(Decimal("0.01")) for k, v in by_cat.items()},
    )


@router.get("/category/{name}")
def category_detail(name: str, db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(Subscription).where(Subscription.category == name)).all()
    if not rows:
        # Still a valid answer; distinguishes empty vs unknown by listing known ones.
        known = db.scalars(select(func.distinct(Subscription.category))).all()
        return {
            "category": name,
            "count": 0,
            "monthly_equivalent_total": 0.0,
            "known_categories": sorted(known),
        }
    monthly = sum(monthly_equivalent(s.amount, s.billing_frequency)
                  for s in rows if s.status == "active")
    return {
        "category": name,
        "count": len(rows),
        "monthly_equivalent_total": float(monthly.quantize(Decimal("0.01"))),
    }


@router.get("/tags")
def list_tags(db: Session = Depends(get_db)) -> list[str]:
    raw = db.scalars(
        select(Subscription.tags).where(Subscription.tags.is_not(None))
    ).all()
    tags: set[str] = set()
    for value in raw:
        tags.update(t.strip().lower() for t in value.split(",") if t.strip())
    return sorted(tags)
