"""SQLAlchemy ORM models for the garage tracker."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())


class Vehicle(Base):
    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    make: Mapped[str] = mapped_column(String(80))            # e.g. Toyota
    model: Mapped[str] = mapped_column(String(80))           # e.g. Land Cruiser 120
    trim: Mapped[Optional[str]] = mapped_column(String(80))  # sub-model / engine
    year: Mapped[int] = mapped_column(Integer)
    license_plate: Mapped[Optional[str]] = mapped_column(String(20))
    vin: Mapped[Optional[str]] = mapped_column(String(40))
    fuel_type: Mapped[Optional[str]] = mapped_column(String(30))
    engine: Mapped[Optional[str]] = mapped_column(String(60))
    default_garage: Mapped[Optional[str]] = mapped_column(String(120))
    initial_odometer: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    service_events: Mapped[list["ServiceEvent"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    fuel_logs: Mapped[list["FuelLog"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    oil_checks: Mapped[list["OilCheck"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["MaintenanceSchedule"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )
    receipts: Mapped[list["Receipt"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        return f"{self.make} {self.model} {self.year}".strip()


# Service event types
SERVICE_TYPES = {
    "oil_change": "החלפת שמן",
    "major_service": "טיפול גדול",
    "minor_service": "טיפול קטן",
    "repair": "תיקון",
    "inspection": "טסט/בדיקה",
    "tire": "צמיגים",
    "other": "אחר",
}


class ServiceEvent(Base):
    __tablename__ = "service_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    odometer: Mapped[Optional[int]] = mapped_column(Integer)
    service_type: Mapped[str] = mapped_column(String(30), default="other")
    garage: Mapped[Optional[str]] = mapped_column(String(120))
    cost: Mapped[Optional[float]] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(8), default="ILS")
    items: Mapped[Optional[list]] = mapped_column(JSON)  # list of action/part strings
    notes: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="manual")  # manual | ocr
    receipt_id: Mapped[Optional[int]] = mapped_column(ForeignKey("receipt.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship(back_populates="service_events")
    receipt: Mapped[Optional["Receipt"]] = relationship(back_populates="service_event")

    @property
    def type_label(self) -> str:
        return SERVICE_TYPES.get(self.service_type, self.service_type)


class FuelLog(Base):
    __tablename__ = "fuel_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    odometer: Mapped[Optional[int]] = mapped_column(Integer)
    liters: Mapped[float] = mapped_column(Float)
    price_total: Mapped[Optional[float]] = mapped_column(Float)
    price_per_liter: Mapped[Optional[float]] = mapped_column(Float)
    station: Mapped[Optional[str]] = mapped_column(String(120))
    full_tank: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship(back_populates="fuel_logs")


OIL_LEVELS = {"ok": "תקין", "low": "חסר", "high": "עודף"}


class OilCheck(Base):
    __tablename__ = "oil_check"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    odometer: Mapped[Optional[int]] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(10), default="ok")  # ok | low | high
    condition: Mapped[Optional[str]] = mapped_column(String(120))
    topped_up: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship(back_populates="oil_checks")

    @property
    def level_label(self) -> str:
        return OIL_LEVELS.get(self.level, self.level)


class MaintenanceSchedule(Base):
    """Manufacturer-recommended service interval for a vehicle."""

    __tablename__ = "maintenance_schedule"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(160))
    interval_km: Mapped[Optional[int]] = mapped_column(Integer)
    interval_months: Mapped[Optional[int]] = mapped_column(Integer)
    last_done_odometer: Mapped[Optional[int]] = mapped_column(Integer)
    last_done_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    vehicle: Mapped[Vehicle] = relationship(back_populates="schedules")


class KnownIssue(Base):
    """Community-reported common failure for a model/year range."""

    __tablename__ = "known_issue"

    id: Mapped[int] = mapped_column(primary_key=True)
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(80))
    year_from: Mapped[Optional[int]] = mapped_column(Integer)
    year_to: Mapped[Optional[int]] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[Optional[str]] = mapped_column(Text)
    trigger_km: Mapped[Optional[int]] = mapped_column(Integer)  # alert when odo passes this
    severity: Mapped[str] = mapped_column(String(20), default="medium")  # low|medium|high
    source: Mapped[Optional[str]] = mapped_column(String(300))


ALERT_STATUS = {
    "upcoming": "מתקרב",
    "due": "נדרש עכשיו",
    "overdue": "באיחור",
    "dismissed": "נדחה",
}


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))  # schedule | issue | state
    title: Mapped[str] = mapped_column(String(220))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="upcoming")
    due_km: Mapped[Optional[int]] = mapped_column(Integer)
    due_date: Mapped[Optional[dt.date]] = mapped_column(Date)
    ref_key: Mapped[str] = mapped_column(String(120), index=True)  # dedupe key
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped[Vehicle] = relationship()

    @property
    def status_label(self) -> str:
        return ALERT_STATUS.get(self.status, self.status)


RECEIPT_STATUS = {
    "pending": "ממתין לפיענוח",
    "parsed": "פוענח - ממתין לאישור",
    "confirmed": "אושר",
    "failed": "פיענוח נכשל",
}


class Receipt(Base):
    __tablename__ = "receipt"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vehicle.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(300))
    content_type: Mapped[Optional[str]] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    parsed_json: Mapped[Optional[dict]] = mapped_column(JSON)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, server_default=func.now())

    vehicle: Mapped[Optional[Vehicle]] = relationship(back_populates="receipts")
    service_event: Mapped[Optional[ServiceEvent]] = relationship(
        back_populates="receipt", uselist=False
    )

    @property
    def status_label(self) -> str:
        return RECEIPT_STATUS.get(self.status, self.status)
