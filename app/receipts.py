"""Scanned-receipt parsing via Claude Vision.

Uploads a garage receipt image/PDF page, asks Claude to return structured JSON,
and stores the raw result on the Receipt row. The user then confirms/edits the
fields before a ServiceEvent is created (human-in-the-loop).
"""
from __future__ import annotations

import base64
import json
from typing import Optional

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Receipt

settings = get_settings()

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

PROMPT = """אתה עוזר שמפענח קבלות וחשבוניות ממוסך רכב בישראל (בעברית).
חלץ מהתמונה את הפרטים והחזר JSON תקין בלבד, ללא טקסט נוסף, במבנה:
{
  "date": "YYYY-MM-DD או null",
  "odometer": מספר קילומטראז' או null,
  "garage": "שם המוסך או null",
  "service_type": "אחד מ: oil_change, major_service, minor_service, repair, inspection, tire, other",
  "items": ["פעולה או חלק 1", "פעולה או חלק 2"],
  "cost": מספר סכום כולל או null,
  "currency": "ILS כברירת מחדל",
  "notes": "הערות חופשיות או null"
}
אם שדה לא ברור, החזר null. אל תמציא נתונים."""


def _media_type(content_type: Optional[str]) -> str:
    if content_type in SUPPORTED_IMAGE_TYPES:
        return content_type
    return "image/jpeg"


def parse_image_bytes(data: bytes, content_type: Optional[str]) -> dict:
    """Call Claude Vision on raw image bytes and return the parsed dict.

    Raises RuntimeError if Vision is not configured or the response is unusable.
    """
    if not settings.vision_enabled:
        raise RuntimeError("פיענוח אוטומטי כבוי (חסר ANTHROPIC_API_KEY).")

    # Imported lazily so the app runs without the SDK/key in dev.
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    b64 = base64.standard_b64encode(data).decode("utf-8")
    message = client.messages.create(
        model=settings.vision_model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _media_type(content_type),
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )
    text = "".join(block.text for block in message.content if block.type == "text").strip()
    return _extract_json(text)


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of the model response."""
    text = text.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError("לא התקבל JSON תקין מהפיענוח.")
    return json.loads(text[start : end + 1])


def parse_receipt(db: Session, receipt: Receipt, data: bytes) -> Receipt:
    """Parse a stored receipt and update its status/parsed_json in place."""
    try:
        parsed = parse_image_bytes(data, receipt.content_type)
        receipt.parsed_json = parsed
        receipt.status = "parsed"
        receipt.error = None
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        receipt.status = "failed"
        receipt.error = str(exc)
    db.commit()
    return receipt
