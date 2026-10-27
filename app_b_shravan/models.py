"""SQLAlchemy models for Application B (Subscription Renewal & Cost Tracker)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

BILLING_FREQUENCIES = ["monthly", "quarterly", "half-yearly", "annual"]
SUBSCRIPTION_STATUSES = ["active", "paused", "cancelled", "expired"]

# Multiplier converting one billing-cycle charge into a monthly-equivalent.
FREQUENCY_MONTHS: dict[str, int] = {
    "monthly": 1,
    "quarterly": 3,
    "half-yearly": 6,
    "annual": 12,
}


def _plan_key(value: str | None) -> str:
    """Normalize NULL plans so the uniqueness constraint actually applies."""
    return (value or "").strip().lower()


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    plan_key: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    service_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="Entertainment", index=True)
    plan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    billing_frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    next_renewal: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)  # comma-separated
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("service_name", "plan_key", "billing_frequency",
                         name="uq_subscription_service_plan_freq"),
        Index("ix_subscription_renewal", "next_renewal", "status"),
    )


class ExpenseShareLog(Base):
    """Tracks which subscription records were shared/exported to Application A.

    Application A performs the actual idempotent import; this log lets B show
    integration status (what was exported at the last sync).
    """

    __tablename__ = "expense_share_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_app: Mapped[str] = mapped_column(String(30), nullable=False)  # 'app_a'
    status: Mapped[str] = mapped_column(String(20), nullable=False)      # success / failed
    records_exported: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ran_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
