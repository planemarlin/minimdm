# Database Migrations

miniMDM uses [Alembic](https://alembic.sqlalchemy.org/) to version-control the `_system` schema (users, audit log, token blocklist, password reset tokens, and schema permissions). User-defined data tables — created from your YAML config — are still managed dynamically by the application and are not touched by Alembic.

## How migrations run

Migrations run **automatically at startup**. When the application starts it calls `alembic upgrade head`, which applies any pending migrations and then continues normally. There is nothing to run manually in a standard deployment.

### First-time setup on an existing database

If you are upgrading a miniMDM installation that was running before Alembic was introduced (prior to version 0.1.3), the system tables already exist but Alembic has never tracked them. The application detects this automatically and **stamps** the database at the latest revision instead of re-running the DDL — no data is lost and no manual steps are required.

## Migration files

Migration files live in `alembic/versions/`. Each file is named `{revision}_{description}.py` and contains an `upgrade()` and a `downgrade()` function.

```
alembic/
  env.py              — environment configuration (reads DATABASE_URL from settings)
  script.py.mako      — template for new migration files
  versions/
    0001_initial_system_tables.py
```

## Writing a new migration

When you need to change the `_system` schema (e.g. add a column to `_system.users`), create a new migration file:

```bash
uv run alembic revision -m "add_last_login_to_users"
```

This generates a new file in `alembic/versions/`. Edit it to add your DDL:

```python
def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        schema="_system",
    )

def downgrade() -> None:
    op.drop_column("users", "last_login_at", schema="_system")
```

Commit the file. It will be applied the next time the application starts.

## Useful Alembic commands

Run these from the project root with `uv run alembic <command>`.

| Command | Description |
|---|---|
| `alembic current` | Show the current revision of the connected database |
| `alembic history` | List all migrations in order |
| `alembic upgrade head` | Apply all pending migrations |
| `alembic downgrade -1` | Roll back the last migration |
| `alembic upgrade head --sql` | Print the SQL that would be executed (dry run) |
| `alembic stamp head` | Mark the DB as up-to-date without running DDL |

## What Alembic does NOT manage

- User-defined data tables (company, division, contact, etc.) — these are created and altered dynamically by `TableManager.sync_schema()` based on your YAML config.
- The `_system` schema itself — created with `CREATE SCHEMA IF NOT EXISTS` before migrations run.
- The `alembic_version` tracking table — created automatically by Alembic inside the `_system` schema on first run.
