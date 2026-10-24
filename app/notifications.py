"""Email alert digest over SMTP.

Builds a concise, summary-first digest of the current maintenance alerts and
mails it. A styled HTML part is paired with a slim plain-text fallback
(``multipart/alternative``). Safe to run when SMTP is unconfigured (no-op).
"""
from __future__ import annotations

import datetime as dt
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from .config import get_settings
from . import alerts

settings = get_settings()

# Status palette, mirrored from app/static/styles.css so the mail matches the UI.
_STATUS_COLOR = {
    "overdue": "#dc2626",
    "due": "#ea580c",
    "upcoming": "#ca8a04",
}
_STATUS_LABEL = {
    "overdue": "באיחור",
    "due": "נדרש עכשיו",
    "upcoming": "מתקרב",
}
# Severities that justify showing a line of detail in the digest.
_ACTIONABLE = ("overdue", "due")


def _counts(active: list) -> dict[str, int]:
    out = {"overdue": 0, "due": 0, "upcoming": 0}
    for a in active:
        if a.status in out:
            out[a.status] += 1
    return out


def _by_vehicle(active: list) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for a in active:
        grouped.setdefault(a.vehicle.display_name, []).append(a)
    return grouped


def _first_line(text: str | None) -> str:
    """First non-empty line of a possibly multi-line detail field."""
    if not text:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


# ---------------------------------------------------------------------------
# Plain-text fallback (summary-first, no detail dump)
# ---------------------------------------------------------------------------
def build_digest(db: Session) -> str:
    today = dt.date.today().isoformat()
    lines = [f"מוסך הבית — סיכום אחזקה ({today})", ""]
    active = alerts.active_alerts(db)
    if not active:
        lines.append("אין התראות פתוחות. הכל תקין ✅")
        lines.append("")
        lines.append("— מערכת מוסך הבית")
        return "\n".join(lines)

    c = _counts(active)
    lines.append(
        f"סיכום: {c['overdue']} באיחור · {c['due']} נדרש עכשיו · {c['upcoming']} מתקרב"
    )
    lines.append("")
    for vehicle_name, items in _by_vehicle(active).items():
        lines.append(f"■ {vehicle_name}")
        for a in items:
            lines.append(f"   • [{_STATUS_LABEL.get(a.status, a.status_label)}] {a.title}")
        lines.append("")
    lines.append("— מערכת מוסך הבית")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Styled HTML part
# ---------------------------------------------------------------------------
def _chip(label: str, count: int, color: str) -> str:
    muted = count == 0
    bg = "#f1f5f9" if muted else color
    fg = "#94a3b8" if muted else "#ffffff"
    return (
        f'<td style="padding:0 4px;">'
        f'<div style="background:{bg};color:{fg};border-radius:10px;'
        f'padding:10px 6px;text-align:center;font-family:Arial,Helvetica,sans-serif;">'
        f'<div style="font-size:22px;font-weight:700;line-height:1;">{count}</div>'
        f'<div style="font-size:11px;margin-top:4px;">{html.escape(label)}</div>'
        f"</div></td>"
    )


def _alert_row(a) -> str:
    color = _STATUS_COLOR.get(a.status, "#64748b")
    label = _STATUS_LABEL.get(a.status, a.status_label)
    pill = (
        f'<span style="display:inline-block;background:{color};color:#fff;'
        f'border-radius:999px;padding:2px 10px;font-size:11px;white-space:nowrap;">'
        f"{html.escape(label)}</span>"
    )
    title = f'<span style="font-weight:700;color:#0f172a;">{html.escape(a.title)}</span>'
    detail_html = ""
    if a.status in _ACTIONABLE:
        detail = _first_line(a.detail)
        if detail:
            detail_html = (
                f'<div style="color:#64748b;font-size:13px;margin-top:3px;">'
                f"{html.escape(detail)}</div>"
            )
    return (
        f'<tr><td style="padding:8px 0;border-bottom:1px solid #e2e8f0;'
        f'border-right:3px solid {color};padding-right:10px;">'
        f'<div>{pill}&nbsp;{title}</div>{detail_html}</td></tr>'
    )


def _vehicle_block(name: str, items: list) -> str:
    rows = "".join(_alert_row(a) for a in items)
    # Plate (if any) shown as a small chip next to the name.
    plate = ""
    if items and getattr(items[0].vehicle, "license_plate", None):
        plate = (
            f'<span style="background:#fde047;color:#000;border-radius:6px;'
            f'padding:1px 8px;font-size:12px;font-weight:700;margin-right:8px;">'
            f"{html.escape(items[0].vehicle.license_plate)}</span>"
        )
    return (
        f'<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;'
        f'padding:14px 16px;margin-bottom:12px;">'
        f'<div style="font-size:16px;font-weight:700;color:#0f172a;margin-bottom:6px;">'
        f"{html.escape(name)}{plate}</div>"
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;">{rows}</table>'
        f"</div>"
    )


def build_digest_html(db: Session) -> str:
    today = dt.date.today().isoformat()
    active = alerts.active_alerts(db)

    head = (
        '<div style="font-size:20px;font-weight:700;color:#0f766e;">מוסך הבית</div>'
        f'<div style="color:#64748b;font-size:13px;margin-top:2px;">סיכום אחזקה · {today}</div>'
    )

    if not active:
        body = (
            '<div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;'
            'padding:24px 16px;text-align:center;">'
            '<div style="font-size:16px;color:#16a34a;font-weight:700;">הכל תקין ✅</div>'
            '<div style="color:#64748b;font-size:13px;margin-top:4px;">אין התראות פתוחות.</div>'
            "</div>"
        )
    else:
        c = _counts(active)
        summary = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;margin:14px 0;"><tr>'
            + _chip("באיחור", c["overdue"], _STATUS_COLOR["overdue"])
            + _chip("נדרש עכשיו", c["due"], _STATUS_COLOR["due"])
            + _chip("מתקרב", c["upcoming"], _STATUS_COLOR["upcoming"])
            + "</tr></table>"
        )
        blocks = "".join(
            _vehicle_block(name, items) for name, items in _by_vehicle(active).items()
        )
        body = summary + blocks

    cta = ""
    if settings.app_url:
        url = html.escape(settings.app_url, quote=True)
        cta = (
            f'<div style="text-align:center;margin:18px 0 6px;">'
            f'<a href="{url}" style="display:inline-block;background:#0f766e;color:#fff;'
            f'text-decoration:none;border-radius:8px;padding:10px 20px;font-size:14px;'
            f'font-weight:700;">פתח את מוסך הבית »</a></div>'
        )

    return (
        '<!doctype html><html lang="he" dir="rtl"><head>'
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        "</head>"
        '<body style="margin:0;background:#f1f5f9;padding:20px 0;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td align="center">'
        '<div style="max-width:600px;width:100%;padding:0 16px;font-family:Arial,Helvetica,sans-serif;'
        'text-align:right;">'
        f"{head}{body}{cta}"
        '<div style="color:#94a3b8;font-size:12px;margin-top:16px;">— מערכת מוסך הבית</div>'
        "</div></td></tr></table></body></html>"
    )


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def digest_subject(db: Session) -> str:
    base = "סיכום התראות אחזקת רכבים"
    c = _counts(alerts.active_alerts(db))
    if c["overdue"]:
        return f"⛔ {base}"
    if c["due"]:
        return f"⚠️ {base}"
    return base


def send_digest(db: Session) -> bool:
    """Send the alert digest by email. Returns True if actually sent."""
    if not settings.email_enabled or not settings.alert_email_to:
        return False

    text_body = build_digest(db)
    html_body = build_digest_html(db)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = digest_subject(db)
    msg["From"] = settings.alert_email_from
    msg["To"] = settings.alert_email_to
    # Plain part first, HTML last: clients render the last supported part.
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
    return True
