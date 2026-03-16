"""Integration tests for schema-based access control.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NON_ADMIN_USER_ID = "00000000-0000-0000-0000-000000000099"
_NON_ADMIN_USERNAME = "perm_test_user"


def _get_engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _non_admin_headers():
    from app.core.auth import create_token
    token = create_token(_NON_ADMIN_USER_ID, _NON_ADMIN_USERNAME, is_admin=False)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers():
    from app.core.auth import create_token, get_user_by_username
    engine = _get_engine()
    user = get_user_by_username(engine, "test_admin")
    user_id = str(user["id"]) if user else "00000000-0000-0000-0000-000000000001"
    token = create_token(user_id, "test_admin", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


def _create_non_admin_user(engine):
    """Insert a non-admin user row so foreign key for permissions table works."""
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO _system.users (id, username, password_hash, is_admin, is_active)
            VALUES (:id, :username, 'x', false, true)
            ON CONFLICT (id) DO NOTHING
        """), {"id": _NON_ADMIN_USER_ID, "username": _NON_ADMIN_USERNAME})
        conn.commit()


def _cleanup_non_admin_user(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM _system.users WHERE id = :id"), {"id": _NON_ADMIN_USER_ID})
        conn.commit()


@pytest.fixture(autouse=True)
def setup_non_admin_user(client):
    """Create and then clean up the non-admin test user for each test."""
    engine = _get_engine()
    _create_non_admin_user(engine)
    yield
    _cleanup_non_admin_user(engine)


def _clear_permissions(engine):
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM _system.schema_permissions WHERE user_id = :id"), {"id": _NON_ADMIN_USER_ID})
        conn.commit()


# ---------------------------------------------------------------------------
# Permission endpoint tests (admin-only)
# ---------------------------------------------------------------------------

def test_get_permissions_requires_admin(client):
    res = client.get(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions",
                     headers=_non_admin_headers())
    assert res.status_code == 403


def test_get_permissions_returns_empty_by_default(client):
    res = client.get(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions")
    assert res.status_code == 200
    assert res.json() == []


def test_set_permission_creates_row(client):
    res = client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    assert res.status_code == 200

    res2 = client.get(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions")
    perms = res2.json()
    assert any(p["schema_name"] == "test" and p["can_read"] and not p["can_write"] for p in perms)

    _clear_permissions(_get_engine())


def test_set_permission_updates_existing_row(client):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": True},
    )
    res = client.get(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions")
    perms = res.json()
    assert any(p["schema_name"] == "test" and p["can_write"] for p in perms)
    _clear_permissions(engine)


def test_delete_permission_removes_row(client):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    res = client.delete(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test")
    assert res.status_code == 204

    res2 = client.get(f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions")
    assert res2.json() == []


def test_set_permission_on_unknown_user_returns_404(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    res = client.put(
        f"/api/admin/users/{fake_id}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Access enforcement — non-admin with no permission
# ---------------------------------------------------------------------------

def test_non_admin_without_permission_cannot_list_records(client):
    res = client.get("/api/records/test/company", headers=_non_admin_headers())
    assert res.status_code == 403


def test_non_admin_without_permission_cannot_get_record(client):
    fake_id = str(uuid.uuid4())
    res = client.get(f"/api/records/test/company/{fake_id}", headers=_non_admin_headers())
    assert res.status_code == 403


def test_non_admin_without_permission_cannot_create_record(client):
    res = client.post("/api/records/test/company",
                      json={"code": "X"},
                      headers=_non_admin_headers())
    assert res.status_code == 403


def test_non_admin_without_permission_cannot_export(client):
    res = client.get("/api/records/test/company/export", headers=_non_admin_headers())
    assert res.status_code == 403


def test_non_admin_without_permission_cannot_access_schema_endpoint(client):
    res = client.get("/api/schemas/test", headers=_non_admin_headers())
    assert res.status_code == 403


def test_non_admin_without_permission_schema_not_in_list(client):
    res = client.get("/api/schemas", headers=_non_admin_headers())
    assert res.status_code == 200
    names = [s["name"] for s in res.json()]
    assert "test" not in names


# ---------------------------------------------------------------------------
# Access enforcement — non-admin with read permission
# ---------------------------------------------------------------------------

def test_non_admin_with_read_permission_can_list_records(client):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    res = client.get("/api/records/test/company", headers=_non_admin_headers())
    assert res.status_code == 200
    _clear_permissions(engine)


def test_non_admin_with_read_permission_cannot_create_record(client):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    res = client.post("/api/records/test/company",
                      json={"code": "READONLY"},
                      headers=_non_admin_headers())
    assert res.status_code == 403
    _clear_permissions(engine)


def test_non_admin_with_read_permission_schema_in_list(client):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": False},
    )
    res = client.get("/api/schemas", headers=_non_admin_headers())
    names = [s["name"] for s in res.json()]
    assert "test" in names
    _clear_permissions(engine)


# ---------------------------------------------------------------------------
# Access enforcement — non-admin with write permission
# ---------------------------------------------------------------------------

def test_non_admin_with_write_permission_can_create_record(client, clean_records):
    engine = _get_engine()
    client.put(
        f"/api/admin/users/{_NON_ADMIN_USER_ID}/permissions/test",
        json={"can_read": True, "can_write": True},
    )
    res = client.post("/api/records/test/company",
                      json={"code": "WRITABLE"},
                      headers=_non_admin_headers())
    assert res.status_code == 201
    _clear_permissions(engine)


# ---------------------------------------------------------------------------
# Admins always have full access
# ---------------------------------------------------------------------------

def test_admin_always_has_access_without_permission_row(client):
    # The admin token (set up in conftest) should always pass
    res = client.get("/api/records/test/company")
    assert res.status_code == 200


def test_admin_sees_all_schemas(client):
    res = client.get("/api/schemas")
    assert res.status_code == 200
    names = [s["name"] for s in res.json()]
    assert "test" in names
