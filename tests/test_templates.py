"""Template rendering tests.

These verify that HTML pages render without errors and that structural
properties (attribute order, injected variables) are correct.
They use the same TestClient fixture as the API tests and require
TEST_DATABASE_URL to be set.
"""


# ---------------------------------------------------------------------------
# Basic page rendering (status 200, no Jinja2 exceptions)
# ---------------------------------------------------------------------------

def test_home_page_renders(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "miniMDM" in res.text


def test_audit_log_page_renders(client):
    res = client.get("/admin/audit")
    assert res.status_code == 200
    assert "Audit Log" in res.text


def test_list_page_renders(client):
    res = client.get("/test/company")
    assert res.status_code == 200


def test_list_page_unknown_object_returns_404(client):
    res = client.get("/test/nonexistent")
    assert res.status_code == 404


def test_new_record_page_renders_without_error(client):
    """Regression: /new previously raised 500 because record_id was missing from context."""
    res = client.get("/test/company/new")
    assert res.status_code == 200


def test_detail_page_renders(client, clean_records):
    rid = client.post(
        "/api/records/test/company", json={"code": "C001", "name": "Test Corp"}
    ).json()["id"]

    res = client.get(f"/test/company/{rid}")
    assert res.status_code == 200


def test_edit_page_renders(client, clean_records):
    rid = client.post(
        "/api/records/test/company", json={"code": "C001"}
    ).json()["id"]

    res = client.get(f"/test/company/{rid}/edit")
    assert res.status_code == 200


def test_history_page_renders(client, clean_records):
    rid = client.post(
        "/api/records/test/company", json={"code": "C001"}
    ).json()["id"]

    res = client.get(f"/test/company/{rid}/history")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# record_id variable in form template
# ---------------------------------------------------------------------------

def test_new_record_page_injects_null_record_id(client):
    """The form template renders {{ record_id | tojson }}; on the new page this must be null."""
    res = client.get("/test/company/new")
    assert res.status_code == 200
    # The Jinja2 filter outputs the literal string 'null' for None
    assert "null" in res.text


def test_edit_page_injects_record_id(client, clean_records):
    """The edit form must contain the record's UUID so JS can load and save it."""
    rid = client.post(
        "/api/records/test/company", json={"code": "C001"}
    ).json()["id"]

    res = client.get(f"/test/company/{rid}/edit")
    assert res.status_code == 200
    # The UUID must appear in the rendered page (injected via {{ record_id | tojson }})
    assert rid in res.text


# ---------------------------------------------------------------------------
# Attribute display order
# ---------------------------------------------------------------------------

def test_list_page_column_headers_in_config_order(client):
    """Column headers must follow config order (code before name), not alphabetical order.

    Regression: Jinja2's tojson filter sorted dict keys alphabetically by default,
    causing 'name' to appear before 'code' in the JavaScript objConfig object.
    The HTML <th> headers are rendered server-side from the Python dict, which
    preserves insertion order — so this test catches the Jinja2 sort_keys issue
    in the JS objConfig as well as any server-side ordering regression.
    """
    res = client.get("/test/company")
    assert res.status_code == 200
    html = res.text

    # Sortable column headers are rendered with id="th-col-{attr_key}".
    # Check relative position of the two headers in the HTML.
    code_pos = html.find('id="th-col-code"')
    name_pos = html.find('id="th-col-name"')

    assert code_pos != -1, "'code' column header not found in list page"
    assert name_pos != -1, "'name' column header not found in list page"
    assert code_pos < name_pos, (
        f"Expected 'Code' header (pos {code_pos}) before 'Name' header (pos {name_pos}), "
        "but order was reversed — possible sort_keys regression"
    )


def test_list_page_objconfig_json_preserves_attribute_order(client):
    """The objConfig JSON embedded in the page script must keep config order.

    This catches the Jinja2 tojson sort_keys=True regression that caused
    JavaScript to iterate attributes in alphabetical order.
    """
    res = client.get("/test/company")
    assert res.status_code == 200
    html = res.text

    # The embedded JSON is: objConfig: { "name": "Company", ...,
    # "attributes": {"code": {...}, "name": {...}} }
    # If sort_keys was True, "name" would appear before "code" inside "attributes".
    # Note: obj_config has a top-level "name" key ("Company") that appears before "attributes",
    # so we must search for key order within the "attributes" section only.
    script_start = html.find("const recordList")
    assert script_start != -1, "RecordList script block not found"
    script_block = html[script_start:]

    attr_start = script_block.find('"attributes"')
    assert attr_start != -1, '"attributes" key not found in objConfig JSON'
    attr_section = script_block[attr_start:]

    code_pos = attr_section.find('"code"')
    name_pos = attr_section.find('"name"')

    assert code_pos != -1 and name_pos != -1
    assert code_pos < name_pos, (
        "In objConfig JSON attributes, 'code' must appear before 'name' — "
        "sort_keys regression detected"
    )
