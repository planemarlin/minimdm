from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.auth import create_token, get_user_by_username, verify_password
from app.config import settings

router = APIRouter()

COOKIE_NAME = "access_token"


@router.post("/auth/login")
async def login(request: Request):
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    engine = request.app.state.table_manager.engine
    user = get_user_by_username(engine, username)

    if not user or not user["is_active"] or not verify_password(password, user["password_hash"]):
        raise HTTPException(401, "Invalid username or password")

    token = create_token(str(user["id"]), user["username"], user["is_admin"])

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
async def logout():
    response = JSONResponse({"status": "ok"})
    response.delete_cookie(COOKIE_NAME)
    return response


@router.get("/auth/me")
async def me(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return {"username": user["username"], "is_admin": user["is_admin"]}
