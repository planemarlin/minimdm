"""Integration tests for GET /api/object-counts (sidebar + home page record counts).

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import os

import pytest

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set – skipping integration tests",
    ),
    pytest.mark.usefixtures("clean_records"),
]

_USER_ID = "00000000-0000-0000-0000-0000000000c1"
_USERNAME = "counts_test_user"


def _engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _headers():
    from app.core.auth import create_token
    return {"Authorization": f"Bearer {create_token(_USER_ID, _USERNAME, is_admin=False)}"}


@pytest.fixture(autouse=True)
def counts_user(client):
    """A non-admin user whose permissions each test sets explicitly."""
    from sqlalchemy import text
    with _engine().connect() as conn:
        conn.execute(text("""
            INSERT INTO _system.users (id, username, password_hash, is_admin, is_active)
            VALUES (:id, :username, 'x', false, true)
            ON CONFLICT (id) DO NOTHING
        """), {"id": _USER_ID, "username": _USERNAME})
        conn.commit()
    yield
    with _engine().connect() as conn:
        conn.execute(text("DELETE FROM _system.users WHERE id = :id"), {"id": _USER_ID})
        conn.commit()


def _grant(*, read=True, write=False, publish=False):
    from app.core.permissions import set_permission
    set_permission(_engine(), _USER_ID, "test", can_read=read, can_write=write, can_publish=publish)


def _seed(client):
    """2 active companies (+1 deleted), 1 active + 2 draft governed items."""
    client.post("/api/records/test/company", json={"code": "C1"})
    client.post("/api/records/test/company", json={"code": "C2"})
    deleted = client.post("/api/records/test/company", json={"code": "C3"}).json()["id"]
    client.delete(f"/api/records/test/company/{deleted}")
    published = client.post("/api/records/test/governed_item", json={"code": "G1"}).json()["id"]
    client.post(f"/api/records/test/governed_item/{published}/publish")
    client.post("/api/records/test/governed_item", json={"code": "G2"})
    client.post("/api/records/test/governed_item", json={"code": "G3"})


def test_admin_sees_active_and_pending_counts(client):
    _seed(client)
    res = client.get("/api/object-counts")
    assert res.status_code == 200
    objects = res.json()["schemas"]["test"]
    assert objects["company"] == {"active": 2, "pending": 0}
    assert objects["governed_item"] == {"active": 1, "pending": 2}


def test_every_configured_object_is_listed_with_zero_counts(client):
    objects = client.get("/api/object-counts").json()["schemas"]["test"]
    assert objects["company"] == {"active": 0, "pending": 0}
    assert set(objects) >= {"company", "division", "contact", "governed_item", "reference_data"}


def test_soft_deleted_records_are_not_counted(client):
    rid = client.post("/api/records/test/company", json={"code": "D1"}).json()["id"]
    assert client.get("/api/object-counts").json()["schemas"]["test"]["company"]["active"] == 1
    client.delete(f"/api/records/test/company/{rid}")
    assert client.get("/api/object-counts").json()["schemas"]["test"]["company"]["active"] == 0


def test_editing_active_record_counts_one_active_and_one_pending(client):
    """The draft-copy of an edited golden record is pending; the golden record stays active."""
    rid = client.post("/api/records/test/company", json={"code": "E1", "name": "Old"}).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "New"})
    counts = client.get("/api/object-counts").json()["schemas"]["test"]["company"]
    assert counts == {"active": 1, "pending": 1}


def test_viewer_gets_active_counts_only(client):
    _seed(client)
    _grant(read=True)
    res = client.get("/api/object-counts", headers=_headers())
    assert res.status_code == 200
    objects = res.json()["schemas"]["test"]
    assert objects["company"] == {"active": 2}
    assert objects["governed_item"] == {"active": 1}


def test_editor_gets_active_counts_only(client):
    _seed(client)
    _grant(read=True, write=True)
    objects = client.get("/api/object-counts", headers=_headers()).json()["schemas"]["test"]
    assert objects["governed_item"] == {"active": 1}


def test_publisher_gets_pending_counts(client):
    _seed(client)
    _grant(read=True, write=True, publish=True)
    objects = client.get("/api/object-counts", headers=_headers()).json()["schemas"]["test"]
    assert objects["company"] == {"active": 2, "pending": 0}
    assert objects["governed_item"] == {"active": 1, "pending": 2}


def test_user_without_access_sees_no_schemas(client):
    _seed(client)
    res = client.get("/api/object-counts", headers=_headers())
    assert res.status_code == 200
    assert res.json() == {"schemas": {}}


def test_unauthenticated_request_is_rejected(client):
    res = client.get("/api/object-counts", headers={"Authorization": ""})
    assert res.status_code == 401
