"""Review API for duplicate detection: list flagged groups, dismiss/reopen, scan status.

Flags are created and cleared by the write paths (see app/core/duplicates.py); this module
only reads them and lets users resolve false positives. Who may dismiss follows the
object's ``duplicates.dismissed_by`` (``editor`` = anyone with write access, the default;
``publisher`` = Publishers only); admins always may.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.objects import _check_reason, _client_ip, _get_username, _serialize_row
from app.core import audit as audit_svc
from app.core import duplicates as duplicates_svc
from app.core.permissions import check_permission, require_schema_access
from app.database import get_db

router = APIRouter()

_FLAGS = "_system.duplicate_flags"
_MAX_FLAG_IDS = 500


class FlagAction(BaseModel):
    flag_ids: list[uuid.UUID] = Field(min_length=1, max_length=_MAX_FLAG_IDS)
    reason: Optional[str] = None


def _object(request: Request, schema: str, obj: str) -> tuple:
    """(table manager, object config) or 404."""
    tm = request.app.state.table_manager
    obj_config = tm.get_object_config(schema, obj)
    if obj_config is None:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")
    return tm, obj_config


def _can_dismiss(request: Request, schema: str, obj_config: dict) -> bool:
    user = getattr(request.state, "current_user", None)
    if not user:
        return False
    if user.get("is_admin"):
        return True
    engine = request.app.state.table_manager.engine
    dismissed_by = ((obj_config.get("duplicates") or {}).get("dismissed_by")) or "editor"
    if dismissed_by == "publisher":
        return check_permission(engine, user["user_id"], schema, publish=True)
    return check_permission(engine, user["user_id"], schema, write=True)


def _groups(
    db: Session, tm, schema: str, obj: str, obj_config: dict, *,
    status: str, limit: int, offset: int, entity_id: Optional[uuid.UUID] = None,
) -> tuple[list[dict], int, dict]:
    """Flagged groups with their members and record data.

    Returns ``(groups, total, counts)``: ``total`` is the number of groups with the
    requested status, ``counts`` is ``{"open": n, "dismissed": n}`` for both statuses.

    ``status='open'`` lists groups that still have two or more open members;
    ``status='dismissed'`` lists groups that contain a dismissed member (so they can be
    reopened). ``entity_id`` restricts the result to groups that entity is open in.
    """
    rule_fields = {r["name"]: r["fields"] for r in duplicates_svc.rules_of(obj_config)}
    rules = list(rule_fields)
    if not rules:
        return [], 0, {"open": 0, "dismissed": 0}

    scope = {"s": schema, "o": obj, "rules": rules}
    having = (
        "open_members >= 2" if status == "open" else "dismissed_members >= 1"
    )
    entity_filter = ""
    if entity_id is not None:
        entity_filter = (
            f" AND (rule_name, match_hash) IN (SELECT rule_name, match_hash FROM {_FLAGS} "
            "WHERE schema_name = :s AND object_name = :o AND entity_id = :e "
            "AND status = 'open')"
        )
        scope["e"] = entity_id

    groups_cte = (
        "WITH g AS (SELECT rule_name, match_hash, min(match_value) AS value, "
        "count(*) FILTER (WHERE status = 'open') AS open_members, "
        "count(*) FILTER (WHERE status = 'dismissed') AS dismissed_members "
        f"FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
        f"AND rule_name = ANY(:rules){entity_filter} GROUP BY rule_name, match_hash) "
    )
    n_open, n_dismissed = db.execute(
        text(
            groups_cte + "SELECT count(*) FILTER (WHERE open_members >= 2), "
            "count(*) FILTER (WHERE dismissed_members >= 1) FROM g"
        ),
        scope,
    ).one()
    counts = {"open": n_open, "dismissed": n_dismissed}

    page = db.execute(
        text(
            groups_cte
            + "SELECT rule_name, match_hash, value FROM g "
            f"WHERE {having} ORDER BY rule_name, value, match_hash LIMIT :limit OFFSET :offset"
        ),
        {**scope, "limit": limit, "offset": offset},
    ).all()
    if not page:
        return [], counts[status], counts
    total = counts[status]

    members = db.execute(
        text(
            f"SELECT id, rule_name, match_hash, entity_id, status, dismissed_by, dismissed_at, "
            f"dismiss_reason FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
            "AND rule_name = ANY(:rules) AND match_hash = ANY(:hashes)"
        ),
        {**scope, "hashes": [p[1] for p in page]},
    ).all()

    # Record data for every member entity, and which of them have a pending draft copy.
    table = tm.get_table(schema, obj)
    entity_ids = list({m[3] for m in members})
    records = {
        row["_id"]: dict(row)
        for row in db.execute(select(table).where(table.c._id.in_(entity_ids))).mappings()
    }
    with_draft = {
        r[0] for r in db.execute(
            select(table.c._draft_of_id)
            .where(table.c._draft_of_id.in_(entity_ids))
            .where(table.c._state == "draft")
            .where(table.c._deleted_at.is_(None))
        )
    }

    by_group: dict[tuple, list[dict]] = {}
    for fid, rule, mhash, eid, st, d_by, d_at, d_reason in members:
        record = records.get(eid)
        by_group.setdefault((rule, mhash), []).append({
            "flag_id": str(fid),
            "entity_id": str(eid),
            "status": st,
            "dismissed_by": d_by,
            "dismissed_at": d_at.isoformat() if d_at else None,
            "dismiss_reason": d_reason,
            "has_draft": eid in with_draft,
            "record": _serialize_row(record) if record else None,
        })

    groups = []
    for rule, mhash, value in page:
        group_members = sorted(
            by_group.get((rule, mhash), []),
            key=lambda m: ((m["record"] or {}).get("_created_at") or "", m["entity_id"]),
        )
        groups.append({"rule": rule, "fields": rule_fields[rule], "value": value,
                       "match_hash": mhash, "members": group_members})
    return groups, total, counts


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------

@router.get(
    "/duplicates/{schema}/{obj}",
    summary="List flagged duplicate groups",
    description=(
        "Groups of records that share a normalised value under one of the object's "
        "duplicate rules. `status=open` (default) lists groups with at least two open "
        "members; `status=dismissed` lists groups with a dismissed member, so a dismissal "
        "can be reopened. `counts` gives the number of open and dismissed groups whichever "
        "status is listed. Each group names the `fields` its rule compares and carries "
        "`value`, the normalised form that matched (kept for reference, not for display). "
        "Requires write access to the schema."
    ),
)
def list_groups(
    schema: str,
    obj: str,
    request: Request,
    status: str = Query("open", pattern="^(open|dismissed)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema, write=True)
    tm, obj_config = _object(request, schema, obj)
    groups, total, counts = _groups(
        db, tm, schema, obj, obj_config, status=status, limit=limit, offset=offset
    )
    return {
        "status": status,
        "rules": [r["name"] for r in duplicates_svc.rules_of(obj_config)],
        "total": total,
        "counts": counts,
        "limit": limit,
        "offset": offset,
        "can_dismiss": _can_dismiss(request, schema, obj_config),
        "groups": groups,
    }


@router.get(
    "/duplicates/{schema}/{obj}/record/{record_id}",
    summary="Duplicate groups one record is flagged in",
    description=(
        "The open groups the record (or, for a draft copy, its golden record) belongs to. "
        "Used for the notice on the record page. Requires write access to the schema."
    ),
)
def groups_for_record(
    schema: str,
    obj: str,
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    require_schema_access(request, schema, write=True)
    tm, obj_config = _object(request, schema, obj)
    try:
        rid = uuid.UUID(record_id)
    except ValueError:
        raise HTTPException(400, "Invalid record ID")

    table = tm.get_table(schema, obj)
    row = db.execute(
        select(table.c._id, table.c._draft_of_id).where(table.c._id == rid)
    ).first()
    if not row:
        raise HTTPException(404, "Record not found")

    groups, total, _counts = _groups(
        db, tm, schema, obj, obj_config, status="open", limit=50, offset=0,
        entity_id=row[1] or row[0],
    )
    return {
        "entity_id": str(row[1] or row[0]),
        "total": total,
        "can_dismiss": _can_dismiss(request, schema, obj_config),
        "groups": groups,
    }


def _resolve(
    action: str, body: FlagAction, schema: str, obj: str, request: Request, db: Session,
) -> dict:
    """Shared body of dismiss/reopen: permission, update, one audit entry per flag."""
    tm, obj_config = _object(request, schema, obj)
    require_schema_access(request, schema, write=True)
    if not _can_dismiss(request, schema, obj_config):
        raise HTTPException(
            403,
            f"Publisher role required to {action} duplicates of '{obj}' "
            "(duplicates.dismissed_by: publisher)",
        )
    _check_reason(body.reason, obj_config)

    scope = {"s": schema, "o": obj, "ids": body.flag_ids}
    known = db.execute(
        text(
            f"SELECT count(*) FROM {_FLAGS} WHERE schema_name = :s AND object_name = :o "
            "AND id = ANY(:ids)"
        ),
        scope,
    ).scalar()
    if not known:
        raise HTTPException(404, "No such duplicate flags for this object")

    now = datetime.now(timezone.utc)
    user_name = _get_username(request)
    if action == "dismiss":
        sql = (
            f"UPDATE {_FLAGS} SET status = 'dismissed', dismissed_by = :u, dismissed_at = :now, "
            "dismiss_reason = :reason, updated_at = :now WHERE schema_name = :s "
            "AND object_name = :o AND id = ANY(:ids) AND status = 'open' "
            "RETURNING entity_id, rule_name, match_value"
        )
        old_status, new_status, audit_action = "open", "dismissed", "DUPLICATE_DISMISSED"
    else:
        sql = (
            f"UPDATE {_FLAGS} SET status = 'open', dismissed_by = NULL, dismissed_at = NULL, "
            "dismiss_reason = NULL, updated_at = :now WHERE schema_name = :s "
            "AND object_name = :o AND id = ANY(:ids) AND status = 'dismissed' "
            "RETURNING entity_id, rule_name, match_value"
        )
        old_status, new_status, audit_action = "dismissed", "open", "DUPLICATE_REOPENED"

    changed = db.execute(
        text(sql), {**scope, "u": user_name, "now": now, "reason": body.reason}
    ).all()
    audit_table = tm.get_audit_table()
    for entity_id, rule, value in changed:
        audit_svc.log_change(
            db, audit_table, schema, obj, entity_id, audit_action,
            old_values={"status": old_status},
            new_values={"status": new_status, "rule": rule, "value": value},
            reason=body.reason, ip_address=_client_ip(request), user_name=user_name,
        )
    db.commit()
    return {"changed": len(changed)}


@router.post(
    "/duplicates/{schema}/{obj}/dismiss",
    summary="Dismiss flags as 'not a duplicate'",
    description=(
        "Marks open flags as dismissed. Pass the `flag_id` of one member to dismiss just "
        "that record, or all members' ids to dismiss the whole group. A dismissal holds "
        "until the record's matching value changes or a new record joins the group. "
        "Allowed for anyone with write access, or Publishers only if the object sets "
        "`duplicates.dismissed_by: publisher`. Audited."
    ),
)
def dismiss(
    schema: str, obj: str, body: FlagAction, request: Request, db: Session = Depends(get_db),
):
    return _resolve("dismiss", body, schema, obj, request, db)


@router.post(
    "/duplicates/{schema}/{obj}/reopen",
    summary="Reopen dismissed flags",
    description="Undoes a dismissal. Same permission rule as dismissing. Audited.",
)
def reopen(
    schema: str, obj: str, body: FlagAction, request: Request, db: Session = Depends(get_db),
):
    return _resolve("reopen", body, schema, obj, request, db)


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

@router.get(
    "/duplicates/{schema}/{obj}/scan",
    summary="Duplicate scan status",
    description=(
        "When the object was last scanned and how long that took, whether its rules have "
        "changed since, and whether a scan is running now. `record_count` is the number "
        "of records a new scan would read."
    ),
)
def scan_status(schema: str, obj: str, request: Request):
    require_schema_access(request, schema, write=True)
    tm, obj_config = _object(request, schema, obj)
    engine = tm.engine
    has_rules = bool(duplicates_svc.rules_of(obj_config))
    running = has_rules and duplicates_svc.scan_running(engine, schema, obj)
    info = duplicates_svc.scan_info(engine, schema, obj, obj_config)
    last = None
    if info["scanned_at"]:
        last = {
            "scanned_at": info["scanned_at"].isoformat(),
            "record_count": info["record_count"],
            "duration_ms": info["duration_ms"],
        }
    return {
        "has_rules": has_rules,
        "running": running,
        "needs_rescan": has_rules and info["needs_rescan"],
        "rescan_mode": (request.app.state.app_config.get("duplicates") or {}).get(
            "rescan", "on_rule_change"
        ),
        "record_count": (
            duplicates_svc.count_live_records(engine, schema, obj)
            if has_rules and not running else None
        ),
        "last_scan": last,
    }


@router.post(
    "/duplicates/{schema}/{obj}/rescan",
    status_code=202,
    summary="Rescan an object for duplicates",
    description=(
        "Rebuilds all duplicate flags of the object from its data, in the background "
        "(about 12 s for a million records). Dismissals are kept where the same record "
        "still matches. Admin only."
    ),
)
def rescan(schema: str, obj: str, request: Request, background_tasks: BackgroundTasks):
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin role required to rescan for duplicates")
    tm, obj_config = _object(request, schema, obj)
    if not duplicates_svc.rules_of(obj_config):
        raise HTTPException(422, f"Object '{obj}' has no duplicate rules configured")
    if duplicates_svc.scan_running(tm.engine, schema, obj):
        raise HTTPException(409, "A duplicate scan of this object is already running")

    # The scan writes its own audit entry (DUPLICATE_SCAN) when it completes.
    background_tasks.add_task(
        duplicates_svc.rescan_in_background, tm.engine, schema, obj, obj_config,
        "manual", _get_username(request),
    )
    return {"status": "started"}
