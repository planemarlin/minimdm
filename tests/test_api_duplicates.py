"""Duplicate detection wired into every record write path.

One test per path that writes a record (create, edit's three branches, revert, publish's
two branches, delete, retire, import, upsert import, bulk import and inbound), each
asserting that flags are raised or cleared. The matching rules themselves are covered in
tests/test_duplicates.py.
"""
import os

import pytest
from sqlalchemy import text

from app.core import duplicates as duplicates_svc

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)

ITEM = "dup_item"
GOVERNED = "dup_governed_item"
EMAIL = "Same email"


def _create(client, obj, **values):
    res = client.post(f"/api/records/test/{obj}", json=values)
    assert res.status_code == 201, res.text
    return res.json()


def _flagged(client, obj, rule=None) -> set:
    """Entity ids (as strings) currently flagged on the object."""
    sql = ("SELECT entity_id::text FROM _system.duplicate_flags "
           "WHERE schema_name = 'test' AND object_name = :o")
    params = {"o": obj}
    if rule:
        sql += " AND rule_name = :r"
        params["r"] = rule
    engine = client.app.state.table_manager.engine
    with engine.connect() as conn:
        return {r[0] for r in conn.execute(text(sql), params)}


def _import_csv(client, obj, csv_text, query=""):
    files = {"file": ("data.csv", csv_text.encode(), "text/csv")}
    return client.post(f"/api/records/test/{obj}/import?format=csv{query}", files=files)


# --- create / edit ------------------------------------------------------------------

def test_create_flags_a_duplicate_and_reports_it(client, clean_records):
    first = _create(client, ITEM, email="Anna@X.com")
    assert "possible_duplicates" not in first
    second = _create(client, ITEM, email=" anna@x.COM")

    assert _flagged(client, ITEM) == {first["id"], second["id"]}
    assert second["possible_duplicates"] == [
        {"rule": EMAIL, "value": "anna x com", "matches": [first["id"]]}
    ]


def test_a_different_value_is_not_flagged(client, clean_records):
    _create(client, ITEM, email="a@x.com")
    _create(client, ITEM, email="b@x.com")
    assert _flagged(client, ITEM) == set()


def test_edit_of_an_active_record_flags_through_its_draft_copy(client, clean_records):
    a = _create(client, ITEM, email="a@x.com")
    b = _create(client, ITEM, email="b@x.com")

    # Editing an active record creates a draft copy; the entity stays the golden record.
    res = client.put(f"/api/records/test/{ITEM}/{a['id']}", json={"email": "b@x.com"})
    assert res.status_code == 200 and res.json()["draft"] is True
    assert res.json()["possible_duplicates"][0]["matches"] == [b["id"]]
    assert _flagged(client, ITEM) == {a["id"], b["id"]}

    # Editing the existing draft again moves it out of the group
    res = client.put(f"/api/records/test/{ITEM}/{a['id']}", json={"email": "c@x.com"})
    assert res.status_code == 200
    assert _flagged(client, ITEM) == set()


def test_edit_of_a_draft_in_place_flags(client, clean_records):
    d1 = _create(client, GOVERNED, email="a@x.com")
    d2 = _create(client, GOVERNED, email="b@x.com")
    assert _flagged(client, GOVERNED) == set()

    res = client.put(f"/api/records/test/{GOVERNED}/{d2['id']}", json={"email": "A@x.com"})
    assert res.status_code == 200
    assert _flagged(client, GOVERNED) == {d1["id"], d2["id"]}


# --- publish / revert / retire / delete ----------------------------------------------

def test_new_record_drafts_are_compared_and_survive_publish(client, clean_records):
    d1 = _create(client, GOVERNED, email="a@x.com")
    d2 = _create(client, GOVERNED, email="a@x.com")
    assert _flagged(client, GOVERNED) == {d1["id"], d2["id"]}

    res = client.post(f"/api/records/test/{GOVERNED}/{d1['id']}/publish")
    assert res.status_code == 200
    assert _flagged(client, GOVERNED) == {d1["id"], d2["id"]}


def test_publishing_a_draft_copy_and_reverting_update_the_flags(client, clean_records):
    a = _create(client, ITEM, email="a@x.com")
    b = _create(client, ITEM, email="b@x.com")
    draft_id = client.put(
        f"/api/records/test/{ITEM}/{a['id']}", json={"email": "b@x.com"}
    ).json()["id"]
    assert draft_id != a["id"]

    res = client.post(f"/api/records/test/{ITEM}/{draft_id}/publish")
    assert res.status_code == 200
    assert _flagged(client, ITEM) == {a["id"], b["id"]}
    # The draft copy is gone; nothing may be left pointing at it
    assert draft_id not in _flagged(client, ITEM)

    res = client.post(f"/api/records/test/{ITEM}/{a['id']}/revert/1")
    assert res.status_code == 200
    assert _flagged(client, ITEM) == set()


def test_retire_removes_the_record_from_matching(client, clean_records):
    a = _create(client, ITEM, email="a@x.com")
    b = _create(client, ITEM, email="a@x.com")
    assert _flagged(client, ITEM) == {a["id"], b["id"]}

    res = client.post(f"/api/records/test/{ITEM}/{b['id']}/retire")
    assert res.status_code == 200
    assert _flagged(client, ITEM) == set()


def test_delete_removes_the_record_from_matching(client, clean_records):
    a = _create(client, ITEM, email="a@x.com")
    b = _create(client, ITEM, email="a@x.com")
    c = _create(client, ITEM, email="a@x.com")
    assert _flagged(client, ITEM) == {a["id"], b["id"], c["id"]}

    assert client.delete(f"/api/records/test/{ITEM}/{c['id']}").status_code == 204
    assert _flagged(client, ITEM) == {a["id"], b["id"]}
    assert client.delete(f"/api/records/test/{ITEM}/{b['id']}").status_code == 204
    assert _flagged(client, ITEM) == set()


# --- import --------------------------------------------------------------------------

def test_import_checks_each_row_for_a_small_import(client, clean_records):
    res = _import_csv(client, ITEM, "code,email\nA,x@x.com\nB,X@x.com\nC,y@x.com\n")
    assert res.status_code == 200
    assert res.json()["duplicate_check"] == "inline"
    assert len(_flagged(client, ITEM)) == 2


def test_upsert_import_flags_the_draft_copy_it_creates(client, clean_records):
    a = _create(client, ITEM, code="A", email="a@x.com")
    b = _create(client, ITEM, code="B", email="b@x.com")

    res = _import_csv(client, ITEM, "code,email\nA,b@x.com\n",
                      "&upsert_key=code&initial_state=draft")
    assert res.status_code == 200 and res.json()["updated"] == 1
    assert _flagged(client, ITEM) == {a["id"], b["id"]}


def test_a_failed_strict_import_leaves_no_flags(client, clean_records):
    res = _import_csv(client, ITEM, "code,email,qty\nA,x@x.com,1\nB,x@x.com,2\nC,z@x.com,abc\n")
    assert res.status_code == 422
    assert _flagged(client, ITEM) == set()


def test_a_big_import_commits_first_and_rescans_in_the_background(
        client, clean_records, monkeypatch):
    monkeypatch.setattr(duplicates_svc, "BULK_IMPORT_RESCAN_THRESHOLD", 2)
    res = _import_csv(client, ITEM, "code,email\nA,x@x.com\nB,X@x.com\nC,y@x.com\n")
    assert res.status_code == 200
    assert res.json()["duplicate_check"] == "rescan_scheduled"
    # The test client runs background tasks before returning
    assert len(_flagged(client, ITEM)) == 2

    engine = client.app.state.table_manager.engine
    with engine.connect() as conn:
        scanned = conn.execute(text(
            "SELECT record_count FROM _system.duplicate_scans "
            "WHERE schema_name = 'test' AND object_name = :o"), {"o": ITEM}).scalar()
    assert scanned == 3
    # ... and the outstanding-rescan mark set by the import is cleared by that scan
    assert client.get(f"/api/duplicates/test/{ITEM}/scan").json()["needs_rescan"] is False
    with engine.connect() as conn:
        entry = conn.execute(text(
            "SELECT user_name, new_values FROM _system.audit_log WHERE action = 'DUPLICATE_SCAN' "
            "AND new_values->>'schema' = 'test'")).one()
    assert entry.user_name == "test_admin" and entry.new_values["trigger"] == "import"


def test_a_big_import_leaves_a_rescan_request_if_the_scan_never_runs(
        client, clean_records, monkeypatch):
    """Server dies between the import's commit and its background scan."""
    monkeypatch.setattr(duplicates_svc, "BULK_IMPORT_RESCAN_THRESHOLD", 2)
    # An earlier scan exists, so only the import's request can say the flags are stale
    assert client.post(f"/api/duplicates/test/{ITEM}/rescan").status_code == 202
    assert client.get(f"/api/duplicates/test/{ITEM}/scan").json()["needs_rescan"] is False

    with monkeypatch.context() as patch:
        patch.setattr(duplicates_svc, "rescan_in_background", lambda *a, **k: None)
        res = _import_csv(client, ITEM, "code,email\nA,x@x.com\nB,X@x.com\nC,y@x.com\n")
    assert res.status_code == 200 and res.json()["duplicate_check"] == "rescan_scheduled"
    assert _flagged(client, ITEM) == set()             # rows are in, unchecked
    assert client.get(f"/api/duplicates/test/{ITEM}/scan").json()["needs_rescan"] is True

    # What the next startup does for an object that needs it
    engine = client.app.state.table_manager.engine
    cfg = {"schemas": {"test": {"objects": {
        ITEM: client.app.state.table_manager.get_object_config("test", ITEM)}}},
        "duplicates": {"rescan": "on_rule_change"}}
    duplicates_svc.start_auto_rescan(engine, cfg).join(timeout=30)
    assert len(_flagged(client, ITEM)) == 2
    assert client.get(f"/api/duplicates/test/{ITEM}/scan").json()["needs_rescan"] is False


def test_objects_without_rules_are_untouched(client, clean_records):
    res = _import_csv(client, "company", "code,name\nC1,A\nC2,B\n")
    assert res.status_code == 200
    assert "duplicate_check" not in res.json()
    company = _create(client, "company", code="C9", name="x")
    assert "possible_duplicates" not in company


# --- inbound -------------------------------------------------------------------------

def _inbound(client, key, payload):
    return client.post(f"/api/inbound/test/{ITEM}", json=payload, headers={"X-Api-Key": key})


def test_inbound_drafts_are_flagged_and_updates_clear_them(client, clean_records, inbound_key):
    r1 = _inbound(client, inbound_key, {"erp_id": "E1", "mail": "a@x.com"})
    r2 = _inbound(client, inbound_key, {"erp_id": "E2", "mail": "A@x.com"})
    assert r1.status_code == r2.status_code == 201
    assert _flagged(client, ITEM) == {r1.json()["id"], r2.json()["id"]}

    # Updating E1 in place (it is still a draft) moves it out of the group
    r3 = _inbound(client, inbound_key, {"erp_id": "E1", "mail": "z@x.com"})
    assert r3.status_code == 200
    assert _flagged(client, ITEM) == set()


def test_inbound_update_of_an_active_record_flags_through_its_draft_copy(
        client, clean_records, inbound_key):
    active = _create(client, ITEM, email="a@x.com", _source_system="test_erp", _source_id="E9")
    other = _create(client, ITEM, email="b@x.com")

    res = _inbound(client, inbound_key, {"erp_id": "E9", "mail": "b@x.com"})
    assert res.status_code == 200
    assert res.json()["id"] != active["id"]   # a draft copy was written
    assert _flagged(client, ITEM) == {active["id"], other["id"]}

    # A second push updates that draft copy and moves it away again
    res = _inbound(client, inbound_key, {"erp_id": "E9", "mail": "c@x.com"})
    assert res.status_code == 200
    assert _flagged(client, ITEM) == set()
