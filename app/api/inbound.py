import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.import_export import _inbound_upsert
from app.config import settings
from app.core import audit as audit_svc
from app.core.keys import hash_api_key
from app.core.limiter import limiter
from app.database import get_db

router = APIRouter()

_ZERO_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _get_tm(request: Request):
    return request.app.state.table_manager


def _verify_inbound_key(schema: str, obj: str, request: Request, db: Session = Depends(get_db)):
    """Authenticate inbound webhook requests via X-Api-Key header.

    Validates the key against the inbound_keys table, sets a synthetic
    current_user so audit logging captures the source name, then resolves
    the matching inbound_sources config entry for the field_map.
    """
    tm = _get_tm(request)

    if tm.get_object_config(schema, obj) is None:
        raise HTTPException(404, f"Object '{schema}/{obj}' not found.")

    raw_key = request.headers.get("X-Api-Key", "")
    if not raw_key:
        _log_inbound_failed(request, schema, obj, "Missing X-Api-Key header")
        raise HTTPException(401, "Missing X-Api-Key header.")

    key_hash = hash_api_key(raw_key)

    inbound_keys_table = tm.get_inbound_keys_table()
    rows = db.execute(
        select(inbound_keys_table)
        .where(inbound_keys_table.c.schema_name == schema)
        .where(inbound_keys_table.c.is_active.is_(True))
    ).mappings().all()

    matched = None
    for row in rows:
        if hmac.compare_digest(key_hash, row["key_hash"]):
            matched = row
            break

    if matched is None:
        _log_inbound_failed(request, schema, obj, "Invalid or revoked API key")
        raise HTTPException(401, "Invalid or revoked API key.")

    source_name = matched["source_name"]

    # Record last_used_at without failing the request if it errors
    try:
        db.execute(
            inbound_keys_table.update()
            .where(inbound_keys_table.c.id == matched["id"])
            .values(last_used_at=datetime.now(timezone.utc))
        )
        db.flush()
    except Exception:  # nosec B110
        pass

    sources = tm.get_inbound_sources(schema, obj)
    source_config = next((s for s in sources if s["name"] == source_name), None)
    if source_config is None:
        _log_inbound_failed(
            request, schema, obj,
            f"Key authenticated as '{source_name}' but source is not configured for {schema}/{obj}",
            key_id=matched["id"],
        )
        raise HTTPException(
            403,
            f"Source '{source_name}' is not configured for '{schema}/{obj}'."
            " Add an inbound_sources entry to the schema config.",
        )

    request.state.current_user = {"username": f"inbound:{source_name}"}
    request.state.inbound_key_id = matched["id"]
    return source_config


def _log_inbound_failed(request: Request, schema: str, obj: str, reason: str, key_id=None):
    """Log a failed inbound authentication attempt to the audit log. Never raises."""
    try:
        from app.core.network import client_ip as _client_ip
        tm = request.app.state.table_manager
        audit_table = tm.get_audit_table()
        with Session(tm.engine) as s:
            audit_svc.log_change(
                s, audit_table,
                schema_name="_system", object_name="inbound",
                record_id=key_id or _ZERO_UUID,
                action="INBOUND_CALL_FAILED",
                old_values=None,
                new_values={"schema": schema, "object": obj},
                reason=reason,
                user_name=None,
                ip_address=_client_ip(request),
            )
            s.commit()
    except Exception:  # nosec B110 — audit log must never block operations
        pass


def _log_inbound_call(request: Request, source_name: str, schema: str, obj: str, status: str):
    """Log a successful inbound API call to _system/inbound in the audit log. Never raises."""
    try:
        from app.core.network import client_ip as _client_ip
        tm = request.app.state.table_manager
        audit_table = tm.get_audit_table()
        key_id = getattr(request.state, "inbound_key_id", None)
        with Session(tm.engine) as s:
            audit_svc.log_change(
                s, audit_table,
                schema_name="_system", object_name="inbound",
                record_id=key_id,
                action="INBOUND_CALL",
                old_values=None,
                new_values={"schema": schema, "object": obj, "result": status},
                reason=f"Inbound push to {schema}/{obj} — {status}",
                user_name=f"inbound:{source_name}",
                ip_address=_client_ip(request),
            )
            s.commit()
    except Exception:  # nosec B110 — audit log must never block operations
        pass


@router.post("/inbound/{schema}/{obj}")
@limiter.limit("120/minute")
async def receive_inbound(
    schema: str,
    obj: str,
    request: Request,
    source_config: dict = Depends(_verify_inbound_key),
    db: Session = Depends(get_db),
):
    # Enforce body size limit before parsing to prevent memory exhaustion.
    _limit = settings.max_upload_size
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _limit:
        raise HTTPException(413, f"Request body too large (max {_limit // 1024} KB)")
    raw = await request.body()
    if len(raw) > _limit:
        raise HTTPException(413, f"Request body too large (max {_limit // 1024} KB)")
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"Invalid JSON body: {e}") from e
    if not isinstance(body, dict):
        raise HTTPException(400, "Request body must be a JSON object")

    tm = _get_tm(request)

    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}/{obj}' not found.")

    field_map = source_config["field_map"]
    mapped = {field_map[k]: v for k, v in body.items() if k in field_map}

    source_name = source_config["name"]
    reason = f"Inbound webhook from {source_name}"

    status, record_id = _inbound_upsert(
        db=db,
        table=table,
        history_table=history_table,
        audit_table=audit_table,
        source_name=source_name,
        mapped_data=mapped,
        reason=reason,
        request=request,
        schema=schema,
        obj=obj,
        match_key=source_config.get("match_key"),
    )
    db.commit()
    _log_inbound_call(request, source_name, schema, obj, status)

    status_code = 201 if status == "created" else 200
    return JSONResponse({"status": status, "id": str(record_id)}, status_code=status_code)
