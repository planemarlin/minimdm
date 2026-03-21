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
