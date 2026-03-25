import uuid
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    text,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.engine import Engine

TYPE_MAP = {
    "string": Text,
    "text": Text,
    "numeric": Numeric,
    "integer": Integer,
    "boolean": Boolean,
    "email": Text,
    "date": DateTime,
}


class TableManager:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.metadata = MetaData()
        self._tables: dict[str, Table] = {}  # key: "schema.object"
        self._config: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def sync_schema(self, config: dict) -> None:
        """Create or update all PostgreSQL schemas and tables from config.

        Safe to call multiple times (e.g. on config hot-reload): existing tables
        are inspected and any new columns are added via ALTER TABLE.
        """
        self._config = config
        schemas = config.get("schemas", {})

        # Reset in-memory state so redefined tables pick up new columns.
        self._tables = {}
        self.metadata = MetaData()

        with self.engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS _system"))
            for schema_name in schemas:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
            conn.commit()

        # Define tables in Python (order matters: parents before children)
        for schema_name, schema_body in schemas.items():
            objects = schema_body.get("objects", {})
            ordered = _topological_sort(objects)
            for obj_key in ordered:
                obj_body = objects[obj_key]
                self._define_table(schema_name, obj_key, obj_body, schema_name)
                self._define_history_table(schema_name, obj_key, obj_body)

        self._ensure_audit_log_table()

        # Add any new columns to existing tables before create_all runs.
        self._alter_existing_tables()

        # Create tables that don't exist yet (existing ones are left intact).
        self.metadata.create_all(self.engine)

        # Add FK and UNIQUE constraints to tables that already existed.
        self._ensure_constraints()

    def get_table(self, schema: str, obj: str) -> Table:
        key = f"{schema}.{obj}"
        if key not in self._tables:
            raise KeyError(f"Table '{key}' not found. Has the config been loaded?")
        return self._tables[key]

    def get_history_table(self, schema: str, obj: str) -> Table:
        return self.get_table(schema, f"{obj}_history")

    def get_audit_table(self) -> Table:
        return self.get_table("_system", "audit_log")

    def list_schemas(self) -> list[str]:
        return list(self._config.get("schemas", {}).keys())

    def list_objects(self, schema: str) -> list[dict]:
        schema_body = self._config.get("schemas", {}).get(schema, {})
        result = []
        for obj_key, obj_body in schema_body.get("objects", {}).items():
            result.append(
                {
                    "key": obj_key,
                    "name": obj_body.get("name", obj_key),
                    "description": obj_body.get("description", ""),
                    "parent": obj_body.get("parent"),
                    "attributes": obj_body.get("attributes", {}),
                }
            )
        return result

    def get_object_config(self, schema: str, obj: str) -> Optional[dict]:
        return (
            self._config.get("schemas", {})
            .get(schema, {})
            .get("objects", {})
            .get(obj)
        )

    def get_config(self) -> dict:
        return self._config

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _define_table(
        self, schema: str, obj_key: str, obj_body: dict, schema_name: str
    ) -> Table:
        table_key = f"{schema}.{obj_key}"
        if table_key in self._tables:
            return self._tables[table_key]

        columns = [
            Column("_id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column("_created_at", DateTime(timezone=True), nullable=False),
            Column("_updated_at", DateTime(timezone=True), nullable=False),
            Column("_created_by", Text, nullable=True),
            Column("_deleted_at", DateTime(timezone=True), nullable=True),
        ]

        parent = obj_body.get("parent")
        if parent:
            columns.append(Column(
                f"_{parent}_id",
                PGUUID(as_uuid=True),
                ForeignKey(
                    f"{schema_name}.{parent}._id",
                    ondelete="SET NULL",
                    name=f"fk_{obj_key}_{parent}",
                ),
                nullable=True,
            ))

        for attr_key, attr_body in obj_body.get("attributes", {}).items():
            ref_obj = attr_body.get("reference")
            if ref_obj:
                columns.append(Column(
                    f"{attr_key}_id",
                    PGUUID(as_uuid=True),
                    ForeignKey(
                        f"{schema_name}.{ref_obj}._id",
                        ondelete="SET NULL",
                        name=f"fk_{obj_key}_{attr_key}",
                    ),
                    nullable=True,
                    comment=attr_body.get("name", attr_key),
                ))
            else:
                col = self._make_column(attr_key, attr_body)
                if col is not None:
                    columns.append(col)

        table = Table(obj_key, self.metadata, *columns, schema=schema)
        self._tables[table_key] = table
        return table

    def _define_history_table(
        self, schema: str, obj_key: str, obj_body: dict
    ) -> Table:
        table_key = f"{schema}.{obj_key}_history"
        if table_key in self._tables:
            return self._tables[table_key]

        columns = [
            Column(
                "_history_id",
                PGUUID(as_uuid=True),
                primary_key=True,
                default=uuid.uuid4,
            ),
            Column("_id", PGUUID(as_uuid=True), nullable=False, index=True),
            Column("_version", Integer, nullable=False),
            Column("_valid_from", DateTime(timezone=True), nullable=False),
            Column("_valid_to", DateTime(timezone=True), nullable=True),
            Column("_changed_at", DateTime(timezone=True), nullable=False),
            Column("_changed_by", Text, nullable=True),
            Column("_change_reason", Text, nullable=True),
            Column("_action", Text, nullable=False),  # INSERT | UPDATE | DELETE
            Column("_created_at", DateTime(timezone=True), nullable=True),
            Column("_created_by", Text, nullable=True),
        ]

        parent = obj_body.get("parent")
        if parent:
            columns.append(Column(f"_{parent}_id", PGUUID(as_uuid=True), nullable=True))

        for attr_key, attr_body in obj_body.get("attributes", {}).items():
            if attr_body.get("reference"):
                columns.append(Column(f"{attr_key}_id", PGUUID(as_uuid=True), nullable=True))
            else:
                col_type = TYPE_MAP.get(attr_body.get("type", "string"), Text)
                columns.append(Column(attr_key, col_type, nullable=True))

        table = Table(f"{obj_key}_history", self.metadata, *columns, schema=schema)
        self._tables[table_key] = table
        return table

    def _ensure_audit_log_table(self) -> Table:
        table_key = "_system.audit_log"
        if table_key in self._tables:
            return self._tables[table_key]

        columns = [
            Column("id", PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
            Column("timestamp", DateTime(timezone=True), nullable=False),
            Column("user_name", Text, nullable=True),
            Column("schema_name", Text, nullable=False),
            Column("object_name", Text, nullable=False),
            Column("record_id", PGUUID(as_uuid=True), nullable=False),
            Column("action", Text, nullable=False),
            Column("old_values", JSON, nullable=True),
            Column("new_values", JSON, nullable=True),
            Column("reason", Text, nullable=True),
            Column("ip_address", Text, nullable=True),
        ]

        table = Table("audit_log", self.metadata, *columns, schema="_system")
        self._tables[table_key] = table
        return table

    def _alter_existing_tables(self) -> None:
        """Add columns that are in the Python metadata but missing from the database."""
        insp = sa_inspect(self.engine)
        with self.engine.connect() as conn:
            for key, table in self._tables.items():
                if table.schema is None:
                    continue
                schema = table.schema
                tbl_name = table.name
                try:
                    existing = {c["name"] for c in insp.get_columns(tbl_name, schema=schema)}
                except Exception:
                    continue  # Table not in DB yet — create_all will handle it
                for col in table.c:
                    if col.name not in existing:
                        col_type = col.type.compile(dialect=self.engine.dialect)
                        conn.execute(text(
                            f'ALTER TABLE "{schema}"."{tbl_name}" '
                            f'ADD COLUMN IF NOT EXISTS "{col.name}" {col_type}'
                        ))
            conn.commit()

    def _ensure_constraints(self) -> None:
        """Add FK and UNIQUE constraints to existing tables where missing.

        PostgreSQL does not support ADD CONSTRAINT IF NOT EXISTS for FK/UNIQUE,
        so we query pg_constraint to discover what already exists and only issue
        ALTER TABLE for genuinely absent constraints. Safe to call on every startup.
        """
        schemas = self._config.get("schemas", {})
        with self.engine.connect() as conn:
            for schema_name, schema_body in schemas.items():
                for obj_key, obj_body in schema_body.get("objects", {}).items():
                    existing = self._existing_constraint_names(conn, schema_name, obj_key)

                    parent = obj_body.get("parent")
                    if parent:
                        cname = f"fk_{obj_key}_{parent}"
                        if cname not in existing:
                            conn.execute(text(
                                f'ALTER TABLE "{schema_name}"."{obj_key}" '
                                f'ADD CONSTRAINT "{cname}" '
                                f'FOREIGN KEY ("_{parent}_id") '
                                f'REFERENCES "{schema_name}"."{parent}"("_id") '
                                f'ON DELETE SET NULL'
                            ))

                    for attr_key, attr_body in obj_body.get("attributes", {}).items():
                        ref_obj = attr_body.get("reference")
                        if ref_obj:
                            cname = f"fk_{obj_key}_{attr_key}"
                            if cname not in existing:
                                conn.execute(text(
                                    f'ALTER TABLE "{schema_name}"."{obj_key}" '
                                    f'ADD CONSTRAINT "{cname}" '
                                    f'FOREIGN KEY ("{attr_key}_id") '
                                    f'REFERENCES "{schema_name}"."{ref_obj}"("_id") '
                                    f'ON DELETE SET NULL'
                                ))

                        if attr_body.get("unique"):
                            cname = f"uq_{obj_key}_{attr_key}"
                            if cname not in existing:
                                conn.execute(text(
                                    f'ALTER TABLE "{schema_name}"."{obj_key}" '
                                    f'ADD CONSTRAINT "{cname}" '
                                    f'UNIQUE ("{attr_key}")'
                                ))
            conn.commit()

    @staticmethod
    def _existing_constraint_names(conn, schema: str, table: str) -> set[str]:
        """Return the names of all constraints on a given table."""
        rows = conn.execute(text("""
            SELECT c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = :schema AND t.relname = :table
        """), {"schema": schema, "table": table})
        return {row[0] for row in rows}

    @staticmethod
    def _make_column(attr_key: str, attr_body: dict) -> Optional[Column]:
        if attr_body.get("reference"):
            return Column(
                f"{attr_key}_id",
                PGUUID(as_uuid=True),
                nullable=True,
                comment=attr_body.get("name", attr_key),
            )
        col_type = TYPE_MAP.get(attr_body.get("type", "string"), Text)
        return Column(
            attr_key,
            col_type,
            nullable=not attr_body.get("required", False),
            unique=attr_body.get("unique", False),
            comment=attr_body.get("name", attr_key),
        )


def _topological_sort(objects: dict) -> list[str]:
    """Sort objects so parents come before children."""
    visited: set[str] = set()
    result: list[str] = []

    def visit(key: str) -> None:
        if key in visited:
            return
        visited.add(key)
        parent = objects.get(key, {}).get("parent")
        if parent and parent in objects:
            visit(parent)
        result.append(key)

    for key in objects:
        visit(key)

    return result
