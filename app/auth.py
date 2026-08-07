"""Authentication helpers: password hashing and session user lookup."""
from __future__ import annotations

from typing import Optional

import bcrypt
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def authenticate(db: Session, email: str, password: str) -> Optional[User]:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user and verify_password(password, user.password_hash):
        return user
    return None


def current_user(request: Request, db: Session) -> Optional[User]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    return db.get(User, uid)
