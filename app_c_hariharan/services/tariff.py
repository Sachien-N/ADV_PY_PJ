"""Tariff & billing calculations for Application C.

All arithmetic uses Decimal. Tariff slabs are configurable — this module
never hardcodes an "official" rate; it applies whatever slabs the owner has
entered (with their documented source/effective date).
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

import models

TWO_PLACES = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def energy_charge_for_units(slabs: list[models.TariffSlab], units: Decimal) -> Decimal:
    """Tiered slab calculation: first `up_to` units at slab rate, remainder next."""
    remaining = Decimal(units)
    total = Decimal("0")
    lower = Decimal("0")
    for slab in sorted(slabs, key=lambda s: s.up_to_kwh):
        width = Decimal(slab.up_to_kwh) - lower
        if width <= 0:
            continue
        take = min(remaining, width)
        if take <= 0:
            break
        total += take * Decimal(slab.rate_per_kwh)
        remaining -= take
        lower = Decimal(slab.up_to_kwh)
    if remaining > 0:
        # Units beyond the highest slab are charged at the top slab rate.
        if slabs:
            top = max(slabs, key=lambda s: s.up_to_kwh)
            total += remaining * Decimal(top.rate_per_kwh)
    return money(total)


def active_slabs(db: Session, on_date: dt.date) -> list[models.TariffSlab]:
    stmt = (
        select(models.TariffSlab)
        .where(models.TariffSlab.effective_from <= on_date)
        .order_by(models.TariffSlab.up_to_kwh)
    )
    return list(db.scalars(stmt))


def additional_charges(db: Session, units: Decimal) -> tuple[Decimal, list[str]]:
    total = Decimal("0")
    names: list[str] = []
    for chg in db.scalars(select(models.ChargeConfig)):
        if not chg.applicable:
            continue
        if chg.charge_type == "fixed":
            total += Decimal(chg.amount)
        elif chg.charge_type == "per_kwh":
            total += Decimal(chg.amount) * Decimal(units)
        names.append(chg.name)
    return money(total), names


def estimate_bill(db: Session, units: Decimal, on_date: dt.date | None = None) -> dict:
    """Return an estimated bill breakdown for the given consumed units."""
    on_date = on_date or dt.date.today()
    slabs = active_slabs(db, on_date)
    energy = energy_charge_for_units(slabs, Decimal(units)) if slabs else Decimal("0")
    extra, _names = additional_charges(db, Decimal(units))
    return {
        "units_kwh": Decimal(units),
        "energy_charge": energy,
        "additional_charges": extra,
        "estimated_total": money(energy + extra),
    }


def appliance_monthly_kwh(ap: models.Appliance) -> Decimal:
    """kWh/month contributed by an appliance (rated W x h/day x days / 1000)."""
    kwh = (
        Decimal(ap.rated_power_w)
        * Decimal(ap.daily_hours)
        * Decimal(30.42)
        * Decimal(ap.quantity)
        / Decimal(1000)
    )
    return kwh.quantize(Decimal("0.001"))
