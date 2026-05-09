import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.permissions import get_accessible_schemas
from app.database import get_db

router = APIRouter()


def _parse_dt(value: str) -> Optional[datetime]:
    """Parse an ISO-format datetime string; treat naive values as UTC."""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


@router.get("/audit")
def list_audit_log(
    request: Request,
    schema: str = Query(None),
    obj: str = Query(None),
    action: str = Query(None),
    from_time: Optional[str] = Query(
        None, description="ISO datetime — include entries at or after this time"
    ),
    to_time: Optional[str] = Query(
        None, description="ISO datetime — include entries at or before this time"
    ),
    user: str = Query(None, description="Filter by username (case-insensitive, partial match)"),
    exclude_system: bool = Query(
        False, description="Exclude entries from system schemas (schema_name starting with '_')"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    tm = request.app.state.table_manager
    try:
        audit_table = tm.get_audit_table()
    except KeyError:
        return {"records": [], "total": 0, "page": page, "page_size": page_size, "pages": 0}

    from sqlalchemy import func

    user = getattr(request.state, "current_user", None)
    is_admin = user and user.get("is_admin")

    filters = []
    # Non-admins can only see audit entries for schemas they can read
    # (system schema _system is implicitly excluded unless they are admin)
    if not is_admin and user:
        accessible = get_accessible_schemas(tm.engine, user["user_id"])
        filters.append(audit_table.c.schema_name.in_(accessible))

    if exclude_system:
        filters.append(~audit_table.c.schema_name.startswith("_", autoescape=True))
    if schema:
        filters.append(audit_table.c.schema_name == schema)
    if obj:
        filters.append(audit_table.c.object_name == obj)
    if action:
        filters.append(audit_table.c.action == action.upper())
    if user:
        filters.append(audit_table.c.user_name.ilike(f"%{user}%"))
    if from_time:
        ft = _parse_dt(from_time)
        if ft:
            filters.append(audit_table.c.timestamp >= ft)
    if to_time:
        tt = _parse_dt(to_time)
        if tt:
            filters.append(audit_table.c.timestamp <= tt)

    q = select(audit_table)
    if filters:
        q = q.where(and_(*filters))

    total = db.execute(select(func.count()).select_from(q.subquery())).scalar()
    rows = db.execute(
        q.order_by(audit_table.c.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).mappings().all()

    def _ser(v):
        if isinstance(v, uuid.UUID):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        return v


    return {
        "records": [{k: _ser(v) for k, v in r.items()} for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }
