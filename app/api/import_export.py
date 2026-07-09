import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import Boolean, DateTime, Integer, Numeric, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.core import audit as audit_svc
from app.core.limiter import limiter
from app.core.permissions import check_permission, require_schema_access
from app.database import get_db

logger = logging.getLogger(__name__)
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
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get(
    "/records/{schema}/{obj}/export",
    summary="Export master records",
    description=(
        "Exports MDM records in CSV, TSV, or JSON format. "
        "Defaults to master (golden) records; use `?state=` to export draft candidates "
        "or retired records."
    ),
)
def export_records(
    schema: str,
    obj: str,
    request: Request,
    format: str = Query("csv", pattern="^(csv|tsv|json)$"),
    state: str = Query("active", pattern="^(active|draft|retired|all)$"),
    limit: Optional[int] = Query(None, ge=1, description="Maximum number of rows to export"),
    offset: int = Query(0, ge=0, description="Number of rows to skip"),
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema)
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    base_query = select(table).where(table.c._deleted_at.is_(None)).order_by(table.c._created_at)
    if state != "all":
        base_query = base_query.where(table.c._state == state)
    total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar()

    paginated = base_query.offset(offset)
    if limit is not None:
        paginated = paginated.limit(limit)

    rows = db.execute(paginated).mappings().all()
    serialized = [_serialize_row(dict(r)) for r in rows]

    extra_headers = {
        "X-Total-Count": str(total),
        "X-Offset": str(offset),
    }

    if format == "json":
        content = json.dumps(serialized, indent=2, ensure_ascii=False)
        filename = f"{schema}_{obj}.json"
        return StreamingResponse(
            iter([content]),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', **extra_headers},
        )

    delimiter = "\t" if format == "tsv" else ","
    filename = f"{schema}_{obj}.{format}"

    if not serialized:
        return StreamingResponse(
            iter([""]),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="{filename}"', **extra_headers},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=serialized[0].keys(), delimiter=delimiter)
    writer.writeheader()
    writer.writerows(serialized)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', **extra_headers},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post(
    "/records/{schema}/{obj}/import",
    summary="Import records",
    description=(
        "Bulk-imports records from CSV, TSV, or JSON. "
        "Records enter the MDM lifecycle as master records or draft candidates "
        "depending on `initial_state` and object configuration."
    ),
)
@limiter.limit("10/minute")
async def import_records(
    schema: str,
    obj: str,
    request: Request,
    file: UploadFile = File(...),
    format: str = Query("csv", pattern="^(csv|tsv|json)$"),
    upsert_key: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    initial_state: str = Query(
        "active",
        pattern="^(active|draft)$",
        description="State for newly inserted records (active or draft). "
                    "Importing as active requires Publisher or Admin.",
    ),
    strict: bool = Query(True, description="Roll back all rows if any row fails (default: true)"),
    source_system: Optional[str] = Query(
        None, description="Source system name applied to all imported records"
    ),
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema, write=True)

    if initial_state == "active":
        user = getattr(request.state, "current_user", None)
        if not user or (
            not user.get("is_admin")
            and not check_permission(
                request.app.state.table_manager.engine, user["user_id"], schema, publish=True
            )
        ):
            raise HTTPException(
                403,
                "Importing records as 'active' requires Publisher or Admin role. "
                "Use initial_state=draft to import as drafts instead."
            )
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
        history_table = tm.get_history_table(schema, obj)
        audit_table = tm.get_audit_table()
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    import_obj_config = tm.get_object_config(schema, obj) or {}
    if initial_state == "active" and not import_obj_config.get("allow_direct_active_import", True):
        raise HTTPException(
            422,
            f"Object '{obj}' does not allow direct active import "
            "(allow_direct_active_import: false in config). Use initial_state=draft instead."
        )

    if upsert_key:
        user_cols = {c.name for c in table.c if not c.name.startswith("_")}
        if upsert_key not in user_cols:
            raise HTTPException(
                400, f"upsert_key '{upsert_key}' is not a valid column for this object"
            )

    if not reason and file.filename:
        reason = f"Import of file {file.filename}"

    content = await file.read(settings.max_upload_size + 1)
    if len(content) > settings.max_upload_size:
        raise HTTPException(
            413,
            f"File too large. "
            f"Maximum upload size is {settings.max_upload_size // (1024 * 1024)} MB.",
        )
    text = content.decode("utf-8-sig")  # handle BOM

    if format == "json":
        try:
            rows = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"Invalid JSON: {e}")
        if not isinstance(rows, list):
            raise HTTPException(400, "JSON must be a list of objects")
    else:
        delimiter = "\t" if format == "tsv" else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)

    inserted = 0
    updated = 0
    errors = []

    for i, row in enumerate(rows):
        # In non-strict mode use a savepoint per row so a DB-level error on one row
        # does not abort the whole transaction and prevents committing previous rows.
        sp = db.begin_nested() if not strict else None
        try:
            if upsert_key:
                action = _upsert_row(
                    db, table, history_table, audit_table,
                    row, upsert_key, reason, request, schema, obj, initial_state, source_system
                )
                if action == "updated":
                    updated += 1
                else:
                    inserted += 1
            else:
                _import_row(
                    db, table, history_table, audit_table,
                    row, reason, request, schema, obj, initial_state, source_system
                )
                inserted += 1
            if sp:
                sp.commit()
        except Exception as e:
            errors.append({"row": i + 1, "error": str(e)})
            if sp:
                sp.rollback()

    if errors and strict:
        db.rollback()
        raise HTTPException(
            422,
            {
                "detail": "Import rolled back: one or more rows failed. "
                          "Fix the errors and retry, or use strict=false to "
                          "commit valid rows only.",
                "errors": errors,
                "total": len(rows),
            },
        )

    db.commit()

    return {
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
        "total": len(rows),
    }


def _inbound_upsert(
    db, table, history_table, audit_table, source_name: str, mapped_data: dict,
    reason: str, request, schema: str, obj: str, match_key: Optional[str] = None,
) -> tuple[str, uuid.UUID]:
    """Upsert an inbound webhook payload as a draft record.

    Lookup order:
    1. Primary: (_source_system, _source_id) compound key.
    2. Fallback (if match_key is set and the value is present): match on the
       named attribute. If exactly one record matches, it is "claimed" —
       _source_system and _source_id are written onto the active record so that
       future pushes hit the primary path. Ambiguous matches (>1) are logged and
       fall through to creating a new draft.

    Only fields present in mapped_data are written; all other fields on an
    existing record are preserved (partial update semantics).

    Returns ("created" | "updated", record_uuid).
    """
    from app.api.objects import _client_ip, _get_username, _integrity_error_message
    now = datetime.now(timezone.utc)
    values = _coerce_row(mapped_data, table)
    values["_source_system"] = source_name

    source_id_val = values.get("_source_id")
    existing = None
    if source_id_val is not None:
        from sqlalchemy import case as sa_case
        existing = db.execute(
            select(table)
            .where(table.c._source_system == source_name)
            .where(table.c._source_id == source_id_val)
            .where(table.c._deleted_at.is_(None))
            .where(table.c._state != "retired")
            .order_by(sa_case((table.c._state == "draft", 0), else_=1))
        ).mappings().first()

    # Fallback: match by business key when _source_id lookup missed
    if existing is None and match_key and match_key in mapped_data:
        match_val = mapped_data[match_key]
        col = getattr(table.c, match_key, None)
        if col is not None and match_val is not None:
            candidates = db.execute(
                select(table)
                .where(col == match_val)
                .where(table.c._deleted_at.is_(None))
                .where(table.c._state != "retired")
                .with_for_update()
            ).mappings().all()

            # Separate active records from their draft copies.
            # One active record + any number of its own draft children is NOT
            # ambiguous — it is one logical entity in the draft/publish lifecycle.
            active_cands = [c for c in candidates if c.get("_state") == "active"]
            draft_cands = [c for c in candidates if c.get("_state") == "draft"]

            if len(active_cands) == 1:
                active_cand = active_cands[0]
                # All drafts must be children of this active record
                unrelated = [d for d in draft_cands
                             if d.get("_draft_of_id") != active_cand["_id"]]
                if not unrelated:
                    existing = active_cand
                    # Claim: stamp _source_system (and _source_id if available) so
                    # future pushes can use the primary lookup path.
                    claim_vals: dict = {"_source_system": source_name}
                    if source_id_val is not None:
                        claim_vals["_source_id"] = source_id_val
                    db.execute(
                        table.update()
                        .where(table.c._id == active_cand["_id"])
                        .values(**claim_vals)
                    )
                else:
                    logger.warning(
                        "inbound %s/%s: match_key '%s'=%r matched %d records — "
                        "ambiguous, creating new draft",
                        schema, obj, match_key, match_val, len(candidates),
                    )
            elif len(active_cands) == 0 and len(draft_cands) == 1:
                # Only a standalone draft (no active record yet)
                existing = draft_cands[0]
                claim_target_id = existing["_id"]
                claim_vals = {"_source_system": source_name}
                if source_id_val is not None:
                    claim_vals["_source_id"] = source_id_val
                db.execute(
                    table.update()
                    .where(table.c._id == claim_target_id)
                    .values(**claim_vals)
                )
            elif len(candidates) > 0:
                logger.warning(
                    "inbound %s/%s: match_key '%s'=%r matched %d records — "
                    "ambiguous, creating new draft",
                    schema, obj, match_key, match_val, len(candidates),
                )

    user_name = _get_username(request)

    if existing is None:
        record_id = uuid.uuid4()
        insert_values = {**values, "_id": record_id, "_created_at": now,
                         "_updated_at": now, "_state": "draft"}
        try:
            db.execute(table.insert().values(**insert_values))
        except IntegrityError as e:
            db.rollback()
            raise HTTPException(422, _integrity_error_message(e)) from e
        audit_svc.write_history(
            db, history_table, insert_values, version=1, action="INSERT",
            valid_from=now, reason=reason, user_name=user_name,
        )
        audit_svc.log_change(
            db, audit_table, schema, obj, record_id, "INSERT",
            old_values=None, new_values=audit_svc._serialize(insert_values),
            reason=reason, ip_address=_client_ip(request), user_name=user_name,
        )
        return "created", record_id

    rid = existing["_id"]
    existing_state = existing.get("_state", "active")
    old_values = dict(existing)

    if existing_state == "active":
        existing_draft = db.execute(
            select(table)
            .where(table.c._draft_of_id == rid)
            .where(table.c._state == "draft")
            .where(table.c._deleted_at.is_(None))
        ).mappings().first()

        if existing_draft:
            draft_id = existing_draft["_id"]
            draft_updates = {**values, "_updated_at": now}
            try:
                db.execute(table.update().where(table.c._id == draft_id).values(**draft_updates))
            except IntegrityError as e:
                db.rollback()
                from app.api.objects import _integrity_error_message
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
                action="UPDATE", valid_from=now, reason=reason, user_name=user_name,
            )
            audit_svc.log_change(
                db, audit_table, schema, obj, draft_id, "UPDATE",
                old_values=audit_svc._serialize(dict(existing_draft)),
                new_values=audit_svc._serialize(new_draft_values),
                reason=reason, ip_address=_client_ip(request), user_name=user_name,
            )
            return "updated", draft_id

        # No existing draft — create draft copy, overlaying only the mapped fields
        draft_id = uuid.uuid4()
        draft_values = {
            k: v for k, v in old_values.items()
            if k not in ("_id", "_created_at", "_updated_at", "_deleted_at",
                         "_state", "_draft_of_id")
        }
        draft_values.update(values)
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
            db, history_table, draft_values, version=1, action="INSERT",
            valid_from=now, reason=reason, user_name=user_name,
        )
        audit_svc.log_change(
            db, audit_table, schema, obj, draft_id, "DRAFT_CREATED",
            old_values=None, new_values=audit_svc._serialize(draft_values),
            reason=reason, ip_address=_client_ip(request), user_name=user_name,
        )
        return "updated", draft_id

    # Existing record is a draft — update it in place (only mapped fields)
    updates = {**values, "_updated_at": now}
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
    try:
        db.execute(table.update().where(table.c._id == rid).values(**updates))
    except IntegrityError as e:
        db.rollback()
        from app.api.objects import _integrity_error_message
        raise HTTPException(422, _integrity_error_message(e)) from e
    new_values = {**old_values, **updates}
    audit_svc.write_history(
        db, history_table, new_values, version=current_version + 1,
        action="UPDATE", valid_from=now, reason=reason, user_name=user_name,
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, rid, "UPDATE",
        old_values=audit_svc._serialize(old_values),
        new_values=audit_svc._serialize(new_values),
        reason=reason, ip_address=_client_ip(request), user_name=user_name,
    )
    return "updated", rid


def _coerce_value(val: str, col_type):
    """Convert a CSV string to the appropriate Python type for a SQLAlchemy column."""
    if val == "" or val is None:
        return None
    if isinstance(col_type, Boolean):
        return val.strip().lower() in ("true", "1", "yes", "t")
    if isinstance(col_type, Integer):
        try:
            return int(val)
        except ValueError:
            raise ValueError(f"'{val}' is not a valid integer")
    if isinstance(col_type, Numeric):
        try:
            return Decimal(val)
        except InvalidOperation:
            raise ValueError(f"'{val}' is not a valid number")
    if isinstance(col_type, DateTime):
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            raise ValueError(f"'{val}' is not a valid date (expected ISO 8601, e.g. 2024-03-01)")
    return val


_IMPORTABLE_SYSTEM_COLS = {"_source_system", "_source_id"}


def _coerce_row(row: dict, table) -> dict:
    """Apply type coercion to all values in a CSV row based on column types."""
    col_types = {c.name: c.type for c in table.c}
    accepted = {
        c.name for c in table.c
        if not c.name.startswith("_") or c.name in _IMPORTABLE_SYSTEM_COLS
    }
    result = {}
    for k, v in row.items():
        k = k.strip()  # normalize headers (handles trailing spaces from Excel/LibreOffice)
        if k not in accepted:
            continue
        result[k] = _coerce_value(v, col_types[k]) if k in col_types else (v if v != "" else None)
    return result


def _import_row(db, table, history_table, audit_table, row: dict, reason, request, schema, obj,
                initial_state: str = "active", source_system: Optional[str] = None):
    from app.api.objects import _client_ip, _get_username
    now = datetime.now(timezone.utc)
    row_keys = {k.strip() for k in row.keys()}
    values = _coerce_row(row, table)
    record_id = uuid.uuid4()
    values["_id"] = record_id
    values["_created_at"] = now
    values["_updated_at"] = now
    values["_state"] = initial_state
    if source_system and "_source_system" not in row_keys:
        values["_source_system"] = source_system

    db.execute(table.insert().values(**values))
    audit_svc.write_history(
        db, history_table, values, version=1, action="INSERT", valid_from=now,
        reason=reason, user_name=_get_username(request)
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, record_id, "INSERT",
        old_values=None, new_values=audit_svc._serialize(values),
        reason=reason, ip_address=_client_ip(request), user_name=_get_username(request)
    )


def _upsert_row(
    db, table, history_table, audit_table, row: dict, upsert_key: str, reason, request, schema, obj,
    initial_state: str = "active", source_system: Optional[str] = None,
):
    from app.api.objects import _client_ip, _get_username
    now = datetime.now(timezone.utc)
    row_keys = {k.strip() for k in row.keys()}
    values = _coerce_row(row, table)
    if source_system and "_source_system" not in row_keys:
        values["_source_system"] = source_system

    match_value = values.get(upsert_key)
    existing = None
    if match_value is not None:
        existing = db.execute(
            select(table)
            .where(table.c[upsert_key] == match_value)
            .where(table.c._deleted_at.is_(None))
        ).mappings().first()

    if existing:
        rid = existing["_id"]
        existing_state = existing["_state"] if "_state" in existing.keys() else "active"
        old_values = dict(existing)

        if initial_state == "draft" and existing_state == "active":
            # Draft-copy-on-edit: leave the active record unchanged; create/update a draft.
            existing_draft = db.execute(
                select(table)
                .where(table.c._draft_of_id == rid)
                .where(table.c._state == "draft")
                .where(table.c._deleted_at.is_(None))
            ).mappings().first()

            if existing_draft:
                draft_id = existing_draft["_id"]
                draft_updates = {**values, "_updated_at": now}
                db.execute(table.update().where(table.c._id == draft_id).values(**draft_updates))
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
                    action="UPDATE", valid_from=now, reason=reason, user_name=_get_username(request)
                )
                audit_svc.log_change(
                    db, audit_table, schema, obj, draft_id, "UPDATE",
                    old_values=audit_svc._serialize(dict(existing_draft)),
                    new_values=audit_svc._serialize(new_draft_values),
                    reason=reason, ip_address=_client_ip(request), user_name=_get_username(request)
                )
            else:
                draft_id = uuid.uuid4()
                draft_values = {
                    k: v for k, v in old_values.items()
                    if k not in ("_id", "_created_at", "_updated_at", "_deleted_at",
                                 "_state", "_draft_of_id")
                }
                draft_values.update(values)
                draft_values["_id"] = draft_id
                draft_values["_created_at"] = now
                draft_values["_updated_at"] = now
                draft_values["_deleted_at"] = None
                draft_values["_state"] = "draft"
                draft_values["_draft_of_id"] = rid
                db.execute(table.insert().values(**draft_values))
                audit_svc.write_history(
                    db, history_table, draft_values, version=1,
                    action="INSERT", valid_from=now, reason=reason, user_name=_get_username(request)
                )
                audit_svc.log_change(
                    db, audit_table, schema, obj, draft_id, "DRAFT_CREATED",
                    old_values=None, new_values=audit_svc._serialize(draft_values),
                    reason=reason, ip_address=_client_ip(request), user_name=_get_username(request)
                )
            return "updated"

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

        updates = {**values, "_updated_at": now}
        db.execute(table.update().where(table.c._id == rid).values(**updates))

        new_values = {**old_values, **updates}
        audit_svc.write_history(
            db, history_table, new_values, version=current_version + 1,
            action="UPDATE", valid_from=now, reason=reason, user_name=_get_username(request)
        )
        audit_svc.log_change(
            db, audit_table, schema, obj, rid, "UPDATE",
            old_values=audit_svc._serialize(old_values),
            new_values=audit_svc._serialize(new_values),
            reason=reason, ip_address=_client_ip(request), user_name=_get_username(request)
        )
        return "updated"
    else:
        record_id = uuid.uuid4()
        values["_id"] = record_id
        values["_created_at"] = now
        values["_updated_at"] = now
        values["_state"] = initial_state
        db.execute(table.insert().values(**values))
        audit_svc.write_history(
            db, history_table, values, version=1, action="INSERT", valid_from=now,
            reason=reason, user_name=_get_username(request)
        )
        audit_svc.log_change(
            db, audit_table, schema, obj, record_id, "INSERT",
            old_values=None, new_values=audit_svc._serialize(values),
            reason=reason, ip_address=_client_ip(request), user_name=_get_username(request)
        )
        return "inserted"
