"""API integration tests for CSV/TSV/JSON import and export.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import json

import pytest

pytestmark = pytest.mark.usefixtures("clean_records")


# ---------------------------------------------------------------------------
# Export – empty table
# ---------------------------------------------------------------------------

def test_export_csv_empty(client):
    res = client.get("/api/records/test/company/export?format=csv")
    assert res.status_code == 200


def test_export_tsv_empty(client):
    res = client.get("/api/records/test/company/export?format=tsv")
    assert res.status_code == 200


def test_export_json_empty(client):
    res = client.get("/api/records/test/company/export?format=json")
    assert res.status_code == 200
    assert res.json() == []


# ---------------------------------------------------------------------------
# Export – with data
# ---------------------------------------------------------------------------

def test_export_csv_contains_data(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha"})
    client.post("/api/records/test/company", json={"code": "C002", "name": "Beta"})

    res = client.get("/api/records/test/company/export?format=csv")
    assert res.status_code == 200
    content = res.text
    assert "C001" in content
    assert "C002" in content


def test_export_json_contains_data(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Alpha"})

    res = client.get("/api/records/test/company/export?format=json")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert data[0]["code"] == "C001"


def test_export_excludes_deleted_records(client):
    rid = client.post("/api/records/test/company", json={"code": "C001"}).json()["id"]
    client.post("/api/records/test/company", json={"code": "C002"})
    client.delete(f"/api/records/test/company/{rid}")

    data = client.get("/api/records/test/company/export?format=json").json()
    codes = {r["code"] for r in data}
    assert codes == {"C002"}


def test_export_unknown_object_returns_404(client):
    res = client.get("/api/records/test/nonexistent/export?format=csv")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Import – insert only
# ---------------------------------------------------------------------------

def test_import_csv_insert_only(client):
    csv_content = "code,name\nC001,Alpha Corp\nC002,Beta Ltd\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post("/api/records/test/company/import?format=csv", files=files)

    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 2
    assert data["updated"] == 0
    assert data["errors"] == []
    assert data["total"] == 2

    records = client.get("/api/records/test/company").json()
    assert records["total"] == 2


def test_import_tsv(client):
    tsv_content = "code\tname\nC001\tAlpha Corp\n"
    files = {"file": ("data.tsv", tsv_content.encode(), "text/tab-separated-values")}
    res = client.post("/api/records/test/company/import?format=tsv", files=files)

    assert res.status_code == 200
    assert res.json()["inserted"] == 1


def test_import_json(client):
    payload = [{"code": "J01", "name": "Json Corp"}, {"code": "J02", "name": "Json Ltd"}]
    files = {"file": ("data.json", json.dumps(payload).encode(), "application/json")}
    res = client.post("/api/records/test/company/import?format=json", files=files)

    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 2
    assert data["errors"] == []


def test_import_ignores_unknown_columns(client):
    """Columns not in the object schema should be silently ignored."""
    csv_content = "code,name,irrelevant_col\nC001,Alpha,ignored\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post("/api/records/test/company/import?format=csv", files=files)

    assert res.status_code == 200
    assert res.json()["inserted"] == 1


def test_import_invalid_json_returns_400(client):
    files = {"file": ("data.json", b"not valid json", "application/json")}
    res = client.post("/api/records/test/company/import?format=json", files=files)
    assert res.status_code == 400


def test_import_json_non_list_returns_400(client):
    files = {"file": ("data.json", b'{"code": "C001"}', "application/json")}
    res = client.post("/api/records/test/company/import?format=json", files=files)
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Import – upsert
# ---------------------------------------------------------------------------

def test_upsert_updates_existing_record(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Original"})

    csv_content = "code,name\nC001,Updated Name\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code",
        files=files,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["updated"] == 1
    assert data["inserted"] == 0

    records = client.get("/api/records/test/company").json()
    assert records["total"] == 1
    assert records["records"][0]["name"] == "Updated Name"


def test_upsert_inserts_when_no_match(client):
    csv_content = "code,name\nC999,New Corp\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code",
        files=files,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 1
    assert data["updated"] == 0


def test_upsert_mixed_update_and_insert(client):
    client.post("/api/records/test/company", json={"code": "C001", "name": "Original"})

    csv_content = "code,name\nC001,Updated\nC003,New Corp\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code",
        files=files,
    )

    assert res.status_code == 200
    data = res.json()
    assert data["updated"] == 1
    assert data["inserted"] == 1

    records = client.get("/api/records/test/company").json()
    assert records["total"] == 2


def test_upsert_creates_history_entry_for_update(client):
    rid = client.post(
        "/api/records/test/company", json={"code": "C001", "name": "v1"}
    ).json()["id"]

    csv_content = "code,name\nC001,v2\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code",
        files=files,
    )

    history = client.get(f"/api/records/test/company/{rid}/history").json()
    assert len(history) == 2
    assert any(h["_action"] == "UPDATE" for h in history)


def test_upsert_invalid_key_returns_400(client):
    csv_content = "code,name\nC001,Alpha\n"
    files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=nonexistent_col",
        files=files,
    )
    assert res.status_code == 400


# ---------------------------------------------------------------------------
# Upload size limit
# ---------------------------------------------------------------------------

def test_import_oversized_file_returns_413(client):
    """Files exceeding MAX_UPLOAD_SIZE must be rejected with 413."""
    import os
    os.environ["MAX_UPLOAD_SIZE"] = "100"  # 100 bytes for this test
    from importlib import reload

    import app.config as cfg_mod
    reload(cfg_mod)
    import app.api.import_export as ie_mod
    reload(ie_mod)

    big_content = b"code,name\n" + b"X,Y\n" * 50  # well over 100 bytes
    files = {"file": ("big.csv", big_content, "text/csv")}
    res = client.post("/api/records/test/company/import?format=csv", files=files)
    assert res.status_code == 413

    # Restore default
    os.environ.pop("MAX_UPLOAD_SIZE", None)
    reload(cfg_mod)
    reload(ie_mod)


# ---------------------------------------------------------------------------
# Strict mode rollback
# ---------------------------------------------------------------------------

def test_import_strict_mode_rolls_back_on_error(client):
    """With strict=true (default), a row error rolls back all rows including valid ones."""
    # contact has a company_id UUID reference column — passing a non-UUID string
    # causes a PostgreSQL type error, which is a reliable way to trigger a row failure.
    csv_content = "name,company_id\nAlice,\nBob,not-a-valid-uuid\n"
    files = {"file": ("mixed.csv", csv_content.encode(), "text/csv")}
    res = client.post("/api/records/test/contact/import?format=csv", files=files)
    assert res.status_code == 422
    data = res.json()
    assert "errors" in data["detail"]
    # Alice must NOT have been committed — the whole import was rolled back
    records = client.get("/api/records/test/contact").json()
    assert records["total"] == 0


def test_import_non_strict_mode_commits_valid_rows(client):
    """With strict=false, valid rows are committed even when some rows fail."""
    csv_content = "name,company_id\nAlice,\nBob,not-a-valid-uuid\n"
    files = {"file": ("mixed.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/contact/import?format=csv&strict=false", files=files
    )
    assert res.status_code == 200
    data = res.json()
    assert data["inserted"] == 1
    assert len(data["errors"]) == 1
    # Alice must be present; Bob was skipped
    records = client.get("/api/records/test/contact").json()
    assert records["total"] == 1
