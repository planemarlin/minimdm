import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.core.auth import (
    cleanup_expired_tokens,
    count_users,
    create_user,
    decode_token,
    ensure_token_blocklist_table,
    ensure_users_table,
    is_token_revoked,
    is_user_active,
)
from app.core.limiter import limiter
from app.core.permissions import ensure_permissions_table, get_accessible_schemas
from app.core.schema_loader import load_config, validate_config
from app.core.table_manager import TableManager
from app.database import engine

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)

_DEFAULT_SECRET_KEY = "change-me-in-production-use-a-long-random-string"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.secret_key == _DEFAULT_SECRET_KEY:
        logger.error(
            "SECRET_KEY is set to the default placeholder value. "
            "JWTs can be trivially forged. Set SECRET_KEY in your .env file before deploying."
        )

    # Validate database connectivity before accepting requests
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("Cannot connect to the database: %s", exc)
        raise RuntimeError(f"Database connection failed at startup: {exc}") from exc

    tm = TableManager(engine)

    # Create _system schema first, then system tables
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS _system"))
        conn.commit()

    tm._ensure_audit_log_table()
    ensure_users_table(engine)
    ensure_token_blocklist_table(engine)
    cleanup_expired_tokens(engine)
    ensure_permissions_table(engine)
    tm.metadata.create_all(engine)

    # Auto-create first admin if credentials are configured and no users exist
    if settings.admin_username and settings.admin_password:
        if count_users(engine) == 0:
            create_user(engine, settings.admin_username, settings.admin_password, is_admin=True)
            logger.info("Created initial admin user: %s", settings.admin_username)

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

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
templates.env.policies["json.dumps_kwargs"] = {"sort_keys": False}

# -----------------------------------------------------------------
# Auth middleware
# -----------------------------------------------------------------

_PUBLIC_PATHS = {"/login", "/api/auth/login", "/health", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _PUBLIC_PATHS or path.startswith("/static"):
            request.state.current_user = None
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        else:
            token = request.cookies.get("access_token")

        user = None
        if token:
            payload = decode_token(token)
            if payload:
                user_id = payload.get("user_id")
                jti = payload.get("jti")
                engine = request.app.state.table_manager.engine
                if user_id and is_user_active(engine, user_id):
                    if not jti or not is_token_revoked(engine, jti):
                        user = {
                            "user_id": user_id,
                            "username": payload.get("sub"),
                            "is_admin": payload.get("is_admin", False),
                            "jti": jti,
                            "exp": payload.get("exp"),
                        }

        request.state.current_user = user

        if user is None:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)
            next_url = request.url.path
            if request.url.query:
                next_url += f"?{request.url.query}"
            return RedirectResponse(
                url=f"/login?next={next_url}", status_code=303
            )

        return await call_next(request)


app.add_middleware(AuthMiddleware)

# -----------------------------------------------------------------
# API routers
# -----------------------------------------------------------------
from app.api import (  # noqa: E402
    admin_api,
    audit_api,
    auth_api,
    import_export,
    objects,
    schemas_api,
)

# Import/export must be registered before objects to avoid /export being
# matched by the /{record_id} wildcard route.
app.include_router(auth_api.router, prefix="/api", tags=["Auth"])
app.include_router(admin_api.router, prefix="/api", tags=["Admin"])
app.include_router(import_export.router, prefix="/api", tags=["Import / Export"])
app.include_router(objects.router, prefix="/api", tags=["Records"])
app.include_router(schemas_api.router, prefix="/api", tags=["Schemas"])
app.include_router(audit_api.router, prefix="/api", tags=["Audit"])


# -----------------------------------------------------------------
# Health check
# -----------------------------------------------------------------


@app.get("/health", tags=["Health"])
async def health(request: Request):
    try:
        engine = request.app.state.table_manager.engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            {"status": "unhealthy", "detail": str(exc)}, status_code=503
        )
    return {"status": "ok", "version": settings.app_version}


# -----------------------------------------------------------------
# Web UI routes
# -----------------------------------------------------------------

def _sidebar_schemas(request: Request) -> list[dict]:
    """Build the schemas list for the sidebar, filtered by user permissions."""
    tm = request.app.state.table_manager
    user = getattr(request.state, "current_user", None)
    all_schemas = tm.list_schemas()
    if user and user.get("is_admin"):
        visible = all_schemas
    elif user:
        accessible = get_accessible_schemas(tm.engine, user["user_id"])
        visible = [s for s in all_schemas if s in accessible]
    else:
        visible = []
    return [{"name": s, "objects": tm.list_objects(s)} for s in visible]



@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request, "auth/login.html", {"app_name": settings.app_name}
    )


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user or not user.get("is_admin"):
        return templates.TemplateResponse(
            request, "error.html",
            {"message": "Admin access required", "app_name": settings.app_name},
            status_code=403,
        )
    tm = request.app.state.table_manager
    return templates.TemplateResponse(
        request, "admin/users.html",
        {
            "schemas": _sidebar_schemas(request),
            "all_schemas": tm.list_schemas(),
            "app_name": settings.app_name,
        },
    )


@app.get("/admin/audit", response_class=HTMLResponse)
async def admin_audit(request: Request):
    user = getattr(request.state, "current_user", None)
    if not user or not user.get("is_admin"):
        return templates.TemplateResponse(
            request, "error.html",
            {"message": "Admin access required", "app_name": settings.app_name},
            status_code=403,
        )
    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    tm = request.app.state.table_manager
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "schemas": _sidebar_schemas(request),
            "any_schemas_configured": bool(tm.list_schemas()),
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}", response_class=HTMLResponse)
async def object_list(request: Request, schema: str, obj: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "objects/list.html",
        {
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/new", response_class=HTMLResponse)
async def object_new(request: Request, schema: str, obj: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "objects/form.html",
        {
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": None,
            "record": None,
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}", response_class=HTMLResponse)
async def object_detail(request: Request, schema: str, obj: str, record_id: str):
    from app.core.permissions import check_permission

    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    user = getattr(request.state, "current_user", None)
    if user and user.get("is_admin"):
        can_write = True
    elif user:
        can_write = check_permission(tm.engine, user["user_id"], schema, write=True)
    else:
        can_write = False
    return templates.TemplateResponse(
        request,
        "objects/detail.html",
        {
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "can_write": can_write,
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}/edit", response_class=HTMLResponse)
async def object_edit(request: Request, schema: str, obj: str, record_id: str):
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "objects/form.html",
        {
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "record": None,  # JS will load via API
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )


@app.get("/{schema}/{obj}/{record_id}/history", response_class=HTMLResponse)
async def object_history(request: Request, schema: str, obj: str, record_id: str):
    from app.core.permissions import check_permission

    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if not obj_config:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": f"Object '{schema}.{obj}' not found", "app_name": settings.app_name},
            status_code=404,
        )
    user = getattr(request.state, "current_user", None)
    if user and user.get("is_admin"):
        can_write = True
    elif user:
        can_write = check_permission(tm.engine, user["user_id"], schema, write=True)
    else:
        can_write = False
    return templates.TemplateResponse(
        request,
        "objects/history.html",
        {
            "schema": schema,
            "obj": obj,
            "obj_config": obj_config,
            "record_id": record_id,
            "can_write": can_write,
            "schemas": _sidebar_schemas(request),
            "app_name": settings.app_name,
        },
    )
