import datetime as dt

from app import telemetry
from app.models import FuelLog, Vehicle


def _vehicle(db, **kw):
    v = Vehicle(make="Toyota", model="Land Cruiser 120", year=2006, initial_odometer=200000, **kw)
    db.add(v)
    db.commit()
    return v


def test_current_odometer_uses_highest_reading(db):
    v = _vehicle(db)
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 1, 1), odometer=205000, liters=50))
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 2, 1), odometer=205600, liters=48))
    db.commit()
    assert telemetry.current_odometer(db, v) == 205600


def test_current_odometer_falls_back_to_initial(db):
    v = _vehicle(db)
    assert telemetry.current_odometer(db, v) == 200000


def test_km_per_month(db):
    v = _vehicle(db)
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 1, 1), odometer=200000, liters=50))
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 3, 1), odometer=203040, liters=50))
    db.commit()
    rate = telemetry.km_per_month(db, v)
    # ~3040 km over ~60 days -> ~1540 km/month
    assert rate is not None and 1400 < rate < 1650


def test_fuel_economy(db):
    v = _vehicle(db)
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 1, 1), odometer=200000, liters=60, full_tank=True))
    db.add(FuelLog(vehicle_id=v.id, date=dt.date(2024, 1, 20), odometer=200600, liters=60, full_tank=True, price_total=400))
    db.commit()
    econ = telemetry.fuel_economy(db, v.id)
    # 60L over 600km -> 10 L/100km
    assert econ.avg_l_per_100km == 10.0
    assert econ.total_liters == 120.0
