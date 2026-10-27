"""Pydantic schemas for Application C (Electricity Manager)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ----------------------------- Appliance -----------------------------

class ApplianceBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Other", max_length=60)
    rated_power_w: Decimal = Field(gt=Decimal("0"), le=Decimal("100000"))
    daily_hours: Decimal = Field(ge=Decimal("0"), le=Decimal("24"))
    quantity: int = Field(default=1, ge=1, le=100)
    notes: str | None = None
    active: bool = True


class ApplianceCreate(ApplianceBase):
    pass


class ApplianceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    category: str | None = Field(default=None, max_length=60)
    rated_power_w: Decimal | None = Field(default=None, gt=Decimal("0"))
    daily_hours: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("24"))
    quantity: int | None = Field(default=None, ge=1)
    notes: str | None = None
    active: bool | None = None


class ApplianceOut(ApplianceBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    monthly_kwh: Decimal | None = None


# ----------------------------- Meter readings -----------------------------

READING_SOURCES = ("manual", "simulated")


class ReadingCreate(BaseModel):
    reading_date: dt.date
    reading_kwh: Decimal = Field(ge=Decimal("0"), le=Decimal("99999999"))
    source: str = "manual"
    note: str | None = None

    @field_validator("source")
    @classmethod
    def _src(cls, v: str) -> str:
        if v not in READING_SOURCES:
            raise ValueError("source must be 'manual' or 'simulated'")
        return v


class ReadingOut(ReadingCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    consumption_since_prev_kwh: Decimal | None = None


# ----------------------------- Tariff -----------------------------

class SlabCreate(BaseModel):
    name: str = Field(default="Default domestic", max_length=80)
    up_to_kwh: Decimal = Field(gt=Decimal("0"))
    rate_per_kwh: Decimal = Field(ge=Decimal("0"), le=Decimal("1000"))
    effective_from: dt.date
    source: str | None = Field(default=None, max_length=200)


class SlabOut(SlabCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ChargeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    amount: Decimal = Field(ge=Decimal("0"))
    charge_type: str = "fixed"  # fixed | per_kwh
    applicable: bool = True

    @field_validator("charge_type")
    @classmethod
    def _ct(cls, v: str) -> str:
        if v not in ("fixed", "per_kwh"):
            raise ValueError("charge_type must be 'fixed' or 'per_kwh'")
        return v


class ChargeOut(ChargeCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ----------------------------- Bills / payments -----------------------------

class ActualBillCreate(BaseModel):
    bill_month: str  # YYYY-MM
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    units_consumed: Decimal | None = Field(default=None, ge=Decimal("0"))
    bill_date: dt.date | None = None
    source_label: str = "genuine"  # genuine | demo
    note: str | None = None

    @field_validator("bill_month")
    @classmethod
    def _month(cls, v: str) -> str:
        try:
            dt.date.fromisoformat(v + "-01")
        except ValueError as exc:
            raise ValueError("bill_month must be YYYY-MM") from exc
        return v

    @field_validator("source_label")
    @classmethod
    def _lbl(cls, v: str) -> str:
        if v not in ("genuine", "demo"):
            raise ValueError("source_label must be 'genuine' or 'demo'")
        return v


class ActualBillOut(ActualBillCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class PaymentCreate(BaseModel):
    bill_id: int | None = None
    paid_on: dt.date
    amount: Decimal = Field(gt=Decimal("0"))
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    method: str = Field(default="Other", max_length=40)
    source_label: str = "genuine"
    note: str | None = None

    @field_validator("source_label")
    @classmethod
    def _lbl(cls, v: str) -> str:
        if v not in ("genuine", "demo"):
            raise ValueError("source_label must be 'genuine' or 'demo'")
        return v


class PaymentOut(PaymentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# ----------------------------- Estimates / analysis -----------------------------

class EstimateOut(BaseModel):
    month: str
    units_kwh: Decimal
    energy_charge: Decimal
    additional_charges: Decimal
    estimated_total: Decimal
    currency: str = "INR"
    is_estimate: bool = True
    disclaimer: str = "Estimated bill based on configured tariff slabs; not an official bill."


class BillComparison(BaseModel):
    month: str
    estimated_total: Decimal | None
    actual_amount: Decimal | None
    difference: Decimal | None
    source_label: str | None


class MonthlyConsumption(BaseModel):
    month: str
    units_kwh: Decimal
    deviation_pct: float | None
    significant: bool


class ConsumptionAnalysis(BaseModel):
    months: list[MonthlyConsumption]
    trailing_average_kwh: Decimal | None
    threshold_pct: float
    sufficient_history: bool
    message: str | None = None


# ----------------------------- Integration -----------------------------

class ExternalExpenseRecord(BaseModel):
    """Shape served to Application A at GET /integration/expenses.

    Only recorded charges (actual bills and payments) are exposed; estimates
    are never included so they cannot be double-counted.
    """

    id: int
    bill_month: str | None = None
    reading_date: dt.date | None = None
    description: str
    amount: Decimal
    currency: str = "INR"
    kind: str  # actual_bill | payment
    external_ref: str


class CategoryMapItem(BaseModel):
    requested_category: str
    mapped_category: str
    source: str = "app_a"


class SyncResult(BaseModel):
    target: str
    status: str
    pushed: int
    skipped_duplicates: int
    detail: str | None = None
