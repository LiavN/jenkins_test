from app import notifications
from app.models import Alert, Vehicle


def _vehicle(db, **kw):
    v = Vehicle(make="Toyota", model="Land Cruiser 120", year=2006,
                initial_odometer=200000, license_plate="38-171-14", **kw)
    db.add(v)
    db.commit()
    return v


def _alert(db, vehicle, status, title, detail, ref_key):
    a = Alert(vehicle_id=vehicle.id, source="schedule", title=title,
              detail=detail, status=status, ref_key=ref_key)
    db.add(a)
    db.commit()
    return a


def test_html_summary_first_and_trims_upcoming_detail(db):
    v = _vehicle(db)
    _alert(db, v, "overdue", "החלפת שמן מנוע", "בק״מ ~210,000", "sched:1")
    _alert(db, v, "upcoming", "בדיקת בלמים",
           "שורה ראשונה ארוכה\nשורה שנייה שלא אמורה להופיע במייל", "sched:2")

    html = notifications.build_digest_html(db)
    # Vehicle + actionable alert are present, with the overdue status color.
    assert v.display_name in html
    assert "החלפת שמן מנוע" in html
    assert notifications._STATUS_COLOR["overdue"] in html
    # Upcoming alert title shows, but its multi-line detail is NOT dumped.
    assert "בדיקת בלמים" in html
    assert "שורה שנייה שלא אמורה להופיע" not in html
    # Plate chip rendered.
    assert "38-171-14" in html


def test_text_digest_is_compact(db):
    v = _vehicle(db)
    _alert(db, v, "due", "טיפול 10,000", "טיפול תקופתי\nפירוט ארוך נוסף", "sched:1")

    text = notifications.build_digest(db)
    assert "סיכום:" in text
    assert "טיפול 10,000" in text
    # No multi-line detail paragraphs leaking into the text digest.
    assert "פירוט ארוך נוסף" not in text


def test_empty_state(db):
    _vehicle(db)
    assert "הכל תקין" in notifications.build_digest(db)
    assert "הכל תקין" in notifications.build_digest_html(db)


def test_subject_prefixes_by_severity(db):
    v = _vehicle(db)
    assert notifications.digest_subject(db) == "סיכום התראות אחזקת רכבים"
    _alert(db, v, "due", "טיפול", "", "sched:1")
    assert notifications.digest_subject(db).startswith("⚠️")
    _alert(db, v, "overdue", "שמן", "", "sched:2")
    assert notifications.digest_subject(db).startswith("⛔")


def test_send_digest_noop_without_smtp(db):
    _vehicle(db)
    assert notifications.send_digest(db) is False
