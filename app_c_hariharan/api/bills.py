"""Actual bills, payments and tariff configuration endpoints.

Actual bills and payments are stored separately from estimates so recorded
charges can never be confused with computed ones.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
import schemas
from api.auth import require_token
from database import get_db

router = APIRouter(tags=["bills, payments & tariff"])


# ----------------------------- Actual bills -----------------------------

@router.get("/bill/actual", response_model=list[schemas.ActualBillOut])
def list_actual_bills(
    start: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    end: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    db: Session = Depends(get_db),
):
    stmt = select(models.ActualBill).order_by(models.ActualBill.bill_month.desc())
    if start:
        stmt = stmt.where(models.ActualBill.bill_month >= start)
    if end:
        stmt = stmt.where(models.ActualBill.bill_month <= end)
    return list(db.scalars(stmt))


@router.post("/bill/actual", response_model=schemas.ActualBillOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_actual_bill(payload: schemas.ActualBillCreate, db: Session = Depends(get_db)):
    exists = db.scalar(
        select(models.ActualBill).where(models.ActualBill.bill_month == payload.bill_month)
    )
    if exists:
        raise HTTPException(409, f"An actual bill for {payload.bill_month} already exists")
    bill = models.ActualBill(**payload.model_dump())
    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill


@router.put("/bill/actual/{bill_id}", response_model=schemas.ActualBillOut,
            dependencies=[Depends(require_token)])
def update_actual_bill(bill_id: int, payload: schemas.ActualBillCreate,
                       db: Session = Depends(get_db)):
    bill = db.get(models.ActualBill, bill_id)
    if not bill:
        raise HTTPException(404, "Actual bill not found")
    clash = db.scalar(
        select(models.ActualBill).where(
            models.ActualBill.bill_month == payload.bill_month,
            models.ActualBill.id != bill_id,
        )
    )
    if clash:
        raise HTTPException(409, "Another bill already covers that month")
    for key, value in payload.model_dump().items():
        setattr(bill, key, value)
    db.commit()
    db.refresh(bill)
    return bill


@router.delete("/bill/actual/{bill_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_actual_bill(bill_id: int, db: Session = Depends(get_db)):
    bill = db.get(models.ActualBill, bill_id)
    if not bill:
        raise HTTPException(404, "Actual bill not found")
    db.delete(bill)
    db.commit()


# ----------------------------- Payments -----------------------------

@router.get("/payments", response_model=list[schemas.PaymentOut])
def list_payments(
    start: dt.date | None = Query(default=None),
    end: dt.date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    stmt = select(models.Payment).order_by(models.Payment.paid_on.desc())
    if start:
        stmt = stmt.where(models.Payment.paid_on >= start)
    if end:
        stmt = stmt.where(models.Payment.paid_on <= end)
    return list(db.scalars(stmt))


@router.post("/payments", response_model=schemas.PaymentOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_payment(payload: schemas.PaymentCreate, db: Session = Depends(get_db)):
    if payload.bill_id is not None and not db.get(models.ActualBill, payload.bill_id):
        raise HTTPException(422, "bill_id does not reference an existing actual bill")
    pay = models.Payment(**payload.model_dump())
    db.add(pay)
    db.commit()
    db.refresh(pay)
    return pay


@router.delete("/payments/{payment_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_payment(payment_id: int, db: Session = Depends(get_db)):
    pay = db.get(models.Payment, payment_id)
    if not pay:
        raise HTTPException(404, "Payment not found")
    db.delete(pay)
    db.commit()


# ----------------------------- Tariff config -----------------------------

@router.get("/tariff/slabs", response_model=list[schemas.SlabOut])
def list_slabs(db: Session = Depends(get_db)):
    return list(db.scalars(
        select(models.TariffSlab).order_by(models.TariffSlab.effective_from,
                                           models.TariffSlab.up_to_kwh)
    ))


@router.post("/tariff/slabs", response_model=schemas.SlabOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_slab(payload: schemas.SlabCreate, db: Session = Depends(get_db)):
    slab = models.TariffSlab(**payload.model_dump())
    db.add(slab)
    db.commit()
    db.refresh(slab)
    return slab


@router.delete("/tariff/slabs/{slab_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_slab(slab_id: int, db: Session = Depends(get_db)):
    slab = db.get(models.TariffSlab, slab_id)
    if not slab:
        raise HTTPException(404, "Tariff slab not found")
    db.delete(slab)
    db.commit()


@router.get("/tariff/charges", response_model=list[schemas.ChargeOut])
def list_charges(db: Session = Depends(get_db)):
    return list(db.scalars(select(models.ChargeConfig).order_by(models.ChargeConfig.name)))


@router.post("/tariff/charges", response_model=schemas.ChargeOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_charge(payload: schemas.ChargeCreate, db: Session = Depends(get_db)):
    exists = db.scalar(
        select(models.ChargeConfig).where(models.ChargeConfig.name == payload.name)
    )
    if exists:
        raise HTTPException(409, f"Charge '{payload.name}' already exists")
    chg = models.ChargeConfig(**payload.model_dump())
    db.add(chg)
    db.commit()
    db.refresh(chg)
    return chg


@router.delete("/tariff/charges/{charge_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_charge(charge_id: int, db: Session = Depends(get_db)):
    chg = db.get(models.ChargeConfig, charge_id)
    if not chg:
        raise HTTPException(404, "Charge not found")
    db.delete(chg)
    db.commit()
