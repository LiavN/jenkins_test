import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.auth import hash_password
from app.config import INSECURE_SECRET, Settings, require_secure_config
from app.db import Base, get_db
from app.main import app
from app.models import User


# --- config fail-safe ------------------------------------------------------
def test_require_secure_config_rejects_default_secret():
    with pytest.raises(RuntimeError):
        require_secure_config(Settings(secret_key=INSECURE_SECRET, debug=False))


def test_require_secure_config_rejects_empty_secret():
    with pytest.raises(RuntimeError):
        require_secure_config(Settings(secret_key="", debug=False))


def test_require_secure_config_allows_debug_and_real_key():
    require_secure_config(Settings(secret_key=INSECURE_SECRET, debug=True))  # no raise
    require_secure_config(Settings(secret_key="x" * 40, debug=False))  # no raise


# --- security headers ------------------------------------------------------
def test_security_headers_present():
    client = TestClient(app)
    r = client.get("/login")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


# --- login throttling ------------------------------------------------------
def _empty_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_login_lockout_after_max_failures():
    main._LOGIN_FAILS.clear()
    app.dependency_overrides[get_db] = lambda: _empty_session()
    try:
        _run_lockout()
    finally:
        app.dependency_overrides.clear()
        main._LOGIN_FAILS.clear()


def _run_lockout():
    client = TestClient(app)
    email = "lockme@example.com"
    for _ in range(main._LOGIN_MAX):
        r = client.post("/login", data={"email": email, "password": "wrong"},
                        follow_redirects=False)
        assert r.status_code == 401
    # Next attempt is locked out.
    r = client.post("/login", data={"email": email, "password": "wrong"},
                    follow_redirects=False)
    assert r.status_code == 429
    assert "יותר מדי נסיונות" in r.text


# --- change password -------------------------------------------------------
def _logged_in_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(User(name="בדיקה", email="u@example.com",
                     password_hash=hash_password("oldpass1")))
    session.commit()
    app.dependency_overrides[get_db] = lambda: session
    main._LOGIN_FAILS.clear()
    client = TestClient(app)
    r = client.post("/login", data={"email": "u@example.com", "password": "oldpass1"},
                    follow_redirects=False)
    assert r.status_code == 303
    return client, session


def test_change_password_flow():
    try:
        client, _ = _logged_in_client()
        # Wrong current password rejected.
        r = client.post("/account/password",
                        data={"current": "nope", "new": "newpass12", "confirm": "newpass12"})
        assert "הסיסמה הנוכחית שגויה" in r.text
        # Too short rejected.
        r = client.post("/account/password",
                        data={"current": "oldpass1", "new": "short", "confirm": "short"})
        assert "לפחות 8 תווים" in r.text
        # Mismatch rejected.
        r = client.post("/account/password",
                        data={"current": "oldpass1", "new": "newpass12", "confirm": "other123"})
        assert "אינם תואמים" in r.text
        # Success, then old password no longer works and new one does.
        r = client.post("/account/password",
                        data={"current": "oldpass1", "new": "newpass12", "confirm": "newpass12"})
        assert "עודכנה בהצלחה" in r.text
        client.get("/logout")
        main._LOGIN_FAILS.clear()
        bad = client.post("/login", data={"email": "u@example.com", "password": "oldpass1"},
                          follow_redirects=False)
        assert bad.status_code == 401
        good = client.post("/login", data={"email": "u@example.com", "password": "newpass12"},
                           follow_redirects=False)
        assert good.status_code == 303
    finally:
        app.dependency_overrides.clear()


# --- upload hardening ------------------------------------------------------
def test_upload_rejects_bad_type_and_oversize():
    try:
        client, _ = _logged_in_client()
        # Disallowed content type.
        r = client.post("/receipts/upload",
                        files={"file": ("x.txt", b"hello", "text/plain")},
                        data={"vehicle_id": ""})
        assert "סוג קובץ לא נתמך" in r.text
        # Oversize (shrink the cap so the test payload stays small).
        orig = main._MAX_UPLOAD_BYTES
        main._MAX_UPLOAD_BYTES = 4
        try:
            r = client.post("/receipts/upload",
                            files={"file": ("x.png", b"123456789", "image/png")},
                            data={"vehicle_id": ""})
            assert "גדול מדי" in r.text
        finally:
            main._MAX_UPLOAD_BYTES = orig
    finally:
        app.dependency_overrides.clear()
