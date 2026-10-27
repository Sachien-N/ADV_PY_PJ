"""Appliance CRUD endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
import schemas
from api.auth import require_token
from database import get_db
from services import tariff

router = APIRouter(tags=["appliances"])


@router.get("/appliances", response_model=list[schemas.ApplianceOut])
def list_appliances(active_only: bool = False, db: Session = Depends(get_db)):
    stmt = select(models.Appliance).order_by(models.Appliance.name)
    if active_only:
        stmt = stmt.where(models.Appliance.active.is_(True))
    out = []
    for ap in db.scalars(stmt):
        item = schemas.ApplianceOut.model_validate(ap)
        item.monthly_kwh = tariff.appliance_monthly_kwh(ap) if ap.active else None
        out.append(item)
    return out


@router.post("/appliances", response_model=schemas.ApplianceOut, status_code=201,
             dependencies=[Depends(require_token)])
def create_appliance(payload: schemas.ApplianceCreate, db: Session = Depends(get_db)):
    exists = db.scalar(
        select(models.Appliance).where(models.Appliance.name == payload.name)
    )
    if exists:
        raise HTTPException(409, f"Appliance '{payload.name}' already exists")
    ap = models.Appliance(**payload.model_dump())
    db.add(ap)
    db.commit()
    db.refresh(ap)
    out = schemas.ApplianceOut.model_validate(ap)
    out.monthly_kwh = tariff.appliance_monthly_kwh(ap)
    return out


@router.get("/appliances/{appliance_id}", response_model=schemas.ApplianceOut)
def get_appliance(appliance_id: int, db: Session = Depends(get_db)):
    ap = db.get(models.Appliance, appliance_id)
    if not ap:
        raise HTTPException(404, "Appliance not found")
    out = schemas.ApplianceOut.model_validate(ap)
    out.monthly_kwh = tariff.appliance_monthly_kwh(ap) if ap.active else None
    return out


@router.put("/appliances/{appliance_id}", response_model=schemas.ApplianceOut,
            dependencies=[Depends(require_token)])
def update_appliance(appliance_id: int, payload: schemas.ApplianceUpdate,
                     db: Session = Depends(get_db)):
    ap = db.get(models.Appliance, appliance_id)
    if not ap:
        raise HTTPException(404, "Appliance not found")
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(422, "No fields to update")
    if "name" in data:
        clash = db.scalar(
            select(models.Appliance).where(
                models.Appliance.name == data["name"],
                models.Appliance.id != appliance_id,
            )
        )
        if clash:
            raise HTTPException(409, "Another appliance already uses that name")
    for key, value in data.items():
        setattr(ap, key, value)
    db.commit()
    db.refresh(ap)
    out = schemas.ApplianceOut.model_validate(ap)
    out.monthly_kwh = tariff.appliance_monthly_kwh(ap) if ap.active else None
    return out


@router.delete("/appliances/{appliance_id}", status_code=204,
               dependencies=[Depends(require_token)])
def delete_appliance(appliance_id: int, db: Session = Depends(get_db)):
    ap = db.get(models.Appliance, appliance_id)
    if not ap:
        raise HTTPException(404, "Appliance not found")
    db.delete(ap)
    db.commit()
