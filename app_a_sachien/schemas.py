"""Pydantic schemas for Application A. Money uses Decimal everywhere."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models import EXPENSE_CATEGORIES

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ExpenseBase(BaseModel):
    expense_date: dt.date
    merchant: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, description="Positive amount, 2 decimal places")
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    category: str
    payment_method: str = Field(default="Card", max_length=50)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(
                f"category must be one of {EXPENSE_CATEGORIES}"
            )
        return v


class ExpenseCreate(ExpenseBase):
    # Optional push-integration fields (used by peer apps, e.g. App C).
    # Manual clients simply omit them; they are ignored on PUT updates so
    # automatic imports never overwrite manual provenance fields.
    source_app: str | None = Field(default=None, max_length=30)
    external_id: str | None = Field(default=None, max_length=120)


class ExpenseUpdate(BaseModel):
    expense_date: dt.date | None = None
    merchant: str | None = Field(default=None, min_length=1, max_length=200)
    amount: Decimal | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    category: str | None = None
    payment_method: str | None = Field(default=None, max_length=50)
    description: str | None = None

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str | None) -> str | None:
        if v is not None and v not in EXPENSE_CATEGORIES:
            raise ValueError(f"category must be one of {EXPENSE_CATEGORIES}")
        return v


class ExpenseOut(ExpenseBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    external_id: str | None = None
    last_synced_at: dt.datetime | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ExpenseList(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[ExpenseOut]


class CategoryRuleCreate(BaseModel):
    pattern: str = Field(min_length=1, max_length=200)
    category: str
    priority: int = 100

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(f"category must be one of {EXPENSE_CATEGORIES}")
        return v


class CategoryRuleOut(CategoryRuleCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class BudgetCreate(BaseModel):
    month: str
    category: str
    limit_amount: Decimal = Field(gt=0)

    @field_validator("month")
    @classmethod
    def valid_month(cls, v: str) -> str:
        if not MONTH_RE.match(v):
            raise ValueError("month must be formatted YYYY-MM e.g. 2026-10")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        if v not in EXPENSE_CATEGORIES:
            raise ValueError(f"category must be one of {EXPENSE_CATEGORIES}")
        return v


class BudgetUpdate(BaseModel):
    limit_amount: Decimal = Field(gt=0)


class BudgetOut(BudgetCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class BudgetStatus(BaseModel):
    month: str
    category: str
    limit_amount: Decimal
    spent: Decimal
    remaining: Decimal
    utilization_percent: Decimal
    over_budget: bool


class CategorySummaryItem(BaseModel):
    category: str
    total: Decimal
    count: int


class SummaryOut(BaseModel):
    month: str
    total_spent: Decimal
    by_category: list[CategorySummaryItem]
    budgets: list[BudgetStatus]
    external_sources: dict[str, Decimal]


class SyncResult(BaseModel):
    source_app: str
    status: str
    records_imported: int
    records_skipped: int
    message: str | None = None
    last_successful_sync: dt.datetime | None = None


class IntegrationStatus(BaseModel):
    subscription_api: dict
    electricity_api: dict
    last_syncs: dict


# ---- External API response validation (Application B / C payloads) ----

class ExternalSubscription(BaseModel):
    """Validates records returned by Application B /subscriptions/export."""

    model_config = ConfigDict(extra="ignore")

    id: int | str
    service_name: str
    amount: Decimal
    currency: str = "INR"
    billing_frequency: str
    monthly_equivalent: Decimal
    next_renewal: dt.date | None = None
    status: str
    category: str | None = None


class ExternalElectricityExpense(BaseModel):
    """Validates records returned by Application C /integration/expenses."""

    model_config = ConfigDict(extra="ignore")

    id: int | str
    reading_date: dt.date | None = None
    bill_month: str | None = None
    description: str
    amount: Decimal
    currency: str = "INR"
    kind: str  # 'actual_bill' or 'payment'; estimates are excluded upstream
    external_ref: str
