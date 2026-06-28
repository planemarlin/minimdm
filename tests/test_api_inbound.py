"""Integration tests for the inbound webhook receiver (POST /api/inbound/{schema}/{obj})."""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set",
)

INBOUND_URL = "/api/inbound/test/company"


def _post(client, raw_key, payload):
    return client.post(
        INBOUND_URL,
        json=payload,
        headers={"X-Api-Key": raw_key},
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def test_missing_api_key(client, clean_records):
    res = client.post(INBOUND_URL, json={"erp_id": "E1", "company_name": "Acme",
                                         "company_code": "A1"})
    assert res.status_code == 401


def test_wrong_api_key(client, clean_records, inbound_key):
    res = client.post(
        INBOUND_URL,
        json={"erp_id": "E1", "company_name": "Acme", "company_code": "A1"},
        headers={"X-Api-Key": "completely-wrong-key"},
    )
    assert res.status_code == 401


def test_unknown_schema(client, inbound_key):
    res = client.post(
        "/api/inbound/nonexistent/company",
        json={"erp_id": "E1"},
        headers={"X-Api-Key": inbound_key},
    )
    assert res.status_code == 404


def test_unknown_object(client, inbound_key):
    res = client.post(
        "/api/inbound/test/nonexistent",
        json={"erp_id": "E1"},
        headers={"X-Api-Key": inbound_key},
    )
    assert res.status_code == 404


def test_object_without_inbound_sources(client, inbound_key):
    """division has no inbound_sources configured — should return 403."""
    res = client.post(
        "/api/inbound/test/division",
        json={"erp_id": "E1"},
        headers={"X-Api-Key": inbound_key},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Create (new record)
# ---------------------------------------------------------------------------

def test_missing_required_field_returns_422(client, clean_records, inbound_key):
    """Omitting a required field must return 422, not crash with a 500."""
    # 'code' is required:true in the test schema — send a push without it
    res = _post(client, inbound_key, {"erp_id": "E-REQ", "company_name": "No Code"})
    assert res.status_code == 422


def test_create_new_draft(client, clean_records, inbound_key):
    res = _post(client, inbound_key,
                {"erp_id": "E001", "company_name": "Acme", "company_code": "ACM"})
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "created"
    assert "id" in data

    # Verify the record exists as a draft
    record_res = client.get(f"/api/records/test/company/{data['id']}")
    assert record_res.status_code == 200
    rec = record_res.json()
    assert rec["_state"] == "draft"
    assert rec["_source_system"] == "test_erp"
    assert rec["_source_id"] == "E001"
    assert rec["name"] == "Acme"
    assert rec["code"] == "ACM"


def test_field_mapping_applied(client, clean_records, inbound_key):
    """Source field names should not appear; miniMDM field names should."""
    res = _post(client, inbound_key,
                {"erp_id": "E002", "company_name": "Beta", "company_code": "BTA"})
    assert res.status_code == 201
    rec = client.get(f"/api/records/test/company/{res.json()['id']}").json()
    assert "erp_id" not in rec
    assert "company_name" not in rec
    assert rec["name"] == "Beta"
    assert rec["_source_id"] == "E002"


def test_source_system_not_overridable(client, clean_records, inbound_key):
    """Payload attempts to override _source_system — config value must win."""
    res = _post(client, inbound_key, {
        "erp_id": "E003", "company_name": "Gamma", "company_code": "GAM",
        "_source_system": "attacker",
    })
    assert res.status_code == 201
    rec = client.get(f"/api/records/test/company/{res.json()['id']}").json()
    assert rec["_source_system"] == "test_erp"


def test_audit_log_shows_inbound_username(client, clean_records, inbound_key):
    res = _post(client, inbound_key,
                {"erp_id": "E010", "company_name": "Audit Co", "company_code": "AUD"})
    assert res.status_code == 201
    record_id = res.json()["id"]

    audit_res = client.get(f"/api/audit?record_id={record_id}")
    assert audit_res.status_code == 200
    entries = audit_res.json()["records"]
    assert any(e.get("user_name") == "inbound:test_erp" for e in entries)


# ---------------------------------------------------------------------------
# Update — existing active record
# ---------------------------------------------------------------------------

def test_update_creates_draft_copy(client, clean_records, inbound_key):
    """Second push with same erp_id and an existing active record → draft copy."""
    # First push → draft
    first_res = _post(client, inbound_key,
                      {"erp_id": "E004", "company_name": "Delta", "company_code": "DLT"})
    assert first_res.status_code == 201
    draft_id = first_res.json()["id"]

    # Publish the draft so there's an active record
    pub = client.post(f"/api/records/test/company/{draft_id}/publish")
    assert pub.status_code == 200

    # Second push → should create a draft copy of the active record
    second_res = _post(client, inbound_key, {"erp_id": "E004", "company_name": "Delta Updated"})
    assert second_res.status_code == 200
    data = second_res.json()
    assert data["status"] == "updated"
    new_draft_id = data["id"]
    assert new_draft_id != draft_id

    new_draft = client.get(f"/api/records/test/company/{new_draft_id}").json()
    assert new_draft["_state"] == "draft"
    assert new_draft["name"] == "Delta Updated"
    assert new_draft["_draft_of_id"] is not None

    # Active record is unchanged
    active = client.get(f"/api/records/test/company/{draft_id}").json()
    assert active["_state"] == "active"
    assert active["name"] == "Delta"


def test_update_preserves_unmapped_fields(client, clean_records, inbound_key):
    """Publisher-enriched fields not in field_map must survive an inbound update."""
    # Create active record via inbound
    first = _post(client, inbound_key,
                  {"erp_id": "E005", "company_name": "Echo", "company_code": "ECH"})
    assert first.status_code == 201
    draft_id = first.json()["id"]
    client.post(f"/api/records/test/company/{draft_id}/publish")

    # Publisher enriches the active record's name (unmapped field) — simulate via regular API
    # (name is mapped but code is also mapped; there are no truly unmapped user fields in this
    # test schema. We test that code is preserved when the push omits it.)
    second = _post(client, inbound_key, {"erp_id": "E005", "company_name": "Echo Renamed"})
    assert second.status_code == 200
    new_draft = client.get(f"/api/records/test/company/{second.json()['id']}").json()
    assert new_draft["name"] == "Echo Renamed"
    assert new_draft["code"] == "ECH"  # preserved from active record, not in this push


def test_third_push_updates_existing_draft(client, clean_records, inbound_key):
    """Three pushes: active → draft created → draft updated (no duplicate draft)."""
    first = _post(client, inbound_key,
                  {"erp_id": "E006", "company_name": "Foxtrot", "company_code": "FOX"})
    assert first.status_code == 201
    client.post(f"/api/records/test/company/{first.json()['id']}/publish")

    second = _post(client, inbound_key, {"erp_id": "E006", "company_name": "Foxtrot v2"})
    assert second.status_code == 200
    draft_id = second.json()["id"]

    third = _post(client, inbound_key, {"erp_id": "E006", "company_name": "Foxtrot v3"})
    assert third.status_code == 200
    assert third.json()["id"] == draft_id  # same draft, not a new one

    updated_draft = client.get(f"/api/records/test/company/{draft_id}").json()
    assert updated_draft["name"] == "Foxtrot v3"


def test_push_update_publish_push_push(client, clean_records, inbound_key):
    """Reproduce reported bug: create draft, update it, publish, then push twice more.

    The second post-publish push must update the draft copy created by the first
    post-publish push, NOT create a second draft record.
    """
    # Push 1 → creates standalone draft
    p1 = _post(client, inbound_key,
               {"erp_id": "E007", "company_name": "Golf v1", "company_code": "GLF"})
    assert p1.status_code == 201
    draft_id = p1.json()["id"]

    # Push 2 → updates that draft in place
    p2 = _post(client, inbound_key, {"erp_id": "E007", "company_name": "Golf v2"})
    assert p2.status_code == 200
    assert p2.json()["id"] == draft_id

    # Publish → standalone draft becomes active record (same _id)
    pub = client.post(f"/api/records/test/company/{draft_id}/publish")
    assert pub.status_code == 200

    # Push 3 → active record found, draft copy created
    p3 = _post(client, inbound_key, {"erp_id": "E007", "company_name": "Golf v3"})
    assert p3.status_code == 200
    copy_draft_id = p3.json()["id"]
    assert copy_draft_id != draft_id  # a new draft, not the active record

    # Push 4 → must update the draft copy, NOT create a second draft
    p4 = _post(client, inbound_key, {"erp_id": "E007", "company_name": "Golf v4"})
    assert p4.status_code == 200
    assert p4.json()["id"] == copy_draft_id  # same draft copy

    updated = client.get(f"/api/records/test/company/{copy_draft_id}").json()
    assert updated["name"] == "Golf v4"


# ---------------------------------------------------------------------------
# Revoked key
# ---------------------------------------------------------------------------

def test_revoked_key_rejected(client, clean_records, inbound_key):
    # Confirm key works
    res = _post(client, inbound_key,
                {"erp_id": "E007", "company_name": "Golf", "company_code": "GLF"})
    assert res.status_code == 201

    # Revoke: find key by prefix
    keys_res = client.get("/api/admin/inbound-keys")
    assert keys_res.status_code == 200
    key_entry = next(
        (k for k in keys_res.json() if k["source_name"] == "test_erp" and k["is_active"]),
        None,
    )
    assert key_entry is not None
    del_res = client.delete(f"/api/admin/inbound-keys/{key_entry['id']}")
    assert del_res.status_code == 204

    # Now the same key should fail
    res2 = _post(client, inbound_key,
                 {"erp_id": "E008", "company_name": "Hotel", "company_code": "HTL"})
    assert res2.status_code == 401


# ---------------------------------------------------------------------------
# last_used_at updated
# ---------------------------------------------------------------------------

def test_last_used_at_updated(client, clean_records, inbound_key):
    _post(client, inbound_key, {"erp_id": "E009", "company_name": "India", "company_code": "IND"})

    keys = client.get("/api/admin/inbound-keys").json()
    key_entry = next(
        (k for k in keys if k["source_name"] == "test_erp" and k["is_active"]),
        None,
    )
    assert key_entry is not None
    assert key_entry["last_used_at"] is not None


# ---------------------------------------------------------------------------
# match_key fallback matching
# ---------------------------------------------------------------------------

def test_match_key_claims_existing_active_record(client, clean_records, inbound_key):
    """Pushing a record whose _source_id is unknown but whose business key (code) matches
    an existing active record should update that record via draft-copy-on-edit rather than
    creating a duplicate, and write _source_id onto the active record so future pushes
    hit the primary path."""
    # Create an active record manually with no _source_id
    create = client.post("/api/records/test/company", json={"name": "Gamma", "code": "GAM"})
    assert create.status_code == 201
    active_id = create.json()["id"]

    # Push via inbound — erp_id is new, but code "GAM" matches the existing record
    res = _post(client, inbound_key, {"erp_id": "E-GAM", "company_name": "Gamma ERP",
                                      "company_code": "GAM"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "updated"
    draft_id = data["id"]
    assert draft_id != str(active_id)

    # Draft is linked to the original active record
    draft = client.get(f"/api/records/test/company/{draft_id}").json()
    assert draft["_state"] == "draft"
    assert draft["_draft_of_id"] == str(active_id)
    assert draft["name"] == "Gamma ERP"

    # Active record now has _source_id stamped on it (claimed)
    active = client.get(f"/api/records/test/company/{active_id}").json()
    assert active["_source_system"] == "test_erp"
    assert active["_source_id"] == "E-GAM"


def test_match_key_subsequent_push_uses_primary_path(client, clean_records, inbound_key):
    """After a record is claimed via match_key, the next push matches by _source_id
    and updates the same draft rather than creating a duplicate."""
    client.post("/api/records/test/company", json={"name": "Hotel", "code": "HTL"})

    # First push: claim via match_key, creates draft
    first = _post(client, inbound_key, {"erp_id": "E-HTL", "company_name": "Hotel ERP",
                                        "company_code": "HTL"})
    assert first.status_code == 200
    draft_id = first.json()["id"]

    # Second push: hits primary _source_id path, updates same draft
    second = _post(client, inbound_key, {"erp_id": "E-HTL", "company_name": "Hotel ERP v2",
                                         "company_code": "HTL"})
    assert second.status_code == 200
    assert second.json()["id"] == draft_id


def test_match_key_second_push_after_claim_updates_draft(client, clean_records, inbound_key):
    """Reproduce the reported bug: after match_key claims an active record and creates a
    draft, the SECOND push must update that draft — not create a new one.

    Before the fix the match_key candidates query returned both the active record AND the
    draft copy (both share the same code value), counted them as >1 = 'ambiguous', and
    created a new standalone draft instead of updating the existing one.
    """
    # Create an active record with no _source_id (simulates a manually-entered record)
    client.post("/api/records/test/company", json={"name": "Juliet", "code": "JLT"})

    # Push 1: match_key claims the active record via code="JLT", creates draft copy
    p1 = _post(client, inbound_key, {"erp_id": "E-JLT", "company_name": "Juliet ERP",
                                     "company_code": "JLT"})
    assert p1.status_code == 200
    draft_id = p1.json()["id"]

    # Push 2: BOTH the active record AND the draft copy have code="JLT".
    # This must update the existing draft, not create a second one.
    p2 = _post(client, inbound_key, {"erp_id": "E-JLT", "company_name": "Juliet ERP v2",
                                     "company_code": "JLT"})
    assert p2.status_code == 200
    assert p2.json()["status"] == "updated"
    assert p2.json()["id"] == draft_id  # same draft, not a new record

    updated = client.get(f"/api/records/test/company/{draft_id}").json()
    assert updated["name"] == "Juliet ERP v2"


def test_match_key_no_match_creates_new_draft(client, clean_records, inbound_key):
    """When match_key finds no existing record, a new draft is created normally."""
    res = _post(client, inbound_key, {"erp_id": "E-BRNW", "company_name": "Brand New",
                                      "company_code": "BRNW"})
    assert res.status_code == 201
    assert res.json()["status"] == "created"


# ---------------------------------------------------------------------------
# Admin key management
# ---------------------------------------------------------------------------

def test_generate_and_list_key(client):
    res = client.post("/api/admin/inbound-keys", json={
        "schema_name": "test",
        "source_name": "test_erp",
        "description": "Test gen",
    })
    assert res.status_code == 201
    data = res.json()
    assert "key" in data
    assert len(data["key"]) > 20
    assert data["key_prefix"] == data["key"][:8]

    # Clean up
    client.delete(f"/api/admin/inbound-keys/{data['id']}")


def test_generate_key_missing_fields(client):
    res = client.post("/api/admin/inbound-keys", json={"schema_name": "test"})
    assert res.status_code == 400


def test_list_inbound_sources(client):
    res = client.get("/api/admin/inbound-keys/sources")
    assert res.status_code == 200
    sources = res.json()
    assert any(s["schema_name"] == "test" and s["source_name"] == "test_erp" for s in sources)


def test_generate_key_invalid_source_name(client):
    """source_name must be a valid identifier — rejects names with special chars."""
    for bad_name in ["my-source", "123source", "src name", "src'name"]:
        res = client.post("/api/admin/inbound-keys", json={
            "schema_name": "test",
            "source_name": bad_name,
        })
        assert res.status_code == 400, f"expected 400 for source_name={bad_name!r}"


def test_inbound_oversized_body(client, inbound_key):
    """Payloads exceeding MAX_UPLOAD_SIZE are rejected with 413."""
    big_payload = {"erp_id": "X", "company_name": "A" * (11 * 1024 * 1024)}
    res = client.post(
        "/api/inbound/test/company",
        json=big_payload,
        headers={"X-Api-Key": inbound_key},
    )
    assert res.status_code == 413


def test_inbound_invalid_json(client, inbound_key):
    """Non-JSON body is rejected with 400."""
    res = client.post(
        "/api/inbound/test/company",
        content=b"not json at all",
        headers={"X-Api-Key": inbound_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_inbound_non_object_json(client, inbound_key):
    """JSON array body (not an object) is rejected with 400."""
    res = client.post(
        "/api/inbound/test/company",
        content=b'["a", "b"]',
        headers={"X-Api-Key": inbound_key, "Content-Type": "application/json"},
    )
    assert res.status_code == 400


def test_inbound_call_audit_event(client, clean_records, inbound_key):
    """A successful inbound push writes an INBOUND_CALL entry to the _system audit log."""
    client.post(
        "/api/inbound/test/company",
        json={"erp_id": "AUDIT-1", "company_name": "Audit Co", "company_code": "AUD1"},
        headers={"X-Api-Key": inbound_key},
    )
    audit = client.get("/api/audit?schema=_system&action=INBOUND_CALL").json()
    assert audit["total"] >= 1
    entry = audit["records"][0]
    assert entry["action"] == "INBOUND_CALL"
    assert entry["user_name"] == "inbound:test_erp"


def test_inbound_call_failed_audit_event(client):
    """A rejected inbound push (bad key) writes an INBOUND_CALL_FAILED entry."""
    client.post(
        "/api/inbound/test/company",
        json={"erp_id": "X"},
        headers={"X-Api-Key": "invalid-key-value"},
    )
    audit = client.get("/api/audit?schema=_system&action=INBOUND_CALL_FAILED").json()
    assert audit["total"] >= 1
    assert audit["records"][0]["action"] == "INBOUND_CALL_FAILED"
