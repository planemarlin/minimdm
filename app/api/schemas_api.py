from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from app.config import settings
from app.core.permissions import (
    get_accessible_schemas,
    get_publishable_schemas,
    get_user_permissions,
    require_schema_access,
)
from app.core.schema_loader import load_config, validate_config

router = APIRouter()


@router.get(
    "/schemas",
    summary="List MDM schemas",
    description=(
        "Returns all schemas accessible to the current user, "
        "each with their MDM object definitions."
    ),
)
def list_schemas(request: Request):
    tm = request.app.state.table_manager
    config = tm.get_config()
    user = getattr(request.state, "current_user", None)
    is_admin = user and user.get("is_admin")
    if not is_admin and user:
        accessible = get_accessible_schemas(tm.engine, user["user_id"])
    else:
        accessible = None  # admins see all

    result = []
    for schema_name, schema_body in config.get("schemas", {}).items():
        if accessible is not None and schema_name not in accessible:
            continue
        objects = schema_body.get("objects", {})
        result.append(
            {
                "name": schema_name,
                "object_count": len(objects),
                "objects": [
                    {
                        "key": k,
                        "name": v.get("name", k),
                        "description": v.get("description", ""),
                    }
                    for k, v in objects.items()
                ],
            }
        )
    return result


@router.get(
    "/schemas/{schema}",
    summary="Get schema definition",
    description="Returns the MDM object definitions for a single schema.",
)
def get_schema(schema: str, request: Request):
    require_schema_access(request, schema)
    tm = request.app.state.table_manager
    config = tm.get_config()
    schema_body = config.get("schemas", {}).get(schema)
    if not schema_body:
        raise HTTPException(404, f"Schema '{schema}' not found")
    return {
        "name": schema,
        "objects": schema_body.get("objects", {}),
    }


@router.get(
    "/schemas/{schema}/objects/{obj}",
    summary="Get MDM object definition",
    description="Returns the attribute schema and configuration for a single MDM object type.",
)
def get_object(schema: str, obj: str, request: Request):
    require_schema_access(request, schema)
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")
    return {"schema": schema, "key": obj, **obj_config}


@router.post("/config/reload")
def reload_config(request: Request):
    """Reload config from disk and sync database schema."""
    user = getattr(request.state, "current_user", None)
    if not user or not user.get("is_admin"):
        raise HTTPException(403, "Admin access required")
    config_path = Path(settings.config_file)
    if not config_path.exists():
        raise HTTPException(404, f"Config file not found: {settings.config_file}")

    try:
        config = load_config(str(config_path))
    except Exception as e:
        raise HTTPException(400, f"Failed to parse config: {e}")

    errors = validate_config(config)
    if errors:
        raise HTTPException(422, {"errors": errors})

    tm = request.app.state.table_manager
    tm.sync_schema(config)
    request.app.state.app_config = config

    return {"status": "ok", "message": "Config reloaded successfully"}


@router.get("/config")
def get_config(request: Request):
    cfg = request.app.state.app_config
    result = {k: v for k, v in cfg.items() if k != "webhooks"}
    user = getattr(request.state, "current_user", None)
    if not (user and user.get("is_admin")):
        # Same visibility rule as GET /api/schemas: non-admins only see schemas
        # they hold a read permission for.
        tm = request.app.state.table_manager
        accessible = get_accessible_schemas(tm.engine, user["user_id"]) if user else set()
        result["schemas"] = {
            name: body for name, body in cfg.get("schemas", {}).items() if name in accessible
        }
    return result


@router.get("/pending-count")
def pending_draft_count(request: Request):
    """Return the number of pending draft records the user can publish.

    Counts drafts in schemas where the user has publish access (all schemas for
    admins); everyone else gets 0. Used by the Pending badge in the top bar.
    """
    tm = request.app.state.table_manager
    user = getattr(request.state, "current_user", None)
    if not user:
        return {"total": 0}

    if user.get("is_admin"):
        publishable = None
    else:
        publishable = get_publishable_schemas(tm.engine, user["user_id"])
        if not publishable:
            return {"total": 0}

    selects = []
    for schema_name in tm.list_schemas():
        if publishable is not None and schema_name not in publishable:
            continue
        for obj in tm.list_objects(schema_name):
            try:
                table = tm.get_table(schema_name, obj["key"])
            except KeyError:
                continue
            selects.append(
                select(func.count().label("n"))
                .select_from(table)
                .where(table.c._state == "draft")
                .where(table.c._deleted_at.is_(None))
            )
    if not selects:
        return {"total": 0}
    with Session(tm.engine) as db:
        total = sum(n for (n,) in db.execute(union_all(*selects)).all())
    return {"total": total}


@router.get(
    "/object-counts",
    summary="Record counts per object",
    description=(
        "Returns the number of active (golden) records for every object in the schemas "
        "the current user can read. Users with publish access to a schema (and admins) "
        "also get the number of pending drafts per object. Soft-deleted records are "
        "never counted."
    ),
)
def object_counts(request: Request):
    """Counts for the sidebar and the home page cards.

    Shape: ``{"schemas": {schema: {object: {"active": n, "pending": n}}}}`` — the
    ``pending`` key is present only where the user may publish.
    """
    tm = request.app.state.table_manager
    user = getattr(request.state, "current_user", None)
    if not user:
        return {"schemas": {}}

    if user.get("is_admin"):
        readable = set(tm.list_schemas())
        publishable = readable
    else:
        perms = get_user_permissions(tm.engine, user["user_id"])
        readable = {p["schema_name"] for p in perms if p["can_read"]}
        publishable = {p["schema_name"] for p in perms if p["can_publish"]}

    selects = []
    for schema_name in tm.list_schemas():
        if schema_name not in readable:
            continue
        for obj in tm.list_objects(schema_name):
            try:
                table = tm.get_table(schema_name, obj["key"])
            except KeyError:
                continue
            selects.append(
                select(
                    literal(schema_name).label("schema"),
                    literal(obj["key"]).label("object"),
                    func.count().filter(table.c._state == "active").label("active"),
                    func.count().filter(table.c._state == "draft").label("pending"),
                )
                .select_from(table)
                .where(table.c._deleted_at.is_(None))
            )

    result: dict[str, dict[str, dict[str, int]]] = {}
    if selects:
        with Session(tm.engine) as db:
            rows = db.execute(union_all(*selects)).all()
        for schema_name, obj_key, active, pending in rows:
            counts = {"active": active}
            if schema_name in publishable:
                counts["pending"] = pending
            result.setdefault(schema_name, {})[obj_key] = counts
    return {"schemas": result}
