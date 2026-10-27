"""Pydantic schemas for Application B. Money uses Decimal everywhere."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import BILLING_FREQUENCIES, FREQUENCY_MONTHS, SUBSCRIPTION_STATUSES

TWO_PLACES = Decimal("0.01")


def add_months(date: dt.date, months: int) -> dt.date:
    """Add calendar months, clamping day to the target month's length."""
    total = (date.year * 12 + date.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(date.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def compute_next_renewal(start_date: dt.date, frequency: str,
                        reference: dt.date | None = None) -> dt.date:
    """First renewal date strictly after the reference date (default today)."""
    ref = reference or dt.date.today()
    step = FREQUENCY_MONTHS[frequency]
    renewal = start_date
    # Guard against pathological loops (e.g. far-future start dates).
    for _ in range(2000):
        if renewal > ref:
            return renewal
        renewal = add_months(renewal, step)
    return renewal


def monthly_equivalent(amount: Decimal, frequency: str) -> Decimal:
    return (amount / FREQUENCY_MONTHS[frequency]).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )


class SubscriptionBase(BaseModel):
    service_name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="Entertainment", max_length=50)
    plan: str | None = Field(default=None, max_length=100)
    amount: Decimal = Field(gt=0, description="Charge per billing cycle")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    billing_frequency: str = "monthly"
    start_date: dt.date
    next_renewal: dt.date | None = None
    status: str = "active"
    tags: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("billing_frequency")
    @classmethod
    def valid_frequency(cls, v: str) -> str:
        if v not in BILLING_FREQUENCIES:
            raise ValueError(f"billing_frequency must be one of {BILLING_FREQUENCIES}")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str) -> str:
        if v not in SUBSCRIPTION_STATUSES:
            raise ValueError(f"status must be one of {SUBSCRIPTION_STATUSES}")
        return v

    @field_validator("start_date")
    @classmethod
    def valid_start(cls, v: dt.date) -> dt.date:
        if v > dt.date.today():
            raise ValueError("start_date cannot be in the future")
        return v


class SubscriptionCreate(SubscriptionBase):
    pass


class SubscriptionUpdate(BaseModel):
    service_name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=50)
    plan: str | None = None
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    billing_frequency: str | None = None
    start_date: dt.date | None = None
    next_renewal: dt.date | None = None
    status: str | None = None
    tags: str | None = None
    notes: str | None = None

    @field_validator("billing_frequency")
    @classmethod
    def valid_frequency(cls, v: str | None) -> str | None:
        if v is not None and v not in BILLING_FREQUENCIES:
            raise ValueError(f"billing_frequency must be one of {BILLING_FREQUENCIES}")
        return v

    @field_validator("status")
    @classmethod
    def valid_status(cls, v: str | None) -> str | None:
        if v is not None and v not in SUBSCRIPTION_STATUSES:
            raise ValueError(f"status must be one of {SUBSCRIPTION_STATUSES}")
        return v


class SubscriptionOut(SubscriptionBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: dt.datetime
    updated_at: dt.datetime

    @property
    def monthly_equivalent(self) -> Decimal:
        return monthly_equivalent(self.amount, self.billing_frequency)


class SubscriptionList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[SubscriptionOut]


class RenewalItem(BaseModel):
    subscription_id: int
    service_name: str
    amount: Decimal
    currency: str
    billing_frequency: str
    next_renewal: dt.date
    days_until_renewal: int
    status: str


class CostTotals(BaseModel):
    active_count: int
    monthly_total: Decimal
    annual_total: Decimal
    by_category: dict[str, Decimal]


# ---- Payload exported to Application A (validated on both sides) ----

class ExportedSubscription(BaseModel):
    """One eligible recurring-cost record for expense import into App A."""

    id: int
    service_name: str
    amount: Decimal
    currency: str
    billing_frequency: str
    monthly_equivalent: Decimal
    next_renewal: dt.date | None
    status: str
    category: str


class ExportBundle(BaseModel):
    generated_at: dt.datetime
    items: list[ExportedSubscription]


class ExternalCategoryMap(BaseModel):
    """Validates Application A's /categories response."""

    model_config = ConfigDict(extra="ignore")

    categories: list[str]

    @classmethod
    def from_response(cls, data: object) -> "ExternalCategoryMap":
        if isinstance(data, list):
            return cls(categories=[str(c) for c in data])
        raise ValueError("Application A /categories must return a JSON list")


class SyncResult(BaseModel):
    target_app: str
    status: str
    records_exported: int
    message: str | None = None
    last_successful_sync: dt.datetime | None = None
