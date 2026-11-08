"""Add _system.duplicate_flags and _system.duplicate_scans for duplicate detection.

duplicate_flags holds one row per (rule, entity, match) where an entity shares a
normalised match key with at least one other entity; a flag can be dismissed.
duplicate_scans remembers, per object, which rule set was last scanned (so a changed
rule set can be rescanned), how big/slow that scan was, and whether a rescan has been
requested (a big import commits first and is scanned afterwards; if the server dies in
between, the request survives and the next startup picks it up).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: TableManager.sync_schema() also creates these tables from its
    # SQLAlchemy definitions, so either may get there first. Keep both in step
    # (tests/test_duplicate_tables.py compares the two).
    op.execute("""
        CREATE TABLE IF NOT EXISTS _system.duplicate_flags (
            id           UUID DEFAULT gen_random_uuid() NOT NULL,
            schema_name  TEXT NOT NULL,
            object_name  TEXT NOT NULL,
            rule_name    TEXT NOT NULL,
            entity_id    UUID NOT NULL,
            match_hash   TEXT NOT NULL,
            match_value  TEXT,
            status       TEXT DEFAULT 'open' NOT NULL,
            created_at   TIMESTAMP WITH TIME ZONE NOT NULL,
            updated_at   TIMESTAMP WITH TIME ZONE NOT NULL,
            dismissed_by TEXT,
            dismissed_at TIMESTAMP WITH TIME ZONE,
            dismiss_reason TEXT,
            PRIMARY KEY (id),
            CONSTRAINT uq_duplicate_flags_member
                UNIQUE (schema_name, object_name, rule_name, entity_id, match_hash),
            CONSTRAINT ck_duplicate_flags_status CHECK (status IN ('open', 'dismissed'))
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_duplicate_flags_group
        ON _system.duplicate_flags (schema_name, object_name, rule_name, match_hash)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_duplicate_flags_entity
        ON _system.duplicate_flags (schema_name, object_name, entity_id)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS _system.duplicate_scans (
            schema_name       TEXT NOT NULL,
            object_name       TEXT NOT NULL,
            rules_fingerprint TEXT NOT NULL,
            record_count      INTEGER,
            duration_ms       INTEGER,
            scanned_at        TIMESTAMP WITH TIME ZONE NOT NULL,
            rescan_requested_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (schema_name, object_name)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _system.duplicate_scans")
    op.execute("DROP TABLE IF EXISTS _system.duplicate_flags")
