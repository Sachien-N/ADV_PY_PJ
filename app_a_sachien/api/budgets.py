"""Budget CRUD endpoints."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.auth import require_token
from database import get_db
from models import Budget
from schemas import BudgetCreate, BudgetOut, BudgetUpdate
from services.budgets import budget_status

router = APIRouter(tags=["budgets"])
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@router.get("/budgets", response_model=list[BudgetOut])
def list_budgets(month: str | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(Budget)
    if month:
        if not MONTH_RE.match(month):
            raise HTTPException(422, "month must be formatted YYYY-MM")
        stmt = stmt.where(Budget.month == month)
    return db.scalars(stmt.order_by(Budget.month.desc(), Budget.category)).all()


@router.post("/budgets", response_model=BudgetOut, status_code=201, dependencies=[Depends(require_token)])
def create_budget(payload: BudgetCreate, db: Session = Depends(get_db)):
    existing = db.scalars(
        select(Budget).where(Budget.month == payload.month, Budget.category == payload.category)
    ).first()
    if existing:
        raise HTTPException(409, f"Budget for {payload.category} in {payload.month} already exists")
    budget = Budget(**payload.model_dump())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@router.put("/budgets/{budget_id}", response_model=BudgetOut, dependencies=[Depends(require_token)])
def update_budget(budget_id: int, payload: BudgetUpdate, db: Session = Depends(get_db)):
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(404, "Budget not found")
    budget.limit_amount = payload.limit_amount
    db.commit()
    db.refresh(budget)
    return budget


@router.delete("/budgets/{budget_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_budget(budget_id: int, db: Session = Depends(get_db)):
    budget = db.get(Budget, budget_id)
    if not budget:
        raise HTTPException(404, "Budget not found")
    db.delete(budget)
    db.commit()


@router.get("/budgets/status")
def budgets_status(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                   db: Session = Depends(get_db)):
    """Utilization / remaining / overspending for a month."""
    return {"month": month, "statuses": budget_status(db, month)}
