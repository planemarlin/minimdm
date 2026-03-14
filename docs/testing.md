# Testing

## Test suite overview

| File | Type | Requires DB |
|---|---|---|
| `tests/test_schema_loader.py` | Unit – config parsing | No |
| `tests/test_table_manager.py` | Unit – table manager helpers | No |
| `tests/test_api_records.py` | Integration – CRUD, history, revert | Yes |
| `tests/test_api_import_export.py` | Integration – import/export, upsert | Yes |
| `tests/test_templates.py` | Template rendering – page structure | Yes |

Unit tests run anywhere. Integration and template tests require a PostgreSQL test database and are automatically skipped when `TEST_DATABASE_URL` is not set.

## Setting up the test database

Create a dedicated database so tests never touch your production data:

```sql
CREATE DATABASE minimdm_test;
GRANT ALL PRIVILEGES ON DATABASE minimdm_test TO minimdm;
-- PostgreSQL 15+ also requires:
GRANT CREATE ON SCHEMA public TO minimdm;
```

Run these commands as a superuser, for example:

```bash
psql -U postgres -c "CREATE DATABASE minimdm_test;"
psql -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE minimdm_test TO minimdm;"
psql -U postgres -d minimdm_test -c "GRANT CREATE ON SCHEMA public TO minimdm;"
```

The test fixture creates all required schemas and tables automatically at the start of each test run, and drops the `test` schema when the run finishes. No manual schema setup is needed.

## Running the tests

**All tests** (unit tests run; integration tests run if `TEST_DATABASE_URL` is set):

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/ -v
```

**Unit tests only** (no database needed):

```bash
uv run pytest tests/test_schema_loader.py tests/test_table_manager.py -v
```

**Integration and template tests only:**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/test_api_records.py tests/test_api_import_export.py tests/test_templates.py -v
```

**With coverage report:**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/ --cov=app --cov-report=term-missing
```

## What the integration tests cover

**`test_api_records.py`**
- Create, list (with pagination), get, update, soft-delete
- `include_deleted` query parameter
- Case-insensitive search across string columns
- History entries after INSERT, UPDATE, and DELETE
- Revert to a previous version
- Revert a deleted record (regression: version numbering must not reset to 1)
- 404/400 responses for unknown objects, missing records, and invalid UUIDs

**`test_api_import_export.py`**
- Export CSV, TSV, and JSON (empty table and with data)
- Export excludes soft-deleted records
- CSV, TSV, and JSON import (insert-only)
- Upsert: update on key match, insert when no match, mixed batches
- Upsert creates correct history entries for updated records
- 400 responses for invalid JSON and unknown upsert keys

**`test_templates.py`**
- Every page type (home, list, new, detail, edit, history) renders HTTP 200
- Unknown object returns 404
- New-record form renders without a 500 error (regression: `record_id` was missing from context)
- New-record form outputs `null` for `record_id` in the script block
- Edit form contains the record UUID in the script block
- Column headers in the list page follow config order, not alphabetical order
- `objConfig` JSON embedded in the list page preserves attribute insertion order (regression: Jinja2 `tojson` was applying `sort_keys=True`)

## Test isolation

Each integration test that creates or modifies data requests the `clean_records` fixture, which deletes all rows from the test schema tables before the test runs. The session-scoped `client` fixture creates the schema once for the whole run and drops it on teardown. Tests that only read HTML (template tests) do not need `clean_records`.
