"""Add _system.inbound_keys table for inbound webhook API key management.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-28
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS makes this safe to run against databases where sync_schema
    # already created the table at app startup before the migration was applied.
    op.execute("""
        CREATE TABLE IF NOT EXISTS _system.inbound_keys (
            id          UUID DEFAULT gen_random_uuid() NOT NULL,
            schema_name TEXT NOT NULL,
            source_name TEXT NOT NULL,
            key_prefix  TEXT NOT NULL,
            key_hash    TEXT NOT NULL,
            description TEXT,
            created_at  TIMESTAMP WITH TIME ZONE NOT NULL,
            last_used_at TIMESTAMP WITH TIME ZONE,
            is_active   BOOLEAN DEFAULT true NOT NULL,
            PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_inbound_keys_schema_active
        ON _system.inbound_keys (schema_name, is_active)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS _system.inbound_keys")
