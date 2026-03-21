"""Schema-level access control.

Table: _system.schema_permissions
  user_id     UUID     FK to _system.users.id
  schema_name TEXT
  can_read    BOOLEAN
  can_write   BOOLEAN
  PRIMARY KEY (user_id, schema_name)

Admins always have full access and bypass all checks.
Non-admins have no access unless a row explicitly grants it.
"""
import uuid

from fastapi import HTTPException, Request
from sqlalchemy import MetaData, Table, select, text
from sqlalchemy.orm import Session


def ensure_permissions_table(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _system.schema_permissions (
                user_id     UUID NOT NULL REFERENCES _system.users(id) ON DELETE CASCADE,
                schema_name TEXT NOT NULL,
                can_read    BOOLEAN NOT NULL DEFAULT TRUE,
                can_write   BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (user_id, schema_name)
            )
        """))
        conn.commit()


def _perms_table(engine) -> Table:
    meta = MetaData()
    return Table("schema_permissions", meta, schema="_system", autoload_with=engine)


def get_user_permissions(engine, user_id: str) -> list[dict]:
    """Return all permission rows for a user (list of {schema_name, can_read, can_write})."""
    tbl = _perms_table(engine)
    with Session(engine) as s:
        rows = s.execute(
            select(tbl).where(tbl.c.user_id == uuid.UUID(user_id)).order_by(tbl.c.schema_name)
        ).mappings().all()
        return [
            {
                "schema_name": r["schema_name"],
                "can_read": r["can_read"],
                "can_write": r["can_write"],
            }
            for r in rows
        ]


def set_permission(engine, user_id: str, schema_name: str, can_read: bool, can_write: bool) -> None:
    """Insert or update a permission row for a user/schema pair.

    Write access implies read access. Removing read access also removes write access.
    """
    if can_write:
        can_read = True
    if not can_read:
        can_write = False
    tbl = _perms_table(engine)
    uid = uuid.UUID(user_id)
    with Session(engine) as s:
        existing = s.execute(
            select(tbl).where(tbl.c.user_id == uid).where(tbl.c.schema_name == schema_name)
        ).mappings().first()
        if existing:
            s.execute(
                tbl.update()
                .where(tbl.c.user_id == uid)
                .where(tbl.c.schema_name == schema_name)
                .values(can_read=can_read, can_write=can_write)
            )
        else:
            s.execute(tbl.insert().values(
                user_id=uid, schema_name=schema_name, can_read=can_read, can_write=can_write
            ))
        s.commit()


def delete_permission(engine, user_id: str, schema_name: str) -> None:
    """Remove a permission row, revoking all access for that user/schema pair."""
    tbl = _perms_table(engine)
    uid = uuid.UUID(user_id)
    with Session(engine) as s:
        s.execute(
            tbl.delete().where(tbl.c.user_id == uid).where(tbl.c.schema_name == schema_name)
        )
        s.commit()


def check_permission(engine, user_id: str, schema_name: str, write: bool = False) -> bool:
    """Return True if the user has the requested access to the schema."""
    tbl = _perms_table(engine)
    uid = uuid.UUID(user_id)
    with Session(engine) as s:
        row = s.execute(
            select(tbl).where(tbl.c.user_id == uid).where(tbl.c.schema_name == schema_name)
        ).mappings().first()
        if not row:
            return False
        if write:
            return bool(row["can_write"])
        return bool(row["can_read"])


def get_accessible_schemas(engine, user_id: str) -> set[str]:
    """Return the set of schema names the user can read."""
    tbl = _perms_table(engine)
    uid = uuid.UUID(user_id)
    with Session(engine) as s:
        rows = s.execute(
            select(tbl.c.schema_name).where(tbl.c.user_id == uid).where(tbl.c.can_read == True)  # noqa: E712
        ).all()
        return {r[0] for r in rows}


def require_schema_access(request: Request, schema: str, write: bool = False) -> None:
    """Raise HTTP 403 if the current user cannot access the schema.

    Admins always pass. Non-admins need an explicit permission row.
    """
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("is_admin"):
        return
    engine = request.app.state.table_manager.engine
    if not check_permission(engine, user["user_id"], schema, write=write):
        action = "write to" if write else "read"
        raise HTTPException(
            403, f"Access denied: you do not have permission to {action} schema '{schema}'"
        )
