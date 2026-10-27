"""Budget calculation service (Decimal precision, no float money)."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Budget, Expense

TWO_PLACES = Decimal("0.01")


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    """'YYYY-MM' -> (first_day, last_day) of that month."""
    year, mon = int(month[:4]), int(month[5:7])
    return dt.date(year, mon, 1), dt.date(year, mon, calendar.monthrange(year, mon)[1])


def q2(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def monthly_totals(db: Session, month: str) -> dict[str, Decimal]:
    start, end = month_bounds(month)
    rows = db.execute(
        select(Expense.category, Expense.amount).where(
            Expense.expense_date >= start, Expense.expense_date <= end
        )
    ).all()
    totals: dict[str, Decimal] = {}
    for category, amount in rows:
        totals[category] = totals.get(category, Decimal("0")) + amount
    return {k: q2(v) for k, v in totals.items()}


def budget_status(db: Session, month: str) -> list[dict]:
    """Utilization, remaining and overspending per configured budget."""
    totals = monthly_totals(db, month)
    budgets = db.scalars(select(Budget).where(Budget.month == month)).all()
    out = []
    for b in budgets:
        spent = totals.get(b.category, Decimal("0"))
        remaining = q2(b.limit_amount - spent)
        utilization = (
            q2(spent / b.limit_amount * 100) if b.limit_amount else Decimal("0")
        )
        out.append(
            {
                "month": month,
                "category": b.category,
                "limit_amount": q2(b.limit_amount),
                "spent": spent,
                "remaining": remaining,
                "utilization_percent": utilization,
                "over_budget": spent > b.limit_amount,
            }
        )
    return out
