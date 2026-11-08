"""Review API for duplicate detection (/api/duplicates/...) and the sidebar counts.

Covers listing/filtering/pagination, dismiss and reopen (including who may do it, per
`duplicates.dismissed_by`), the per-record lookup, scan status and rescan, and the
`duplicates` figure in /api/object-counts, for every role.
"""
import os
import uuid

import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="TEST_DATABASE_URL not set",
    ),
    pytest.mark.usefixtures("clean_records"),
]

ITEM = "dup_item"            # dismissed_by: editor (default)
GOVERNED = "dup_governed_item"  # dismissed_by: publisher
_USER_ID = "00000000-0000-0000-0000-0000000000d1"
_USERNAME = "dup_review_user"


def _engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _headers():
    from app.core.auth import create_token
    return {"Authorization": f"Bearer {create_token(_USER_ID, _USERNAME, is_admin=False)}"}


@pytest.fixture(autouse=True)
def review_user(client):
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


def _create(client, obj, **values):
    res = client.post(f"/api/records/test/{obj}", json=values)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _pair(client, obj=ITEM, email="a@x.com"):
    return _create(client, obj, email=email), _create(client, obj, email=email)


def _groups(client, obj=ITEM, **params):
    res = client.get(f"/api/duplicates/test/{obj}", params=params)
    assert res.status_code == 200, res.text
    return res.json()


def _flag_ids(client, obj=ITEM, **params):
    return [m["flag_id"] for g in _groups(client, obj, **params)["groups"] for m in g["members"]]


def _audit_actions(action):
    with _engine().connect() as conn:
        return conn.execute(text(
            "SELECT count(*) FROM _system.audit_log WHERE schema_name = 'test' AND action = :a"),
            {"a": action}).scalar()


# --- listing -------------------------------------------------------------------------

def test_lists_groups_with_member_records(client):
    a, b = _pair(client)
    _create(client, ITEM, email="other@x.com")

    data = _groups(client)
    assert data["total"] == 1 and data["status"] == "open"
    assert data["counts"] == {"open": 1, "dismissed": 0}
    assert data["rules"] == ["Same email", "Same phone"]
    assert data["can_dismiss"] is True
    (group,) = data["groups"]
    assert group["rule"] == "Same email" and group["fields"] == ["email"]
    assert group["value"] == "a x com"      # the normalised match key, for reference only
    assert {m["entity_id"] for m in group["members"]} == {a, b}
    member = group["members"][0]
    assert member["status"] == "open" and member["has_draft"] is False
    assert member["record"]["email"] == "a@x.com" and member["record"]["_state"] == "active"


def test_a_draft_copy_is_shown_through_its_golden_record(client):
    a, b = _pair(client, email="a@x.com")
    res = client.put(f"/api/records/test/{ITEM}/{a}", json={"phone": "123"})
    assert res.status_code == 200
    members = {m["entity_id"]: m for m in _groups(client)["groups"][0]["members"]}
    assert members[a]["has_draft"] is True and members[b]["has_draft"] is False


def test_pagination_and_totals(client):
    for i in range(3):
        _pair(client, email=f"p{i}@x.com")
    page1 = _groups(client, limit=2, offset=0)
    page2 = _groups(client, limit=2, offset=2)
    assert page1["total"] == page2["total"] == 3
    assert page1["counts"] == page2["counts"] == {"open": 3, "dismissed": 0}
    assert len(page1["groups"]) == 2 and len(page2["groups"]) == 1
    assert not {g["match_hash"] for g in page1["groups"]} & {
        g["match_hash"] for g in page2["groups"]}


def test_flags_of_removed_rules_are_ignored(client):
    a, b = _pair(client)
    now = "now()"
    with _engine().begin() as conn:
        for entity in (a, b):
            conn.execute(text(
                "INSERT INTO _system.duplicate_flags (id, schema_name, object_name, rule_name, "
                "entity_id, match_hash, status, created_at, updated_at) "
                f"VALUES (gen_random_uuid(), 'test', :o, 'Removed rule', :e, 'h', 'open', "
                f"{now}, {now})"), {"o": ITEM, "e": entity})
    assert [g["rule"] for g in _groups(client)["groups"]] == ["Same email"]


def test_object_without_rules_lists_nothing(client):
    res = client.get("/api/duplicates/test/company")
    assert res.status_code == 200
    assert res.json()["groups"] == [] and res.json()["rules"] == []


def test_unknown_object_and_bad_parameters(client):
    assert client.get("/api/duplicates/test/nope").status_code == 404
    assert client.get(f"/api/duplicates/test/{ITEM}", params={"status": "x"}).status_code == 422
    assert client.get(f"/api/duplicates/test/{ITEM}", params={"limit": 0}).status_code == 422


# --- dismiss / reopen ----------------------------------------------------------------

def test_dismissing_one_member_hides_the_group_and_reopen_restores_it(client):
    a, b = _pair(client)
    flag_ids = _flag_ids(client)

    res = client.post(f"/api/duplicates/test/{ITEM}/dismiss",
                      json={"flag_ids": [flag_ids[0]], "reason": "different people"})
    assert res.status_code == 200 and res.json() == {"changed": 1}
    gone = _groups(client)                          # only one open member left
    assert gone["groups"] == []
    assert gone["counts"] == {"open": 0, "dismissed": 1}   # the counts cover both statuses

    dismissed = _groups(client, status="dismissed")["groups"][0]["members"]
    gone = next(m for m in dismissed if m["status"] == "dismissed")
    assert gone["dismissed_by"] == "test_admin" and gone["dismiss_reason"] == "different people"
    assert gone["dismissed_at"]

    res = client.post(f"/api/duplicates/test/{ITEM}/reopen", json={"flag_ids": [flag_ids[0]]})
    assert res.json() == {"changed": 1}
    assert len(_groups(client)["groups"]) == 1
    assert _audit_actions("DUPLICATE_DISMISSED") == 1
    assert _audit_actions("DUPLICATE_REOPENED") == 1


def test_dismissing_a_whole_group_and_repeating_it(client):
    _pair(client)
    flag_ids = _flag_ids(client)
    res = client.post(f"/api/duplicates/test/{ITEM}/dismiss", json={"flag_ids": flag_ids})
    assert res.json() == {"changed": 2}
    assert _groups(client)["groups"] == []
    # Already dismissed: nothing to change, not an error
    res = client.post(f"/api/duplicates/test/{ITEM}/dismiss", json={"flag_ids": flag_ids})
    assert res.status_code == 200 and res.json() == {"changed": 0}


def test_a_newcomer_reopens_a_dismissed_group(client):
    _pair(client)
    client.post(f"/api/duplicates/test/{ITEM}/dismiss", json={"flag_ids": _flag_ids(client)})
    assert _groups(client)["groups"] == []

    _create(client, ITEM, email="A@x.com")
    members = _groups(client)["groups"][0]["members"]
    assert len(members) == 3 and {m["status"] for m in members} == {"open"}


def test_dismiss_validation(client):
    url = f"/api/duplicates/test/{ITEM}/dismiss"
    assert client.post(url, json={"flag_ids": []}).status_code == 422
    assert client.post(url, json={"flag_ids": ["not-a-uuid"]}).status_code == 422
    assert client.post(url, json={}).status_code == 422
    assert client.post(url, json={"flag_ids": [str(uuid.uuid4())]}).status_code == 404
    # A flag of another object is not reachable through this one
    _pair(client)
    other = _flag_ids(client)
    assert client.post(f"/api/duplicates/test/{GOVERNED}/dismiss",
                       json={"flag_ids": other}).status_code == 404


# --- per-record lookup ---------------------------------------------------------------

def test_groups_for_a_record(client):
    a, b = _pair(client)
    c = _create(client, ITEM, email="solo@x.com")

    data = client.get(f"/api/duplicates/test/{ITEM}/record/{a}").json()
    assert data["entity_id"] == a and data["total"] == 1
    assert {m["entity_id"] for m in data["groups"][0]["members"]} == {a, b}
    assert client.get(f"/api/duplicates/test/{ITEM}/record/{c}").json()["groups"] == []

    # A draft copy resolves to its golden record's entity
    draft = client.put(f"/api/records/test/{ITEM}/{a}", json={"phone": "1"}).json()["id"]
    assert client.get(f"/api/duplicates/test/{ITEM}/record/{draft}").json()["entity_id"] == a


def test_groups_for_a_record_errors(client):
    assert client.get(f"/api/duplicates/test/{ITEM}/record/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/api/duplicates/test/{ITEM}/record/nope").status_code == 400


# --- roles ---------------------------------------------------------------------------

def test_viewer_and_users_without_access_cannot_use_the_review_api(client):
    _pair(client)
    flag_ids = _flag_ids(client)
    from app.core.permissions import delete_permission

    viewer = lambda: _grant(read=True)  # noqa: E731
    no_access = lambda: delete_permission(_engine(), _USER_ID, "test")  # noqa: E731
    for set_up in (viewer, no_access):
        set_up()
        h = _headers()
        assert client.get(f"/api/duplicates/test/{ITEM}", headers=h).status_code == 403
        assert client.get(f"/api/duplicates/test/{ITEM}/record/{uuid.uuid4()}",
                          headers=h).status_code == 403
        assert client.get(f"/api/duplicates/test/{ITEM}/scan", headers=h).status_code == 403
        assert client.post(f"/api/duplicates/test/{ITEM}/dismiss", headers=h,
                           json={"flag_ids": flag_ids}).status_code == 403
        assert client.post(f"/api/duplicates/test/{ITEM}/reopen", headers=h,
                           json={"flag_ids": flag_ids}).status_code == 403
    # Nothing was changed by the refused calls
    assert len(_groups(client)["groups"]) == 1


def test_editor_dismisses_when_dismissed_by_is_editor_but_not_when_publisher(client):
    _pair(client, ITEM)
    _pair(client, GOVERNED)
    _grant(read=True, write=True)
    h = _headers()

    res = client.get(f"/api/duplicates/test/{ITEM}", headers=h)
    assert res.status_code == 200 and res.json()["can_dismiss"] is True
    ids = [m["flag_id"] for g in res.json()["groups"] for m in g["members"]]
    assert client.post(f"/api/duplicates/test/{ITEM}/dismiss", headers=h,
                       json={"flag_ids": ids}).json() == {"changed": 2}

    res = client.get(f"/api/duplicates/test/{GOVERNED}", headers=h)
    assert res.status_code == 200 and res.json()["can_dismiss"] is False
    ids = [m["flag_id"] for g in res.json()["groups"] for m in g["members"]]
    denied = client.post(f"/api/duplicates/test/{GOVERNED}/dismiss", headers=h,
                         json={"flag_ids": ids})
    assert denied.status_code == 403 and "Publisher" in denied.json()["detail"]
    assert client.post(f"/api/duplicates/test/{GOVERNED}/reopen", headers=h,
                       json={"flag_ids": ids}).status_code == 403
    assert len(client.get(f"/api/duplicates/test/{GOVERNED}").json()["groups"]) == 1


def test_publisher_can_dismiss_where_dismissed_by_is_publisher(client):
    _pair(client, GOVERNED)
    ids = _flag_ids(client, GOVERNED)
    _grant(read=True, write=True, publish=True)
    h = _headers()

    assert client.get(f"/api/duplicates/test/{GOVERNED}", headers=h).json()["can_dismiss"] is True
    res = client.post(f"/api/duplicates/test/{GOVERNED}/dismiss", headers=h,
                      json={"flag_ids": ids})
    assert res.status_code == 200 and res.json() == {"changed": 2}
    assert _audit_actions("DUPLICATE_DISMISSED") == 2


# --- scanning ------------------------------------------------------------------------

def test_scan_status_and_rescan(client):
    _pair(client)
    status = client.get(f"/api/duplicates/test/{ITEM}/scan").json()
    assert status["has_rules"] is True and status["running"] is False
    assert status["needs_rescan"] is True and status["last_scan"] is None
    assert status["record_count"] == 2
    assert status["rescan_mode"] == "on_rule_change"

    res = client.post(f"/api/duplicates/test/{ITEM}/rescan")
    assert res.status_code == 202 and res.json() == {"status": "started"}

    status = client.get(f"/api/duplicates/test/{ITEM}/scan").json()  # task ran before returning
    assert status["needs_rescan"] is False
    assert status["last_scan"]["record_count"] == 2
    assert status["last_scan"]["duration_ms"] >= 0 and status["last_scan"]["scanned_at"]
    with _engine().connect() as conn:
        (entry,) = conn.execute(text(
            "SELECT user_name, new_values FROM _system.audit_log WHERE action = 'DUPLICATE_SCAN' "
            "AND new_values->>'schema' = 'test' AND new_values->>'object' = :o"),
            {"o": ITEM}).all()
    assert entry.user_name == "test_admin" and entry.new_values["trigger"] == "manual"
    assert len(_groups(client)["groups"]) == 1


def test_scan_status_for_an_object_without_rules(client):
    status = client.get("/api/duplicates/test/company/scan").json()
    assert status["has_rules"] is False and status["needs_rescan"] is False
    assert status["record_count"] is None and status["last_scan"] is None


def test_rescan_is_admin_only_and_needs_rules(client):
    _grant(read=True, write=True, publish=True)    # even a Publisher may not
    assert client.post(f"/api/duplicates/test/{ITEM}/rescan",
                       headers=_headers()).status_code == 403
    assert client.post("/api/duplicates/test/company/rescan").status_code == 422
    assert client.post("/api/duplicates/test/nope/rescan").status_code == 404


def test_a_running_scan_is_visible_and_blocks_another(client):
    key = "duplicate-rescan:test.dup_item"
    with _engine().connect() as conn:
        tx = conn.begin()
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": key})
        try:
            status = client.get(f"/api/duplicates/test/{ITEM}/scan").json()
            assert status["running"] is True and status["record_count"] is None
            assert client.post(f"/api/duplicates/test/{ITEM}/rescan").status_code == 409
        finally:
            tx.rollback()
    assert client.get(f"/api/duplicates/test/{ITEM}/scan").json()["running"] is False


# --- counts --------------------------------------------------------------------------

def _counts(client, **kw):
    res = client.get("/api/object-counts", **kw)
    assert res.status_code == 200
    return res.json()["schemas"]["test"]


def test_object_counts_report_open_duplicate_groups(client):
    counts = _counts(client)
    assert counts[ITEM]["duplicates"] == 0 and counts[GOVERNED]["duplicates"] == 0
    assert "duplicates" not in counts["company"]          # no rules, no figure

    _pair(client, ITEM, "a@x.com")
    _pair(client, ITEM, "b@x.com")
    assert _counts(client)[ITEM]["duplicates"] == 2
    client.post(f"/api/duplicates/test/{ITEM}/dismiss",
                json={"flag_ids": _flag_ids(client)[:1]})
    assert _counts(client)[ITEM]["duplicates"] == 1


def test_object_counts_duplicates_are_for_writers_only(client):
    _pair(client)
    _grant(read=True)
    assert "duplicates" not in _counts(client, headers=_headers())[ITEM]
    _grant(read=True, write=True)
    assert _counts(client, headers=_headers())[ITEM]["duplicates"] == 1


# --- reasons --------------------------------------------------------------------------

def test_dismiss_needs_a_reason_when_the_object_requires_one(client):
    AUDITED = "dup_audited_item"
    for _ in range(2):
        res = client.post(f"/api/records/test/{AUDITED}",
                          json={"email": "a@x.com", "_reason": "seed"})
        assert res.status_code == 201, res.text
    ids = _flag_ids(client, AUDITED)
    url = f"/api/duplicates/test/{AUDITED}/dismiss"

    assert client.post(url, json={"flag_ids": ids}).status_code == 422
    ok = client.post(url, json={"flag_ids": ids, "reason": "different people"})
    assert ok.status_code == 200 and ok.json() == {"changed": 2}
