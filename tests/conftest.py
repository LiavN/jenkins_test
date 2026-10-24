import os

# Use an in-memory DB and disable external calls before importing the app.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ANTHROPIC_API_KEY", "")
os.environ.setdefault("SECRET_KEY", "test-secret")
# Tests run over plain HTTP via TestClient; debug relaxes the HTTPS-only cookie.
os.environ.setdefault("DEBUG", "true")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app import models  # noqa: F401  (register tables)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    try:
        yield session
    finally:
        session.close()
