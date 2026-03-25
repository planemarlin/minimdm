"""Alembic migration runner for the _system schema.

Called once at application startup to bring the _system schema up to date.

Brownfield detection
--------------------
When Alembic has never run on a database that already has the _system tables
(e.g. a deployment from before Alembic was introduced), we stamp the database
at the latest revision instead of re-running the DDL. This makes the transition
transparent — no manual steps required.

Cases handled:
  1. Fresh install (no _system tables at all): run all migrations.
  2. Legacy install (_system.users exists but no alembic_version table): stamp.
  3. Already Alembic-managed: apply any pending migrations.
"""
import logging
import os

from alembic.config import Config as AlembicConfig
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect as sa_inspect

from alembic import command as alembic_command

logger = logging.getLogger(__name__)

# Path to alembic/ directory — two levels up from this file (app/core/migrations.py)
_ALEMBIC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "alembic")


def _make_config(engine) -> AlembicConfig:
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", os.path.abspath(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    return cfg


def run_migrations(engine) -> None:
    """Apply all pending _system schema migrations at startup."""
    cfg = _make_config(engine)

    with engine.connect() as conn:
        # Check whether Alembic has ever tracked this database.
        insp = sa_inspect(engine)
        version_table_exists = "alembic_version" in insp.get_table_names(schema="_system")

        if not version_table_exists:
            # Check whether this is a legacy install (tables already exist).
            users_table_exists = "users" in insp.get_table_names(schema="_system")
            if users_table_exists:
                logger.info(
                    "Legacy database detected (system tables exist without Alembic). "
                    "Stamping to head — no DDL will be executed."
                )
                alembic_command.stamp(cfg, "head")
            else:
                logger.info("Fresh database — running all migrations.")
                alembic_command.upgrade(cfg, "head")
        else:
            # Alembic is already set up; apply any pending migrations.
            ctx = MigrationContext.configure(
                conn,
                opts={
                    "version_table": "alembic_version",
                    "version_table_schema": "_system",
                },
            )
            current = ctx.get_current_revision()
            logger.info("Current schema revision: %s — upgrading to head.", current)
            alembic_command.upgrade(cfg, "head")
