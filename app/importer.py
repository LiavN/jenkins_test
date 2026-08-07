"""Optional CSV bulk import for history that already lives in a spreadsheet.

Expected columns (Hebrew or English headers accepted):
  service:  date, odometer, service_type, garage, cost, items, notes
  fuel:     date, odometer, liters, price_total, station, full_tank, notes
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Optional

from sqlalchemy.orm import Session

from .models import FuelLog, ServiceEvent

# Map possible header names -> canonical field.
ALIASES = {
    "date": "date", "תאריך": "date",
    "odometer": "odometer", "km": "odometer", "קמ": "odometer", "קילומטראז": "odometer",
    "service_type": "service_type", "type": "service_type", "סוג": "service_type",
    "garage": "garage", "מוסך": "garage",
    "cost": "cost", "עלות": "cost", "מחיר": "cost",
    "items": "items", "פעולות": "items", "חלקים": "items",
    "notes": "notes", "הערות": "notes",
    "liters": "liters", "ליטר": "liters", "ליטרים": "liters",
    "price_total": "price_total", "סהכ": "price_total",
    "station": "station", "תחנה": "station",
    "full_tank": "full_tank", "מיכל_מלא": "full_tank",
}


def _canon(header: str) -> str:
    key = header.strip().lower().replace('"', "").replace("'", "").replace(" ", "_")
    return ALIASES.get(key, key)


def _pint(v) -> Optional[int]:
    v = (str(v) if v is not None else "").strip().replace(",", "")
    try:
        return int(float(v)) if v else None
    except ValueError:
        return None


def _pfloat(v) -> Optional[float]:
    v = (str(v) if v is not None else "").strip().replace(",", "")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _pdate(v) -> Optional[dt.date]:
    v = (str(v) if v is not None else "").strip()
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def import_csv(db: Session, vehicle_id: int, kind: str, text: str) -> int:
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [_canon(h) for h in (reader.fieldnames or [])]
    count = 0
    for row in reader:
        row = {_canon(k): v for k, v in row.items()}
        date = _pdate(row.get("date"))
        if date is None:
            continue
        if kind == "fuel":
            liters = _pfloat(row.get("liters")) or 0
            db.add(
                FuelLog(
                    vehicle_id=vehicle_id,
                    date=date,
                    odometer=_pint(row.get("odometer")),
                    liters=liters,
                    price_total=_pfloat(row.get("price_total")),
                    station=(row.get("station") or "").strip() or None,
                    full_tank=str(row.get("full_tank", "")).strip().lower()
                    not in {"0", "false", "לא", "no"},
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
        else:
            items = [x.strip() for x in (row.get("items") or "").split(";") if x.strip()]
            db.add(
                ServiceEvent(
                    vehicle_id=vehicle_id,
                    date=date,
                    odometer=_pint(row.get("odometer")),
                    service_type=(row.get("service_type") or "other").strip() or "other",
                    garage=(row.get("garage") or "").strip() or None,
                    cost=_pfloat(row.get("cost")),
                    items=items or None,
                    notes=(row.get("notes") or "").strip() or None,
                    source="manual",
                )
            )
        count += 1
    db.commit()
    return count
