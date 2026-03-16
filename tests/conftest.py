import os

# Override DATABASE_URL with the test database URL before any app module is
# imported (app.database creates the engine at import time via settings).
_test_db_url = os.environ.get("TEST_DATABASE_URL")
if _test_db_url:
    os.environ["DATABASE_URL"] = _test_db_url

import pytest
from sqlalchemy import text

from app.core.table_manager import TableManager

SAMPLE_CONFIG = {
    "schemas": {
        "test": {
            "objects": {
                "company": {
                    "name": "Company",
                    "description": "Test company",
                    "parent": None,
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "reference": None},
                        "name": {"name": "Name", "type": "string", "required": False, "reference": None},
                    },
                },
                "division": {
                    "name": "Division",
                    "description": "Test division",
                    "parent": "company",
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "reference": None},
                    },
                },
                "contact": {
                    "name": "Contact",
                    "description": "Test contact with a reference to company",
                    "parent": None,
                    "attributes": {
                        "name": {"name": "Name", "type": "string", "required": True, "reference": None},
                        "company": {"name": "Company", "type": "string", "required": False, "reference": "company"},
                    },
                },
            }
        }
    }
}


@pytest.fixture(scope="session")
def client():
    """Session-scoped TestClient backed by a real PostgreSQL test database.

    Requires TEST_DATABASE_URL to be set; tests are skipped otherwise.
    The 'test' schema is created fresh and dropped after the session.
    """
    if not _test_db_url:
        pytest.skip("TEST_DATABASE_URL not set – skipping integration tests")

    from fastapi.testclient import TestClient
    from app.main import app as fastapi_app
    from app.core.auth import create_token

    with TestClient(fastapi_app) as c:
        # Inject a test admin token so all requests pass through AuthMiddleware.
        token = create_token("00000000-0000-0000-0000-000000000001", "test_admin", is_admin=True)
        c.headers.update({"Authorization": f"Bearer {token}"})

        tm = fastapi_app.state.table_manager
        # Replace whatever config was loaded from YAML with the test config.
        tm.sync_schema(SAMPLE_CONFIG)
        fastapi_app.state.app_config = SAMPLE_CONFIG
        yield c

        # Teardown: remove the test schema from the database.
        with tm.engine.connect() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "test" CASCADE'))
            conn.commit()


@pytest.fixture
def clean_records(client):
    """Truncate all test-schema records before each test that uses this fixture."""
    from app.main import app as fastapi_app
    tm = fastapi_app.state.table_manager
    with tm.engine.connect() as conn:
        conn.execute(text('DELETE FROM "test"."contact_history"'))
        conn.execute(text('DELETE FROM "test"."contact"'))
        conn.execute(text('DELETE FROM "test"."division_history"'))
        conn.execute(text('DELETE FROM "test"."division"'))
        conn.execute(text('DELETE FROM "test"."company_history"'))
        conn.execute(text('DELETE FROM "test"."company"'))
        conn.execute(text("DELETE FROM _system.audit_log WHERE schema_name = 'test'"))
        conn.commit()
    yield


@pytest.fixture
def sample_config():
    return SAMPLE_CONFIG
