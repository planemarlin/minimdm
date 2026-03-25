"""Create all _system schema tables.

Revision ID: 0001
Revises: –
Create Date: 2026-03-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # users — must be created before tables that reference it
    # ------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.VARCHAR(100), nullable=False),
        sa.Column("password_hash", sa.VARCHAR(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.UniqueConstraint("username", name="uq_users_username"),
        schema="_system",
    )

    # ------------------------------------------------------------------
    # audit_log
    # ------------------------------------------------------------------
    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("timestamp", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("user_name", sa.Text(), nullable=True),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column("object_name", sa.Text(), nullable=False),
        sa.Column("record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("old_values", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("new_values", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.Text(), nullable=True),
        schema="_system",
    )

    # ------------------------------------------------------------------
    # token_blocklist — revoked JWT JTIs
    # ------------------------------------------------------------------
    op.create_table(
        "token_blocklist",
        sa.Column("jti", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        schema="_system",
    )

    # ------------------------------------------------------------------
    # password_reset_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "password_reset_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("token", name="uq_password_reset_tokens_token"),
        schema="_system",
    )

    # ------------------------------------------------------------------
    # schema_permissions — references users; created last
    # ------------------------------------------------------------------
    op.create_table(
        "schema_permissions",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schema_name", sa.Text(), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default="false"),
        sa.PrimaryKeyConstraint("user_id", "schema_name", name="pk_schema_permissions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["_system.users.id"],
            name="fk_schema_permissions_user_id",
            ondelete="CASCADE",
        ),
        schema="_system",
    )


def downgrade() -> None:
    op.drop_table("schema_permissions", schema="_system")
    op.drop_table("password_reset_tokens", schema="_system")
    op.drop_table("token_blocklist", schema="_system")
    op.drop_table("audit_log", schema="_system")
    op.drop_table("users", schema="_system")
