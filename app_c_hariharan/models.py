"""SQLAlchemy models for Application C (Electricity Manager).

Money values use NUMERIC with fixed precision; quantities use Decimal too so
that tariff arithmetic is exact. Every application keeps its own database.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Appliance(Base):
    __tablename__ = "appliances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    category: Mapped[str] = mapped_column(String(60), default="Other")
    rated_power_w: Mapped[Decimal] = mapped_column(Numeric(10, 2))   # watts
    daily_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2))      # hours/day
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MeterReading(Base):
    """Total household meter reading (kWh). source = manual | simulated."""

    __tablename__ = "meter_readings"
    __table_args__ = (
        UniqueConstraint("reading_date", name="uq_reading_date"),
        Index("ix_reading_date", "reading_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reading_date: Mapped[dt.date] = mapped_column(Date)
    reading_kwh: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual|simulated
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class TariffSlab(Base):
    """Configurable domestic tariff slabs (per-unit rates).

    IMPORTANT: Rates are user-configurable. Do NOT invent official tariffs;
    owners must enter verified rates with a source and effective date.
    """

    __tablename__ = "tariff_slabs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), default="Default domestic")
    up_to_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # upper bound of slab
    rate_per_kwh: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    effective_from: Mapped[dt.date] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChargeConfig(Base):
    """Fixed charges applied on top of energy charges (configurable)."""

    __tablename__ = "charge_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    charge_type: Mapped[str] = mapped_column(String(20), default="fixed")  # fixed|per_kwh
    applicable: Mapped[bool] = mapped_column(Boolean, default=True)


class ActualBill(Base):
    """A real electricity bill received from the provider (recorded, not estimated)."""

    __tablename__ = "actual_bills"
    __table_args__ = (
        UniqueConstraint("bill_month", name="uq_bill_month"),
        Index("ix_bill_month", "bill_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_month: Mapped[str] = mapped_column(String(7))  # YYYY-MM
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    units_consumed: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)
    bill_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    source_label: Mapped[str] = mapped_column(String(20), default="genuine")  # genuine|demo
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Payment(Base):
    """Actual payment made against a bill (stored separately from bills)."""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int | None] = mapped_column(
        ForeignKey("actual_bills.id", ondelete="SET NULL"), nullable=True
    )
    paid_on: Mapped[dt.date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    method: Mapped[str] = mapped_column(String(40), default="Other")
    source_label: Mapped[str] = mapped_column(String(20), default="genuine")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    bill: Mapped[ActualBill | None] = relationship()


class SyncState(Base):
    """Bookkeeping for pushes into Application A (idempotency + last sync)."""

    __tablename__ = "sync_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(40), unique=True)  # e.g. 'app_a'
    external_ref: Mapped[str] = mapped_column(String(120), default="")
    last_synced_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    records_pushed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
