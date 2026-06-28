"""Admin-only API endpoints for user management."""
import re
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit as audit_svc
from app.core.auth import create_reset_token, create_user, get_user_by_id, list_users, update_user
from app.core.keys import hash_api_key
from app.core.permissions import delete_permission, get_user_permissions, set_permission

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

router = APIRouter()


def _require_admin(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user or not user.get("is_admin"):
        raise HTTPException(403, "Admin access required")


def _client_ip(request: Request) -> str:
    from app.core.network import client_ip
    return client_ip(request)


def _log_admin(request: Request, action: str, target_user_id: uuid.UUID, reason: str = None):
    """Write an admin action entry to the audit log. Never raises."""
    try:
        actor = request.state.current_user
        tm = request.app.state.table_manager
        audit_table = tm.get_audit_table()
        with Session(tm.engine) as s:
            audit_svc.log_change(
                s, audit_table,
                schema_name="_system", object_name="users",
                record_id=target_user_id, action=action,
                old_values=None, new_values=None,
                reason=reason, user_name=actor["username"],
                ip_address=_client_ip(request),
            )
            s.commit()
    except Exception:  # nosec B110 — audit log must never block operations
        pass


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
    if len(password) < 12:
        raise HTTPException(400, "Password must be at least 12 characters")

    engine = request.app.state.table_manager.engine
    try:
        user = create_user(engine, username, password, is_admin=is_admin)
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, f"Username '{username}' already exists")
        raise HTTPException(500, "Failed to create user")
    role = "admin" if is_admin else "user"
    _log_admin(request, "USER_CREATED", uuid.UUID(user["id"]),
               reason=f"Created {role} account '{username}'")
    return user


@router.patch("/admin/users/{user_id}")
async def patch_user(user_id: str, request: Request):
    _require_admin(request)
    data = await request.json()

    engine = request.app.state.table_manager.engine
    existing = get_user_by_id(engine, user_id)
    if not existing:
        raise HTTPException(404, "User not found")

    if data.get("password") and len(data["password"]) < 12:
        raise HTTPException(400, "Password must be at least 12 characters")

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
    target_uuid = existing["id"]
    target_name = existing["username"]
    if "is_active" in data:
        action = "USER_ACTIVATED" if data["is_active"] else "USER_DEACTIVATED"
        verb = action.lower().replace("_", " ")
        _log_admin(request, action, target_uuid, reason=f"Account '{target_name}' {verb}")
    if "is_admin" in data:
        role = "admin" if data["is_admin"] else "user"
        _log_admin(request, "USER_ROLE_CHANGED", target_uuid,
                   reason=f"Role of '{target_name}' changed to {role}")
    if data.get("password"):
        _log_admin(request, "USER_PASSWORD_CHANGED", target_uuid,
                   reason=f"Password changed for '{target_name}'")
    return {"status": "ok"}


@router.post("/admin/users/{user_id}/reset-link")
def generate_reset_link(user_id: str, request: Request):
    _require_admin(request)
    engine = request.app.state.table_manager.engine
    target = get_user_by_id(engine, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    token, expires_at = create_reset_token(engine, user_id)
    _log_admin(request, "PASSWORD_RESET_LINK_CREATED", uuid.UUID(user_id),
               reason=f"Password reset link generated for '{target['username']}'")
    base_url = str(request.base_url).rstrip("/")
    return {
        "reset_url": f"{base_url}/reset-password?token={token}",
        "expires_at": expires_at.isoformat(),
    }


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
    can_publish = bool(data.get("can_publish", False))
    engine = request.app.state.table_manager.engine
    target = get_user_by_id(engine, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    set_permission(engine, user_id, schema_name, can_read=can_read, can_write=can_write,
                   can_publish=can_publish)
    target_name = target["username"]
    if not can_read and not can_write and not can_publish:
        _log_admin(request, "PERMISSION_REVOKED", uuid.UUID(user_id),
                   reason=f"Revoked access to schema '{schema_name}' from '{target_name}'")
    else:
        perms = []
        if can_read:
            perms.append("read")
        if can_write:
            perms.append("write")
        if can_publish:
            perms.append("publish")
        _log_admin(request, "PERMISSION_GRANTED", uuid.UUID(user_id),
                   reason=f"Granted {'+'.join(perms)} on schema '{schema_name}' to '{target_name}'")
    return {"status": "ok"}


@router.delete("/admin/users/{user_id}/permissions/{schema_name}", status_code=204)
def remove_permission(user_id: str, schema_name: str, request: Request):
    _require_admin(request)
    engine = request.app.state.table_manager.engine
    target = get_user_by_id(engine, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    delete_permission(engine, user_id, schema_name)
    _log_admin(request, "PERMISSION_REVOKED", uuid.UUID(user_id),
               reason=f"Revoked access to schema '{schema_name}' from '{target['username']}'")


# ------------------------------------------------------------------
# Inbound API key management
# ------------------------------------------------------------------

def _serialize_key_row(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "schema_name": row["schema_name"],
        "source_name": row["source_name"],
        "key_prefix": row["key_prefix"],
        "description": row["description"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "last_used_at": row["last_used_at"].isoformat() if row["last_used_at"] else None,
        "is_active": row["is_active"],
    }


@router.get("/admin/inbound-keys")
def list_inbound_keys(request: Request):
    _require_admin(request)
    tm = request.app.state.table_manager
    table = tm.get_inbound_keys_table()
    with Session(tm.engine) as db:
        rows = db.execute(
            select(table).order_by(table.c.created_at.desc())
        ).mappings().all()
    return [_serialize_key_row(dict(r)) for r in rows]


@router.get("/admin/inbound-keys/sources")
def list_inbound_sources(request: Request):
    """Return all configured inbound_sources entries from the loaded config."""
    _require_admin(request)
    tm = request.app.state.table_manager
    result = []
    for schema_name in tm.list_schemas():
        for obj in tm.list_objects(schema_name):
            obj_config = tm.get_object_config(schema_name, obj["key"])
            for src in (obj_config or {}).get("inbound_sources", []):
                result.append({
                    "schema_name": schema_name,
                    "object_name": obj["key"],
                    "source_name": src["name"],
                })
    return result


@router.post("/admin/inbound-keys", status_code=201)
async def create_inbound_key(request: Request):
    _require_admin(request)
    data = await request.json()
    schema_name = (data.get("schema_name") or "").strip()
    source_name = (data.get("source_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not schema_name or not source_name:
        raise HTTPException(400, "schema_name and source_name are required")
    if not _IDENTIFIER_RE.match(source_name):
        raise HTTPException(
            400,
            "source_name must be a valid identifier "
            "(letters, digits, underscores; must start with a letter or underscore)",
        )

    tm = request.app.state.table_manager
    if schema_name not in tm.list_schemas():
        raise HTTPException(404, f"Schema '{schema_name}' not found")

    raw_key = secrets.token_urlsafe(32)
    key_hash = hash_api_key(raw_key)
    key_prefix = raw_key[:8]
    key_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    table = tm.get_inbound_keys_table()
    with Session(tm.engine) as db:
        db.execute(table.insert().values(
            id=key_id,
            schema_name=schema_name,
            source_name=source_name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            description=description,
            created_at=now,
            last_used_at=None,
            is_active=True,
        ))
        db.commit()

    _log_admin(request, "INBOUND_KEY_CREATED", key_id,
               reason=f"Inbound key created for source '{source_name}' in schema '{schema_name}'")

    return {
        "id": str(key_id),
        "schema_name": schema_name,
        "source_name": source_name,
        "key_prefix": key_prefix,
        "description": description,
        "created_at": now.isoformat(),
        "key": raw_key,
    }


@router.delete("/admin/inbound-keys/{key_id}", status_code=204)
def revoke_inbound_key(key_id: str, request: Request):
    _require_admin(request)
    tm = request.app.state.table_manager
    table = tm.get_inbound_keys_table()
    try:
        key_uuid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(400, "Invalid key ID")
    with Session(tm.engine) as db:
        row = db.execute(
            select(table).where(table.c.id == key_uuid)
        ).mappings().first()
        if not row:
            raise HTTPException(404, "Inbound key not found")
        db.execute(
            table.update().where(table.c.id == key_uuid).values(is_active=False)
        )
        db.commit()
    prefix = row["key_prefix"]
    src = row["source_name"]
    _log_admin(request, "INBOUND_KEY_REVOKED", key_uuid,
               reason=f"Inbound key '{prefix}...' for source '{src}' revoked")
