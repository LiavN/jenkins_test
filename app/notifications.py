"""Email alert summaries over SMTP.

Reuses the idea from the original Jenkins ``emailext`` step: gather the current
alerts and mail a digest. Safe to run when SMTP is unconfigured (no-op).
"""
from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from .config import get_settings
from . import alerts

settings = get_settings()


def build_digest(db: Session) -> str:
    lines = ["שלום,", "", "סיכום התראות אחזקת רכבים:", ""]
    active = alerts.active_alerts(db)
    if not active:
        lines.append("אין התראות פתוחות. הכל תקין ✅")
    else:
        by_vehicle: dict[str, list] = {}
        for a in active:
            by_vehicle.setdefault(a.vehicle.display_name, []).append(a)
        for vehicle_name, items in by_vehicle.items():
            lines.append(f"■ {vehicle_name}")
            for a in items:
                lines.append(f"   [{a.status_label}] {a.title}")
                if a.detail:
                    lines.append(f"      {a.detail}")
            lines.append("")
    lines.append("— מערכת Garage")
    return "\n".join(lines)


def send_digest(db: Session) -> bool:
    """Send the alert digest by email. Returns True if actually sent."""
    body = build_digest(db)
    if not settings.email_enabled or not settings.alert_email_to:
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "סיכום התראות אחזקת רכבים"
    msg["From"] = settings.alert_email_from
    msg["To"] = settings.alert_email_to

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    return True
