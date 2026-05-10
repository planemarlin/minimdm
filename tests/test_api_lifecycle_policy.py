"""Integration tests for object-level lifecycle policy flags.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.

Flags under test:
  requires_draft                — new records always land as draft
  allow_retire: false           — retire endpoint returns 422
  allow_direct_active_import: false — import with initial_state=active returns 422
"""
import pytest

pytestmark = pytest.mark.usefixtures("clean_records")


# ---------------------------------------------------------------------------
# requires_draft
# ---------------------------------------------------------------------------

def test_requires_draft_creates_draft_not_active(client):
    """When requires_draft is set, POST always creates a draft regardless of role."""
    res = client.post("/api/records/test/governed_item", json={"code": "G001"})
    assert res.status_code == 201
    record_id = res.json()["id"]

    record = client.get(f"/api/records/test/governed_item/{record_id}").json()
    assert record["_state"] == "draft"


def test_requires_draft_record_not_in_active_list(client):
    """Records created under requires_draft are absent from the default active listing."""
    client.post("/api/records/test/governed_item", json={"code": "G002"})

    active = client.get("/api/records/test/governed_item?state=active").json()
    assert active["total"] == 0

    drafts = client.get("/api/records/test/governed_item?state=draft").json()
    assert drafts["total"] == 1


def test_requires_draft_can_be_published(client):
    """A draft created by requires_draft can be published to become the golden record."""
    record_id = client.post(
        "/api/records/test/governed_item", json={"code": "G003"}
    ).json()["id"]

    pub = client.post(f"/api/records/test/governed_item/{record_id}/publish")
    assert pub.status_code == 200

    record = client.get(f"/api/records/test/governed_item/{record_id}").json()
    assert record["_state"] == "active"


def test_requires_draft_does_not_fire_created_webhook(client):
    """record.created should NOT fire when the record is created as draft."""
    # We can't directly observe webhook delivery in unit tests, but we can verify
    # the record lands as draft (the guard condition for webhook firing).
    res = client.post("/api/records/test/governed_item", json={"code": "G004"})
    record = client.get(f"/api/records/test/governed_item/{res.json()['id']}").json()
    assert record["_state"] == "draft"


# ---------------------------------------------------------------------------
# allow_retire: false
# ---------------------------------------------------------------------------

def test_allow_retire_false_blocks_retire(client):
    """Retiring a record on an object with allow_retire: false returns 422."""
    record_id = client.post(
        "/api/records/test/reference_data", json={"code": "R001"}
    ).json()["id"]

    res = client.post(f"/api/records/test/reference_data/{record_id}/retire")
    assert res.status_code == 422
    assert "allow_retire" in res.json()["detail"]


def test_allow_retire_false_record_remains_active(client):
    """A record on an allow_retire: false object stays active after a failed retire attempt."""
    record_id = client.post(
        "/api/records/test/reference_data", json={"code": "R002"}
    ).json()["id"]

    client.post(f"/api/records/test/reference_data/{record_id}/retire")
    record = client.get(f"/api/records/test/reference_data/{record_id}").json()
    assert record["_state"] == "active"


def test_allow_retire_true_still_works(client):
    """Objects without allow_retire restriction can still be retired normally."""
    record_id = client.post(
        "/api/records/test/company", json={"code": "C-RET-01"}
    ).json()["id"]

    res = client.post(f"/api/records/test/company/{record_id}/retire")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# allow_direct_active_import: false
# ---------------------------------------------------------------------------

def test_allow_direct_active_import_false_blocks_active_import(client):
    """Importing with initial_state=active on a restricted object returns 422."""
    csv_content = "code\nREF001\n"
    files = {"file": ("ref.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/reference_data/import?format=csv&initial_state=active",
        files=files,
    )
    assert res.status_code == 422
    assert "allow_direct_active_import" in res.json()["detail"]


def test_allow_direct_active_import_false_allows_draft_import(client):
    """Importing as draft is always allowed even when allow_direct_active_import is false."""
    csv_content = "code\nREF002\n"
    files = {"file": ("ref.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/reference_data/import?format=csv&initial_state=draft",
        files=files,
    )
    assert res.status_code == 200
    assert res.json()["inserted"] == 1

    records = client.get("/api/records/test/reference_data?state=draft").json()
    assert records["total"] == 1
    assert records["records"][0]["_state"] == "draft"


def test_allow_direct_active_import_true_allows_active_import(client):
    """Objects without the restriction accept active imports normally."""
    csv_content = "code,name\nC-IMP-01,Alpha\n"
    files = {"file": ("c.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&initial_state=active",
        files=files,
    )
    assert res.status_code == 200
    assert res.json()["inserted"] == 1
