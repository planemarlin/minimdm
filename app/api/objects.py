import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.core import audit as audit_svc
from app.database import get_db

router = APIRouter()


def _get_tm(request: Request):
    return request.app.state.table_manager


def _serialize_row(row: dict) -> dict:
    result = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# List / search records
# ---------------------------------------------------------------------------

@router.get("/records/{schema}/{obj}")
def list_records(
    schema: str,
    obj: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    q = select(table)
    if not include_deleted:
        q = q.where(table.c._deleted_at.is_(None))

    if search:
        text_cols = [
            c for c in table.c
            if isinstance(c.type, String) and not c.name.startswith("_")
        ]
        if text_cols:
            q = q.where(or_(*[c.ilike(f"%{search}%") for c in text_cols]))

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(
        q.order_by(table.c._created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings().all()

    return {
        "records": [_serialize_row(dict(r)) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


# ---------------------------------------------------------------------------
# Get single record
# ---------------------------------------------------------------------------

@router.get("/records/{schema}/{obj}/{record_id}")
def get_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    row = db.execute(
        select(table).where(table.c._id == rid).where(table.c._deleted_at.is_(None))
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Record not found")

    return _serialize_row(dict(row))


# ---------------------------------------------------------------------------
# Create record
# ---------------------------------------------------------------------------

@router.post("/records/{schema}/{obj}", status_code=201)
def create_record(
    schema: str,
    obj: str,
    request: Request,
    body: dict,
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    now = datetime.now(timezone.utc)
    record_id = uuid.uuid4()
    values = _filter_columns(body, table)
    values["_id"] = record_id
    values["_created_at"] = now
    values["_updated_at"] = now

    db.execute(table.insert().values(**values))

    full_row = {**values}
    audit_svc.write_history(
        db, history_table, full_row, version=1, action="INSERT", valid_from=now,
        reason=body.get("_reason"), user_name=None
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, record_id, "INSERT",
        old_values=None, new_values=audit_svc._serialize(values),
        reason=body.get("_reason"), ip_address=_client_ip(request)
    )
    db.commit()

    return {"id": str(record_id)}


# ---------------------------------------------------------------------------
# Update record
# ---------------------------------------------------------------------------

@router.put("/records/{schema}/{obj}/{record_id}")
def update_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    body: dict,
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    existing = db.execute(
        select(table).where(table.c._id == rid).where(table.c._deleted_at.is_(None))
    ).mappings().first()

    if not existing:
        raise HTTPException(404, "Record not found")

    old_values = dict(existing)
    now = datetime.now(timezone.utc)

    # Close current history version
    current_version_row = db.execute(
        select(history_table).where(history_table.c._id == rid).where(history_table.c._valid_to.is_(None))
    ).mappings().first()
    current_version = current_version_row["_version"] if current_version_row else 0

    if current_version_row:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == current_version_row["_history_id"])
            .values(_valid_to=now)
        )

    updates = _filter_columns(body, table)
    updates["_updated_at"] = now

    db.execute(table.update().where(table.c._id == rid).values(**updates))

    new_values = {**old_values, **updates}
    audit_svc.write_history(
        db, history_table, new_values, version=current_version + 1,
        action="UPDATE", valid_from=now,
        reason=body.get("_reason"), user_name=None
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "UPDATE",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=body.get("_reason"), ip_address=_client_ip(request)
    )
    db.commit()

    return {"id": record_id}


# ---------------------------------------------------------------------------
# Delete record (soft delete)
# ---------------------------------------------------------------------------

@router.delete("/records/{schema}/{obj}/{record_id}", status_code=204)
def delete_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    existing = db.execute(
        select(table).where(table.c._id == rid).where(table.c._deleted_at.is_(None))
    ).mappings().first()

    if not existing:
        raise HTTPException(404, "Record not found")

    now = datetime.now(timezone.utc)

    current_version_row = db.execute(
        select(history_table).where(history_table.c._id == rid).where(history_table.c._valid_to.is_(None))
    ).mappings().first()
    current_version = current_version_row["_version"] if current_version_row else 0

    if current_version_row:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == current_version_row["_history_id"])
            .values(_valid_to=now)
        )

    old_values = dict(existing)
    db.execute(table.update().where(table.c._id == rid).values(_deleted_at=now, _updated_at=now))

    audit_svc.write_history(
        db, history_table, old_values, version=current_version + 1,
        action="DELETE", valid_from=now, valid_to=now,
        reason=reason, user_name=None
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "DELETE",
        old_values=audit_svc._serialize(old_values), new_values=None,
        reason=reason, ip_address=_client_ip(request)
    )
    db.commit()


# ---------------------------------------------------------------------------
# Record history
# ---------------------------------------------------------------------------

@router.get("/records/{schema}/{obj}/{record_id}/history")
def get_record_history(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        history_table = tm.get_history_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    rows = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .order_by(history_table.c._version.desc())
    ).mappings().all()

    return [_serialize_row(dict(r)) for r in rows]


# ---------------------------------------------------------------------------
# Revert to a previous version
# ---------------------------------------------------------------------------

@router.post("/records/{schema}/{obj}/{record_id}/revert/{version}", status_code=200)
def revert_record(
    schema: str,
    obj: str,
    record_id: str,
    version: int,
    request: Request,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    target = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._version == version)
    ).mappings().first()

    if not target:
        raise HTTPException(404, f"Version {version} not found for record")

    existing = db.execute(
        select(table).where(table.c._id == rid)
    ).mappings().first()

    if not existing:
        raise HTTPException(404, "Record not found")

    old_values = dict(existing)
    now = datetime.now(timezone.utc)

    # Close current history
    current = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._valid_to.is_(None))
    ).mappings().first()
    current_version = current["_version"] if current else 0

    if current:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == current["_history_id"])
            .values(_valid_to=now)
        )

    # Build values from historical snapshot - only user columns
    revert_values: dict = {}
    obj_config = tm.get_object_config(schema, obj) or {}
    for attr_key, attr_body in obj_config.get("attributes", {}).items():
        if attr_body.get("reference"):
            col = f"{attr_key}_id"
        else:
            col = attr_key
        if col in dict(target):
            revert_values[col] = dict(target)[col]

    parent = obj_config.get("parent")
    if parent:
        pk = f"_{parent}_id"
        if pk in dict(target):
            revert_values[pk] = dict(target)[pk]

    revert_values["_updated_at"] = now
    revert_values["_deleted_at"] = None

    db.execute(table.update().where(table.c._id == rid).values(**revert_values))

    new_values = {**old_values, **revert_values}
    audit_svc.write_history(
        db, history_table, new_values, version=current_version + 1,
        action="REVERT", valid_from=now,
        reason=reason or f"Reverted to version {version}", user_name=None
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "REVERT",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=reason or f"Reverted to version {version}",
        ip_address=_client_ip(request)
    )
    db.commit()

    return {"id": record_id, "reverted_to_version": version}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _filter_columns(body: dict, table) -> dict:
    """Keep only keys that map to actual table columns (excluding system columns)."""
    col_names = {c.name for c in table.c if not c.name.startswith("_")}
    return {k: v for k, v in body.items() if k in col_names}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
