"""SQLAlchemy models for Application A (Expense & Budget Manager)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base

EXPENSE_CATEGORIES = [
    "Food", "Travel", "Bills", "Entertainment",
    "Shopping", "Subscriptions", "Other",
]


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    expense_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    merchant: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payment_method: Mapped[str] = mapped_column(String(50), nullable=False, default="Card")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # External integration fields (never duplicated thanks to the unique constraint)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_expense_source_external"),
        Index("ix_expense_month", "expense_date", "category"),
    )


class CategoryRule(Base):
    """Transparent, editable merchant->category rules."""

    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    pattern: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[int] = mapped_column(default=100)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Budget(Base):
    """Monthly per-category budgets. month format: YYYY-MM."""

    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (UniqueConstraint("month", "category", name="uq_budget_month_category"),)


class SyncLog(Base):
    """Tracks synchronization runs with external applications."""

    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_app: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success / failed
    records_imported: Mapped[int] = mapped_column(default=0)
    records_skipped: Mapped[int] = mapped_column(default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    ran_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
