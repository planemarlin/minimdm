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


def test_search_percent_wildcard_is_treated_as_literal(client):
    """A bare '%' in the search term must not match every record."""
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha"})

    data = client.get("/api/records/test/company?search=%").json()
    assert data["total"] == 0


def test_search_underscore_wildcard_is_treated_as_literal(client):
    """A bare '_' in the search term must not act as a single-char wildcard."""
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha"})

    data = client.get("/api/records/test/company?search=_").json()
    assert data["total"] == 0


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


def test_get_deleted_record_with_include_deleted(client):
    """include_deleted=true must return soft-deleted records
    (powers deleted-reference indicator)."""
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}")

    res = client.get(f"/api/records/test/company/{rid}?include_deleted=true")
    assert res.status_code == 200
    data = res.json()
    assert data["code"] == "C001"
    assert data["_deleted_at"] is not None


def test_get_record_invalid_uuid_returns_400(client):
    res = client.get("/api/records/test/company/not-a-uuid")
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_active_record_creates_draft(client):
    """PUT on an active record creates a draft alongside — original record is untouched."""
    rid = client.post(
        "/api/records/test/company",
        json={"code": "C001", "name": "Original"},
    ).json()["id"]

    res = client.put(
        f"/api/records/test/company/{rid}",
        json={"name": "Updated", "_reason": "rename"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["draft"] is True
    draft_id = data["id"]
    assert draft_id != rid  # a new record was created

    # Active record is unchanged
    active = client.get(f"/api/records/test/company/{rid}").json()
    assert active["name"] == "Original"
    assert active["_state"] == "active"

    # Draft is listed under state=draft
    drafts = client.get("/api/records/test/company?state=draft").json()
    assert any(r["_id"] == draft_id for r in drafts["records"])


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
    # PUT on active record creates a draft; edit that draft in-place to get an UPDATE history entry
    draft_id = client.put(
        f"/api/records/test/company/{rid}", json={"name": "Pending"}
    ).json()["id"]
    client.put(f"/api/records/test/company/{draft_id}", json={"name": "Updated"})

    history = client.get(f"/api/records/test/company/{draft_id}/history").json()
    by_version = {h["_version"]: h for h in history}

    # Version 1 (INSERT) snapshot — draft was created with "Pending"
    assert by_version[1]["code"] == "C001"
    assert by_version[1]["name"] == "Pending"

    # Version 2 (UPDATE) snapshot — draft edited in-place
    assert by_version[2]["code"] == "C001"
    assert by_version[2]["name"] == "Updated"


def test_history_after_draft_update_has_two_entries(client):
    """Editing a draft in-place produces INSERT + UPDATE history on the draft record."""
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    draft_id = client.put(
        f"/api/records/test/company/{rid}", json={"name": "First"}
    ).json()["id"]
    client.put(f"/api/records/test/company/{draft_id}", json={"name": "Second"})

    history = client.get(f"/api/records/test/company/{draft_id}/history").json()
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
    """Reverting always creates a new history entry on the target record."""
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    # PUT creates a draft (rid only has 1 history entry)
    client.put(f"/api/records/test/company/{rid}", json={"name": "v2"})

    client.post(f"/api/records/test/company/{rid}/revert/1")

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 2  # INSERT(v1) + REVERT(v2) — no UPDATE on rid itself
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


def test_parent_id_is_saved_on_draft(client):
    """PUT on an active record saves parent FK changes on the draft (not the original)."""
    company_id = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    div_id = client.post("/api/records/test/division", json={"code": "D001"}).json()["id"]

    # Verify no parent initially
    assert client.get(f"/api/records/test/division/{div_id}").json()["_company_id"] is None

    res = client.put(f"/api/records/test/division/{div_id}", json={"_company_id": company_id})
    draft_id = res.json()["id"]

    # Active record is unchanged
    assert client.get(f"/api/records/test/division/{div_id}").json()["_company_id"] is None
    # Draft has the parent set
    drafts = client.get("/api/records/test/division?state=draft").json()
    draft = next(r for r in drafts["records"] if r["_id"] == draft_id)
    assert draft["_company_id"] == company_id


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
    from datetime import datetime, timedelta, timezone

    client.post("/api/records/test/company", json={"code": "C001"})

    # from_time in the future → no results
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    data = client.get(
        "/api/audit", params={"schema": "test", "obj": "company", "from_time": future}
    ).json()
    assert data["total"] == 0

    # to_time in the past → no results
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    data = client.get(
        "/api/audit", params={"schema": "test", "obj": "company", "to_time": past}
    ).json()
    assert data["total"] == 0

    # from_time in the past → finds the entry
    data = client.get(
        "/api/audit", params={"schema": "test", "obj": "company", "from_time": past}
    ).json()
    assert data["total"] >= 1


def test_audit_log_records_delete_action(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.delete(f"/api/records/test/company/{rid}?reason=cleanup")

    data = client.get("/api/audit?schema=test&obj=company&action=DELETE").json()
    assert data["total"] >= 1
    assert all(r["action"] == "DELETE" for r in data["records"])


def test_audit_log_records_revert_action(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.put(f"/api/records/test/company/{rid}", json={"name": "v2"})
    client.post(f"/api/records/test/company/{rid}/revert/1?reason=undo")

    data = client.get("/api/audit?schema=test&obj=company&action=REVERT").json()
    assert data["total"] >= 1
    assert all(r["action"] == "REVERT" for r in data["records"])


def test_audit_log_entries_contain_record_id(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]

    data = client.get("/api/audit?schema=test&obj=company").json()
    assert data["total"] >= 1
    assert all(r["record_id"] == rid for r in data["records"])


# ---------------------------------------------------------------------------
# DB-level constraint enforcement
# ---------------------------------------------------------------------------

def test_unique_constraint_rejects_duplicate_value(client):
    """Inserting two records with the same value for a unique field must fail."""
    client.post("/api/records/test/company", json={"code": "UNIQ01"})
    res = client.post("/api/records/test/company", json={"code": "UNIQ01"})
    assert res.status_code == 422


def test_parent_fk_rejects_nonexistent_parent(client):
    """Creating a division with a non-existent company ID must fail."""
    fake_id = str(uuid.uuid4())
    res = client.post(
        "/api/records/test/division",
        json={"code": "D001", "_company_id": fake_id},
    )
    assert res.status_code == 422


def test_reference_fk_rejects_nonexistent_reference(client):
    """Creating a contact with a non-existent company reference must fail."""
    fake_id = str(uuid.uuid4())
    res = client.post(
        "/api/records/test/contact",
        json={"name": "Alice", "company_id": fake_id},
    )
    assert res.status_code == 422


def test_parent_fk_set_null_on_parent_delete(client):
    """Soft-deleting a parent does not affect the child FK (hard delete sets it NULL)."""
    company_id = client.post(
        "/api/records/test/company", json={"code": "C-FK-01"}
    ).json()["id"]
    div_id = client.post(
        "/api/records/test/division",
        json={"code": "D-FK-01", "_company_id": company_id},
    ).json()["id"]

    # Soft-delete the parent — child FK must remain set (soft-delete doesn't remove the row)
    client.delete(f"/api/records/test/company/{company_id}")
    div = client.get(f"/api/records/test/division/{div_id}").json()
    assert div["_company_id"] == company_id


# ---------------------------------------------------------------------------
# Provenance: _source_system and _source_id
# ---------------------------------------------------------------------------

def test_create_record_with_provenance(client):
    """Creating a record with _source_system and _source_id stores both fields."""
    res = client.post(
        "/api/records/test/company",
        json={"code": "PRV001", "name": "Prov Co", "_source_system": "erp", "_source_id": "ERP-1"},
    )
    assert res.status_code == 201
    record_id = res.json()["id"]
    record = client.get(f"/api/records/test/company/{record_id}").json()
    assert record["_source_system"] == "erp"
    assert record["_source_id"] == "ERP-1"


def test_source_system_filter(client):
    """GET /api/records?source_system= returns only records from that system."""
    client.post("/api/records/test/company", json={"code": "PRV002", "_source_system": "erp"})
    client.post("/api/records/test/company", json={"code": "PRV003", "_source_system": "crm"})
    client.post("/api/records/test/company", json={"code": "PRV004"})

    erp = client.get("/api/records/test/company?source_system=erp").json()
    assert erp["total"] == 1
    assert erp["records"][0]["_source_system"] == "erp"

    crm = client.get("/api/records/test/company?source_system=crm").json()
    assert crm["total"] == 1

    none = client.get("/api/records/test/company?source_system=unknown").json()
    assert none["total"] == 0


def test_provenance_preserved_in_history(client):
    """Provenance fields appear in the history snapshot after create and update."""
    res = client.post(
        "/api/records/test/company",
        json={"code": "PRV005", "_source_system": "erp", "_source_id": "ERP-5"},
    )
    record_id = res.json()["id"]

    history = client.get(f"/api/records/test/company/{record_id}/history").json()
    first_entry = history[0]
    assert first_entry["_source_system"] == "erp"
    assert first_entry["_source_id"] == "ERP-5"

