import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit as audit_svc
from app.core.auth import create_token, get_user_by_username, verify_password

router = APIRouter()

COOKIE_NAME = "access_token"

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
    except Exception:
        pass  # Never block auth on audit failure


@router.post("/auth/login")
async def login(request: Request):
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    engine = request.app.state.table_manager.engine
    user = get_user_by_username(engine, username)

    if not user or not verify_password(password, user["password_hash"]):
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
        samesite="lax",
        max_age=settings.token_expire_hours * 3600,
    )
    return response


@router.post("/auth/logout")
async def logout(request: Request):
    user = getattr(request.state, "current_user", None)
    if user:
        _log_auth(request, "LOGOUT", uuid.UUID(user["user_id"]), user["username"])
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/auth/me")
async def me(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"username": user["username"], "is_admin": user["is_admin"]}
