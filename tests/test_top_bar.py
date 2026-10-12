"""Template tests for the top bar and sidebar footer: grouping, active page, API Docs link.

Requires TEST_DATABASE_URL (the client fixture); the module is skipped otherwise.
"""
import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)

_USER_ID = "00000000-0000-0000-0000-0000000000c3"
_USERNAME = "top_bar_test_user"


def _engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _headers():
    from app.core.auth import create_token
    return {"Authorization": f"Bearer {create_token(_USER_ID, _USERNAME, is_admin=False)}"}


@pytest.fixture
def viewer(client):
    """A non-admin user with read-only access to the test schema."""
    from sqlalchemy import text

    from app.core.permissions import set_permission
    with _engine().connect() as conn:
        conn.execute(text("""
            INSERT INTO _system.users (id, username, password_hash, is_admin, is_active)
            VALUES (:id, :username, 'x', false, true)
            ON CONFLICT (id) DO NOTHING
        """), {"id": _USER_ID, "username": _USERNAME})
        conn.commit()
    set_permission(_engine(), _USER_ID, "test", can_read=True, can_write=False, can_publish=False)
    yield
    with _engine().connect() as conn:
        conn.execute(text("DELETE FROM _system.users WHERE id = :id"), {"id": _USER_ID})
        conn.commit()


def _top_bar(html: str) -> str:
    return html[html.index('<header class="mdm-top">'):html.index("</header>")]


def _sidebar(html: str) -> str:
    return html[html.index('<nav class="mdm-side"'):html.index("</nav>")]


def test_api_docs_link_is_in_the_sidebar_not_the_top_bar(client):
    html = client.get("/").text
    assert 'href="/docs"' not in _top_bar(html)
    assert 'href="/docs"' in _sidebar(html)


def test_api_docs_link_opens_in_new_tab_with_noopener(client):
    link = re.search(r'<a[^>]*href="/docs"[^>]*>', _sidebar(client.get("/").text)).group(0)
    assert 'target="_blank"' in link
    assert 'rel="noopener"' in link


def test_api_docs_link_is_visible_to_viewers(client, viewer):
    assert 'href="/docs"' in _sidebar(client.get("/", headers=_headers()).text)


def test_admin_top_bar_has_three_groups(client):
    assert _top_bar(client.get("/").text).count('class="mdm-top-group') == 3


def test_viewer_top_bar_has_no_work_group(client, viewer):
    """No Pending/Users/Audit Log for a Viewer, so no empty group (and no stray divider)."""
    top = _top_bar(client.get("/", headers=_headers()).text)
    assert top.count('class="mdm-top-group') == 2
    assert 'href="/pending"' not in top
    assert 'href="/admin/users"' not in top


@pytest.mark.parametrize("path, href", [
    ("/pending", "/pending"),
    ("/admin/users", "/admin/users"),
    ("/admin/audit", "/admin/audit"),
])
def test_current_page_link_is_marked(client, path, href):
    top = _top_bar(client.get(path).text)
    current = re.findall(r'<a[^>]*aria-current="page"[^>]*>', top)
    assert len(current) == 1
    assert f'href="{href}"' in current[0]


def test_no_top_bar_link_is_marked_on_other_pages(client):
    assert "aria-current" not in _top_bar(client.get("/").text)


def test_theme_button_exposes_pressed_state(client):
    top = _top_bar(client.get("/").text)
    assert 'id="theme-btn"' in top
    assert "aria-pressed" in top
