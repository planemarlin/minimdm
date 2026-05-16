import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit as audit_svc
from app.core.auth import (
    DUMMY_HASH,
    consume_reset_token,
    create_token,
    get_user_by_id,
    get_user_by_username,
    revoke_token,
    update_user,
    verify_password,
)
from app.core.limiter import limiter

router = APIRouter()

COOKIE_NAME = "access_token"


class LoginRequest(BaseModel):
    username: str
    password: str

_ZERO_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _log_auth(request: Request, action: str, user_id: uuid.UUID, username: str, reason: str = None):
    try:
        tm = request.app.state.table_manager
        audit_table = tm.get_audit_table()
        engine = tm.engine
        with Session(engine) as s:
            audit_svc.log_change(
                s, audit_table,
                schema_name="_system", object_name="users",
                record_id=user_id, action=action,
                old_values=None, new_values=None,
                reason=reason, user_name=username,
                ip_address=_client_ip(request),
            )
            s.commit()
    except Exception:  # nosec B110 — audit log must never block auth
        pass  # Never block auth on audit failure


@router.post("/auth/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    engine = request.app.state.table_manager.engine
    user = get_user_by_username(engine, username)

    # Always run bcrypt regardless of whether the user exists to prevent
    # timing-based username enumeration.
    password_ok = verify_password(password, user["password_hash"] if user else DUMMY_HASH)
    if not user or not password_ok:
        _log_auth(request, "LOGIN_FAILED", _ZERO_UUID, username,
                  reason=f"Failed login attempt for '{username}'")
        raise HTTPException(401, "Invalid username or password")

    if not user["is_active"]:
        _log_auth(request, "LOGIN_FAILED", user["id"], username,
                  reason=f"Login attempt for inactive account '{username}'")
        raise HTTPException(401, "Account is disabled. Contact an administrator.")

    token = create_token(str(user["id"]), user["username"], user["is_admin"])
    _log_auth(request, "LOGIN", user["id"], user["username"])

    response = JSONResponse({"username": user["username"], "is_admin": user["is_admin"]})
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.secure_cookie,
        max_age=settings.token_expire_hours * 3600,
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    user = getattr(request.state, "current_user", None)
    if user:
        jti = user.get("jti")
        exp = user.get("exp")
        if jti and exp:
            engine = request.app.state.table_manager.engine
            expires_at = datetime.fromtimestamp(exp, tz=timezone.utc)
            revoke_token(engine, jti, expires_at)
        _log_auth(request, "LOGOUT", uuid.UUID(user["user_id"]), user["username"])
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.post("/auth/reset-password")
async def reset_password(request: Request):
    data = await request.json()
    token = (data.get("token") or "").strip()
    password = data.get("password") or ""

    if not token:
        raise HTTPException(400, "Token is required")
    if len(password) < 12:
        raise HTTPException(400, "Password must be at least 12 characters")

    engine = request.app.state.table_manager.engine
    user_id = consume_reset_token(engine, token)
    if not user_id:
        raise HTTPException(400, "Reset link is invalid or has expired")

    user = get_user_by_id(engine, user_id)
    update_user(engine, user_id, password=password)
    _log_auth(request, "USER_PASSWORD_CHANGED", uuid.UUID(user_id), user["username"],
              reason=f"Password reset via reset link for '{user['username']}'")
    return {"status": "ok"}


@router.get("/auth/me")
async def me(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"username": user["username"], "is_admin": user["is_admin"]}
