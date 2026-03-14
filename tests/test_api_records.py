"""API integration tests for record CRUD, history, and revert.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import uuid

import pytest

pytestmark = pytest.mark.usefixtures("clean_records")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_record(client):
    res = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Alpha Corp", "_reason": "initial load"},
    )
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    # id must be a valid UUID
    uuid.UUID(data["id"])


def test_create_record_unknown_object_returns_404(client):
    res = client.post("/api/records/test/nonexistent", json={"code": "X"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# List / search
# ---------------------------------------------------------------------------

def test_list_records_empty(client):
    res = client.get("/api/records/test/company")
    assert res.status_code == 200
    data = res.json()
    assert data["records"] == []
    assert data["total"] == 0


def test_list_records_returns_created_records(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha"})
    client.post("/api/records/test/company", json={"code": "C002", "name": "Beta"})

    res = client.get("/api/records/test/company")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    codes = {r["code"] for r in data["records"]}
    assert codes == {"C001", "C002"}


def test_list_excludes_deleted_by_default(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}")

    data = client.get("/api/records/test/company").json()
    assert data["total"] == 0


def test_list_include_deleted(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}")

    data = client.get("/api/records/test/company?include_deleted=true").json()
    assert data["total"] == 1
    assert data["records"][0]["_deleted_at"] is not None


def test_search_filters_by_string_attribute(client):
    client.post("/api/records/test/company", json={"code": "ALPHA01", "name": "Alpha Corp"})
    client.post("/api/records/test/company", json={"code": "BETA02", "name": "Beta Ltd"})

    res = client.get("/api/records/test/company?search=Alpha")
    data = res.json()
    assert data["total"] == 1
    assert data["records"][0]["code"] == "ALPHA01"


def test_search_is_case_insensitive(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha Corp"})

    data = client.get("/api/records/test/company?search=alpha").json()
    assert data["total"] == 1


def test_list_unknown_schema_returns_404(client):
    res = client.get("/api/records/nonexistent/object")
    assert res.status_code == 404


def test_list_pagination(client):
    for i in range(5):
        client.post("/api/records/test/company", json={"code": f"C{i:03d}"})

    res = client.get("/api/records/test/company?page=1&page_size=2")
    data = res.json()
    assert data["total"] == 5
    assert len(data["records"]) == 2
    assert data["pages"] == 3


# ---------------------------------------------------------------------------
# Get single record
# ---------------------------------------------------------------------------

def test_get_record(client):
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Alpha"},
    ).json()["id"]

    res = client.get(f"/api/records/test/company/{rid}")
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == "C001"
    assert data["name"] == "Alpha"


def test_get_record_not_found(client):
    res = client.get(f"/api/records/test/company/{uuid.uuid4()}")
    assert res.status_code == 404


def test_get_deleted_record_returns_404(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}")

    res = client.get(f"/api/records/test/company/{rid}")
    assert res.status_code == 404


def test_get_record_invalid_uuid_returns_400(client):
    res = client.get("/api/records/test/company/not-a-uuid")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_record(client):
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Original"},
    ).json()["id"]

    res = client.put(
        f"/api/records/test/company/{rid}",
        json={"name": "Updated", "_reason": "rename"},
    )
    assert res.status_code == 200

    record = client.get(f"/api/records/test/company/{rid}").json()
    assert record["name"] == "Updated"
    assert record["code"] == "C001"  # unchanged


def test_update_nonexistent_record_returns_404(client):
    res = client.put(
        f"/api/records/test/company/{uuid.uuid4()}",
        json={"name": "X"},
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Delete (soft)
# ---------------------------------------------------------------------------

def test_soft_delete_record(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]

    res = client.delete(f"/api/records/test/company/{rid}")
    assert res.status_code == 204


def test_delete_nonexistent_record_returns_404(client):
    res = client.delete(f"/api/records/test/company/{uuid.uuid4()}")
    assert res.status_code == 404


def test_delete_already_deleted_returns_404(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}")

    res = client.delete(f"/api/records/test/company/{rid}")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def test_history_after_create_has_one_insert_entry(client):
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "_reason": "initial"},
    ).json()["id"]

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 1
    assert history[0]["_version"] == 1
    assert history[0]["_action"] == "INSERT"


def test_history_entries_include_attribute_snapshot(client):
    """Each history row must carry the full attribute snapshot so the UI can display values."""
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Original"},
    ).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "Updated"})

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    by_version = {h["_version"]: h for h in history}

    # Version 1 (INSERT) snapshot
    assert by_version[1]["code"] == "C001"
    assert by_version[1]["name"] == "Original"

    # Version 2 (UPDATE) snapshot
    assert by_version[2]["code"] == "C001"
    assert by_version[2]["name"] == "Updated"


def test_history_after_update_has_two_entries(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "Changed"})

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 2
    actions = {h["_action"] for h in history}
    assert actions == {"INSERT", "UPDATE"}
    versions = sorted(h["_version"] for h in history)
    assert versions == [1, 2]


def test_history_after_delete_has_delete_entry(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}?reason=cleanup")

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 2
    assert any(h["_action"] == "DELETE" for h in history)


def test_history_invalid_uuid_returns_400(client):
    res = client.get("/api/records/test/company/bad-id/history")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------

def test_revert_to_previous_version(client):
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Original"},
    ).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "Changed"})

    res = client.post(f"/api/records/test/company/{rid}/revert/1?reason=undo")
    assert res.status_code == 200
    assert res.json()["reverted_to_version"] == 1

    record = client.get(f"/api/records/test/company/{rid}").json()
    assert record["name"] == "Original"


def test_revert_creates_new_history_entry(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "v2"})

    client.post(f"/api/records/test/company/{rid}/revert/1")

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 3
    assert any(h["_action"] == "REVERT" for h in history)


def test_revert_deleted_record_restores_it(client):
    """Reverting a deleted record should restore it (regression: version was reset to 1)."""
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "ToDelete"},
    ).json()["id"]
    client.delete(f"/api/records/test/company/{rid}?reason=cleanup")

    # Revert to the INSERT snapshot (version 1)
    res = client.post(f"/api/records/test/company/{rid}/revert/1")
    assert res.status_code == 200

    # Record must be accessible again
    record = client.get(f"/api/records/test/company/{rid}").json()
    assert record["code"] == "C001"
    assert record["_deleted_at"] is None

    # Version numbering must not reset — should be INSERT(1), DELETE(2), REVERT(3)
    history = client.get(f"/api/records/test/company/{rid}/history").json()
    versions = sorted(h["_version"] for h in history)
    assert versions == [1, 2, 3]


def test_revert_nonexistent_version_returns_404(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    res = client.post(f"/api/records/test/company/{rid}/revert/99")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Parent-child relationships
# ---------------------------------------------------------------------------

def test_parent_id_is_saved_on_create(client):
    company_id = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    div_id = client.post("/api/records/test/division",
        json={"code": "D001", "_company_id": company_id}).json()["id"]

    rec = client.get(f"/api/records/test/division/{div_id}").json()
    assert rec["_company_id"] == company_id


def test_parent_id_is_saved_on_update(client):
    company_id = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    div_id = client.post("/api/records/test/division", json={"code": "D001"}).json()["id"]

    # Verify no parent initially
    assert client.get(f"/api/records/test/division/{div_id}").json()["_company_id"] is None

    client.put(f"/api/records/test/division/{div_id}", json={"_company_id": company_id})
    assert client.get(f"/api/records/test/division/{div_id}").json()["_company_id"] == company_id


def test_list_records_filter_by_parent_id(client):
    c1 = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    c2 = client.post("/api/records/test/company", json={"code": "C002"}).json()["id"]
    client.post("/api/records/test/division", json={"code": "D001", "_company_id": c1})
    client.post("/api/records/test/division", json={"code": "D002", "_company_id": c1})
    client.post("/api/records/test/division", json={"code": "D003", "_company_id": c2})

    data = client.get("/api/records/test/division", params={"parent_id": c1}).json()
    assert data["total"] == 2
    assert all(r["_company_id"] == c1 for r in data["records"])

    data = client.get("/api/records/test/division", params={"parent_id": c2}).json()
    assert data["total"] == 1
    assert data["records"][0]["code"] == "D003"


# ---------------------------------------------------------------------------
# Audit log API
# ---------------------------------------------------------------------------

def test_audit_log_records_create(client):
    client.post("/api/records/test/company", json={"code": "C001", "_reason": "audit test"})

    res = client.get("/api/audit?schema=test&obj=company")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(r["action"] == "INSERT" for r in data["records"])


def test_audit_log_filter_by_action(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "Updated"})

    inserts = client.get("/api/audit?schema=test&obj=company&action=INSERT").json()
    updates = client.get("/api/audit?schema=test&obj=company&action=UPDATE").json()

    assert all(r["action"] == "INSERT" for r in inserts["records"])
    assert all(r["action"] == "UPDATE" for r in updates["records"])


def test_audit_log_filter_by_time(client):
    from datetime import datetime, timezone, timedelta

    client.post("/api/records/test/company", json={"code": "C001"})

    # from_time in the future → no results
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    data = client.get("/api/audit", params={"schema": "test", "obj": "company", "from_time": future}).json()
    assert data["total"] == 0

    # to_time in the past → no results
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    data = client.get("/api/audit", params={"schema": "test", "obj": "company", "to_time": past}).json()
    assert data["total"] == 0

    # from_time in the past → finds the entry
    data = client.get("/api/audit", params={"schema": "test", "obj": "company", "from_time": past}).json()
    assert data["total"] >= 1
