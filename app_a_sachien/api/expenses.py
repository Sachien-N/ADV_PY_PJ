"""Expense CRUD, categorization, summary, CSV import/export endpoints."""
from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from api.auth import require_token
from database import get_db
from models import EXPENSE_CATEGORIES, Expense
from schemas import (
    CategoryRuleCreate,
    CategoryRuleOut,
    ExpenseCreate,
    ExpenseList,
    ExpenseOut,
    ExpenseUpdate,
)
from services.budgets import month_bounds
from services.categorization import categorize_merchant, ensure_default_rules

router = APIRouter(tags=["expenses"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "app": "expense-manager", "time": dt.datetime.now(dt.timezone.utc).isoformat()}


@router.get("/categories", response_model=list[str])
def list_categories(db: Session = Depends(get_db)) -> list[str]:
    """Categories exposed to Applications B and C for consistent mapping."""
    return EXPENSE_CATEGORIES


@router.get("/category/{name}")
def category_detail(name: str, db: Session = Depends(get_db)) -> dict:
    if name not in EXPENSE_CATEGORIES:
        raise HTTPException(404, f"Unknown category '{name}'")
    total = db.scalar(
        select(func.sum(Expense.amount)).where(Expense.category == name)
    )
    count = db.scalar(select(func.count(Expense.id)).where(Expense.category == name))
    return {"category": name, "total_spent": float(total or 0), "expense_count": count or 0}


@router.get("/categorize")
def categorize(merchant: str = Query(min_length=1), db: Session = Depends(get_db)) -> dict:
    return {"merchant": merchant, "category": categorize_merchant(db, merchant)}


# --------------------------- Rules (editable) ---------------------------

@router.get("/rules", response_model=list[CategoryRuleOut])
def list_rules(db: Session = Depends(get_db)):
    from models import CategoryRule

    ensure_default_rules(db)
    return db.scalars(select(CategoryRule).order_by(CategoryRule.priority.desc())).all()


@router.post("/rules", response_model=CategoryRuleOut, status_code=201, dependencies=[Depends(require_token)])
def create_rule(payload: CategoryRuleCreate, db: Session = Depends(get_db)):
    from models import CategoryRule

    existing = db.scalars(select(CategoryRule).where(CategoryRule.pattern == payload.pattern)).first()
    if existing:
        existing.category, existing.priority = payload.category, payload.priority
    else:
        existing = CategoryRule(**payload.model_dump())
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@router.delete("/rules/{rule_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    from models import CategoryRule

    rule = db.get(CategoryRule, rule_id)
    if not rule:
        raise HTTPException(404, "Rule not found")
    db.delete(rule)
    db.commit()


# --------------------------- Expenses CRUD ---------------------------

@router.get("/expenses", response_model=ExpenseList)
def list_expenses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    search: str | None = None,
    category: str | None = None,
    source: str | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    sort: str = "-expense_date",
    db: Session = Depends(get_db),
):
    stmt = select(Expense)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(Expense.merchant.ilike(like), Expense.description.ilike(like)))
    if category:
        stmt = stmt.where(Expense.category == category)
    if source:
        stmt = stmt.where(Expense.source == source)
    if date_from:
        stmt = stmt.where(Expense.expense_date >= date_from)
    if date_to:
        stmt = stmt.where(Expense.expense_date <= date_to)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order_col = getattr(Expense, sort.lstrip("-"))
    order = order_col.desc() if sort.startswith("-") else order_col.asc()
    items = db.scalars(stmt.order_by(order, Expense.id.desc())
                       .offset((page - 1) * page_size).limit(page_size)).all()
    return ExpenseList(total=total, page=page, page_size=page_size, items=items)


@router.post("/expenses", response_model=ExpenseOut, status_code=201, dependencies=[Depends(require_token)])
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    source = data.pop("source_app", None) or "manual"
    external_id = data.pop("external_id", None)
    if source not in ("manual", "subscription", "electricity"):
        raise HTTPException(422, "source_app must be manual|subscription|electricity")
    if source != "manual" and not external_id:
        raise HTTPException(422, "external_id is required for imported records")
    if source != "manual" and external_id:
        existing = db.scalar(
            select(Expense).where(Expense.source == source, Expense.external_id == external_id)
        )
        if existing:  # idempotent import: never duplicate
            return existing
    expense = Expense(source=source, external_id=external_id, **data)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("/expenses/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    return expense


@router.put("/expenses/{expense_id}", response_model=ExpenseOut, dependencies=[Depends(require_token)])
def update_expense(expense_id: int, payload: ExpenseUpdate, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "No fields to update")
    for key, value in data.items():
        setattr(expense, key, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    expense = db.get(Expense, expense_id)
    if not expense:
        raise HTTPException(404, "Expense not found")
    db.delete(expense)
    db.commit()


# --------------------------- Summary ---------------------------

@router.get("/summary")
def summary(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"), db: Session = Depends(get_db)):
    from services.budgets import budget_status, monthly_totals, q2

    totals = monthly_totals(db, month)
    by_cat = sorted(
        ({"category": c, "total": t, "count": db.scalar(
            select(func.count(Expense.id)).where(
                Expense.category == c,
                Expense.expense_date >= month_bounds(month)[0],
                Expense.expense_date <= month_bounds(month)[1],
            )) or 0} for c, t in totals.items()),
        key=lambda x: x["total"], reverse=True,
    )
    external: dict[str, float] = {}
    start, end = month_bounds(month)
    rows = db.execute(
        select(Expense.source, func.sum(Expense.amount)).where(
            Expense.source != "manual", Expense.expense_date >= start, Expense.expense_date <= end
        ).group_by(Expense.source)
    ).all()
    for src, amount in rows:
        external[src] = float(q2(Decimal(amount or 0)))
    return {
        "month": month,
        "total_spent": sum(totals.values(), Decimal("0")),
        "by_category": by_cat,
        "budgets": budget_status(db, month),
        "external_sources": external,
    }


# --------------------------- CSV import / export ---------------------------

REQUIRED_CSV_COLUMNS = {"date", "merchant", "amount", "category"}


@router.get("/export/csv")
def export_csv(db: Session = Depends(get_db)):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "date", "merchant", "amount", "currency", "category",
                     "payment_method", "description", "source", "external_id"])
    for e in db.scalars(select(Expense).order_by(Expense.expense_date)).all():
        writer.writerow([e.id, e.expense_date.isoformat(), e.merchant, str(e.amount),
                         e.currency, e.category, e.payment_method, e.description or "",
                         e.source, e.external_id or ""])
    buf.seek(0)
    return StreamingResponse(io.BytesIO(buf.getvalue().encode()),
                             media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=expenses.csv"})


@router.post("/import/csv", dependencies=[Depends(require_token)])
async def import_csv(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        raise HTTPException(422, "Missing 'file' form field")
    raw = await upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "File must be UTF-8 encoded CSV")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not REQUIRED_CSV_COLUMNS.issubset(set(reader.fieldnames)):
        raise HTTPException(422, f"CSV must contain columns: {sorted(REQUIRED_CSV_COLUMNS)}")
    imported, errors = 0, []
    for i, row in enumerate(reader, start=2):
        try:
            category = (row.get("category") or "").strip()
            if category not in EXPENSE_CATEGORIES:
                category = categorize_merchant(db, row["merchant"])
            db.add(Expense(
                expense_date=dt.date.fromisoformat(row["date"].strip()),
                merchant=row["merchant"].strip()[:200],
                amount=Decimal(row["amount"]),
                currency=(row.get("currency") or "INR").strip().upper(),
                category=category,
                payment_method=(row.get("payment_method") or "Card").strip()[:50],
                description=(row.get("description") or "")[:2000] or None,
                source="csv",
            ))
            imported += 1
        except Exception as exc:
            errors.append(f"line {i}: {exc}")
    db.commit()
    return {"imported": imported, "errors": errors}
