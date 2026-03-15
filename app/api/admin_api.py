"""Admin-only API endpoints for user management."""
from fastapi import APIRouter, HTTPException, Request

from app.core.auth import create_user, get_user_by_id, list_users, update_user
from app.core.permissions import delete_permission, get_user_permissions, set_permission

router = APIRouter()


def _require_admin(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user or not user.get("is_admin"):
        raise HTTPException(403, "Admin access required")


@router.get("/admin/users")
def get_users(request: Request):
    _require_admin(request)
    engine = request.app.state.table_manager.engine
    return list_users(engine)


@router.post("/admin/users", status_code=201)
async def add_user(request: Request):
    _require_admin(request)
    data = await request.json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    is_admin = bool(data.get("is_admin", False))

    if not username or not password:
        raise HTTPException(400, "Username and password are required")

    engine = request.app.state.table_manager.engine
    try:
        user = create_user(engine, username, password, is_admin=is_admin)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, f"Username '{username}' already exists")
        raise HTTPException(500, "Failed to create user")
    return user


@router.patch("/admin/users/{user_id}")
async def patch_user(user_id: str, request: Request):
    _require_admin(request)
    data = await request.json()

    engine = request.app.state.table_manager.engine
    existing = get_user_by_id(engine, user_id)
    if not existing:
        raise HTTPException(404, "User not found")

    # Prevent the last admin from losing admin rights or being deactivated
    current_user = request.state.current_user
    if str(existing["id"]) == current_user["user_id"]:
        if data.get("is_admin") is False or data.get("is_active") is False:
            raise HTTPException(400, "Cannot remove admin rights or deactivate your own account")

    update_user(
        engine, user_id,
        is_admin=data.get("is_admin"),
        is_active=data.get("is_active"),
        password=data.get("password") or None,
    )
    return {"status": "ok"}


@router.get("/admin/users/{user_id}/permissions")
def get_permissions(user_id: str, request: Request):
    _require_admin(request)
    engine = request.app.state.table_manager.engine
    if not get_user_by_id(engine, user_id):
        raise HTTPException(404, "User not found")
    return get_user_permissions(engine, user_id)


@router.put("/admin/users/{user_id}/permissions/{schema_name}", status_code=200)
async def upsert_permission(user_id: str, schema_name: str, request: Request):
    _require_admin(request)
    data = await request.json()
    can_read = bool(data.get("can_read", True))
    can_write = bool(data.get("can_write", False))
    engine = request.app.state.table_manager.engine
    if not get_user_by_id(engine, user_id):
        raise HTTPException(404, "User not found")
    set_permission(engine, user_id, schema_name, can_read=can_read, can_write=can_write)
    return {"status": "ok"}


@router.delete("/admin/users/{user_id}/permissions/{schema_name}", status_code=204)
def remove_permission(user_id: str, schema_name: str, request: Request):
    _require_admin(request)
    engine = request.app.state.table_manager.engine
    if not get_user_by_id(engine, user_id):
        raise HTTPException(404, "User not found")
    delete_permission(engine, user_id, schema_name)
