"""Schema-level access control.

Table: _system.schema_permissions
  user_id     UUID     FK to _system.users.id
  schema_name TEXT
  can_read    BOOLEAN  — Viewer role
  can_write   BOOLEAN  — Editor role (implies read)
  can_publish BOOLEAN  — Publisher role (implies write + read)
  PRIMARY KEY (user_id, schema_name)

Admins always have full access and bypass all checks.
Non-admins have no access unless a row explicitly grants it.
"""
import uuid

from fastapi import HTTPException, Request
from sqlalchemy import Boolean, Column, MetaData, Table, Text, select, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session


def ensure_permissions_table(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS _system.schema_permissions (
                user_id     UUID NOT NULL REFERENCES _system.users(id) ON DELETE CASCADE,
                schema_name TEXT NOT NULL,
                can_read    BOOLEAN NOT NULL DEFAULT TRUE,
                can_write   BOOLEAN NOT NULL DEFAULT FALSE,
                can_publish BOOLEAN NOT NULL DEFAULT FALSE,
                PRIMARY KEY (user_id, schema_name)
            )
        """))
        conn.execute(text("""
            ALTER TABLE _system.schema_permissions
            ADD COLUMN IF NOT EXISTS can_publish BOOLEAN NOT NULL DEFAULT FALSE
        """))
        conn.commit()


def _perms_table(engine) -> Table:
    meta = MetaData()
    return Table(
        "schema_permissions", meta,
        Column("user_id", PGUUID(as_uuid=True), nullable=False),
        Column("schema_name", Text, nullable=False),
        Column("can_read", Boolean, nullable=False),
        Column("can_write", Boolean, nullable=False),
        Column("can_publish", Boolean, nullable=False),
        schema="_system",
    )


def get_user_permissions(engine, user_id: str) -> list[dict]:
    """Return all permission rows for a user."""
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
                "can_publish": r["can_publish"],
            }
            for r in rows
        ]


def set_permission(
    engine, user_id: str, schema_name: str,
    can_read: bool, can_write: bool, can_publish: bool = False
) -> None:
    """Insert or update a permission row for a user/schema pair.

    Publisher implies write + read. Write implies read.
    Removing read also removes write and publish.
    """
    if can_publish:
        can_write = True
    if can_write:
        can_read = True
    if not can_read:
        can_write = False
        can_publish = False
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
                .values(can_read=can_read, can_write=can_write, can_publish=can_publish)
            )
        else:
            s.execute(tbl.insert().values(
                user_id=uid, schema_name=schema_name,
                can_read=can_read, can_write=can_write, can_publish=can_publish
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


def check_permission(
    engine, user_id: str, schema_name: str, write: bool = False, publish: bool = False
) -> bool:
    """Return True if the user has the requested access to the schema."""
    tbl = _perms_table(engine)
    uid = uuid.UUID(user_id)
    with Session(engine) as s:
        row = s.execute(
            select(tbl).where(tbl.c.user_id == uid).where(tbl.c.schema_name == schema_name)
        ).mappings().first()
        if not row:
            return False
        if publish:
            return bool(row["can_publish"])
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


def require_publish_access(request: Request, schema: str) -> None:
    """Raise HTTP 403 if the user does not have Publisher (or Admin) access.

    Required for lifecycle transitions: draft → active (publish) and active → retired (retire).
    """
    user = getattr(request.state, "current_user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    if user.get("is_admin"):
        return
    engine = request.app.state.table_manager.engine
    if not check_permission(engine, user["user_id"], schema, publish=True):
        raise HTTPException(
            403,
            f"Publisher role required to perform lifecycle transitions on schema '{schema}'"
        )
