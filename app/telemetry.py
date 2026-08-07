"""Derived vehicle metrics: current odometer, usage rate, fuel economy.

These are computed from the logged records rather than stored, so they stay
correct as history is imported or edited.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import FuelLog, OilCheck, ServiceEvent, Vehicle


@dataclass
class OdoPoint:
    date: dt.date
    odometer: int


def _odo_points(db: Session, vehicle_id: int) -> list[OdoPoint]:
    """All (date, odometer) readings across every record type, sorted by date."""
    points: list[OdoPoint] = []
    for model in (ServiceEvent, FuelLog, OilCheck):
        rows = db.execute(
            select(model.date, model.odometer).where(model.vehicle_id == vehicle_id)
        ).all()
        for date, odo in rows:
            if odo is not None and date is not None:
                points.append(OdoPoint(date=date, odometer=int(odo)))
    points.sort(key=lambda p: (p.date, p.odometer))
    return points


def current_odometer(db: Session, vehicle: Vehicle) -> int:
    """Highest odometer reading seen, falling back to the vehicle's initial value."""
    points = _odo_points(db, vehicle.id)
    best = vehicle.initial_odometer or 0
    for p in points:
        if p.odometer > best:
            best = p.odometer
    return best


def km_per_month(db: Session, vehicle: Vehicle) -> Optional[float]:
    """Average km/month derived from the first and last odometer readings."""
    points = _odo_points(db, vehicle.id)
    if len(points) < 2:
        return None
    first, last = points[0], points[-1]
    days = (last.date - first.date).days
    km = last.odometer - first.odometer
    if days <= 0 or km <= 0:
        return None
    return round(km / days * 30.4, 1)


def project_date_for_km(db: Session, vehicle: Vehicle, target_km: int) -> Optional[dt.date]:
    """Estimate the calendar date at which the vehicle reaches target_km."""
    rate = km_per_month(db, vehicle)
    cur = current_odometer(db, vehicle)
    if not rate or target_km <= cur:
        return None
    months = (target_km - cur) / rate
    return dt.date.today() + dt.timedelta(days=int(months * 30.4))


@dataclass
class FuelEconomy:
    avg_l_per_100km: Optional[float]
    last_l_per_100km: Optional[float]
    total_liters: float
    total_cost: float


def fuel_economy(db: Session, vehicle_id: int) -> FuelEconomy:
    """Compute fuel economy from consecutive full-tank fill-ups."""
    logs = db.scalars(
        select(FuelLog).where(FuelLog.vehicle_id == vehicle_id).order_by(FuelLog.odometer)
    ).all()
    total_liters = sum(l.liters or 0 for l in logs)
    total_cost = sum(l.price_total or 0 for l in logs)

    # Distance-based economy needs consecutive odometer readings on full tanks.
    consumptions: list[float] = []
    prev = None
    for log in logs:
        if log.odometer is None:
            continue
        if prev is not None and log.full_tank and log.odometer > prev.odometer:
            dist = log.odometer - prev.odometer
            if dist > 0 and log.liters:
                consumptions.append(log.liters / dist * 100)
        if log.full_tank:
            prev = log

    avg = round(sum(consumptions) / len(consumptions), 2) if consumptions else None
    last = round(consumptions[-1], 2) if consumptions else None
    return FuelEconomy(
        avg_l_per_100km=avg,
        last_l_per_100km=last,
        total_liters=round(total_liters, 1),
        total_cost=round(total_cost, 2),
    )


def maintenance_cost(db: Session, vehicle_id: int) -> float:
    rows = db.scalars(
        select(ServiceEvent.cost).where(ServiceEvent.vehicle_id == vehicle_id)
    ).all()
    return round(sum(c or 0 for c in rows), 2)
