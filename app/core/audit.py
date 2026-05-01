import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session


def log_change(
    db: Session,
    audit_table,
    schema_name: str,
    object_name: str,
    record_id: uuid.UUID,
    action: str,
    old_values: Optional[dict],
    new_values: Optional[dict],
    reason: Optional[str] = None,
    user_name: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Insert a row into the audit log."""
    db.execute(
        audit_table.insert().values(
            id=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
            user_name=user_name,
            schema_name=schema_name,
            object_name=object_name,
            record_id=record_id,
            action=action,
            old_values=_serialize(old_values),
            new_values=_serialize(new_values),
            reason=reason,
            ip_address=ip_address,
        )
    )


def write_history(
    db: Session,
    history_table,
    record: dict,
    version: int,
    action: str,
    valid_from: datetime,
    valid_to: Optional[datetime] = None,
    reason: Optional[str] = None,
    user_name: Optional[str] = None,
) -> None:
    """Insert a versioned snapshot into the history table."""
    history_cols = {c.name for c in history_table.c}
    row = {k: v for k, v in record.items() if k in history_cols}
    row["_history_id"] = uuid.uuid4()
    row["_version"] = version
    row["_valid_from"] = valid_from
    row["_valid_to"] = valid_to
    row["_changed_at"] = datetime.now(timezone.utc)
    row["_changed_by"] = user_name
    row["_change_reason"] = reason
    row["_action"] = action
    db.execute(history_table.insert().values(**row))


def _serialize(values: Optional[dict]) -> Optional[dict]:
    if values is None:
        return None
    result = {}
    for k, v in values.items():
        if isinstance(v, uuid.UUID):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        elif isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result
