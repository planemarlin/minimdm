from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.schema_loader import load_config, validate_config

router = APIRouter()


@router.get("/schemas")
def list_schemas(request: Request):
    tm = request.app.state.table_manager
    config = tm.get_config()
    result = []
    for schema_name, schema_body in config.get("schemas", {}).items():
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


@router.get("/schemas/{schema}")
def get_schema(schema: str, request: Request):
    tm = request.app.state.table_manager
    config = tm.get_config()
    schema_body = config.get("schemas", {}).get(schema)
    if not schema_body:
        raise HTTPException(404, f"Schema '{schema}' not found")
    return {
        "name": schema,
        "objects": schema_body.get("objects", {}),
    }


@router.get("/schemas/{schema}/objects/{obj}")
def get_object(schema: str, obj: str, request: Request):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")
    return {"schema": schema, "key": obj, **obj_config}


@router.post("/config/reload")
def reload_config(request: Request):
    """Reload config from disk and sync database schema."""
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
    return request.app.state.app_config
