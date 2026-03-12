import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
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
# Export
# ---------------------------------------------------------------------------

@router.get("/records/{schema}/{obj}/export")
def export_records(
    schema: str,
    obj: str,
    request: Request,
    format: str = Query("csv", pattern="^(csv|tsv|json)$"),
    db: Session = Depends(get_db),
):
    tm = _get_tm(request)
    try:
        table = tm.get_table(schema, obj)
    except KeyError:
        raise HTTPException(404, f"Object '{schema}.{obj}' not found")

    rows = db.execute(
        select(table).where(table.c._deleted_at.is_(None)).order_by(table.c._created_at)
    ).mappings().all()

    serialized = [_serialize_row(dict(r)) for r in rows]

    if format == "json":
        content = json.dumps(serialized, indent=2, ensure_ascii=False)
        media_type = "application/json"
        filename = f"{schema}_{obj}.json"
        return StreamingResponse(
            iter([content]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    delimiter = "\t" if format == "tsv" else ","
    ext = format
    filename = f"{schema}_{obj}.{ext}"
    media_type = "text/plain"

    if not serialized:
        return StreamingResponse(
            iter([""]),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=serialized[0].keys(), delimiter=delimiter)
    writer.writeheader()
    writer.writerows(serialized)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post("/records/{schema}/{obj}/import")
async def import_records(
    schema: str,
    obj: str,
    request: Request,
    file: UploadFile = File(...),
    format: str = Query("csv", pattern="^(csv|tsv|json)$"),
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

    content = await file.read()
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
        try:
            _import_row(
                db, table, history_table, audit_table,
                row, reason, request, schema, obj
            )
            inserted += 1
        except Exception as e:
            errors.append({"row": i + 1, "error": str(e)})

    db.commit()

    return {
        "inserted": inserted,
        "updated": updated,
        "errors": errors,
        "total": len(rows),
    }


def _import_row(db, table, history_table, audit_table, row: dict, reason, request, schema, obj):
    now = datetime.now(timezone.utc)
    user_cols = {c.name for c in table.c if not c.name.startswith("_")}
    values = {k: (v if v != "" else None) for k, v in row.items() if k in user_cols}
    record_id = uuid.uuid4()
    values["_id"] = record_id
    values["_created_at"] = now
    values["_updated_at"] = now

    from app.api.objects import _client_ip
    db.execute(table.insert().values(**values))
    audit_svc.write_history(
        db, history_table, values, version=1, action="INSERT", valid_from=now, reason=reason
    )
    audit_svc.log_change(
        db, audit_table, schema, obj, record_id, "INSERT",
        old_values=None, new_values=audit_svc._serialize(values),
        reason=reason, ip_address=_client_ip(request)
    )
