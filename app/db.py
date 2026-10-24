"""Database engine, session, and base model."""
from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()

# Ensure the sqlite directory exists for file-based URLs.
if settings.database_url.startswith("sqlite"):
    # sqlite:////data/garage.db -> /data/garage.db ; sqlite:///./data/garage.db -> ./data/garage.db
    path = settings.database_url.split("sqlite://", 1)[1].lstrip("/")
    if path and settings.database_url.startswith("sqlite:////"):
        path = "/" + path
    db_dir = os.path.dirname(path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency: yield a session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called on startup."""
    from . import models  # noqa: F401  (register models)

    Base.metadata.create_all(bind=engine)
