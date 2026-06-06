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
| `tests/browser/test_auth.py` | Browser – login/logout, auth redirects | Yes |
| `tests/browser/test_records.py` | Browser – list and create records | Yes |
| `tests/browser/test_edit_delete.py` | Browser – edit, delete, reason enforcement | Yes |
| `tests/browser/test_lifecycle.py` | Browser – draft/publish/retire state machine | Yes |
| `tests/browser/test_history_revert.py` | Browser – history view and revert | Yes |
| `tests/browser/test_import_export.py` | Browser – CSV/TSV import, CSV export download | Yes |
| `tests/browser/test_admin.py` | Browser – users page and audit log | Yes |

Unit tests run anywhere. Integration and template tests require a PostgreSQL test database and are automatically skipped when `TEST_DATABASE_URL` is not set. Browser tests additionally require the Playwright Chromium binary (see below).

## Browser (end-to-end) tests

The browser test suite drives a real Chromium browser against a live miniMDM server to verify that the UI behaves correctly from a user's perspective. These tests complement the API integration tests by catching template bugs, JavaScript errors, and full user flows.

### Prerequisites

Install the Playwright Chromium binary once per machine (this is separate from the Python package):

```bash
uv run playwright install chromium
```

The `playwright` and `pytest-playwright` packages are already included in the `dev` dependency group and are installed by `uv sync --group dev`.

### Running browser tests

**Headless (silent, default — same as CI):**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/browser/ -v
```

**Headed (a real browser window opens — useful when writing or debugging tests):**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/browser/ --headed
```

**Slow-motion (headed, 500 ms between each action — useful for stepping through a failing test):**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/browser/ --headed --slowmo 500
```

**Run all suites together:**

```bash
TEST_DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm_test \
  uv run pytest tests/ -v
```

### How browser tests work

Each test session spins up a real `uvicorn` subprocess on port 8765, pointing at `TEST_DATABASE_URL`. A dedicated `browser` schema is synced from `tests/browser/test_config.yaml`. An admin user (`browser_admin`) is pre-created in the test database before the server starts.

A `clean_browser_records` fixture (autouse) truncates all `browser`-schema tables and audit log entries before each test, so tests are fully isolated. The server process is terminated when the session ends.

All tests skip automatically when `TEST_DATABASE_URL` is not set, consistent with the rest of the test suite.

### What the browser tests cover

**`test_auth.py`**
- Login page renders for unauthenticated users
- Successful login redirects to home and shows the username in the header
- Wrong password shows an inline error and stays on the login page
- Logout redirects to `/login`
- Direct navigation to a protected route redirects to `/login`

**`test_records.py`**
- Company list page loads and finishes rendering records
- Admin sees the New record button
- New record form submits and navigates to the detail page
- A record created via API appears in the list

**`test_edit_delete.py`**
- Editing a record updates the values shown on the draft detail page
- Edit form pre-fills current field values
- Deleting a record redirects to the object list
- Soft-deleted records do not appear in the default active list view
- A reason supplied at deletion is stored and visible in the record history
- Saving an `audited_item` (require_change_reason) without a reason shows an inline server error

**`test_lifecycle.py`**
- Editing an active record creates a draft with a different UUID
- The draft detail page shows the Publish button
- Publishing a draft navigates back to the original active record with the Retire button visible
- Retiring an active record transitions it to Retired and hides the Edit and Retire buttons
- Creating a `governed_item` (requires_draft) produces a Draft record directly

**`test_history_revert.py`**
- A newly created record shows a Version 1 INSERT entry in history
- A reason supplied during an edit is visible in the draft's history entry
- Reverting to an earlier version (via the `window.prompt` dialog) restores the original field values

**`test_import_export.py`**
- Clicking Export CSV in the Tools menu triggers a `.csv` file download
- Uploading a CSV file via the import modal adds records to the list
- Uploading a TSV file via the import modal adds records to the list

**`test_admin.py`**
- User Management page renders with the correct heading
- The `browser_admin` user appears in the users table
- Creating a user via the New user modal adds them to the table
- Audit Log page renders with the correct heading
- After creating a record, its INSERT entry appears in the audit log filtered by schema
- The Auth Events tab shows login activity for the admin user

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

**`test_api_query_params.py`**
- `?role=master` returns only active (golden) records
- `?role=draft` returns only draft candidate records
- `?role=master` excludes draft records from results
- `?role=xyz` (invalid value) returns HTTP 400 with list of valid values
- `?role=` and `?state=` combined always returns HTTP 400 regardless of whether values agree

**`test_schema_loader.py`** (governance metadata)
- `owner` and `steward` are parsed from YAML object config into the normalized dict
- Objects without `owner`/`steward` default both fields to `None`
- Existing `test_defaults_filled` asserts `owner: None` and `steward: None` on object level

**`test_templates.py`**
- Every page type (home, list, new, detail, edit, history) renders HTTP 200
- Unknown object returns 404
- New-record form renders without a 500 error (regression: `record_id` was missing from context)
- New-record form outputs `null` for `record_id` in the script block
- Edit form contains the record UUID in the script block
- Column headers in the list page follow config order, not alphabetical order
- `objConfig` JSON embedded in the list page preserves attribute insertion order (regression: Jinja2 `tojson` was applying `sort_keys=True`)
- Owner and steward are displayed on the list page when configured on the object
- Owner/steward block is absent when neither field is set

## Test isolation

Each integration test that creates or modifies data requests the `clean_records` fixture, which deletes all rows from the test schema tables before the test runs. The session-scoped `client` fixture creates the schema once for the whole run and drops it on teardown. Tests that only read HTML (template tests) do not need `clean_records`.
