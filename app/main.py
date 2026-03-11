import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.core.schema_loader import load_config, validate_config
from app.core.table_manager import TableManager
from app.database import engine

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tm = TableManager(engine)
    # Always ensure the audit log table exists
    tm._ensure_audit_log_table()
    tm.metadata.create_all(engine)

    app.state.table_manager = tm
    app.state.app_config = {}

    config_path = Path(settings.config_file)
    if config_path.exists():
        try:
            config = load_config(str(config_path))
            errors = validate_config(config)
            if errors:
                for e in errors:
                    logger.warning("Config validation: %s", e)
            else:
                tm.sync_schema(config)
                app.state.app_config = config
                logger.info("Loaded config from %s", config_path)
        except Exception as exc:
            logger.warning("Failed to load config: %s", exc)
    else:
        logger.info(
            "No config file found at %s. Serving empty schema.", config_path
        )

    yield

    engine.dispose()


app = FastAPI(
    title="miniMDM",
    description="A minimal lightweight Master Data Management application",
    version=settings.app_version,
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# -----------------------------------------------------------------
# API routers
# -----------------------------------------------------------------
from app.api import audit_api, import_export, objects, schemas_api  # noqa: E402

app.include_router(objects.router, prefix="/api", tags=["Records"])
app.include_router(schemas_api.router, prefix="/api", tags=["Schemas"])
app.include_router(import_export.router, prefix="/api", tags=["Import / Export"])
app.include_router(audit_api.router, prefix="/api", tags=["Audit"])


# -----------------------------------------------------------------
# Web UI routes
# -----------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    tm = request.app.state.table_manager
    schemas_list = []
    for schema_name in tm.list_schemas():
        schemas_list.append(
            {"name": schema_name, "objects": tm.list_objects(schema_name)}
        )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}", response_class=HTMLResponse)
async def object_list(request: Request, schema: str, obj: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    schemas_list = [
        {"name": s, "objects": tm.list_objects(s)} for s in tm.list_schemas()
    ]
    return templates.TemplateResponse(
        "objects/list.html",
        {
            "request": request,
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/new", response_class=HTMLResponse)
async def object_new(request: Request, schema: str, obj: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    schemas_list = [
        {"name": s, "objects": tm.list_objects(s)} for s in tm.list_schemas()
    ]
    return templates.TemplateResponse(
        "objects/form.html",
        {
            "request": request,
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record": None,
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}", response_class=HTMLResponse)
async def object_detail(request: Request, schema: str, obj: str, record_id: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    schemas_list = [
        {"name": s, "objects": tm.list_objects(s)} for s in tm.list_schemas()
    ]
    return templates.TemplateResponse(
        "objects/detail.html",
        {
            "request": request,
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}/edit", response_class=HTMLResponse)
async def object_edit(request: Request, schema: str, obj: str, record_id: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    schemas_list = [
        {"name": s, "objects": tm.list_objects(s)} for s in tm.list_schemas()
    ]
    return templates.TemplateResponse(
        "objects/form.html",
        {
            "request": request,
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "record": None,  # JS will load via API
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}/history", response_class=HTMLResponse)
async def object_history(request: Request, schema: str, obj: str, record_id: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    schemas_list = [
        {"name": s, "objects": tm.list_objects(s)} for s in tm.list_schemas()
    ]
    return templates.TemplateResponse(
        "objects/history.html",
        {
            "request": request,
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "schemas": schemas_list,
            "app_name": settings.app_name,
        },
    )
