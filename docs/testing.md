# Testing

## Test suite overview

| File | Type | Requires DB |
|---|---|---|
| `tests/test_schema_loader.py` | Unit – config parsing | No |
| `tests/test_table_manager.py` | Unit – table manager helpers | No |
| `tests/test_api_records.py` | Integration – CRUD, history, revert | Yes |
| `tests/test_api_lifecycle.py` | Integration – lifecycle states, draft/publish/retire | Yes |
| `tests/test_api_import_export.py` | Integration – import/export, upsert, initial_state | Yes |
| `tests/test_api_auth.py` | Integration – authentication, token handling | Yes |
| `tests/test_api_permissions.py` | Integration – schema-based access control | Yes |
| `tests/test_api_webhooks.py` | Integration – webhook delivery on publish/retire | Yes |
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
  uv run pytest tests/test_api_records.py tests/test_api_lifecycle.py \
               tests/test_api_import_export.py tests/test_api_auth.py \
               tests/test_api_permissions.py tests/test_templates.py -v
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

**`test_api_lifecycle.py`**
- New records default to `active` state
- `?state=` filter on list: `active`, `draft`, `retired`, `all`
- Draft copy on edit: PUT on active creates a draft alongside; active is unchanged
- Second PUT on the same active record reuses the existing draft rather than creating a second
- PUT on a draft updates it in place (no new draft created)
- System columns (`_state`, `_draft_of_id`) are silently ignored if included in the request body
- Publish: applies draft data to the active record, soft-deletes the draft, writes `PUBLISH` history entry
- Publish returns 404 for non-draft records and unknown IDs
- Retire: transitions active → retired, writes `RETIRE` history entry
- Retire returns 404 for drafts, already-retired records, and unknown IDs
- Full draft → edit → publish workflow end-to-end
- Export `?state=` filter works correctly for active and draft
- History entries snapshot `_state` on create and on lifecycle transitions

**`test_api_auth.py`**
- Unauthenticated requests return 401
- Login with valid and invalid credentials
- Token revocation (logout)
- Permission grant and revoke events are logged in the audit log

**`test_api_permissions.py`**
- Setting a permission creates or updates the row (all three flags: read/write/publish)
- Deleting a permission removes the row
- Non-admin users are blocked from schemas they have no grant for
- Read-only users cannot write; Editors cannot publish

**`test_api_import_export.py`**
- Export CSV, TSV, and JSON (empty table and with data)
- Export excludes soft-deleted records
- Export respects `?state=` filter
- CSV, TSV, and JSON import (insert-only)
- Upsert: update on key match, insert when no match, mixed batches
- Upsert creates correct history entries for updated records
- Import with `initial_state=draft` creates records as drafts
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
