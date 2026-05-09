import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit as audit_svc
from app.core.permissions import require_publish_access, require_schema_access
from app.core.webhooks import fire_webhooks
from app.database import get_db

router = APIRouter()


def _get_tm(request: Request):
    return request.app.state.table_manager


def _check_reason(reason: Optional[str], obj_config: Optional[dict]) -> None:
    if obj_config and obj_config.get("require_change_reason") and not (reason or "").strip():
        raise HTTPException(422, "A reason for this change is required for this object.")


def _get_username(request: Request) -> Optional[str]:
    user = getattr(request.state, "current_user", None)
    return user["username"] if user else None


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

@router.get(
    "/records/{schema}/{obj}",
    summary="List master records",
    description=(
        "Returns active (golden) records by default. "
        "Use `?state=` to query drafts, retired, or all records."
    ),
)
def list_records(
    schema: str,
    obj: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    state: str = Query("active", pattern="^(active|draft|retired|all)$"),
    parent_id: Optional[str] = Query(None),
    ref_field: Optional[str] = Query(None),
    ref_id: Optional[str] = Query(None),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    source_system: Optional[str] = Query(None, description="Filter by source system name"),
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema)
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    obj_cfg = tm.get_object_config(schema, obj) or {}

    q = select(table)
    if not include_deleted:
        q = q.where(table.c._deleted_at.is_(None))
    if state != "all":
        q = q.where(table.c._state == state)

    if parent_id:
        parent_key = obj_cfg.get("parent")
        if parent_key:
            try:
                pid = uuid.UUID(parent_id)
                q = q.where(table.c[f"_{parent_key}_id"] == pid)
            except (ValueError, KeyError):
                pass

    if ref_field and ref_id:
        try:
            rid = uuid.UUID(ref_id)
            q = q.where(table.c[f"{ref_field}_id"] == rid)
        except (ValueError, KeyError):
            pass

    if search:
        text_cols = [
            c for c in table.c
            if isinstance(c.type, String) and not c.name.startswith("_")
        ]
        if text_cols:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(or_(*[c.ilike(f"%{escaped}%") for c in text_cols]))

    if source_system and hasattr(table.c, "_source_system"):
        q = q.where(table.c._source_system == source_system)

    user_col_names = {c.name for c in table.c if not c.name.startswith("_")}
    if sort_by and sort_by in user_col_names:
        sort_col = table.c[sort_by]
    else:
        attrs = obj_cfg.get("attributes", {})
        first_non_ref = next(
            (k for k, v in attrs.items() if not v.get("reference")), None
        )
        sort_col = (
            table.c[first_non_ref]
            if first_non_ref and first_non_ref in user_col_names
            else table.c._created_at
        )

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(
        q.order_by(sort_col.asc() if sort_dir == "asc" else sort_col.desc())
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
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema)
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    q = select(table).where(table.c._id == rid)
    if not include_deleted:
        q = q.where(table.c._deleted_at.is_(None))
    row = db.execute(q).mappings().first()

    if not row:
        raise HTTPException(404, "Record not found")

    return _serialize_row(dict(row))


# ---------------------------------------------------------------------------
# Create record
# ---------------------------------------------------------------------------

@router.post(
    "/records/{schema}/{obj}",
    status_code=201,
    summary="Create a master record",
    description=(
        "Creates a new active (golden) record. "
        "If the object has `requires_draft: true` configured, "
        "the record is created as a draft instead."
    ),
)
def create_record(
    schema: str,
    obj: str,
    request: Request,
    body: dict,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema, write=True)
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    obj_config = tm.get_object_config(schema, obj) or {}
    _check_reason(body.get("_reason"), obj_config)

    now = datetime.now(timezone.utc)
    record_id = uuid.uuid4()
    values = _filter_columns(body, table)
    values["_id"] = record_id
    values["_created_at"] = now
    values["_updated_at"] = now
    initial_state = "draft" if obj_config.get("requires_draft") else "active"
    values["_state"] = initial_state

    try:
        db.execute(table.insert().values(**values))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(422, _integrity_error_message(e)) from e

    full_row = {**values}
    audit_svc.write_history(
        db, history_table, full_row, version=1, action="INSERT", valid_from=now,
        reason=body.get("_reason"), user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, record_id, "INSERT",
        old_values=None, new_values=audit_svc._serialize(values),
        reason=body.get("_reason"), ip_address=_client_ip(request),
        user_name=_get_username(request)
    )
    db.commit()

    if initial_state == "active":
        background_tasks.add_task(
            fire_webhooks, tm.get_config(), "record.created",
            schema, obj, str(record_id), _get_username(request)
        )

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
    require_schema_access(request, schema, write=True)
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

    _check_reason(body.get("_reason"), tm.get_object_config(schema, obj))

    now = datetime.now(timezone.utc)
    record_state = existing["_state"] if "_state" in existing.keys() else "active"

    if record_state == "active":
        # Draft-copy-on-edit: leave the active record unchanged; create/update a draft alongside.
        existing_draft = db.execute(
            select(table)
            .where(table.c._draft_of_id == rid)
            .where(table.c._state == "draft")
            .where(table.c._deleted_at.is_(None))
        ).mappings().first()

        user_updates = _filter_columns(body, table)

        if existing_draft:
            # Update the already-existing draft in place
            draft_id = existing_draft["_id"]
            draft_updates = {**user_updates, "_updated_at": now}
            try:
                db.execute(table.update().where(table.c._id == draft_id).values(**draft_updates))
            except IntegrityError as e:
                db.rollback()
                raise HTTPException(422, _integrity_error_message(e)) from e

            current_version_row = db.execute(
                select(history_table)
                .where(history_table.c._id == draft_id)
                .where(history_table.c._valid_to.is_(None))
                .with_for_update()
            ).mappings().first()
            current_version = current_version_row["_version"] if current_version_row else 0
            if current_version_row:
                db.execute(
                    history_table.update()
                    .where(history_table.c._history_id == current_version_row["_history_id"])
                    .values(_valid_to=now)
                )
            new_draft_values = {**dict(existing_draft), **draft_updates}
            audit_svc.write_history(
                db, history_table, new_draft_values, version=current_version + 1,
                action="UPDATE", valid_from=now,
                reason=body.get("_reason"), user_name=_get_username(request)
            )
            audit_svc.log_change(
                db, audit_table, schema, obj, draft_id, "UPDATE",
                old_values=audit_svc._serialize(dict(existing_draft)),
                new_values=audit_svc._serialize(new_draft_values),
                reason=body.get("_reason"), ip_address=_client_ip(request),
                user_name=_get_username(request)
            )
        else:
            # Create a new draft record alongside the active one
            draft_id = uuid.uuid4()
            draft_values = {
                k: v for k, v in dict(existing).items()
                if k not in ("_id", "_created_at", "_updated_at", "_deleted_at",
                             "_state", "_draft_of_id")
            }
            draft_values.update(user_updates)
            draft_values["_id"] = draft_id
            draft_values["_created_at"] = now
            draft_values["_updated_at"] = now
            draft_values["_deleted_at"] = None
            draft_values["_state"] = "draft"
            draft_values["_draft_of_id"] = rid

            try:
                db.execute(table.insert().values(**draft_values))
            except IntegrityError as e:
                db.rollback()
                raise HTTPException(422, _integrity_error_message(e)) from e

            audit_svc.write_history(
                db, history_table, draft_values, version=1,
                action="INSERT", valid_from=now,
                reason=body.get("_reason"), user_name=_get_username(request)
            )
            audit_svc.log_change(
                db, audit_table, schema, obj, draft_id, "DRAFT_CREATED",
                old_values=None, new_values=audit_svc._serialize(draft_values),
                reason=body.get("_reason"), ip_address=_client_ip(request),
                user_name=_get_username(request)
            )

        db.commit()
        return {"id": str(draft_id), "draft": True}

    # Draft or retired — update in place
    old_values = dict(existing)

    current_version_row = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._valid_to.is_(None))
        .with_for_update()
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

    try:
        db.execute(table.update().where(table.c._id == rid).values(**updates))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(422, _integrity_error_message(e)) from e

    new_values = {**old_values, **updates}
    audit_svc.write_history(
        db, history_table, new_values, version=current_version + 1,
        action="UPDATE", valid_from=now,
        reason=body.get("_reason"), user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "UPDATE",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=body.get("_reason"), ip_address=_client_ip(request),
        user_name=_get_username(request)
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
    require_schema_access(request, schema, write=True)
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

    _check_reason(reason, tm.get_object_config(schema, obj))

    now = datetime.now(timezone.utc)

    current_version_row = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._valid_to.is_(None))
        .with_for_update()
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
        reason=reason, user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "DELETE",
        old_values=audit_svc._serialize(old_values), new_values=None,
        reason=reason, ip_address=_client_ip(request),
        user_name=_get_username(request)
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
    require_schema_access(request, schema)
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
    require_schema_access(request, schema, write=True)
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

    if existing.get("_state") == "retired":
        require_publish_access(request, schema)

    _check_reason(reason, tm.get_object_config(schema, obj))

    old_values = dict(existing)
    now = datetime.now(timezone.utc)

    # Close current history — use latest version by number because a DELETE
    # row has _valid_to set, so _valid_to IS NULL would miss it.
    current = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .order_by(history_table.c._version.desc())
        .limit(1)
        .with_for_update()
    ).mappings().first()
    current_version = current["_version"] if current else 0

    open_row = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._valid_to.is_(None))
    ).mappings().first()
    if open_row:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == open_row["_history_id"])
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
        reason=reason or f"Reverted to version {version}", user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "REVERT",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=reason or f"Reverted to version {version}",
        ip_address=_client_ip(request),
        user_name=_get_username(request)
    )
    db.commit()

    return {"id": record_id, "reverted_to_version": version}


# ---------------------------------------------------------------------------
# Publish draft → active
# ---------------------------------------------------------------------------

@router.post(
    "/records/{schema}/{obj}/{record_id}/publish",
    status_code=200,
    summary="Publish draft to master",
    description=(
        "Promotes a draft record to the active golden record. "
        "The draft's data replaces the master and the draft is removed. "
        "Requires Publisher or Admin."
    ),
)
def publish_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Promote a draft record to active.

    The record_id must be a draft (state='draft') that has a _draft_of_id pointing
    to the active record. The active record is updated with the draft's data and the
    draft is soft-deleted. The active record's stable _id is preserved.
    Requires Publisher or Admin.
    """
    require_publish_access(request, schema)
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    try:
        draft_id = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    draft = db.execute(
        select(table)
        .where(table.c._id == draft_id)
        .where(table.c._state == "draft")
        .where(table.c._deleted_at.is_(None))
    ).mappings().first()
    if not draft:
        raise HTTPException(404, "Draft record not found (must be a draft with state='draft')")

    master_id = draft["_draft_of_id"]
    _check_reason(reason, tm.get_object_config(schema, obj))
    now = datetime.now(timezone.utc)

    if not master_id:
        # New-record draft (created via requires_draft or imported as draft with no master).
        # Promote it directly to active in place — no master to merge into.
        current_version_row = db.execute(
            select(history_table)
            .where(history_table.c._id == draft_id)
            .where(history_table.c._valid_to.is_(None))
            .with_for_update()
        ).mappings().first()
        current_version = current_version_row["_version"] if current_version_row else 0
        if current_version_row:
            db.execute(
                history_table.update()
                .where(history_table.c._history_id == current_version_row["_history_id"])
                .values(_valid_to=now)
            )
        try:
            db.execute(
                table.update()
                .where(table.c._id == draft_id)
                .values(_state="active", _updated_at=now)
            )
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(422, _integrity_error_message(e)) from e

        new_values = {**dict(draft), "_state": "active", "_updated_at": now}
        audit_svc.write_history(
            db, history_table, new_values, version=current_version + 1,
            action="PUBLISH", valid_from=now,
            reason=reason or "Published from draft", user_name=_get_username(request)
        )
        audit_svc.log_change(
            db, audit_table, schema, obj, draft_id, "PUBLISH",
            old_values=audit_svc._serialize(dict(draft)),
            new_values=audit_svc._serialize(new_values),
            reason=reason or "Published from draft", ip_address=_client_ip(request),
            user_name=_get_username(request)
        )
        db.commit()
        background_tasks.add_task(
            fire_webhooks, tm.get_config(), "record.created",
            schema, obj, str(draft_id), _get_username(request)
        )
        return {"id": str(draft_id), "published": True}

    active = db.execute(
        select(table)
        .where(table.c._id == master_id)
        .where(table.c._state == "active")
        .where(table.c._deleted_at.is_(None))
    ).mappings().first()
    if not active:
        raise HTTPException(404, "Linked active record not found")

    # Build the set of user-writable column names (no system cols)
    user_col_names = {
        c.name for c in table.c
        if c.name not in _SYSTEM_COLS and not c.name.startswith("_")
    }
    # Also include parent FK columns (e.g. _division_id)
    parent_fk_cols = {
        c.name for c in table.c
        if c.name.startswith("_") and c.name not in _SYSTEM_COLS
        and c.name not in ("_state", "_draft_of_id", "_created_by")
    }

    # Copy draft's user columns onto the active record
    update_vals: dict = {}
    for col_name in user_col_names | parent_fk_cols:
        if col_name in draft.keys():
            update_vals[col_name] = draft[col_name]
    update_vals["_updated_at"] = now

    # Increment active record's history
    current_version_row = db.execute(
        select(history_table)
        .where(history_table.c._id == master_id)
        .where(history_table.c._valid_to.is_(None))
        .with_for_update()
    ).mappings().first()
    current_version = current_version_row["_version"] if current_version_row else 0
    if current_version_row:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == current_version_row["_history_id"])
            .values(_valid_to=now)
        )

    old_active_values = dict(active)
    try:
        db.execute(table.update().where(table.c._id == master_id).values(**update_vals))
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(422, _integrity_error_message(e)) from e

    new_active_values = {**old_active_values, **update_vals}
    audit_svc.write_history(
        db, history_table, new_active_values, version=current_version + 1,
        action="PUBLISH", valid_from=now,
        reason=reason or "Published from draft", user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, master_id, "PUBLISH",
        old_values=audit_svc._serialize(old_active_values),
        new_values=audit_svc._serialize(new_active_values),
        reason=reason or "Published from draft", ip_address=_client_ip(request),
        user_name=_get_username(request)
    )

    # Soft-delete the draft (it's been superseded)
    db.execute(
        table.update()
        .where(table.c._id == draft_id)
        .values(_deleted_at=now, _updated_at=now)
    )

    db.commit()
    background_tasks.add_task(
        fire_webhooks, tm.get_config(), "record.published",
        schema, obj, str(master_id), _get_username(request)
    )
    return {"id": str(master_id), "published": True}


# ---------------------------------------------------------------------------
# Retire active → retired
# ---------------------------------------------------------------------------

@router.post(
    "/records/{schema}/{obj}/{record_id}/retire",
    status_code=200,
    summary="Retire a master record",
    description=(
        "Transitions an active golden record to retired. "
        "The record is preserved for history and audit but excluded from default responses. "
        "Requires Publisher or Admin."
    ),
)
def retire_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Transition an active record to the retired state. Requires Publisher or Admin."""
    require_publish_access(request, schema)
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

    retire_obj_config = tm.get_object_config(schema, obj) or {}
    if not retire_obj_config.get("allow_retire", True):
        raise HTTPException(
            422,
            f"Object '{obj}' does not allow retirement (allow_retire: false in config)."
        )

    existing = db.execute(
        select(table)
        .where(table.c._id == rid)
        .where(table.c._state == "active")
        .where(table.c._deleted_at.is_(None))
    ).mappings().first()
    if not existing:
        raise HTTPException(404, "Active record not found (only active records can be retired)")

    _check_reason(reason, retire_obj_config)

    now = datetime.now(timezone.utc)
    old_values = dict(existing)

    current_version_row = db.execute(
        select(history_table)
        .where(history_table.c._id == rid)
        .where(history_table.c._valid_to.is_(None))
        .with_for_update()
    ).mappings().first()
    current_version = current_version_row["_version"] if current_version_row else 0
    if current_version_row:
        db.execute(
            history_table.update()
            .where(history_table.c._history_id == current_version_row["_history_id"])
            .values(_valid_to=now)
        )

    db.execute(
        table.update().where(table.c._id == rid).values(_state="retired", _updated_at=now)
    )
    new_values = {**old_values, "_state": "retired", "_updated_at": now}
    audit_svc.write_history(
        db, history_table, new_values, version=current_version + 1,
        action="RETIRE", valid_from=now,
        reason=reason or "Retired", user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "RETIRE",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=reason or "Retired", ip_address=_client_ip(request),
        user_name=_get_username(request)
    )
    db.commit()
    background_tasks.add_task(
        fire_webhooks, tm.get_config(), "record.retired",
        schema, obj, str(rid), _get_username(request)
    )
    return {"id": str(rid), "retired": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYSTEM_COLS = {"_id", "_created_at", "_updated_at", "_deleted_at", "_version",
               "_state", "_draft_of_id"}


def _filter_columns(body: dict, table) -> dict:
    """Keep only keys that map to writable table columns and coerce to the right type.

    System columns are excluded; parent FK columns (e.g. _division_id) are
    included because they start with _ but are legitimate user-settable fields.
    """
    col_types = {c.name: c.type for c in table.c}
    col_names = {c.name for c in table.c if c.name not in _SYSTEM_COLS}
    result = {}
    for k, v in body.items():
        if k not in col_names:
            continue
        if v is None or v == "":
            result[k] = None
            continue
        col_type = col_types.get(k)
        if isinstance(col_type, Boolean):
            result[k] = v if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes", "t")
        elif isinstance(col_type, Integer):
            try:
                result[k] = int(v)
            except (ValueError, TypeError):
                result[k] = v
        elif isinstance(col_type, Numeric):
            try:
                result[k] = Decimal(str(v))
            except InvalidOperation:
                result[k] = v
        elif isinstance(col_type, DateTime):
            if isinstance(v, str):
                try:
                    result[k] = datetime.fromisoformat(v)
                except ValueError:
                    result[k] = v
            else:
                result[k] = v
        else:
            result[k] = v
    return result


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _integrity_error_message(exc: IntegrityError) -> str:
    """Extract a human-readable message from a SQLAlchemy IntegrityError."""
    orig = getattr(exc, "orig", None)
    if orig is not None:
        msg = str(orig).splitlines()[0]
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            return f"A record with this value already exists: {msg}"
        if "foreign key" in msg.lower():
            return f"Referenced record does not exist: {msg}"
        return msg
    return str(exc)
