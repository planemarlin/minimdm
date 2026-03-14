"""Authentication utilities: password hashing, JWT, user table management."""
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.context import CryptContext
from sqlalchemy import Boolean, Column, DateTime, String, Table, MetaData, func, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session

from app.config import settings

ALGORITHM = "HS256"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_token(user_id: str, username: str, is_admin: bool) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.token_expire_hours)
    payload = {
        "sub": username,
        "user_id": user_id,
        "is_admin": is_admin,
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Users table
# ---------------------------------------------------------------------------

def ensure_users_table(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _system.users (
                id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username    VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                is_admin    BOOLEAN NOT NULL DEFAULT FALSE,
                is_active   BOOLEAN NOT NULL DEFAULT TRUE,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        conn.commit()


def _users_table(engine) -> Table:
    meta = MetaData()
    return Table("users", meta, schema="_system", autoload_with=engine)


def count_users(engine) -> int:
    tbl = _users_table(engine)
    with Session(engine) as s:
        return s.execute(select(func.count()).select_from(tbl)).scalar()


def get_user_by_username(engine, username: str) -> Optional[dict]:
    tbl = _users_table(engine)
    with Session(engine) as s:
        row = s.execute(
            tbl.select().where(tbl.c.username == username)
        ).mappings().first()
        return dict(row) if row else None


def create_user(engine, username: str, password: str, is_admin: bool = False) -> None:
    tbl = _users_table(engine)
    with Session(engine) as s:
        s.execute(tbl.insert().values(
            id=uuid.uuid4(),
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
        ))
        s.commit()
