"""Integration tests for 0.4.0 lifecycle: state filtering, draft-copy-on-edit,
publish, retire, and import initial_state.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import uuid

import pytest

pytestmark = pytest.mark.usefixtures("clean_records")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_company(client, code="C001", name="Acme"):
    res = client.post("/api/records/test/company", json={"code": code, "name": name})
    assert res.status_code == 201
    return res.json()["id"]


def _create_draft(client, active_id, *, name="Pending"):
    res = client.put(f"/api/records/test/company/{active_id}", json={"name": name})
    assert res.status_code == 200
    data = res.json()
    assert data["draft"] is True
    return data["id"]


# ---------------------------------------------------------------------------
# New records default to active state
# ---------------------------------------------------------------------------

def test_create_record_defaults_to_active(client):
    rid = _create_company(client)
    rec = client.get(f"/api/records/test/company/{rid}").json()
    assert rec["_state"] == "active"


# ---------------------------------------------------------------------------
# State filter on list
# ---------------------------------------------------------------------------

def test_list_defaults_to_active_only(client):
    _create_company(client, "C001")
    _create_company(client, "C002")
    data = client.get("/api/records/test/company").json()
    assert data["total"] == 2
    assert all(r["_state"] == "active" for r in data["records"])


def test_list_state_draft_excludes_active(client):
    rid = _create_company(client, "C001")
    _create_draft(client, rid)  # one draft exists alongside

    data = client.get("/api/records/test/company?state=draft").json()
    assert data["total"] == 1
    assert data["records"][0]["_state"] == "draft"


def test_list_state_retired_excludes_active_and_draft(client):
    rid = _create_company(client, "C001")
    client.post(f"/api/records/test/company/{rid}/retire")

    data_active = client.get("/api/records/test/company?state=active").json()
    assert data_active["total"] == 0

    data_retired = client.get("/api/records/test/company?state=retired").json()
    assert data_retired["total"] == 1


def test_list_state_all_returns_every_state(client):
    rid = _create_company(client, "C001")
    r2 = _create_company(client, "C002")
    _create_draft(client, rid)
    client.post(f"/api/records/test/company/{r2}/retire")

    data = client.get("/api/records/test/company?state=all").json()
    # active (C001) + draft + retired (C002)
    assert data["total"] == 3


# ---------------------------------------------------------------------------
# Draft-copy-on-edit
# ---------------------------------------------------------------------------

def test_put_on_active_creates_draft_alongside(client):
    rid = _create_company(client, "C001", "Original")
    draft_id = _create_draft(client, rid, name="Pending")
    assert draft_id != rid

    active = client.get(f"/api/records/test/company/{rid}").json()
    assert active["_state"] == "active"
    assert active["name"] == "Original"

    drafts = client.get("/api/records/test/company?state=draft").json()
    draft = next(r for r in drafts["records"] if r["_id"] == draft_id)
    assert draft["_state"] == "draft"
    assert draft["name"] == "Pending"
    assert draft["_draft_of_id"] == rid


def test_put_on_active_second_time_reuses_existing_draft(client):
    """Two consecutive PUTs on the same active record update the same draft, not create a second."""
    rid = _create_company(client, "C001")
    draft_id_1 = _create_draft(client, rid, name="First")
    res2 = client.put(f"/api/records/test/company/{rid}", json={"name": "Second"})
    draft_id_2 = res2.json()["id"]

    assert draft_id_1 == draft_id_2  # same draft updated in place

    drafts = client.get("/api/records/test/company?state=draft").json()
    assert drafts["total"] == 1
    assert drafts["records"][0]["name"] == "Second"


def test_put_on_draft_updates_in_place(client):
    rid = _create_company(client, "C001", "Original")
    draft_id = _create_draft(client, rid, name="First")

    res = client.put(f"/api/records/test/company/{draft_id}", json={"name": "Second"})
    assert res.status_code == 200
    assert res.json().get("draft") is not True  # in-place: no new draft created

    drafts = client.get("/api/records/test/company?state=draft").json()
    assert drafts["records"][0]["name"] == "Second"


def test_system_cols_not_writable_via_body(client):
    """_state and _draft_of_id in the request body must be silently ignored."""
    rid = _create_company(client, "C001")
    client.put(
        f"/api/records/test/company/{rid}",
        json={"name": "X", "_state": "retired", "_draft_of_id": str(uuid.uuid4())},
    )
    # Should have created a draft, not retired the active record
    active = client.get(f"/api/records/test/company/{rid}").json()
    assert active["_state"] == "active"


# ---------------------------------------------------------------------------
# Publish (draft → active)
# ---------------------------------------------------------------------------

def test_publish_applies_draft_to_active_record(client):
    rid = _create_company(client, "C001", "Original")
    draft_id = _create_draft(client, rid, name="Published Name")

    res = client.post(f"/api/records/test/company/{draft_id}/publish")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == rid
    assert data["published"] is True

    # Active record now has the draft's value
    active = client.get(f"/api/records/test/company/{rid}").json()
    assert active["name"] == "Published Name"
    assert active["_state"] == "active"


def test_publish_soft_deletes_the_draft(client):
    rid = _create_company(client, "C001")
    draft_id = _create_draft(client, rid)

    client.post(f"/api/records/test/company/{draft_id}/publish")

    # Draft is gone from both state=draft and state=all with include_deleted=false
    drafts = client.get("/api/records/test/company?state=draft").json()
    assert all(r["_id"] != draft_id for r in drafts["records"])


def test_publish_creates_history_entry_on_active_record(client):
    rid = _create_company(client, "C001")
    draft_id = _create_draft(client, rid, name="New name")
    client.post(f"/api/records/test/company/{draft_id}/publish?reason=approved")

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    actions = [h["_action"] for h in history]
    assert "PUBLISH" in actions
    publish_entry = next(h for h in history if h["_action"] == "PUBLISH")
    assert publish_entry["_change_reason"] == "approved"


def test_publish_returns_404_for_non_draft(client):
    rid = _create_company(client, "C001")
    res = client.post(f"/api/records/test/company/{rid}/publish")
    assert res.status_code == 404


def test_publish_returns_404_for_unknown_id(client):
    res = client.post(f"/api/records/test/company/{uuid.uuid4()}/publish")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Retire (active → retired)
# ---------------------------------------------------------------------------

def test_retire_transitions_active_to_retired(client):
    rid = _create_company(client, "C001")

    res = client.post(f"/api/records/test/company/{rid}/retire")
    assert res.status_code == 200
    assert res.json()["retired"] is True

    # No longer in default (active) list
    active_data = client.get("/api/records/test/company").json()
    assert all(r["_id"] != rid for r in active_data["records"])

    # Visible in retired list
    retired_data = client.get("/api/records/test/company?state=retired").json()
    assert any(r["_id"] == rid for r in retired_data["records"])


def test_retire_creates_history_entry(client):
    rid = _create_company(client, "C001")
    client.post(f"/api/records/test/company/{rid}/retire?reason=end-of-life")

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert any(h["_action"] == "RETIRE" for h in history)
    retire_entry = next(h for h in history if h["_action"] == "RETIRE")
    assert retire_entry["_change_reason"] == "end-of-life"


def test_retire_returns_404_for_non_active_record(client):
    """Retiring a draft or already-retired record must fail."""
    rid = _create_company(client, "C001")
    draft_id = _create_draft(client, rid)

    res = client.post(f"/api/records/test/company/{draft_id}/retire")
    assert res.status_code == 404  # draft, not active


def test_retire_returns_404_for_unknown_id(client):
    res = client.post(f"/api/records/test/company/{uuid.uuid4()}/retire")
    assert res.status_code == 404


def test_retire_then_retire_returns_404(client):
    """Attempting to retire an already-retired record must fail."""
    rid = _create_company(client, "C001")
    client.post(f"/api/records/test/company/{rid}/retire")

    res = client.post(f"/api/records/test/company/{rid}/retire")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Full publish workflow: create → draft → publish → state is active
# ---------------------------------------------------------------------------

def test_full_draft_publish_workflow(client):
    rid = _create_company(client, "C001", "v1")

    # v2 draft
    draft_id = _create_draft(client, rid, name="v2")

    # Further edit the draft
    client.put(f"/api/records/test/company/{draft_id}", json={"name": "v2-final"})

    # Publish
    client.post(f"/api/records/test/company/{draft_id}/publish")

    # Active record has latest draft values
    active = client.get(f"/api/records/test/company/{rid}").json()
    assert active["name"] == "v2-final"
    assert active["_state"] == "active"

    # No draft exists any more
    drafts = client.get("/api/records/test/company?state=draft").json()
    assert drafts["total"] == 0

    # History on active record has INSERT + PUBLISH
    history = client.get(f"/api/records/test/company/{rid}/history").json()
    actions = {h["_action"] for h in history}
    assert "PUBLISH" in actions


# ---------------------------------------------------------------------------
# Export state filter
# ---------------------------------------------------------------------------

def test_export_defaults_to_active_state(client):
    rid = _create_company(client, "C001")
    draft_id = _create_draft(client, rid)

    res = client.get("/api/records/test/company/export?format=json")
    assert res.status_code == 200
    records = res.json()
    ids = [r["_id"] for r in records]
    assert rid in ids
    assert draft_id not in ids


def test_export_with_state_draft(client):
    rid = _create_company(client, "C001")
    draft_id = _create_draft(client, rid)

    res = client.get("/api/records/test/company/export?format=json&state=draft")
    assert res.status_code == 200
    records = res.json()
    ids = [r["_id"] for r in records]
    assert draft_id in ids
    assert rid not in ids


# ---------------------------------------------------------------------------
# State is snapshotted in history
# ---------------------------------------------------------------------------

def test_history_snapshots_state_on_create(client):
    rid = _create_company(client, "C001")
    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert history[0]["_state"] == "active"


def test_history_snapshots_state_on_retire(client):
    rid = _create_company(client, "C001")
    client.post(f"/api/records/test/company/{rid}/retire")
    history = client.get(f"/api/records/test/company/{rid}/history").json()
    by_version = {h["_version"]: h for h in history}
    assert by_version[1]["_state"] == "active"
    assert by_version[2]["_state"] == "retired"
