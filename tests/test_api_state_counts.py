"""Integration tests for GET /api/records/{schema}/{obj}/state-counts
(the counts on the list page's state tabs and next to "Show deleted").

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

_USER_ID = "00000000-0000-0000-0000-0000000000c2"
_USERNAME = "state_counts_test_user"
_URL = "/api/records/test/company/state-counts"


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


def _company(client, code):
    res = client.post("/api/records/test/company", json={"code": code, "name": code})
    assert res.status_code == 201
    return res.json()["id"]


def _seed(client):
    """3 active (1 of them deleted), 1 pending edit draft, 2 retired (1 of them deleted)."""
    _company(client, "A1")
    a2 = _company(client, "A2")
    a3 = _company(client, "A3")
    client.delete(f"/api/records/test/company/{a3}")
    client.put(f"/api/records/test/company/{a2}", json={"name": "edited"})  # draft copy of A2
    r1 = _company(client, "R1")
    r2 = _company(client, "R2")
    client.post(f"/api/records/test/company/{r1}/retire")
    client.post(f"/api/records/test/company/{r2}/retire")
    client.delete(f"/api/records/test/company/{r2}")


def test_counts_each_state_and_deleted(client):
    _seed(client)
    res = client.get(_URL)
    assert res.status_code == 200
    assert res.json() == {
        "states": {"active": 2, "draft": 1, "retired": 1},
        "deleted": {"active": 1, "draft": 0, "retired": 1},
    }


def test_empty_object_has_all_zero_counts(client):
    zeros = {"active": 0, "draft": 0, "retired": 0}
    assert client.get(_URL).json() == {"states": zeros, "deleted": zeros}


def test_counts_match_the_list_endpoint(client):
    """Each tab count equals the list total for that state; the deleted count is what
    ticking "Show deleted" adds to it."""
    _seed(client)
    counts = client.get(_URL).json()
    base = "/api/records/test/company"
    for state in ("active", "draft", "retired"):
        live = client.get(f"{base}?state={state}").json()["total"]
        with_deleted = client.get(f"{base}?state={state}&include_deleted=true").json()["total"]
        assert counts["states"][state] == live
        assert counts["deleted"][state] == with_deleted - live
    all_live = client.get(f"{base}?state=all").json()["total"]
    all_with_deleted = client.get(f"{base}?state=all&include_deleted=true").json()["total"]
    assert sum(counts["states"].values()) == all_live
    assert sum(counts["deleted"].values()) == all_with_deleted - all_live


def test_published_edit_draft_is_not_counted_as_deleted(client):
    """Publishing soft-deletes the edit draft; that workflow artifact is not a user delete."""
    rid = _company(client, "P1")
    draft_id = client.put(f"/api/records/test/company/{rid}", json={"name": "v2"}).json()["id"]
    assert client.get(_URL).json()["states"] == {"active": 1, "draft": 1, "retired": 0}
    client.post(f"/api/records/test/company/{draft_id}/publish")
    counts = client.get(_URL).json()
    assert counts["states"] == {"active": 1, "draft": 0, "retired": 0}
    assert counts["deleted"] == {"active": 0, "draft": 0, "retired": 0}


def test_deleted_standalone_draft_counts_as_deleted(client):
    """A draft created from scratch (no active record behind it) that a user deletes."""
    draft_id = client.post(
        "/api/records/test/governed_item", json={"code": "G1"}
    ).json()["id"]
    url = "/api/records/test/governed_item/state-counts"
    assert client.get(url).json()["states"]["draft"] == 1
    client.delete(f"/api/records/test/governed_item/{draft_id}")
    counts = client.get(url).json()
    assert counts["states"]["draft"] == 0
    assert counts["deleted"]["draft"] == 1


def test_counts_refresh_after_create_edit_and_publish(client):
    """Counts are computed live, so they follow every lifecycle step."""
    def states():
        return client.get(_URL).json()["states"]

    assert states() == {"active": 0, "draft": 0, "retired": 0}
    rid = _company(client, "L1")
    assert states() == {"active": 1, "draft": 0, "retired": 0}
    draft_id = client.put(f"/api/records/test/company/{rid}", json={"name": "v2"}).json()["id"]
    assert states() == {"active": 1, "draft": 1, "retired": 0}
    client.post(f"/api/records/test/company/{draft_id}/publish")
    assert states() == {"active": 1, "draft": 0, "retired": 0}
    client.post(f"/api/records/test/company/{rid}/retire")
    assert states() == {"active": 0, "draft": 0, "retired": 1}


# ---------------------------------------------------------------------------
# Per-role access: anyone who can read the schema sees the full breakdown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "perms",
    [
        {"read": True},
        {"read": True, "write": True},
        {"read": True, "write": True, "publish": True},
    ],
    ids=["viewer", "editor", "publisher"],
)
def test_every_role_with_read_access_gets_the_full_breakdown(client, perms):
    _seed(client)
    _grant(**perms)
    res = client.get(_URL, headers=_headers())
    assert res.status_code == 200
    assert res.json() == {
        "states": {"active": 2, "draft": 1, "retired": 1},
        "deleted": {"active": 1, "draft": 0, "retired": 1},
    }


def test_user_without_access_is_forbidden(client):
    _seed(client)
    assert client.get(_URL, headers=_headers()).status_code == 403


def test_unauthenticated_request_is_rejected(client):
    assert client.get(_URL, headers={"Authorization": ""}).status_code == 401


def test_unknown_object_is_404(client):
    assert client.get("/api/records/test/nope/state-counts").status_code == 404
