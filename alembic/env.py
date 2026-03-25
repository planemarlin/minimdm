"""Alembic migration environment for miniMDM.

Manages only the _system schema (users, audit_log, token_blocklist,
password_reset_tokens, schema_permissions). User-defined data tables are
handled dynamically by TableManager and are not touched by Alembic.

The alembic_version tracking table is stored in the _system schema so all
system metadata lives in one place.
"""
import logging

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings

logger = logging.getLogger("alembic.env")

# Inject the real database URL from application settings.
config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

# We do not use autogenerate (target_metadata = None).
# Write migrations by hand; see docs/migrations.md for instructions.
target_metadata = None

# Store the Alembic version record in the _system schema.
_VERSION_TABLE = "alembic_version"
_VERSION_SCHEMA = "_system"


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=_VERSION_TABLE,
        version_table_schema=_VERSION_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=_VERSION_TABLE,
            version_table_schema=_VERSION_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
