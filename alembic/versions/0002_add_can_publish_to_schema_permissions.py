"""Add can_publish column to _system.schema_permissions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "schema_permissions",
        sa.Column("can_publish", sa.Boolean(), nullable=False, server_default="false"),
        schema="_system",
    )


def downgrade() -> None:
    op.drop_column("schema_permissions", "can_publish", schema="_system")
