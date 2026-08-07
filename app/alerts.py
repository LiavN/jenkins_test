"""Alert engine.

Recomputes alerts for every vehicle from three sources:
  1. Manufacturer maintenance schedules (km + time based).
  2. Vehicle state (oil checks overdue, fuel economy regression).
  3. Community-reported known issues (triggered by mileage).

Alerts are deduped by ``ref_key`` so re-running does not create duplicates,
and user dismissals are preserved.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Alert, KnownIssue, MaintenanceSchedule, OilCheck, Vehicle
from . import telemetry

# Warn when this fraction of an interval has elapsed.
UPCOMING_THRESHOLD = 0.9
# Flag an oil check as stale after this many days.
OIL_CHECK_MAX_DAYS = 180


@dataclass
class Candidate:
    vehicle_id: int
    source: str
    title: str
    detail: str
    status: str
    ref_key: str
    due_km: Optional[int] = None
    due_date: Optional[dt.date] = None


def _schedule_candidates(db: Session, vehicle: Vehicle, cur_km: int) -> list[Candidate]:
    out: list[Candidate] = []
    today = dt.date.today()
    for sched in vehicle.schedules:
        if not sched.active:
            continue
        ratios: list[float] = []
        next_km = None
        next_date = None

        if sched.interval_km and sched.last_done_odometer is not None:
            done = cur_km - sched.last_done_odometer
            ratios.append(done / sched.interval_km)
            next_km = sched.last_done_odometer + sched.interval_km
        elif sched.interval_km and sched.last_done_odometer is None:
            next_km = cur_km + sched.interval_km  # baseline unknown

        if sched.interval_months and sched.last_done_date:
            elapsed = (today - sched.last_done_date).days
            ratios.append(elapsed / (sched.interval_months * 30.4))
            next_date = sched.last_done_date + dt.timedelta(days=int(sched.interval_months * 30.4))

        if not ratios:
            continue
        ratio = max(ratios)
        if ratio >= 1.2:
            status = "overdue"
        elif ratio >= 1.0:
            status = "due"
        elif ratio >= UPCOMING_THRESHOLD:
            status = "upcoming"
        else:
            continue

        bits = []
        if next_km:
            bits.append(f"בק״מ ~{next_km:,}")
        if next_date:
            bits.append(f"עד {next_date.isoformat()}")
        detail = f"{sched.task} — " + " / ".join(bits) if bits else sched.task
        out.append(
            Candidate(
                vehicle_id=vehicle.id,
                source="schedule",
                title=sched.task,
                detail=detail,
                status=status,
                ref_key=f"sched:{sched.id}",
                due_km=next_km,
                due_date=next_date,
            )
        )
    return out


def _state_candidates(db: Session, vehicle: Vehicle) -> list[Candidate]:
    out: list[Candidate] = []
    today = dt.date.today()
    last_oil = db.scalar(
        select(OilCheck)
        .where(OilCheck.vehicle_id == vehicle.id)
        .order_by(OilCheck.date.desc())
    )
    if last_oil is None:
        out.append(
            Candidate(
                vehicle_id=vehicle.id,
                source="state",
                title="לא בוצעה בדיקת שמן",
                detail="לא תועדה אף בדיקת מפלס שמן לרכב זה.",
                status="upcoming",
                ref_key="state:oil_never",
            )
        )
    elif (today - last_oil.date).days > OIL_CHECK_MAX_DAYS:
        days = (today - last_oil.date).days
        out.append(
            Candidate(
                vehicle_id=vehicle.id,
                source="state",
                title="בדיקת שמן ישנה",
                detail=f"בדיקת השמן האחרונה לפני {days} ימים. מומלץ לבדוק מפלס.",
                status="due",
                ref_key="state:oil_stale",
            )
        )

    econ = telemetry.fuel_economy(db, vehicle.id)
    if econ.avg_l_per_100km and econ.last_l_per_100km:
        if econ.last_l_per_100km > econ.avg_l_per_100km * 1.25:
            out.append(
                Candidate(
                    vehicle_id=vehicle.id,
                    source="state",
                    title="עלייה בצריכת דלק",
                    detail=(
                        f"צריכה אחרונה {econ.last_l_per_100km} ל/100ק״מ מול ממוצע "
                        f"{econ.avg_l_per_100km}. ייתכן צורך בבדיקה (מסנן אוויר, לחץ אוויר, מצתים)."
                    ),
                    status="upcoming",
                    ref_key="state:fuel_regression",
                )
            )
    return out


def _issue_candidates(db: Session, vehicle: Vehicle, cur_km: int) -> list[Candidate]:
    out: list[Candidate] = []
    issues = db.scalars(
        select(KnownIssue).where(
            KnownIssue.make == vehicle.make, KnownIssue.model == vehicle.model
        )
    ).all()
    for issue in issues:
        if issue.year_from and vehicle.year < issue.year_from:
            continue
        if issue.year_to and vehicle.year > issue.year_to:
            continue
        # Only surface once the vehicle is within ~10k km of the known trigger.
        if issue.trigger_km is not None and cur_km < issue.trigger_km - 10000:
            continue
        status = "upcoming"
        if issue.trigger_km is not None and cur_km >= issue.trigger_km:
            status = "due"
        detail = issue.description or ""
        if issue.trigger_km:
            detail = f"{detail}\n(נפוץ סביב {issue.trigger_km:,} ק״מ)".strip()
        if issue.source:
            detail = f"{detail}\nמקור: {issue.source}".strip()
        out.append(
            Candidate(
                vehicle_id=vehicle.id,
                source="issue",
                title=f"כשל נפוץ: {issue.title}",
                detail=detail,
                status=status,
                ref_key=f"issue:{issue.id}",
                due_km=issue.trigger_km,
            )
        )
    return out


def recompute_vehicle(db: Session, vehicle: Vehicle) -> None:
    cur_km = telemetry.current_odometer(db, vehicle)
    candidates = (
        _schedule_candidates(db, vehicle, cur_km)
        + _state_candidates(db, vehicle)
        + _issue_candidates(db, vehicle, cur_km)
    )

    existing = {
        a.ref_key: a
        for a in db.scalars(select(Alert).where(Alert.vehicle_id == vehicle.id)).all()
    }
    seen: set[str] = set()

    for c in candidates:
        seen.add(c.ref_key)
        alert = existing.get(c.ref_key)
        if alert:
            # Preserve dismissals; refresh the computed fields.
            alert.title = c.title
            alert.detail = c.detail
            alert.due_km = c.due_km
            alert.due_date = c.due_date
            if not alert.dismissed:
                alert.status = c.status
        else:
            db.add(
                Alert(
                    vehicle_id=c.vehicle_id,
                    source=c.source,
                    title=c.title,
                    detail=c.detail,
                    status=c.status,
                    due_km=c.due_km,
                    due_date=c.due_date,
                    ref_key=c.ref_key,
                )
            )

    # Remove stale non-dismissed alerts that no longer apply.
    for ref_key, alert in existing.items():
        if ref_key not in seen and not alert.dismissed:
            db.delete(alert)

    db.commit()


def recompute_all(db: Session) -> int:
    vehicles = db.scalars(select(Vehicle)).all()
    for v in vehicles:
        recompute_vehicle(db, v)
    return len(vehicles)


def active_alerts(db: Session, vehicle_id: Optional[int] = None) -> list[Alert]:
    stmt = select(Alert).where(Alert.dismissed.is_(False))
    if vehicle_id is not None:
        stmt = stmt.where(Alert.vehicle_id == vehicle_id)
    order = {"overdue": 0, "due": 1, "upcoming": 2, "dismissed": 3}
    alerts = db.scalars(stmt).all()
    return sorted(alerts, key=lambda a: order.get(a.status, 9))
