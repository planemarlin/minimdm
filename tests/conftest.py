import hashlib
import os
import secrets

# Override DATABASE_URL with the test database URL before any app module is
# imported (app.database creates the engine at import time via settings).
_test_db_url = os.environ.get("TEST_DATABASE_URL")
if _test_db_url:
    os.environ["DATABASE_URL"] = _test_db_url
    os.environ["RATE_LIMIT_ENABLED"] = "false"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

SAMPLE_CONFIG = {
    "schemas": {
        "test": {
            "objects": {
                "company": {
                    "name": "Company",
                    "description": "Test company",
                    "owner": "Data Team",
                    "steward": "alice@example.com",
                    "parent": None,
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "unique": True, "reference": None},  # noqa: E501
                        "name": {"name": "Name", "type": "string", "required": False, "unique": False, "reference": None},  # noqa: E501
                    },
                    "inbound_sources": [
                        {
                            "name": "test_erp",
                            "field_map": {
                                "erp_id": "_source_id",
                                "company_name": "name",
                                "company_code": "code",
                            },
                            "match_key": "code",
                        }
                    ],
                },
                "division": {
                    "name": "Division",
                    "description": "Test division",
                    "parent": "company",
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "unique": False, "reference": None},  # noqa: E501
                    },
                },
                "contact": {
                    "name": "Contact",
                    "description": "Test contact with a reference to company",
                    "parent": None,
                    "attributes": {
                        "name": {"name": "Name", "type": "string", "required": True, "unique": False, "reference": None},  # noqa: E501
                        "company": {"name": "Company", "type": "string", "required": False, "unique": False, "reference": "company"},  # noqa: E501
                    },
                },
                # Policy flag test objects
                "governed_item": {
                    "name": "Governed Item",
                    "description": "requires_draft: true — always starts as draft",
                    "parent": None,
                    "requires_draft": True,
                    "allow_retire": True,
                    "allow_direct_active_import": True,
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "unique": False, "reference": None},  # noqa: E501
                    },
                },
                "reference_data": {
                    "name": "Reference Data",
                    "description": "allow_retire: false; allow_direct_active_import: false",
                    "parent": None,
                    "requires_draft": False,
                    "allow_retire": False,
                    "allow_direct_active_import": False,
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "unique": False, "reference": None},  # noqa: E501
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

    from app.core.auth import create_token
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        tm = fastapi_app.state.table_manager
        # Replace whatever config was loaded from YAML with the test config.
        tm.sync_schema(SAMPLE_CONFIG)
        fastapi_app.state.app_config = SAMPLE_CONFIG

        # Create a real test_admin user so is_user_active() passes in the auth middleware.
        from app.core.auth import create_user, get_user_by_username
        existing = get_user_by_username(tm.engine, "test_admin")
        if existing:
            admin_id = str(existing["id"])
        else:
            result = create_user(tm.engine, "test_admin", "test_password", is_admin=True)
            admin_id = result["id"]
        token = create_token(admin_id, "test_admin", is_admin=True)
        c.headers.update({"Authorization": f"Bearer {token}"})

        yield c

        # Teardown: remove the test schema and the test admin user.
        with tm.engine.connect() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "test" CASCADE'))
            conn.execute(text("DELETE FROM _system.users WHERE username = 'test_admin'"))
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
        conn.execute(text('DELETE FROM "test"."governed_item_history"'))
        conn.execute(text('DELETE FROM "test"."governed_item"'))
        conn.execute(text('DELETE FROM "test"."reference_data_history"'))
        conn.execute(text('DELETE FROM "test"."reference_data"'))
        conn.execute(text("DELETE FROM _system.audit_log WHERE schema_name = 'test'"))
        conn.commit()
    yield


@pytest.fixture
def sample_config():
    return SAMPLE_CONFIG


@pytest.fixture
def inbound_key(client):
    """Insert a test inbound API key for the 'test_erp' source and yield the raw key.

    Cleans up the key after the test.
    """
    from datetime import datetime, timezone

    from app.main import app as fastapi_app
    tm = fastapi_app.state.table_manager
    table = tm.get_inbound_keys_table()

    import uuid
    raw_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_id = uuid.uuid4()

    with tm.engine.connect() as conn:
        conn.execute(table.insert().values(
            id=key_id,
            schema_name="test",
            source_name="test_erp",
            key_prefix=raw_key[:8],
            key_hash=key_hash,
            description="Test key",
            created_at=datetime.now(timezone.utc),
            last_used_at=None,
            is_active=True,
        ))
        conn.commit()

    yield raw_key

    with tm.engine.connect() as conn:
        conn.execute(table.delete().where(table.c.id == key_id))
        conn.commit()
