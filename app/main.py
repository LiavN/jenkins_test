"""FastAPI application: routes, forms, and page rendering."""
from __future__ import annotations

import datetime as dt
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import alerts, notifications, receipts, telemetry
from .auth import authenticate, current_user
from .config import get_settings
from .db import get_db, init_db
from .models import (
    SERVICE_TYPES,
    Alert,
    FuelLog,
    KnownIssue,
    MaintenanceSchedule,
    OilCheck,
    Receipt,
    ServiceEvent,
    Vehicle,
)
from .seed_data import seed_all

settings = get_settings()
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Garage — מעקב כשירות רכבים")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, max_age=60 * 60 * 24 * 30)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.globals["SERVICE_TYPES"] = SERVICE_TYPES


# ----------------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------------
@app.on_event("startup")
def _startup() -> None:
    os.makedirs(settings.receipts_dir, exist_ok=True)
    init_db()
    from .db import SessionLocal

    db = SessionLocal()
    try:
        seed_all(db)
        alerts.recompute_all(db)
    finally:
        db.close()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
def require_user(request: Request, db: Session):
    user = current_user(request, db)
    return user


def _redirect_login() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def render(request: Request, db: Session, template: str, **ctx) -> HTMLResponse:
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.year.desc())).all()
    base = {
        "request": request,
        "user": current_user(request, db),
        "nav_vehicles": vehicles,
        "alert_count": len(alerts.active_alerts(db)),
        "today": dt.date.today().isoformat(),
    }
    base.update(ctx)
    return templates.TemplateResponse(template, base)


def _to_int(v: Optional[str]) -> Optional[int]:
    v = (v or "").strip().replace(",", "")
    return int(float(v)) if v else None


def _to_float(v: Optional[str]) -> Optional[float]:
    v = (v or "").strip().replace(",", "")
    return float(v) if v else None


def _to_date(v: Optional[str]) -> Optional[dt.date]:
    v = (v or "").strip()
    return dt.date.fromisoformat(v) if v else None


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    if current_user(request, db):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login")
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate(db, email, password)
    if not user:
        return templates.TemplateResponse(
            "login.html", {"request": request, "error": "אימייל או סיסמה שגויים"}
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.year.desc())).all()
    cards = []
    for v in vehicles:
        v_alerts = alerts.active_alerts(db, v.id)
        next_alert = v_alerts[0] if v_alerts else None
        cards.append(
            {
                "vehicle": v,
                "odometer": telemetry.current_odometer(db, v),
                "km_month": telemetry.km_per_month(db, v),
                "alerts": v_alerts,
                "next_alert": next_alert,
            }
        )
    return render(request, db, "dashboard.html", cards=cards)


# ----------------------------------------------------------------------------
# Vehicles
# ----------------------------------------------------------------------------
@app.get("/vehicles/new", response_class=HTMLResponse)
def vehicle_new(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    return render(request, db, "vehicle_form.html", vehicle=None)


@app.post("/vehicles/new")
def vehicle_create(
    request: Request,
    make: str = Form(...),
    model: str = Form(...),
    year: int = Form(...),
    trim: str = Form(""),
    license_plate: str = Form(""),
    vin: str = Form(""),
    fuel_type: str = Form(""),
    engine: str = Form(""),
    default_garage: str = Form(""),
    initial_odometer: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    v = Vehicle(
        make=make.strip(),
        model=model.strip(),
        year=year,
        trim=trim.strip() or None,
        license_plate=license_plate.strip() or None,
        vin=vin.strip() or None,
        fuel_type=fuel_type.strip() or None,
        engine=engine.strip() or None,
        default_garage=default_garage.strip() or None,
        initial_odometer=_to_int(initial_odometer) or 0,
        notes=notes.strip() or None,
    )
    db.add(v)
    db.commit()
    return RedirectResponse(f"/vehicles/{v.id}", status_code=303)


@app.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
def vehicle_detail(vehicle_id: int, request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    v = db.get(Vehicle, vehicle_id)
    if not v:
        return render(request, db, "message.html", message="הרכב לא נמצא")

    # Build a unified activity log.
    log: list[dict] = []
    for s in v.service_events:
        log.append(
            {
                "date": s.date,
                "kind": "service",
                "title": s.type_label,
                "odometer": s.odometer,
                "detail": ", ".join(s.items or []) if s.items else (s.notes or ""),
                "cost": s.cost,
                "garage": s.garage,
                "id": s.id,
            }
        )
    for f in v.fuel_logs:
        log.append(
            {
                "date": f.date,
                "kind": "fuel",
                "title": "תדלוק",
                "odometer": f.odometer,
                "detail": f"{f.liters} ליטר" + (f" · {f.station}" if f.station else ""),
                "cost": f.price_total,
                "garage": None,
                "id": f.id,
            }
        )
    for o in v.oil_checks:
        log.append(
            {
                "date": o.date,
                "kind": "oil",
                "title": f"בדיקת שמן ({o.level_label})",
                "odometer": o.odometer,
                "detail": o.condition or "",
                "cost": None,
                "garage": None,
                "id": o.id,
            }
        )
    log.sort(key=lambda x: (x["date"] or dt.date.min), reverse=True)

    return render(
        request,
        db,
        "vehicle.html",
        vehicle=v,
        odometer=telemetry.current_odometer(db, v),
        km_month=telemetry.km_per_month(db, v),
        econ=telemetry.fuel_economy(db, v.id),
        maint_cost=telemetry.maintenance_cost(db, v.id),
        alerts=alerts.active_alerts(db, v.id),
        log=log,
    )


# ----------------------------------------------------------------------------
# Quick record entry
# ----------------------------------------------------------------------------
@app.post("/vehicles/{vehicle_id}/fuel")
def add_fuel(
    vehicle_id: int,
    request: Request,
    date: str = Form(...),
    odometer: str = Form(""),
    liters: str = Form(...),
    price_total: str = Form(""),
    station: str = Form(""),
    full_tank: str = Form("on"),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    liters_v = _to_float(liters) or 0
    total = _to_float(price_total)
    db.add(
        FuelLog(
            vehicle_id=vehicle_id,
            date=_to_date(date),
            odometer=_to_int(odometer),
            liters=liters_v,
            price_total=total,
            price_per_liter=round(total / liters_v, 3) if total and liters_v else None,
            station=station.strip() or None,
            full_tank=full_tank == "on",
            notes=notes.strip() or None,
        )
    )
    db.commit()
    _recompute_one(db, vehicle_id)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@app.post("/vehicles/{vehicle_id}/oil")
def add_oil(
    vehicle_id: int,
    request: Request,
    date: str = Form(...),
    odometer: str = Form(""),
    level: str = Form("ok"),
    condition: str = Form(""),
    topped_up: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    db.add(
        OilCheck(
            vehicle_id=vehicle_id,
            date=_to_date(date),
            odometer=_to_int(odometer),
            level=level,
            condition=condition.strip() or None,
            topped_up=topped_up == "on",
            notes=notes.strip() or None,
        )
    )
    db.commit()
    _recompute_one(db, vehicle_id)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@app.post("/vehicles/{vehicle_id}/service")
def add_service(
    vehicle_id: int,
    request: Request,
    date: str = Form(...),
    odometer: str = Form(""),
    service_type: str = Form("other"),
    garage: str = Form(""),
    cost: str = Form(""),
    items: str = Form(""),
    notes: str = Form(""),
    receipt_id: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    item_list = [x.strip() for x in items.replace("\n", ",").split(",") if x.strip()]
    rid = _to_int(receipt_id)
    ev = ServiceEvent(
        vehicle_id=vehicle_id,
        date=_to_date(date),
        odometer=_to_int(odometer),
        service_type=service_type,
        garage=garage.strip() or None,
        cost=_to_float(cost),
        items=item_list or None,
        notes=notes.strip() or None,
        source="ocr" if rid else "manual",
        receipt_id=rid,
    )
    db.add(ev)
    _maybe_mark_schedule_done(db, vehicle_id, ev)
    db.commit()
    if rid:
        receipt = db.get(Receipt, rid)
        if receipt:
            receipt.status = "confirmed"
            receipt.vehicle_id = vehicle_id
            db.commit()
    _recompute_one(db, vehicle_id)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


def _maybe_mark_schedule_done(db: Session, vehicle_id: int, ev: ServiceEvent) -> None:
    """Advance matching manufacturer schedules when a service is logged."""
    if ev.service_type not in {"oil_change", "major_service", "minor_service"}:
        return
    scheds = db.scalars(
        select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id == vehicle_id)
    ).all()
    for s in scheds:
        if "שמן" in s.task and ev.service_type == "oil_change":
            if ev.odometer:
                s.last_done_odometer = ev.odometer
            s.last_done_date = ev.date


def _recompute_one(db: Session, vehicle_id: int) -> None:
    v = db.get(Vehicle, vehicle_id)
    if v:
        alerts.recompute_vehicle(db, v)


# ----------------------------------------------------------------------------
# Alerts
# ----------------------------------------------------------------------------
@app.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    return render(request, db, "alerts.html", alerts=alerts.active_alerts(db))


@app.post("/alerts/{alert_id}/dismiss")
def dismiss_alert(alert_id: int, request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    a = db.get(Alert, alert_id)
    if a:
        a.dismissed = True
        a.status = "dismissed"
        db.commit()
    return RedirectResponse("/alerts", status_code=303)


@app.post("/alerts/recompute")
def recompute_alerts(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    alerts.recompute_all(db)
    return RedirectResponse("/alerts", status_code=303)


# ----------------------------------------------------------------------------
# Receipts (scanned) — upload, parse, confirm
# ----------------------------------------------------------------------------
@app.get("/receipts", response_class=HTMLResponse)
def receipts_page(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    items = db.scalars(select(Receipt).order_by(Receipt.created_at.desc())).all()
    return render(
        request, db, "receipts.html", receipts=items, vision_enabled=settings.vision_enabled
    )


@app.post("/receipts/upload")
async def receipt_upload(
    request: Request,
    vehicle_id: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    data = await file.read()
    ext = os.path.splitext(file.filename or "")[1] or ".bin"
    stored = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(settings.receipts_dir, stored)
    with open(path, "wb") as fh:
        fh.write(data)
    receipt = Receipt(
        vehicle_id=_to_int(vehicle_id),
        filename=stored,
        content_type=file.content_type,
        status="pending",
    )
    db.add(receipt)
    db.commit()

    if settings.vision_enabled and (file.content_type or "").startswith("image/"):
        receipts.parse_receipt(db, receipt, data)
        if receipt.status == "parsed":
            return RedirectResponse(f"/receipts/{receipt.id}/confirm", status_code=303)
    return RedirectResponse("/receipts", status_code=303)


@app.post("/receipts/{receipt_id}/parse")
def receipt_parse(receipt_id: int, request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        return RedirectResponse("/receipts", status_code=303)
    path = os.path.join(settings.receipts_dir, receipt.filename)
    with open(path, "rb") as fh:
        data = fh.read()
    receipts.parse_receipt(db, receipt, data)
    if receipt.status == "parsed":
        return RedirectResponse(f"/receipts/{receipt_id}/confirm", status_code=303)
    return RedirectResponse("/receipts", status_code=303)


@app.get("/receipts/{receipt_id}/confirm", response_class=HTMLResponse)
def receipt_confirm_page(receipt_id: int, request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        return render(request, db, "message.html", message="הקבלה לא נמצאה")
    parsed = receipt.parsed_json or {}
    return render(request, db, "receipt_confirm.html", receipt=receipt, parsed=parsed)


@app.post("/receipts/{receipt_id}/confirm")
def receipt_confirm_submit(
    receipt_id: int,
    request: Request,
    vehicle_id: int = Form(...),
    date: str = Form(...),
    odometer: str = Form(""),
    service_type: str = Form("other"),
    garage: str = Form(""),
    cost: str = Form(""),
    items: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    item_list = [x.strip() for x in items.replace("\n", ",").split(",") if x.strip()]
    ev = ServiceEvent(
        vehicle_id=vehicle_id,
        date=_to_date(date),
        odometer=_to_int(odometer),
        service_type=service_type,
        garage=garage.strip() or None,
        cost=_to_float(cost),
        items=item_list or None,
        notes=notes.strip() or None,
        source="ocr",
        receipt_id=receipt_id,
    )
    db.add(ev)
    _maybe_mark_schedule_done(db, vehicle_id, ev)
    receipt = db.get(Receipt, receipt_id)
    if receipt:
        receipt.status = "confirmed"
        receipt.vehicle_id = vehicle_id
    db.commit()
    _recompute_one(db, vehicle_id)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@app.get("/receipts/{receipt_id}/file")
def receipt_file(receipt_id: int, request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    receipt = db.get(Receipt, receipt_id)
    if not receipt:
        return Response(status_code=404)
    path = os.path.join(settings.receipts_dir, receipt.filename)
    if not os.path.exists(path):
        return Response(status_code=404)
    return FileResponse(path, media_type=receipt.content_type or "application/octet-stream")


# ----------------------------------------------------------------------------
# CSV import (optional convenience)
# ----------------------------------------------------------------------------
@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    return render(request, db, "import.html", result=None)


@app.post("/import")
async def import_submit(
    request: Request,
    vehicle_id: int = Form(...),
    kind: str = Form("service"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    from .importer import import_csv

    data = (await file.read()).decode("utf-8-sig")
    count = import_csv(db, vehicle_id, kind, data)
    _recompute_one(db, vehicle_id)
    return render(request, db, "import.html", result=count)


# ----------------------------------------------------------------------------
# Knowledge base (schedules + known issues)
# ----------------------------------------------------------------------------
@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.year.desc())).all()
    issues = db.scalars(select(KnownIssue).order_by(KnownIssue.make)).all()
    return render(request, db, "knowledge.html", vehicles=vehicles, issues=issues)


@app.post("/knowledge/schedule")
def add_schedule(
    request: Request,
    vehicle_id: int = Form(...),
    task: str = Form(...),
    interval_km: str = Form(""),
    interval_months: str = Form(""),
    last_done_odometer: str = Form(""),
    last_done_date: str = Form(""),
    db: Session = Depends(get_db),
):
    if not current_user(request, db):
        return _redirect_login()
    db.add(
        MaintenanceSchedule(
            vehicle_id=vehicle_id,
            task=task.strip(),
            interval_km=_to_int(interval_km),
            interval_months=_to_int(interval_months),
            last_done_odometer=_to_int(last_done_odometer),
            last_done_date=_to_date(last_done_date),
        )
    )
    db.commit()
    _recompute_one(db, vehicle_id)
    return RedirectResponse("/knowledge", status_code=303)


# ----------------------------------------------------------------------------
# Insights
# ----------------------------------------------------------------------------
@app.get("/insights", response_class=HTMLResponse)
def insights_page(request: Request, db: Session = Depends(get_db)):
    if not current_user(request, db):
        return _redirect_login()
    vehicles = db.scalars(select(Vehicle).order_by(Vehicle.year.desc())).all()
    rows = []
    for v in vehicles:
        rows.append(
            {
                "vehicle": v,
                "odometer": telemetry.current_odometer(db, v),
                "km_month": telemetry.km_per_month(db, v),
                "econ": telemetry.fuel_economy(db, v.id),
                "maint_cost": telemetry.maintenance_cost(db, v.id),
            }
        )
    return render(request, db, "insights.html", rows=rows)


# ----------------------------------------------------------------------------
# Ops endpoints (health + digest for cron/Jenkins)
# ----------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/cron/digest")
def cron_digest(db: Session = Depends(get_db)):
    """Recompute alerts and send the email digest. Called by cron/Jenkins."""
    alerts.recompute_all(db)
    sent = notifications.send_digest(db)
    return {"recomputed": True, "email_sent": sent}
