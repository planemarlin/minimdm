"""API integration tests for schema and config endpoints.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""


# ---------------------------------------------------------------------------
# GET /api/schemas
# ---------------------------------------------------------------------------

def test_list_schemas_returns_test_schema(client):
    res = client.get("/api/schemas")
    assert res.status_code == 200
    data = res.json()
    names = [s["name"] for s in data]
    assert "test" in names


def test_list_schemas_includes_object_list(client):
    res = client.get("/api/schemas")
    data = res.json()
    test_schema = next(s for s in data if s["name"] == "test")
    obj_keys = [o["key"] for o in test_schema["objects"]]
    assert "company" in obj_keys
    assert "division" in obj_keys


def test_list_schemas_objects_have_display_name(client):
    res = client.get("/api/schemas")
    data = res.json()
    test_schema = next(s for s in data if s["name"] == "test")
    company = next(o for o in test_schema["objects"] if o["key"] == "company")
    assert company["name"] == "Company"


# ---------------------------------------------------------------------------
# GET /api/schemas/{schema}
# ---------------------------------------------------------------------------

def test_get_schema_returns_objects(client):
    res = client.get("/api/schemas/test")
    assert res.status_code == 200
    data = res.json()
    assert "objects" in data
    assert "company" in data["objects"]
    assert "division" in data["objects"]


def test_get_schema_unknown_returns_404(client):
    res = client.get("/api/schemas/nonexistent")
    assert res.status_code == 404


def test_get_schema_division_has_parent(client):
    res = client.get("/api/schemas/test")
    data = res.json()
    assert data["objects"]["division"]["parent"] == "company"


# ---------------------------------------------------------------------------
# GET /api/schemas/{schema}/objects/{obj}
# ---------------------------------------------------------------------------

def test_get_object_config_returns_attributes(client):
    res = client.get("/api/schemas/test/objects/company")
    assert res.status_code == 200
    data = res.json()
    assert "attributes" in data
    assert "code" in data["attributes"]
    assert "name" in data["attributes"]


def test_get_object_config_attribute_has_type(client):
    res = client.get("/api/schemas/test/objects/company")
    data = res.json()
    assert data["attributes"]["code"]["type"] == "string"


def test_get_object_config_unknown_object_returns_404(client):
    res = client.get("/api/schemas/test/objects/nonexistent")
    assert res.status_code == 404


def test_get_object_config_division_has_parent_field(client):
    res = client.get("/api/schemas/test/objects/division")
    data = res.json()
    assert data.get("parent") == "company"


# ---------------------------------------------------------------------------
# GET /api/config
# ---------------------------------------------------------------------------

def test_get_config_returns_schemas_key(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    data = res.json()
    assert "schemas" in data
    assert "test" in data["schemas"]
