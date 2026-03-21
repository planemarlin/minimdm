"""Integration tests for list-records query parameters added in recent versions:
- ref_field / ref_id filtering
- sort_by / sort_dir ordering

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import pytest

pytestmark = pytest.mark.usefixtures("clean_records")


# ---------------------------------------------------------------------------
# ref_field / ref_id filtering
# ---------------------------------------------------------------------------

def test_ref_field_filter_returns_only_matching_records(client):
    """Records whose reference attribute matches ref_id are returned; others are not."""
    co1 = client.post(
        "/api/records/test/company", json={"code": "C01", "name": "Alpha"}
    ).json()["id"]
    co2 = client.post(
        "/api/records/test/company", json={"code": "C02", "name": "Beta"}
    ).json()["id"]

    client.post("/api/records/test/contact", json={"name": "Alice", "company_id": co1})
    client.post("/api/records/test/contact", json={"name": "Bob", "company_id": co1})
    client.post("/api/records/test/contact", json={"name": "Carol", "company_id": co2})

    res = client.get(f"/api/records/test/contact?ref_field=company&ref_id={co1}")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    names = {r["name"] for r in data["records"]}
    assert names == {"Alice", "Bob"}


def test_ref_field_filter_returns_empty_when_no_match(client):
    co = client.post(
        "/api/records/test/company", json={"code": "C01", "name": "Alpha"}
    ).json()["id"]
    client.post("/api/records/test/contact", json={"name": "Alice", "company_id": co})

    other_id = "00000000-0000-0000-0000-000000000099"
    res = client.get(f"/api/records/test/contact?ref_field=company&ref_id={other_id}")
    assert res.status_code == 200
    assert res.json()["total"] == 0


def test_ref_field_filter_invalid_uuid_returns_all(client):
    """An invalid ref_id UUID is silently ignored — the filter is not applied."""
    co = client.post("/api/records/test/company", json={"code": "C01"}).json()["id"]
    client.post("/api/records/test/contact", json={"name": "Alice", "company_id": co})

    res = client.get("/api/records/test/contact?ref_field=company&ref_id=not-a-uuid")
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_ref_field_without_ref_id_is_ignored(client):
    """Providing ref_field alone (no ref_id) must not crash and returns all records."""
    co = client.post("/api/records/test/company", json={"code": "C01"}).json()["id"]
    client.post("/api/records/test/contact", json={"name": "Alice", "company_id": co})

    res = client.get("/api/records/test/contact?ref_field=company")
    assert res.status_code == 200
    assert res.json()["total"] == 1


# ---------------------------------------------------------------------------
# sort_by / sort_dir
# ---------------------------------------------------------------------------

def test_sort_by_asc_returns_records_in_order(client):
    client.post("/api/records/test/company", json={"code": "C03", "name": "Gamma"})
    client.post("/api/records/test/company", json={"code": "C01", "name": "Alpha"})
    client.post("/api/records/test/company", json={"code": "C02", "name": "Beta"})

    res = client.get("/api/records/test/company?sort_by=code&sort_dir=asc")
    assert res.status_code == 200
    codes = [r["code"] for r in res.json()["records"]]
    assert codes == sorted(codes)


def test_sort_by_desc_returns_records_in_reverse_order(client):
    client.post("/api/records/test/company", json={"code": "C01"})
    client.post("/api/records/test/company", json={"code": "C03"})
    client.post("/api/records/test/company", json={"code": "C02"})

    res = client.get("/api/records/test/company?sort_by=code&sort_dir=desc")
    assert res.status_code == 200
    codes = [r["code"] for r in res.json()["records"]]
    assert codes == sorted(codes, reverse=True)


def test_invalid_sort_dir_returns_422(client):
    res = client.get("/api/records/test/company?sort_dir=sideways")
    assert res.status_code == 422


def test_unknown_sort_by_falls_back_to_default(client):
    """An unrecognised sort_by column must not crash — falls back to first attribute."""
    client.post("/api/records/test/company", json={"code": "C01"})
    res = client.get("/api/records/test/company?sort_by=nonexistent_col")
    assert res.status_code == 200
    assert res.json()["total"] == 1


def test_default_sort_is_first_attribute(client):
    """Without sort_by the default is the first attribute in the config (code), ascending."""
    client.post("/api/records/test/company", json={"code": "C02"})
    client.post("/api/records/test/company", json={"code": "C01"})

    res = client.get("/api/records/test/company")
    assert res.status_code == 200
    codes = [r["code"] for r in res.json()["records"]]
    assert codes == sorted(codes)
