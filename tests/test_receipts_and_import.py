import datetime as dt

from app import receipts
from app.importer import import_csv
from app.models import Vehicle


def test_extract_json_plain():
    data = receipts._extract_json('{"date": "2024-05-01", "cost": 500}')
    assert data["date"] == "2024-05-01"
    assert data["cost"] == 500


def test_extract_json_with_fence():
    text = '```json\n{"garage": "מוסך טסט", "items": ["שמן", "מסנן"]}\n```'
    data = receipts._extract_json(text)
    assert data["garage"] == "מוסך טסט"
    assert data["items"] == ["שמן", "מסנן"]


def test_import_service_csv(db):
    v = Vehicle(make="Kia", model="Seltos", year=2023, initial_odometer=0)
    db.add(v)
    db.commit()
    csv_text = (
        "date,odometer,service_type,garage,cost,items,notes\n"
        "2024-01-15,15000,oil_change,מוסך מורשה,450,שמן;מסנן שמן,טיפול 15 אלף\n"
        "2024-06-20,25000,minor_service,מוסך מורשה,600,בלמים,\n"
    )
    count = import_csv(db, v.id, "service", csv_text)
    assert count == 2
    assert len(v.service_events) == 2
    first = sorted(v.service_events, key=lambda s: s.date)[0]
    assert first.odometer == 15000
    assert "שמן" in first.items


def test_import_hebrew_headers(db):
    v = Vehicle(make="Kia", model="Seltos", year=2023, initial_odometer=0)
    db.add(v)
    db.commit()
    csv_text = "תאריך,קמ,ליטרים,סהכ,תחנה\n2024-02-01,16000,42.5,300,פז\n"
    count = import_csv(db, v.id, "fuel", csv_text)
    assert count == 1
    assert v.fuel_logs[0].liters == 42.5
