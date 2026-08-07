"""Initial data seeding: users, the two vehicles, manufacturer service
schedules and community-reported known issues.

Idempotent: each block only runs when its table is empty, so restarts are safe.
The seeded intervals/issues are a sensible starting point and are fully
editable from the UI — always verify against the vehicle's own service book.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .config import get_settings
from .models import KnownIssue, MaintenanceSchedule, User, Vehicle

settings = get_settings()


# --- Manufacturer schedule templates -------------------------------------
# (task, interval_km, interval_months)
KIA_SELTOS_2023 = [
    ("החלפת שמן מנוע ומסנן שמן", 10000, 12),
    ("החלפת מסנן אוויר מנוע", 40000, 48),
    ("החלפת מסנן מזגן (תא נוסעים)", 15000, 12),
    ("סבב/בדיקת צמיגים ואיזון", 10000, None),
    ("החלפת נוזל בלמים", None, 24),
    ("החלפת מצתים", 60000, None),
    ("בדיקת מערכת בלמים (רפידות/דיסקים)", 20000, 12),
    ("החלפת נוזל קירור (ראשונה)", 200000, 120),
]

LAND_CRUISER_120_2006 = [
    ("החלפת שמן מנוע ומסנן שמן", 10000, 12),
    ("החלפת מסנן אוויר מנוע", 40000, 48),
    ("החלפת מצתים (אירידיום)", 100000, None),
    ("החלפת שמן גיר אוטומטי (בדיקה/החלפה)", 80000, None),
    ("החלפת שמן דיפרנציאל קדמי/אחורי ומעביר כוח", 40000, 48),
    ("החלפת נוזל בלמים", None, 24),
    ("החלפת נוזל קירור (Toyota SLLC)", 160000, 120),
    ("בדיקת מרכבים תחתונה: פרקי כדור, מצמדי הגה", 20000, 12),
    ("בדיקת מערכת בלמים (רפידות/דיסקים)", 20000, 12),
]

# --- Community-reported known issues -------------------------------------
KNOWN_ISSUES = [
    dict(
        make="Toyota",
        model="Land Cruiser 120",
        year_from=2003,
        year_to=2009,
        title="כשל משאבת הזרקת אוויר משנית (Secondary Air Injection)",
        description=(
            "מנוע 1GR-FE נוטה לכשל במשאבת הזרקת אוויר משנית שמדליק נורת מנוע "
            "(קודים P2440/P2441). תיקון יקר. מומלץ לאבחן מוקדם."
        ),
        trigger_km=120000,
        severity="high",
        source="דיווחי קהילת בעלי לנד קרוזר / פורומים",
    ),
    dict(
        make="Toyota",
        model="Land Cruiser 120",
        year_from=2003,
        year_to=2009,
        title="בלאי פרקי כדור קדמיים (Lower Ball Joints)",
        description="שחיקת פרקי כדור תחתונים קדמיים; מתבטא ברעשים/משחק בהיגוי. בדיקה תקופתית.",
        trigger_km=120000,
        severity="medium",
        source="דיווחי קהילה",
    ),
    dict(
        make="Toyota",
        model="Land Cruiser 120",
        year_from=2003,
        year_to=2009,
        title="סדקים בלוח מחוונים (Dashboard) באקלים חם",
        description="נפוץ בכלי רכב באקלים חם כמו בישראל; אין השפעה מכנית אך אסתטי/בטיחותי.",
        trigger_km=None,
        severity="low",
        source="דיווחי קהילה",
    ),
    dict(
        make="Toyota",
        model="Land Cruiser 120",
        year_from=2003,
        year_to=2009,
        title="תקלות אקטואטור מיזוג (Blend Door Actuator)",
        description="רעשי תקתוק מאזור המזגן / שליטה לא אחידה בטמפרטורה.",
        trigger_km=150000,
        severity="low",
        source="דיווחי קהילה",
    ),
    dict(
        make="Kia",
        model="Seltos",
        year_from=2020,
        year_to=2024,
        title="עדכוני תוכנה למערכת מולטימדיה / התרוקנות מצבר 12V",
        description=(
            "דיווחים על באגים במערכת המולטימדיה ולעתים התרוקנות מצבר בעמידה ממושכת. "
            "מומלץ לוודא שכל עדכוני התוכנה והריקולים בוצעו במוסך המורשה."
        ),
        trigger_km=None,
        severity="low",
        source="דיווחי קהילה / ריקולים אפשריים",
    ),
    dict(
        make="Kia",
        model="Seltos",
        year_from=2020,
        year_to=2024,
        title="בדיקת ריקולים רשמיים",
        description="ודא מול היבואן/מוסך מורשה שאין ריקולים פתוחים לרכב לפי מספר השלדה (VIN).",
        trigger_km=None,
        severity="medium",
        source="יבואן/יצרן",
    ),
]


def _seed_users(db: Session) -> None:
    if db.scalar(select(User).limit(1)):
        return
    for spec in settings.initial_users.split(","):
        spec = spec.strip()
        if not spec:
            continue
        parts = spec.split(":")
        if len(parts) != 3:
            continue
        name, email, password = (p.strip() for p in parts)
        db.add(
            User(
                name=name,
                email=email.lower(),
                password_hash=hash_password(password),
            )
        )
    db.commit()


def _add_schedules(db: Session, vehicle: Vehicle, template) -> None:
    for task, km, months in template:
        db.add(
            MaintenanceSchedule(
                vehicle_id=vehicle.id,
                task=task,
                interval_km=km,
                interval_months=months,
            )
        )


def _seed_vehicles(db: Session) -> None:
    if db.scalar(select(Vehicle).limit(1)):
        return
    seltos = Vehicle(
        make="Kia",
        model="Seltos",
        year=2023,
        fuel_type="בנזין",
        default_garage="מוסך מורשה קיה",
        notes="מטופל במוסך מורשה לפי ספר יצרן.",
    )
    prado = Vehicle(
        make="Toyota",
        model="Land Cruiser 120",
        trim="Prado 1GR-FE",
        year=2006,
        fuel_type="בנזין",
        engine="1GR-FE 4.0 V6",
        default_garage="מוסכים שונים",
        notes="רכב ותיק, מטופל במוסכים שונים.",
    )
    db.add_all([seltos, prado])
    db.commit()
    _add_schedules(db, seltos, KIA_SELTOS_2023)
    _add_schedules(db, prado, LAND_CRUISER_120_2006)
    db.commit()


def _seed_known_issues(db: Session) -> None:
    if db.scalar(select(KnownIssue).limit(1)):
        return
    for issue in KNOWN_ISSUES:
        db.add(KnownIssue(**issue))
    db.commit()


def seed_all(db: Session) -> None:
    _seed_users(db)
    _seed_vehicles(db)
    _seed_known_issues(db)
