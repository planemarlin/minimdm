from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.core.permissions import get_accessible_schemas, require_schema_access
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
    return {k: v for k, v in cfg.items() if k != "webhooks"}
