from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter()


@router.get("/audit")
def list_audit_log(
    request: Request,
    schema: str = Query(None),
    obj: str = Query(None),
    action: str = Query(None),
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
    import uuid
    from datetime import datetime

    filters = []
    if schema:
        filters.append(audit_table.c.schema_name == schema)
    if obj:
        filters.append(audit_table.c.object_name == obj)
    if action:
        filters.append(audit_table.c.action == action.upper())

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
