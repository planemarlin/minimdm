"""Config-based validation rules (v0.8.0) — see docs/reference.md's "Validation
Rules" section for the full contract, and docs/known_issues.md's Design
Decisions section for what's intentionally deferred (allowed-value lists,
reference_state) and why.

The `validation_demo` object lives in tests/conftest.py's SAMPLE_CONFIG (not
here) so it's synced once by the session-scoped `client` fixture like every
other test object, and cleaned up per-test by the shared `clean_records`
fixture.
"""

from app.core.schema_loader import validate_config


def _create(client, **attrs):
    return client.post("/api/records/test/validation_demo", json=attrs)


def test_min_max_violation_requires_confirmation(client, clean_records):
    resp = _create(client, unit_price=-5)
    assert resp.status_code == 422
    body = resp.json()
    assert body["confirmation_required"] is True
    assert any(v["attribute"] == "unit_price" for v in body["validation_rule_violations"])

    resp = client.post(
        "/api/records/test/validation_demo",
        json={"unit_price": -5},
        params={"confirm_validation_override": "true"},
    )
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "invalid"


def test_char_class_alpha_allows_unicode_letters_rejects_digits(client, clean_records):
    resp = _create(client, display_name="Renée")
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    resp = _create(client, display_name="abc123")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_char_class_alnum_rejects_special_characters(client, clean_records):
    resp = _create(client, code="AB12")
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    resp = _create(client, code="AB-12#")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_required_if_value_scoped(client, clean_records):
    # country != US: state may be absent
    resp = _create(client, country="DE")
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    # country == US: state is now required
    resp = _create(client, country="US")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_required_if_presence_scoped(client, clean_records):
    # contact_name absent: contact_phone may be absent
    resp = _create(client)
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    # contact_name present: contact_phone is now required
    resp = _create(client, contact_name="Alice")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_forbidden_if_absent(client, clean_records):
    # both absent: fine
    resp = _create(client)
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    # secondary_ref present while primary_ref absent: violates the rule
    resp = _create(client, secondary_ref="X")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_compare_field_end_date_after_start_date(client, clean_records):
    resp = _create(client, start_date="2026-01-01", end_date="2026-06-01")
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    resp = _create(client, start_date="2026-06-01", end_date="2026-01-01")
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True


def test_compare_field_checked_on_update_of_only_one_side(client, clean_records):
    """A cross-field rule must see the full merged record, not just the
    fields present in a given request — editing only end_date must still be
    checked against the record's existing start_date."""
    create_resp = _create(client, start_date="2026-01-01", end_date="2026-06-01")
    assert create_resp.status_code == 201
    record_id = create_resp.json()["_id"]

    # Only end_date is edited; start_date isn't resent — the merged record
    # (start_date=2026-01-01, end_date=2025-01-01) violates `compare`.
    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"end_date": "2025-01-01"},
    )
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True

    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"end_date": "2025-01-01"},
        params={"confirm_validation_override": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["_validation_status"] == "invalid"


def test_override_persists_validation_status_and_audit_event(client, clean_records):
    resp = client.post(
        "/api/records/test/validation_demo",
        json={"unit_price": -5},
        params={"confirm_validation_override": "true", "override_reason": "known bad legacy data"},
    )
    assert resp.status_code == 201
    record_id = resp.json()["_id"]

    audit_resp = client.get("/api/audit", params={"schema": "test", "obj": "validation_demo"})
    matching = [e for e in audit_resp.json()["records"] if e["record_id"] == record_id]
    actions = [e["action"] for e in matching]
    assert "VALIDATION_OVERRIDE" in actions


def test_hard_constraints_are_not_overridable(client, clean_records):
    """confirm_validation_override must never bypass required/type/unique checks."""
    resp = client.post(
        "/api/records/test/validation_demo",
        json={"unit_price": "not-a-number"},
        params={"confirm_validation_override": "true"},
    )
    assert resp.status_code == 422
    assert "confirmation_required" not in resp.json()


def test_publish_recomputes_validation_status_not_copies_it(client, clean_records):
    """publish_record never blocks on an invalid record (informational only), and
    recomputes _validation_status against the promoted data rather than copying
    the draft's stale status."""
    create_resp = client.post(
        "/api/records/test/validation_demo",
        json={"unit_price": -5},
        params={"confirm_validation_override": "true"},
    )
    assert create_resp.status_code == 201
    record_id = create_resp.json()["_id"]
    assert create_resp.json()["_validation_status"] == "invalid"

    # Editing the active record creates a draft alongside it (draft-copy-on-edit).
    fix_resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"unit_price": 100},
    )
    assert fix_resp.status_code == 200
    assert fix_resp.json()["draft"] is True
    assert fix_resp.json()["_validation_status"] == "valid"
    draft_id = fix_resp.json()["id"]

    publish_resp = client.post(f"/api/records/test/validation_demo/{draft_id}/publish")
    assert publish_resp.status_code == 200

    active = client.get(f"/api/records/test/validation_demo/{record_id}").json()
    assert active["_validation_status"] == "valid"


def test_publish_does_not_block_a_still_invalid_record(client, clean_records):
    """A publisher must be able to promote a draft that still violates a rule —
    publishing is informational only and never requires its own override/confirm
    step, per the design doc's locked decision. The promoted active record must
    correctly carry _validation_status: "invalid", not silently flip to "valid"."""
    create_resp = client.post(
        "/api/records/test/validation_demo",
        json={"unit_price": -5},
        params={"confirm_validation_override": "true"},
    )
    assert create_resp.status_code == 201
    record_id = create_resp.json()["_id"]

    # Edit some other field, leaving unit_price still invalid — no override needed
    # here because unit_price isn't part of this request, but the merged record
    # (used for validation) is still invalid, so the draft is created as invalid.
    edit_resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"code": "AB12"},
        params={"confirm_validation_override": "true"},
    )
    assert edit_resp.status_code == 200
    assert edit_resp.json()["_validation_status"] == "invalid"
    draft_id = edit_resp.json()["id"]

    # Publish must succeed outright — no confirmation_required, no 422.
    publish_resp = client.post(f"/api/records/test/validation_demo/{draft_id}/publish")
    assert publish_resp.status_code == 200
    assert "confirmation_required" not in publish_resp.json()

    active = client.get(f"/api/records/test/validation_demo/{record_id}").json()
    assert active["_validation_status"] == "invalid"
    assert active["unit_price"] == -5


def test_import_never_hard_fails_on_rule_violation_but_flags_rows(client, clean_records):
    csv_content = "code,unit_price\nAB12,100\nCD34,-5\n"
    resp = client.post(
        "/api/records/test/validation_demo/import",
        files={"file": ("demo.csv", csv_content, "text/csv")},
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["imported"] == 2
    flagged = [r for r in body["rows"] if r.get("_validation_status") == "invalid"]
    assert len(flagged) == 1
    assert flagged[0]["code"] == "CD34"


def test_validate_config_rejects_dangling_rule_references():
    bad_config = {
        "schemas": {
            "test": {
                "objects": {
                    "widget": {
                        "attributes": {
                            "a": {
                                "name": "A",
                                "type": "string",
                                "required_if": {"field": "does_not_exist", "equals": "x"},
                            },
                            "b": {
                                "name": "B",
                                "type": "string",
                                "forbidden_if_absent": "also_missing",
                            },
                            "c": {
                                "name": "C",
                                "type": "string",
                                "compare": {"op": "bogus_op", "field": "a"},
                            },
                        }
                    }
                }
            }
        }
    }
    errors = validate_config(bad_config)
    assert any("required_if.field" in e for e in errors)
    assert any("forbidden_if_absent" in e for e in errors)
    assert any("compare.op" in e for e in errors)


def test_validate_config_rejects_invalid_char_class():
    bad_config = {
        "schemas": {"test": {"objects": {"widget": {"attributes": {
            "a": {"name": "A", "type": "string", "char_class": "numeric"},
        }}}}}
    }
    errors = validate_config(bad_config)
    assert any("char_class" in e for e in errors)


def test_client_cannot_set_validation_status_directly(client, clean_records):
    """_validation_status is a computed system column — a caller-supplied value
    in the request body must be silently ignored, not persisted verbatim."""
    resp = _create(client, unit_price=100, _validation_status="invalid")
    assert resp.status_code == 201
    assert resp.json()["_validation_status"] == "valid"

    record_id = resp.json()["_id"]
    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"unit_price": 200, "_validation_status": "invalid"},
    )
    assert resp.status_code == 200
    assert resp.json()["_validation_status"] == "valid"


def test_required_if_checked_on_update_of_only_the_triggering_field(client, clean_records):
    """Same merged-document requirement as the `compare` case, but for
    `required_if`: editing only `country` (not `state`) must still be checked
    against the record's existing (absent) `state`."""
    create_resp = _create(client, country="DE")
    assert create_resp.status_code == 201
    record_id = create_resp.json()["_id"]

    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"country": "US"},
    )
    assert resp.status_code == 422
    assert resp.json()["confirmation_required"] is True

    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"country": "US"},
        params={"confirm_validation_override": "true"},
    )
    assert resp.status_code == 200
    assert resp.json()["_validation_status"] == "invalid"


def test_validation_override_audit_event_on_update(client, clean_records):
    """The VALIDATION_OVERRIDE audit event must also fire on update, not just
    create — every update_record branch (draft-copy-on-edit, in-place) sets it
    independently and each needs its own coverage."""
    create_resp = _create(client, unit_price=100)
    assert create_resp.status_code == 201
    record_id = create_resp.json()["_id"]

    resp = client.put(
        f"/api/records/test/validation_demo/{record_id}",
        json={"unit_price": -5},
        params={"confirm_validation_override": "true", "override_reason": "known bad update"},
    )
    assert resp.status_code == 200
    draft_id = resp.json()["id"]

    audit_resp = client.get("/api/audit", params={"schema": "test", "obj": "validation_demo"})
    matching = [e for e in audit_resp.json()["records"] if e["record_id"] == draft_id]
    assert "VALIDATION_OVERRIDE" in [e["action"] for e in matching]


def test_upsert_import_flags_violation_without_hard_failing(client, clean_records):
    """The upsert import codepath (_upsert_row) has its own separate
    violation-check-and-set wiring from plain import (_import_row) — covers
    both the fresh-insert and update-existing-active-record branches."""
    _create(client, code="AB12", unit_price=100)

    csv_content = "code,unit_price\nAB12,-5\nCD34,50\n"
    resp = client.post(
        "/api/records/test/validation_demo/import?upsert_key=code",
        files={"file": ("demo.csv", csv_content, "text/csv")},
    )
    assert resp.status_code in (200, 201)
    body = resp.json()
    assert body["updated"] == 1
    assert body["inserted"] == 1
    by_code = {r["code"]: r for r in body["rows"]}
    assert by_code["AB12"]["_validation_status"] == "invalid"
    assert by_code["CD34"]["_validation_status"] == "valid"


def test_inbound_push_flags_violation_without_hard_failing(client, clean_records, inbound_key):
    """_inbound_upsert has its own separate violation-check-and-set wiring from
    both _import_row and _upsert_row — a rule violation on a pushed record
    must not reject the webhook call, and must still stamp _validation_status
    on the resulting draft."""
    res = client.post(
        "/api/inbound/test/validation_demo",
        json={"erp_id": "ERP-1", "item_code": "AB12", "price": -5},
        headers={"X-Api-Key": inbound_key},
    )
    assert res.status_code == 201
    draft_id = res.json()["id"]

    record = client.get(f"/api/records/test/validation_demo/{draft_id}").json()
    assert record["_validation_status"] == "invalid"
    assert record["unit_price"] == -5


def test_publish_new_record_draft_recomputes_validation_status(client, clean_records):
    """The "brand new draft, no master record" branch of publish_record (used
    by requires_draft: true objects) recomputes _validation_status the same
    way as the draft-of-an-existing-active-record branch — a separate code
    path in objects.py that needs its own test."""
    resp = client.post(
        "/api/records/test/governed_item",
        json={"code": "GOV-VAL-1", "unit_price": -5},
        params={"confirm_validation_override": "true"},
    )
    assert resp.status_code == 201
    draft_id = resp.json()["_id"]
    assert resp.json()["_validation_status"] == "invalid"

    publish_resp = client.post(f"/api/records/test/governed_item/{draft_id}/publish")
    assert publish_resp.status_code == 200

    active = client.get(f"/api/records/test/governed_item/{draft_id}").json()
    assert active["_state"] == "active"
    assert active["_validation_status"] == "invalid"
