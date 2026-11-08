"""Server-rendered parts of the Duplicates UI: the top-bar link, the review page, and the
notice container on a record's page.

The link and the page skeleton are rendered by the server, and only the count is filled in
by JavaScript. That is what keeps the top bar from flickering, so these tests look at the
raw HTML response, where no JavaScript has run.
"""
import json
import os
import re

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set – skipping integration tests",
    ),
    pytest.mark.usefixtures("clean_records"),
]

_USER_ID = "00000000-0000-0000-0000-0000000000e1"
_USERNAME = "dup_page_test_user"
_LINK = 'id="duplicates-badge-link"'


def _engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _headers():
    from app.core.auth import create_token
    return {"Authorization": f"Bearer {create_token(_USER_ID, _USERNAME, is_admin=False)}"}


@pytest.fixture(autouse=True)
def page_user(client):
    with _engine().connect() as conn:
        conn.execute(text("""
            INSERT INTO _system.users (id, username, password_hash, is_admin, is_active)
            VALUES (:id, :username, 'x', false, true) ON CONFLICT (id) DO NOTHING
        """), {"id": _USER_ID, "username": _USERNAME})
        conn.commit()
    yield
    with _engine().connect() as conn:
        conn.execute(text("DELETE FROM _system.users WHERE id = :id"), {"id": _USER_ID})
        conn.commit()


def _grant(*, read=True, write=False, publish=False):
    from app.core.permissions import set_permission
    set_permission(_engine(), _USER_ID, "test", can_read=read, can_write=write,
                   can_publish=publish)


def _top_bar(html: str) -> str:
    return html[html.index('<header class="mdm-top">'):html.index("</header>")]


def _config(html: str) -> list:
    raw = re.search(r'<script type="application/json" id="dup-config">(.*?)</script>', html, re.S)
    return json.loads(raw.group(1))


# --- top-bar link ---------------------------------------------------------------------

def test_admin_top_bar_has_the_duplicates_link_in_the_work_group(client):
    top = _top_bar(client.get("/").text)
    assert _LINK in top
    assert top.index('href="/pending"') < top.index(_LINK) < top.index('href="/admin/users"')
    assert top.count('class="mdm-top-group') == 3     # still work | icons | account


def test_the_count_is_rendered_hidden_so_filling_it_in_moves_nothing(client):
    top = _top_bar(client.get("/").text)
    count = re.search(r'<span[^>]*id="duplicates-badge-count"[^>]*>', top).group(0)
    assert " hidden" in count and "mdm-top-duplicates-count" in count
    # The link reserves room for the absolutely positioned count (same as Pending)
    link = re.search(r'<a[^>]*id="duplicates-badge-link"[^>]*>', top).group(0)
    assert "mdm-top-duplicates" in link
    css = open("app/static/css/tokens.css", encoding="utf-8").read()
    assert re.search(r"\.mdm-top-duplicates\s*\{\s*padding-right:\s*18px", css)
    assert re.search(r"\.mdm-top-duplicates-count\s*\{[^}]*position:\s*absolute", css)


@pytest.mark.parametrize("grant, visible", [
    (dict(read=True), False),                              # Viewer
    (dict(read=True, write=True), True),                   # Editor
    (dict(read=True, write=True, publish=True), True),     # Publisher
])
def test_duplicates_link_is_for_users_who_can_write(client, grant, visible):
    _grant(**grant)
    assert (_LINK in _top_bar(client.get("/", headers=_headers()).text)) is visible


def test_viewer_top_bar_stays_without_a_work_group(client):
    _grant(read=True)
    assert _top_bar(client.get("/", headers=_headers()).text).count('class="mdm-top-group') == 2


def test_current_page_is_marked_on_the_duplicates_page(client):
    top = _top_bar(client.get("/duplicates").text)
    current = re.findall(r'<a[^>]*aria-current="page"[^>]*>', top)
    assert len(current) == 1 and 'href="/duplicates"' in current[0]


# --- the page -------------------------------------------------------------------------

def test_admin_page_has_a_section_per_object_with_rules_and_rescan_buttons(client):
    html = client.get("/duplicates").text
    for obj in ("dup_item", "dup_governed_item", "dup_audited_item"):
        assert f'id="test-{obj}"' in html
    assert 'id="test-company"' not in html           # no rules, no section
    assert html.count("dup-rescan-btn") == 3         # admin only
    assert 'id="dup-status-seg"' in html
    assert 'id="dup-open-count"' in html and 'id="dup-dismissed-count"' in html
    # Same plain-text schema tag as the Pending page, not a pill
    assert '<span class="schema">TEST</span>' in html


def test_editor_page_has_no_rescan_button(client):
    _grant(read=True, write=True)
    res = client.get("/duplicates", headers=_headers())
    assert res.status_code == 200
    assert 'id="test-dup_item"' in res.text and "dup-rescan-btn" not in res.text


@pytest.mark.parametrize("grant", [dict(read=True), None])
def test_viewers_and_users_without_access_are_refused(client, grant):
    from app.core.permissions import delete_permission
    if grant:
        _grant(**grant)
    else:
        delete_permission(_engine(), _USER_ID, "test")
    res = client.get("/duplicates", headers=_headers())
    assert res.status_code == 403 and "write access" in res.text


def test_page_config_names_the_columns_and_marks_the_rule_fields(client):
    by_obj = {c["key"]: c for c in _config(client.get("/duplicates").text)}
    item = by_obj["dup_item"]
    assert item["schema"] == "test" and item["name"] == "Dup Item"
    assert [r["name"] for r in item["rules"]] == ["Same email", "Same phone"]
    cols = {c["key"]: c for c in item["columns"]}
    assert cols["email"]["rule"] is True and cols["phone"]["rule"] is True
    assert cols["code"]["rule"] is False
    assert item["label_key"] == "code" and item["require_reason"] is False
    assert by_obj["dup_audited_item"]["require_reason"] is True


# --- notice on a record's page --------------------------------------------------------

def _record(client, obj="dup_item", **values):
    res = client.post(f"/api/records/test/{obj}", json=values)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_record_page_has_the_banner_container_for_writers(client):
    rid = _record(client, email="a@x.com")
    html = client.get(f"/test/dup_item/{rid}").text
    box = re.search(r'<div id="duplicate-banner"[^>]*>', html).group(0)
    assert " hidden" in box and f'data-record="{rid}"' in box
    assert 'data-schema="test"' in box and 'data-obj="dup_item"' in box
    assert 'data-label-key="code"' in box


def test_record_page_has_no_banner_for_viewers_or_objects_without_rules(client):
    rid = _record(client, email="a@x.com")
    company = _record(client, "company", code="C1")
    assert "duplicate-banner" not in client.get(f"/test/company/{company}").text

    _grant(read=True)
    assert "duplicate-banner" not in client.get(f"/test/dup_item/{rid}", headers=_headers()).text
