import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.table_manager import TableManager, _topological_sort


class TestTopologicalSort:
    def test_no_parents(self):
        objects = {
            "a": {"parent": None, "attributes": {}},
            "b": {"parent": None, "attributes": {}},
        }
        result = _topological_sort(objects)
        assert set(result) == {"a", "b"}

    def test_parent_before_child(self):
        objects = {
            "child": {"parent": "parent", "attributes": {}},
            "parent": {"parent": None, "attributes": {}},
        }
        result = _topological_sort(objects)
        assert result.index("parent") < result.index("child")

    def test_chain(self):
        objects = {
            "c": {"parent": "b", "attributes": {}},
            "b": {"parent": "a", "attributes": {}},
            "a": {"parent": None, "attributes": {}},
        }
        result = _topological_sort(objects)
        assert result.index("a") < result.index("b") < result.index("c")


class TestTableManagerConfig:
    def test_list_schemas(self, sample_config):
        # TableManager without a real DB - only test config-level methods
        class FakeEngine:
            pass

        tm = TableManager.__new__(TableManager)
        tm._tables = {}
        tm.metadata = __import__("sqlalchemy").MetaData()
        tm._config = sample_config
        tm.engine = FakeEngine()

        schemas = tm.list_schemas()
        assert "test" in schemas

    def test_list_objects(self, sample_config):
        class FakeEngine:
            pass

        tm = TableManager.__new__(TableManager)
        tm._tables = {}
        tm.metadata = __import__("sqlalchemy").MetaData()
        tm._config = sample_config
        tm.engine = FakeEngine()

        objects = tm.list_objects("test")
        keys = [o["key"] for o in objects]
        assert "company" in keys
        assert "division" in keys

    def test_get_object_config(self, sample_config):
        class FakeEngine:
            pass

        tm = TableManager.__new__(TableManager)
        tm._tables = {}
        tm.metadata = __import__("sqlalchemy").MetaData()
        tm._config = sample_config
        tm.engine = FakeEngine()

        obj = tm.get_object_config("test", "company")
        assert obj is not None
        assert obj["name"] == "Company"

        missing = tm.get_object_config("test", "nonexistent")
        assert missing is None


def _widget_config(schema_name: str, unique: bool) -> dict:
    return {
        "schemas": {
            schema_name: {
                "objects": {
                    "widget": {
                        "name": "Widget",
                        "parent": None,
                        "attributes": {
                            "code": {
                                "name": "Code",
                                "type": "string",
                                "required": True,
                                "unique": unique,
                                "reference": None,
                            },
                        },
                    },
                },
            },
        },
    }


@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)
class TestEnsureConstraintsUniqueToggle:
    """Regression coverage for issue #56: sync_schema() must add *and remove*
    the partial unique index as `unique` flips in config, not just add it.

    Uses a dedicated schema + its own TableManager/engine, deliberately not the
    session-scoped `client` fixture's shared table manager/config, since
    re-syncing schema against that shared state would poison every other test
    in the run.
    """

    SCHEMA = "table_manager_uniq_test"

    @pytest.fixture
    def engine(self):
        eng = create_engine(os.environ["TEST_DATABASE_URL"])
        yield eng
        with eng.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.SCHEMA}" CASCADE'))
            conn.commit()
        eng.dispose()

    def _index_oid(self, engine):
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT c.oid FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = :s AND c.relname = :i
                    """
                ),
                {"s": self.SCHEMA, "i": "uq_widget_code"},
            ).first()
        return row[0] if row else None

    def _insert(self, engine, tm, code, deleted=False):
        table = tm.get_table(self.SCHEMA, "widget")
        now = datetime.now(timezone.utc)
        with engine.connect() as conn:
            conn.execute(
                table.insert().values(
                    _id=uuid.uuid4(),
                    _created_at=now,
                    _updated_at=now,
                    _state="active",
                    _deleted_at=now if deleted else None,
                    code=code,
                )
            )
            conn.commit()

    def test_unique_true_creates_index_and_enforces(self, engine):
        tm = TableManager(engine)
        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))

        assert self._index_oid(engine) is not None
        self._insert(engine, tm, "A")
        with pytest.raises(IntegrityError):
            self._insert(engine, tm, "A")

    def test_toggle_true_to_false_drops_index_and_allows_duplicates(self, engine):
        tm = TableManager(engine)
        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))
        self._insert(engine, tm, "A")

        tm.sync_schema(_widget_config(self.SCHEMA, unique=False))

        assert self._index_oid(engine) is None
        # This is the exact issue #56 symptom: before the fix, this duplicate
        # insert still raised IntegrityError even though config now says
        # unique: false.
        self._insert(engine, tm, "A")

    def test_toggle_false_to_true_creates_index_and_enforces(self, engine):
        tm = TableManager(engine)
        tm.sync_schema(_widget_config(self.SCHEMA, unique=False))
        self._insert(engine, tm, "A")

        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))

        assert self._index_oid(engine) is not None
        with pytest.raises(IntegrityError):
            self._insert(engine, tm, "A")

    def test_resync_unchanged_unique_true_is_idempotent(self, engine):
        tm = TableManager(engine)
        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))
        oid_before = self._index_oid(engine)

        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))
        oid_after = self._index_oid(engine)

        # Same physical index (not dropped and recreated) on a no-op re-sync.
        assert oid_before is not None
        assert oid_before == oid_after

    def test_toggle_survives_soft_deleted_duplicate(self, engine):
        """Interaction with issue #44's partial-index predicate: a duplicate
        value that only exists on a soft-deleted row must not block the index
        from being recreated when `unique` is toggled back on.
        """
        tm = TableManager(engine)
        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))
        self._insert(engine, tm, "A", deleted=True)

        tm.sync_schema(_widget_config(self.SCHEMA, unique=False))
        self._insert(engine, tm, "A")  # active row sharing "A" with the deleted one

        # Recreating the index must not fail even though two rows now share
        # "A" physically — the deleted one is excluded by the partial predicate.
        tm.sync_schema(_widget_config(self.SCHEMA, unique=True))
        assert self._index_oid(engine) is not None
