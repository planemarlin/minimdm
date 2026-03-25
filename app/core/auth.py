"""Authentication utilities: password hashing, JWT, user table management."""
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from sqlalchemy import MetaData, Table, func, select, text
from sqlalchemy.orm import Session

from app.config import settings

ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode())


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
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


# ---------------------------------------------------------------------------
# Token blocklist
# ---------------------------------------------------------------------------

def ensure_token_blocklist_table(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _system.token_blocklist (
                jti        UUID PRIMARY KEY,
                expires_at TIMESTAMPTZ NOT NULL
            )
        """))
        conn.commit()


def revoke_token(engine, jti: str, expires_at: datetime) -> None:
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO _system.token_blocklist (jti, expires_at) VALUES (:jti, :exp)"
            " ON CONFLICT DO NOTHING"
        ), {"jti": uuid.UUID(jti), "exp": expires_at})
        conn.commit()


def is_token_revoked(engine, jti: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM _system.token_blocklist WHERE jti = :jti"),
            {"jti": uuid.UUID(jti)},
        ).first()
        return row is not None


def cleanup_expired_tokens(engine) -> None:
    """Delete expired entries from the blocklist — called at startup."""
    with engine.connect() as conn:
        conn.execute(text(
            "DELETE FROM _system.token_blocklist WHERE expires_at < NOW()"
        ))
        conn.commit()


# ---------------------------------------------------------------------------
# Password reset tokens
# ---------------------------------------------------------------------------

_RESET_TOKEN_EXPIRE_HOURS = 24


def ensure_password_reset_tokens_table(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _system.password_reset_tokens (
                id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id    UUID NOT NULL,
                token      TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at    TIMESTAMPTZ
            )
        """))
        # Prune expired / used tokens on every startup
        conn.execute(text("""
            DELETE FROM _system.password_reset_tokens
            WHERE expires_at < NOW() OR used_at IS NOT NULL
        """))
        conn.commit()


def create_reset_token(engine, user_id: str) -> tuple[str, datetime]:
    """Create a one-time password reset token. Returns (token, expires_at)."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_EXPIRE_HOURS)
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO _system.password_reset_tokens (user_id, token, expires_at)
            VALUES (:user_id, :token, :expires_at)
        """), {"user_id": uuid.UUID(user_id), "token": token, "expires_at": expires_at})
        conn.commit()
    return token, expires_at


def consume_reset_token(engine, token: str) -> Optional[str]:
    """Validate a reset token and return the user_id string, or None if invalid/expired."""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, user_id FROM _system.password_reset_tokens
            WHERE token = :token
              AND expires_at > NOW()
              AND used_at IS NULL
        """), {"token": token}).mappings().first()
        if not row:
            return None
        conn.execute(text("""
            UPDATE _system.password_reset_tokens
            SET used_at = NOW() WHERE id = :id
        """), {"id": row["id"]})
        conn.commit()
        return str(row["user_id"])


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


def create_user(engine, username: str, password: str, is_admin: bool = False) -> dict:
    tbl = _users_table(engine)
    user_id = uuid.uuid4()
    with Session(engine) as s:
        s.execute(tbl.insert().values(
            id=user_id,
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
        ))
        s.commit()
    return {"id": str(user_id), "username": username, "is_admin": is_admin}


def list_users(engine) -> list[dict]:
    tbl = _users_table(engine)
    with Session(engine) as s:
        rows = s.execute(tbl.select().order_by(tbl.c.created_at)).mappings().all()
        return [
            {
                "id": str(r["id"]),
                "username": r["username"],
                "is_admin": r["is_admin"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ]


def is_user_active(engine, user_id: str) -> bool:
    """Return True if the user exists and is_active. Used by auth middleware."""
    tbl = _users_table(engine)
    with Session(engine) as s:
        row = s.execute(
            select(tbl.c.is_active).where(tbl.c.id == uuid.UUID(user_id))
        ).first()
        return bool(row and row[0])


def get_user_by_id(engine, user_id: str) -> Optional[dict]:
    tbl = _users_table(engine)
    with Session(engine) as s:
        row = s.execute(
            tbl.select().where(tbl.c.id == uuid.UUID(user_id))
        ).mappings().first()
        return dict(row) if row else None


def update_user(engine, user_id: str, *, is_admin: Optional[bool] = None,
                is_active: Optional[bool] = None, password: Optional[str] = None) -> None:
    tbl = _users_table(engine)
    values: dict = {}
    if is_admin is not None:
        values["is_admin"] = is_admin
    if is_active is not None:
        values["is_active"] = is_active
    if password is not None:
        values["password_hash"] = hash_password(password)
    if not values:
        return
    with Session(engine) as s:
        s.execute(tbl.update().where(tbl.c.id == uuid.UUID(user_id)).values(**values))
        s.commit()
