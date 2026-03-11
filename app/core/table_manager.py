import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    Table,
    Text,
    Boolean,
    JSON,
    text,
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
        """Create or update all PostgreSQL schemas and tables from config."""
        self._config = config
        schemas = config.get("schemas", {})

        with self.engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS _system"))
            for schema_name in schemas:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))
            conn.commit()

        # Define tables (order matters: parents before children)
        for schema_name, schema_body in schemas.items():
            objects = schema_body.get("objects", {})
            ordered = _topological_sort(objects)
            for obj_key in ordered:
                obj_body = objects[obj_key]
                self._define_table(schema_name, obj_key, obj_body, schema_name)
                self._define_history_table(schema_name, obj_key, obj_body)

        self._ensure_audit_log_table()
        self.metadata.create_all(self.engine)

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
            columns.append(
                Column(f"_{parent}_id", PGUUID(as_uuid=True), nullable=True)
            )

        for attr_key, attr_body in obj_body.get("attributes", {}).items():
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
