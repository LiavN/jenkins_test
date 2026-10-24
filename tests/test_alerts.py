import datetime as dt

from app import alerts
from app.models import FuelLog, KnownIssue, MaintenanceSchedule, Vehicle


def _vehicle(db):
    v = Vehicle(make="Toyota", model="Land Cruiser 120", year=2006, initial_odometer=200000)
    db.add(v)
    db.commit()
    return v


def test_schedule_overdue_by_km(db):
    v = _vehicle(db)
    # last oil change long ago; current odo pushed to 215000 via a fuel log.
    db.add(FuelLog(vehicle_id=v.id, date=dt.date.today(), odometer=215000, liters=50))
    db.add(
        MaintenanceSchedule(
            vehicle_id=v.id, task="החלפת שמן מנוע", interval_km=10000,
            last_done_odometer=200000, last_done_date=dt.date(2023, 1, 1),
        )
    )
    db.commit()
    alerts.recompute_vehicle(db, v)
    active = alerts.active_alerts(db, v.id)
    oil = [a for a in active if a.source == "schedule"]
    assert oil, "expected a schedule alert"
    assert oil[0].status == "overdue"  # 15000 km over a 10000 km interval


def test_known_issue_triggers_at_mileage(db):
    v = _vehicle(db)
    db.add(FuelLog(vehicle_id=v.id, date=dt.date.today(), odometer=130000, liters=50))
    db.add(
        KnownIssue(
            make="Toyota", model="Land Cruiser 120", year_from=2003, year_to=2009,
            title="Secondary air pump", description="known failure", trigger_km=120000,
            severity="high",
        )
    )
    db.commit()
    alerts.recompute_vehicle(db, v)
    active = alerts.active_alerts(db, v.id)
    issues = [a for a in active if a.source == "issue"]
    assert issues and issues[0].status == "due"


def test_dismiss_is_preserved_on_recompute(db):
    v = _vehicle(db)
    db.add(FuelLog(vehicle_id=v.id, date=dt.date.today(), odometer=215000, liters=50))
    db.add(
        MaintenanceSchedule(
            vehicle_id=v.id, task="החלפת שמן מנוע", interval_km=10000,
            last_done_odometer=200000, last_done_date=dt.date(2023, 1, 1),
        )
    )
    db.commit()
    alerts.recompute_vehicle(db, v)
    sched_alert = [a for a in alerts.active_alerts(db, v.id) if a.source == "schedule"][0]
    sched_alert.dismissed = True
    sched_alert.status = "dismissed"
    db.commit()
    # Recomputing should not resurrect the dismissed schedule alert.
    alerts.recompute_vehicle(db, v)
    assert not [a for a in alerts.active_alerts(db, v.id) if a.source == "schedule"]
