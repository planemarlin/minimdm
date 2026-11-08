"""The `_system.duplicate_flags` / `_system.duplicate_scans` tables.

They are defined twice — in migration 0004 and as SQLAlchemy tables in TableManager
(like `inbound_keys`) — so these tests pin the two definitions together.
"""
import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

_MIGRATION = Path(__file__).parent.parent / "alembic" / "versions" / (
    "0004_add_duplicate_detection_tables.py"
)
_TABLES = ("duplicate_flags", "duplicate_scans")


@pytest.fixture
def tm(client):
    return client.app.state.table_manager


def _columns(inspector, table: str) -> dict:
    return {
        c["name"]: c["nullable"]
        for c in inspector.get_columns(table, schema="_system")
    }


def test_python_definition_matches_database(tm):
    insp = sa_inspect(tm.engine)
    for name in _TABLES:
        python_cols = {c.name: c.nullable for c in tm.get_table("_system", name).c}
        assert _columns(insp, name) == python_cols


def test_migration_creates_the_same_columns_as_the_python_definition(tm):
    """Re-run migration 0004's DDL from scratch (inside a transaction that is rolled
    back, which PostgreSQL DDL allows) and compare it to the Python definition."""
    spec = importlib.util.spec_from_file_location("migration_0004", _MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    with tm.engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("DROP TABLE _system.duplicate_flags, _system.duplicate_scans"))
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            insp = sa_inspect(conn)
            for name in _TABLES:
                python_cols = {c.name: c.nullable for c in tm.get_table("_system", name).c}
                assert _columns(insp, name) == python_cols
            index_names = {i["name"] for i in insp.get_indexes("duplicate_flags", schema="_system")}
            assert {"ix_duplicate_flags_group", "ix_duplicate_flags_entity"} <= index_names
        finally:
            trans.rollback()


def test_accessors(tm):
    assert tm.get_duplicate_flags_table().name == "duplicate_flags"
    assert tm.get_duplicate_scans_table().name == "duplicate_scans"


def _flag(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    row = {
        "id": uuid.uuid4(), "schema_name": "test", "object_name": "contact",
        "rule_name": "Same email", "entity_id": uuid.uuid4(), "match_hash": "abc",
        "match_value": "a@x.com", "status": "open", "created_at": now, "updated_at": now,
    }
    row.update(overrides)
    return row


def test_flag_status_is_constrained_and_members_are_unique(tm):
    table = tm.get_duplicate_flags_table()
    entity = uuid.uuid4()
    with tm.engine.connect() as conn:
        try:
            conn.execute(table.insert().values(**_flag(entity_id=entity)))
            # Same rule + entity + match is one membership
            with pytest.raises(IntegrityError):
                conn.execute(table.insert().values(**_flag(entity_id=entity)))
            conn.rollback()

            # The same entity may sit in two groups (e.g. golden vs draft value)
            conn.execute(table.insert().values(**_flag(entity_id=entity)))
            conn.execute(table.insert().values(**_flag(entity_id=entity, match_hash="def")))

            with pytest.raises(IntegrityError):
                conn.execute(table.insert().values(**_flag(status="confirmed")))
        finally:
            conn.rollback()
