"""API integration tests for CSV/TSV/JSON import and export.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import json
from datetime import date

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


def test_export_returns_total_count_header(client):
    """X-Total-Count header reports the full dataset size regardless of pagination."""
    for code in ["C001", "C002", "C003"]:
        client.post("/api/records/test/company", json={"code": code})
    res = client.get("/api/records/test/company/export?format=csv")
    assert res.status_code == 200
    assert res.headers["x-total-count"] == "3"


def test_export_limit_restricts_rows(client):
    """limit parameter caps the number of rows returned."""
    for code in ["C001", "C002", "C003"]:
        client.post("/api/records/test/company", json={"code": code})
    res = client.get("/api/records/test/company/export?format=json&limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2
    assert res.headers["x-total-count"] == "3"


def test_export_offset_skips_rows(client):
    """offset parameter skips the specified number of rows."""
    for code in ["C001", "C002", "C003"]:
        client.post("/api/records/test/company", json={"code": code})
    res = client.get("/api/records/test/company/export?format=json&offset=2")
    assert res.status_code == 200
    assert len(res.json()) == 1


# ---------------------------------------------------------------------------
# Import template
# ---------------------------------------------------------------------------

def test_import_template_csv_headers_only_by_default(client):
    res = client.get("/api/records/test/company/import-template?format=csv")
    assert res.status_code == 200
    lines = res.text.strip("\r\n").splitlines()
    assert lines == ["code,name"]


def test_import_template_tsv_headers(client):
    res = client.get("/api/records/test/company/import-template?format=tsv")
    assert res.status_code == 200
    assert res.text.strip("\r\n").splitlines() == ["code\tname"]


def test_import_template_json_shows_column_names_by_default(client):
    """Unlike CSV/TSV, a JSON array has no header row — without a placeholder
    row the column names would be invisible in an empty `[]`."""
    res = client.get("/api/records/test/company/import-template?format=json")
    assert res.status_code == 200
    data = res.json()
    assert data == [{"code": "", "name": ""}]


def test_import_template_csv_with_examples(client):
    res = client.get("/api/records/test/company/import-template?format=csv&examples=true")
    assert res.status_code == 200
    lines = res.text.strip("\r\n").splitlines()
    assert lines[0] == "code,name"
    assert len(lines) == 2
    assert "EXAMPLE-" in lines[1]


def test_import_template_tsv_with_examples(client):
    res = client.get("/api/records/test/company/import-template?format=tsv&examples=true")
    assert res.status_code == 200
    lines = res.text.strip("\r\n").splitlines()
    assert lines[0] == "code\tname"
    assert len(lines) == 2
    assert "EXAMPLE-" in lines[1]


def test_import_template_json_with_examples(client):
    res = client.get("/api/records/test/company/import-template?format=json&examples=true")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 1
    assert set(data[0].keys()) == {"code", "name"}
    assert data[0]["code"] != ""


def test_import_template_json_example_boolean_is_native(client):
    """The importer accepts both a native JSON boolean and a string like "true"/"1"/"yes"
    (see `_coerce_value`), but the JSON template should emit a real `true`, not the
    string `"true"` — it reads as more obviously a boolean in a JSON file."""
    res = client.get(
        "/api/records/test/validation_demo/import-template?format=json&examples=true"
    )
    assert res.status_code == 200
    assert res.json()[0]["approved"] is True


def test_import_template_csv_example_boolean_is_lowercase_text(client):
    """CSV has no native boolean — Python's default str(True) is "True", but the
    importer's string check lowercases before comparing, so the template should
    write the conventional lowercase "true" a spreadsheet user would recognize."""
    res = client.get(
        "/api/records/test/validation_demo/import-template?format=csv&examples=true"
    )
    assert res.status_code == 200
    header, row = res.text.strip("\r\n").splitlines()
    approved_value = dict(zip(header.split(","), row.split(",")))["approved"]
    assert approved_value == "true"


def test_import_template_json_example_date_is_quoted_string(client):
    """Unlike boolean/integer/numeric, JSON has no native date type, so — unlike
    those — the date example value is correctly left as a string and should stay
    quoted in the JSON output, e.g. "2026-09-27", not a bare 2026-09-27."""
    res = client.get(
        "/api/records/test/validation_demo/import-template?format=json&examples=true"
    )
    assert res.status_code == 200
    value = res.json()[0]["start_date"]
    assert isinstance(value, str)
    date.fromisoformat(value)  # raises if it isn't a valid ISO date string


def test_import_template_json_blank_row_uses_null_for_non_text_types(client):
    """Without `examples`, the JSON placeholder row still needs to show every column
    name, but "" only reads sensibly as "fill this in" for a text-like attribute —
    a boolean, number, date, or reference shows null instead."""
    res = client.get("/api/records/test/validation_demo/import-template?format=json")
    assert res.status_code == 200
    row = res.json()[0]
    assert row["country"] == ""  # text-like -> blank string
    assert row["approved"] is None  # boolean
    assert row["unit_price"] is None  # numeric
    assert row["start_date"] is None  # date


def test_import_template_reference_attribute_uses_id_column(client):
    """A `reference` attribute is stored as `{attr}_id`, so the template must
    ask for that column, not the bare attribute key — and leave the example
    value blank rather than fabricate a UUID that would fail on import."""
    res = client.get("/api/records/test/contact/import-template?format=json&examples=true")
    assert res.status_code == 200
    data = res.json()
    assert "company_id" in data[0]
    assert data[0]["company_id"] is None


def test_import_template_reference_attribute_blank_uses_null(client):
    """Same as above, but for the no-`examples` placeholder row: "" would be a
    misleading placeholder for a foreign-key column, so it must be null too."""
    res = client.get("/api/records/test/contact/import-template?format=json")
    assert res.status_code == 200
    assert res.json()[0]["company_id"] is None


def test_import_template_respects_numeric_min(client):
    res = client.get(
        "/api/records/test/governed_item/import-template?format=json&examples=true"
    )
    assert res.status_code == 200
    assert res.json()[0]["unit_price"] == 0


def test_import_template_json_example_numeric_is_native_number(client):
    """Same reasoning as the boolean case: "0" would be a JSON string, not a number —
    the template should emit an unquoted 0, matching the column's real type."""
    res = client.get(
        "/api/records/test/governed_item/import-template?format=json&examples=true"
    )
    assert res.status_code == 200
    data = res.json()[0]
    assert isinstance(data["unit_price"], (int, float))
    assert not isinstance(data["unit_price"], bool)


def test_import_template_csv_example_numeric_is_plain_text(client):
    """CSV has no native number type either way, so this should look unchanged:
    a plain, unquoted-in-the-JSON-sense "0" cell."""
    res = client.get(
        "/api/records/test/governed_item/import-template?format=csv&examples=true"
    )
    assert res.status_code == 200
    header, row = res.text.strip("\r\n").splitlines()
    assert dict(zip(header.split(","), row.split(",")))["unit_price"] == "0"


def test_import_template_example_round_trips_through_import(client):
    """The generated example row, taken as-is, must actually import cleanly."""
    template = client.get(
        "/api/records/test/company/import-template?format=csv&examples=true"
    ).text
    res = client.post(
        "/api/records/test/company/import?format=csv",
        files={"file": ("template.csv", template, "text/csv")},
    )
    assert res.status_code == 200
    assert res.json()["inserted"] == 1


def test_import_template_unknown_object_returns_404(client):
    res = client.get("/api/records/test/nonexistent/import-template?format=csv")
    assert res.status_code == 404


def test_import_template_invalid_format_returns_422(client):
    res = client.get("/api/records/test/company/import-template?format=xml")
    assert res.status_code == 422


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


def test_import_non_utf8_csv_returns_400(client):
    """A CSV saved in a non-UTF-8 encoding (e.g. Windows-1252 from Excel) must
    fail with a clear 400 error instead of an unhandled UnicodeDecodeError."""
    csv_content = "code,name\nC001,Caf\xe9 Corp\n".encode("windows-1252")
    files = {"file": ("data.csv", csv_content, "text/csv")}
    res = client.post("/api/records/test/company/import?format=csv", files=files)
    assert res.status_code == 400
    assert "utf-8" in res.json()["detail"].lower()


def test_import_utf16_tsv_returns_400(client):
    """Excel's 'Unicode Text' export produces UTF-16 .tsv files; these must
    fail with a clear 400 error instead of an unhandled UnicodeDecodeError."""
    tsv_content = "code\tname\nC001\tAlpha Corp\n".encode("utf-16")
    files = {"file": ("data.tsv", tsv_content, "text/tab-separated-values")}
    res = client.post("/api/records/test/company/import?format=tsv", files=files)
    assert res.status_code == 400
    assert "utf-8" in res.json()["detail"].lower()


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


# ---------------------------------------------------------------------------
# Provenance: source_system query param and _source_system/_source_id columns
# ---------------------------------------------------------------------------

def test_import_source_system_query_param_sets_field(client):
    """?source_system= on import sets _source_system on all inserted records."""
    csv_content = "code,name\nP001,Prov Corp\n"
    files = {"file": ("prov.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&source_system=erp", files=files
    )
    assert res.status_code == 200
    records = client.get("/api/records/test/company").json()
    assert records["total"] == 1
    assert records["records"][0]["_source_system"] == "erp"


def test_import_source_system_column_in_csv_takes_precedence(client):
    """Per-row _source_system in the CSV wins over the query param when the column is present."""
    csv_content = "code,name,_source_system\nP002,Row Corp,crm\n"
    files = {"file": ("prov.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&source_system=erp", files=files
    )
    assert res.status_code == 200
    records = client.get("/api/records/test/company").json()
    assert records["total"] == 1
    assert records["records"][0]["_source_system"] == "crm"


def test_import_source_system_column_present_but_empty_still_wins(client):
    """If _source_system column is present but empty, the query param does NOT override it.
    The file controls _source_system whenever the column is present, even for empty cells."""
    csv_content = "code,name,_source_system\nP002b,Empty Corp,\n"
    files = {"file": ("prov.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&source_system=erp", files=files
    )
    assert res.status_code == 200
    records = client.get("/api/records/test/company").json()
    assert records["total"] == 1
    assert records["records"][0]["_source_system"] is None


def test_import_source_id_column_in_csv(client):
    """_source_id can be supplied per-row in the CSV."""
    csv_content = "code,name,_source_system,_source_id\nP003,ID Corp,erp,ERP-42\n"
    files = {"file": ("prov.csv", csv_content.encode(), "text/csv")}
    res = client.post("/api/records/test/company/import?format=csv", files=files)
    assert res.status_code == 200
    records = client.get("/api/records/test/company").json()
    assert records["total"] == 1
    assert records["records"][0]["_source_id"] == "ERP-42"


def test_import_upsert_source_system_query_param(client):
    """?source_system= is also applied during upsert inserts."""
    csv_content = "code,name\nU001,Upsert Corp\n"
    files = {"file": ("up.csv", csv_content.encode(), "text/csv")}
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code&source_system=wms",
        files=files,
    )
    assert res.status_code == 200
    assert res.json()["inserted"] == 1
    records = client.get("/api/records/test/company").json()
    assert records["records"][0]["_source_system"] == "wms"


# ---------------------------------------------------------------------------
# CSV/TSV formula injection (CWE-1236) — pre-v0.8.0 security review
# ---------------------------------------------------------------------------

_FORMULA = '=HYPERLINK("http://evil.example","click")'


def test_csv_export_neutralises_formula_cells(client):
    client.post("/api/records/test/company", json={"code": "F001", "name": _FORMULA})

    res = client.get("/api/records/test/company/export?format=csv")
    assert res.status_code == 200
    # The cell is prefixed with an apostrophe so a spreadsheet shows it as text.
    assert "'=HYPERLINK" in res.text
    assert ',"=HYPERLINK' not in res.text and ",=HYPERLINK" not in res.text


def test_tsv_export_neutralises_all_formula_triggers(client):
    for i, value in enumerate(["=1+1", "+1+1", "-1+1", "@SUM(A1)"]):
        client.post("/api/records/test/company", json={"code": f"T{i}", "name": value})

    res = client.get("/api/records/test/company/export?format=tsv")
    lines = res.text.splitlines()
    for value in ["=1+1", "+1+1", "-1+1", "@SUM(A1)"]:
        assert f"\t'{value}" in "\n".join(lines)


def test_json_export_is_not_neutralised(client):
    client.post("/api/records/test/company", json={"code": "J001", "name": _FORMULA})

    data = client.get("/api/records/test/company/export?format=json").json()
    assert data[0]["name"] == _FORMULA


def test_csv_export_then_reimport_round_trips_formula_text(client):
    client.post("/api/records/test/company", json={"code": "RT01", "name": _FORMULA})
    exported = client.get("/api/records/test/company/export?format=csv").text

    # Re-import the export as an upsert: the stored value must be unchanged, not
    # left with the export-only apostrophe.
    res = client.post(
        "/api/records/test/company/import?format=csv&upsert_key=code",
        files={"file": ("export.csv", exported.encode(), "text/csv")},
    )
    assert res.status_code == 200
    records = client.get("/api/records/test/company").json()["records"]
    assert [r["name"] for r in records if r["code"] == "RT01"] == [_FORMULA]


def test_csv_export_leaves_ordinary_and_numeric_values_alone(client):
    client.post("/api/records/test/company", json={"code": "N001", "name": "Normal Name"})

    res = client.get("/api/records/test/company/export?format=csv")
    assert "Normal Name" in res.text
    assert "'Normal Name" not in res.text


# ---------------------------------------------------------------------------
# Import row errors and native JSON values — pre-v0.8.0 security review
# ---------------------------------------------------------------------------

def test_import_row_error_does_not_leak_sql_or_parameters(client):
    client.post("/api/records/test/company", json={"code": "DUP", "name": "first"})
    res = client.post(
        "/api/records/test/company/import?format=csv&strict=false",
        files={"file": ("d.csv", b"code,name\nDUP,second\n", "text/csv")},
    )
    assert res.status_code == 200
    error = res.json()["errors"][0]["error"]
    assert "already exists" in error
    for leaked in ("INSERT INTO", "[SQL", "parameters", "%(", "_created_at"):
        assert leaked not in error


def test_coerce_value_accepts_native_json_types():
    from datetime import datetime

    from sqlalchemy import Boolean, DateTime, Integer, Numeric

    from app.api.import_export import _coerce_value

    assert _coerce_value(True, Boolean()) is True
    assert _coerce_value(False, Boolean()) is False
    assert _coerce_value("Yes", Boolean()) is True
    assert _coerce_value(5, Integer()) == 5
    assert str(_coerce_value(5.5, Numeric())) == "5.5"
    moment = datetime(2026, 1, 1)
    assert _coerce_value(moment, DateTime()) is moment
    with pytest.raises(ValueError):
        _coerce_value(20260101, DateTime())  # not a string or datetime
    with pytest.raises(ValueError):
        _coerce_value([1], Integer())


def test_json_import_accepts_native_boolean(client):
    payload = [{"code": "JB01", "approved": True}, {"code": "JB02", "approved": False}]
    files = {"file": ("d.json", json.dumps(payload).encode(), "application/json")}
    res = client.post("/api/records/test/validation_demo/import?format=json", files=files)
    assert res.status_code == 200
    assert res.json()["errors"] == []
    listing = client.get("/api/records/test/validation_demo").json()["records"]
    by_code = {r["code"]: r for r in listing}
    assert by_code["JB01"]["approved"] is True
    assert by_code["JB02"]["approved"] is False
