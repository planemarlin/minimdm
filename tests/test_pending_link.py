"""Integration tests for the top-bar Pending link and GET /api/pending-count.

The link is for users who can publish (and admins); the count covers only the
schemas where the user may publish. Requires TEST_DATABASE_URL; the module is
skipped otherwise.
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
_USERNAME = "pending_link_test_user"
_LINK = 'id="pending-badge-link"'


def _engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _headers():
    from app.core.auth import create_token
    return {"Authorization": f"Bearer {create_token(_USER_ID, _USERNAME, is_admin=False)}"}


@pytest.fixture(autouse=True)
def pending_user(client):
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


def _seed_drafts(client, n=2):
    for i in range(n):
        client.post("/api/records/test/governed_item", json={"code": f"PL{i}"}).raise_for_status()


# ---------------------------------------------------------------------------
# /api/pending-count
# ---------------------------------------------------------------------------

def test_admin_count_includes_drafts(client):
    _seed_drafts(client, 2)
    assert client.get("/api/pending-count").json() == {"total": 2}


def test_publisher_count_includes_drafts(client):
    _seed_drafts(client, 3)
    _grant(read=True, write=True, publish=True)
    assert client.get("/api/pending-count", headers=_headers()).json() == {"total": 3}


def test_editor_count_is_zero(client):
    _seed_drafts(client)
    _grant(read=True, write=True)
    assert client.get("/api/pending-count", headers=_headers()).json() == {"total": 0}


def test_viewer_count_is_zero(client):
    _seed_drafts(client)
    _grant(read=True)
    assert client.get("/api/pending-count", headers=_headers()).json() == {"total": 0}


def test_user_without_access_count_is_zero(client):
    _seed_drafts(client)
    assert client.get("/api/pending-count", headers=_headers()).json() == {"total": 0}


def test_soft_deleted_drafts_are_not_counted(client):
    _seed_drafts(client, 2)
    rid = client.post("/api/records/test/governed_item", json={"code": "PLX"}).json()["id"]
    client.delete(f"/api/records/test/governed_item/{rid}")
    assert client.get("/api/pending-count").json() == {"total": 2}


def test_count_is_zero_without_drafts(client):
    assert client.get("/api/pending-count").json() == {"total": 0}


# ---------------------------------------------------------------------------
# Top-bar link
# ---------------------------------------------------------------------------

def test_admin_sees_pending_link_even_without_drafts(client):
    res = client.get("/")
    assert _LINK in res.text
    assert 'href="/pending"' in res.text


def test_publisher_sees_pending_link_even_without_drafts(client):
    _grant(read=True, write=True, publish=True)
    assert _LINK in client.get("/", headers=_headers()).text


def test_editor_does_not_see_pending_link(client):
    _grant(read=True, write=True)
    assert _LINK not in client.get("/", headers=_headers()).text


def test_viewer_does_not_see_pending_link(client):
    _grant(read=True)
    assert _LINK not in client.get("/", headers=_headers()).text


def test_pending_link_comes_first_in_top_bar(client):
    html = client.get("/").text
    top = html[html.index('<header class="mdm-top">'):]
    assert top.index(_LINK) < top.index('href="/admin/users"') < top.index('href="/docs"')


def test_pending_page_still_renders_for_viewer(client):
    """Only the link is hidden; the page itself is not restricted."""
    _grant(read=True)
    assert client.get("/pending", headers=_headers()).status_code == 200
