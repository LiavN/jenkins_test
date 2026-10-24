from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (register tables)
from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import User


def _shared_session():
    # StaticPool keeps a single in-memory connection shared across threads,
    # so the TestClient request thread sees the tables and seeded rows.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _login(session):
    app.dependency_overrides[get_db] = lambda: session
    session.add(User(name="בדיקה", email="t@example.com",
                     password_hash=hash_password("pw")))
    session.commit()
    client = TestClient(app)
    r = client.post("/login", data={"email": "t@example.com", "password": "pw"},
                    follow_redirects=False)
    assert r.status_code in (302, 303)
    return client


def test_send_digest_now_reports_off_without_smtp():
    session = _shared_session()
    try:
        client = _login(session)
        # SMTP is unset under tests -> send_digest returns False -> digest=off.
        r = client.post("/alerts/send-digest", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/alerts?digest=off"
        # The follow-up page renders the Hebrew "not configured" banner.
        page = client.get("/alerts?digest=off")
        assert "המייל אינו מוגדר" in page.text
    finally:
        app.dependency_overrides.clear()
        session.close()


def test_send_digest_requires_login():
    session = _shared_session()
    try:
        app.dependency_overrides[get_db] = lambda: session
        client = TestClient(app)
        r = client.post("/alerts/send-digest", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"
    finally:
        app.dependency_overrides.clear()
        session.close()
