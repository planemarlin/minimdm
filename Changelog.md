# Changelog

All notable changes to miniMDM are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `config/minimdm.example.yaml`: example config file showcasing all key features — required/unique attributes, parent relationships, cross-object references, and all attribute types
- Sorting on parent and reference columns is intentionally not supported; column headers are non-clickable to reflect this; documented in `docs/reference.md` and `docs/known_issues.md`
- Light/dark mode toggle (☾/☀) in header; follows OS preference (`prefers-color-scheme`) on first visit; choice persisted in `localStorage`; no flash of wrong theme on page load
- In-app help: `?` button in header opens a Quick Reference modal covering records, history/revert, reason for change, import/upsert, audit log, and access control
- Tooltips on non-obvious UI elements: Show deleted, upsert dropdown, Import, History, Delete, Revert, and Reset link buttons
- Cookie notice on login page; browser storage section added to `docs/reference.md` documenting the `access_token` cookie and `theme` localStorage key
- `config/minimdm.yaml` and `config/minimdm.json` added to `.gitignore` — these are deployment-specific and should not be committed

### Fixed
- `docs/installation.md`: config file copy command used `minimdm.yaml` as both source and destination; corrected to `minimdm.example.yaml`
- `docs/deployment.md`: health check example showed stale version `0.1.0`; updated to `0.2.0`; added missing `LOG_FORMAT` environment variable to the env vars table
- `README.md`: docs table was missing `docker-setup.md`, `logging.md`, `migrations.md`, and `testing.md`
- Audit log Auth Events tab: pagination buttons called `loadAuditLog` instead of `loadAuthLog`, causing the Data Changes tab to reload on page navigation

## [0.2.0] – 2026-03-25

### Added
- `docs/backup-restore.md`: database backup and restore guide covering `pg_dump`/`pg_restore`, Docker volume backups, cron automation, backup verification, and point-in-time recovery
- Structured logging with request IDs: every request is assigned a UUID that appears in all log lines and is returned as the `X-Request-Id` response header; set `LOG_FORMAT=json` for single-line JSON output suitable for log aggregators; see `docs/logging.md`
- DB-level `FOREIGN KEY` constraints on parent and reference columns (`ON DELETE SET NULL`); `UNIQUE` constraints for attributes marked `unique: true` in the config; `_ensure_constraints()` adds missing constraints to existing tables safely on each startup; create/update now returns 422 with a human-readable message on integrity violations
- Admin-generated password reset link: admins click "Reset link" on the User Management page to generate a one-time URL (valid 24 h); user visits the link, sets a new password, and is redirected to login; tokens are single-use and pruned at startup
- Alembic migrations for the `_system` schema: migration `0001` defines all five system tables; future changes use new numbered migrations; runs automatically at startup; legacy installs (tables exist without Alembic) are stamped to head transparently; see `docs/migrations.md`
- `GET /health` endpoint returns 200 when the database is reachable, 503 otherwise — suitable for load balancer and container health probes
- Bulk import `strict` query parameter (default `true`): rolls back the entire import if any row fails and returns all row errors; set `strict=false` for best-effort mode that commits valid rows using per-row savepoints
- `docs/deployment.md`: production deployment guide covering TLS termination with nginx/Caddy, required environment variables, and a pre-launch security checklist
- Docker and Docker Compose setup for local development: `Dockerfile`, `docker-compose.yml`, and helper scripts (`scripts/docker-setup.sh`, `scripts/docker-rebuild.sh`); see [docs/docker-setup.md](docs/docker-setup.md)
- Edit and Delete buttons on the record detail page are now hidden for users who lack write permission on the schema; admins always see both (closes #11)
- Delete record action now uses an inline modal dialog instead of `confirm()` and `prompt()` browser popups, with an optional reason field and Escape/backdrop-click to dismiss (closes #12)
- Audit log entries for all user management actions: `USER_CREATED`, `USER_ACTIVATED`, `USER_DEACTIVATED`, `USER_ROLE_CHANGED`, `USER_PASSWORD_CHANGED`, `PERMISSION_GRANTED`, `PERMISSION_REVOKED` — visible on the Auth Events tab
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, GitHub issue templates, and PR template to support open-source contributions
- `CONTRIBUTORS.md` listing project maintainer and contributors
- `ruff` added as a dev dependency with lint configuration in `pyproject.toml`
- Reference back-panels on the record detail page: any object that holds a reference attribute pointing to the current record type now appears as a collapsible panel listing all records that reference this record — matching the existing parent-child panel behaviour
- Resolved display labels for parent and reference columns in the record list table: columns now show human-readable values (e.g. "Acme Corp") instead of raw UUIDs; the column header for the parent object is included automatically
- Resolved display labels for parent and reference attributes in the record history view: version snapshots now show the display name of referenced records so that changes to reference fields are human-readable across versions
- Sortable column headers on the record list table: clicking any non-reference column header sorts ascending; clicking again sorts descending; the active sort column shows an arrow indicator; default sort is the first non-reference attribute in the config (ascending)
- Sortable column headers on the User Management page: Username, Role, Status, and Created are all clickable; sorting is client-side and applies to the full user list; Actions column remains static
- Reference and parent dropdowns on the record form are now sorted alphabetically by display label, making long lists easier to navigate
- `GET /api/records/{schema}/{obj}` now accepts `ref_field` and `ref_id` query parameters to filter records by an arbitrary reference attribute value (used for reference back-panels)
- `GET /api/records/{schema}/{obj}` now accepts `sort_by` and `sort_dir` (`asc`|`desc`) query parameters; the default sort is the first non-reference attribute in the object config
- Schema-based access control: non-admin users have no access to any schema by default; admins grant read and/or write access per schema on the User Management page; admins always retain full access regardless of permission rows
- Permission management endpoints: `GET /api/admin/users/{user_id}/permissions`, `PUT /api/admin/users/{user_id}/permissions/{schema_name}`, `DELETE /api/admin/users/{user_id}/permissions/{schema_name}` (admin-only)
- Inline permissions panel on the User Management page: clicking the expand arrow on any non-admin user opens a per-schema read/write toggle table with a Revoke button; changes take effect immediately without a page reload
- Sidebar schemas filtered by user permissions: non-admin users see only the schemas they have read access to; admins see all schemas
- Audit log API results filtered by permissions: non-admin users can only see audit entries for schemas they have read access to
- JWT-based authentication: all routes are protected; users log in at `/login` and receive an httpOnly `access_token` cookie; API clients may alternatively pass `Authorization: Bearer <token>`
- First-run setup: if no users exist at startup, an admin user is created automatically using `ADMIN_USERNAME` / `ADMIN_PASSWORD` from the environment (defaults: `admin` / `admin`)
- User management UI at `/admin/users` (admin-only): create users, change passwords, toggle active/inactive status, toggle admin role
- Admin API at `/api/admin/users` — `GET`, `POST`, `PATCH /{user_id}` for user management; self-protection guard prevents an admin from deactivating or demoting their own account
- Audit log entries for authentication events: `LOGIN`, `LOGIN_FAILED`, and `LOGOUT` written to `_system.audit_log` including username and client IP
- All data-change audit log entries now record the authenticated username in `user_name` (previously always null)
- Admin and Audit Log links in the header navigation (visible to admin users only); username and logout button shown to all authenticated users
- Audit log page split into two tabs: **Data Changes** (INSERT/UPDATE/DELETE/REVERT, excluding system schemas) and **Auth Events** (LOGIN/LOGIN_FAILED/LOGOUT with User and IP Address columns); Data Changes tab gains a User column
- `GET /api/audit` accepts a new `exclude_system` boolean parameter to omit entries from schemas whose name starts with `_`
- 18 integration tests in `tests/test_api_permissions.py` covering permission CRUD, access enforcement (no permission, read-only, read+write), and admin bypass
- 19 integration tests in `tests/test_api_auth.py` covering login/logout, inactive user, audit log entries, user management, and the `exclude_system` filter

### Fixed
- History version counter is now incremented atomically using `SELECT … FOR UPDATE` on the open history row, preventing duplicate version numbers under concurrent updates
- Database connectivity is validated at startup; the application now fails fast with a clear error instead of silently starting with a broken DB connection
- Revert button on the record history page is now hidden for users who lack write permission, consistent with the Edit and Delete buttons on the detail page
- Permission audit entries (`PERMISSION_GRANTED`, `PERMISSION_REVOKED`) now include the target username in the reason field
- Removing all access via the permissions panel (unchecking read) now logs `PERMISSION_REVOKED` instead of a misleading `PERMISSION_GRANTED` entry
- Full-text search now treats `%` and `_` as literal characters instead of SQL LIKE wildcards, preventing unexpected wildcard matches and potential performance issues on large tables
- Resolved all ruff lint violations across `app/` and `tests/` (E501, F401, I001, F841, E402)
- Deleted parent record in the detail view showed a raw UUID instead of the display name; the parent fetch now includes `include_deleted=true` and renders the display name with a red "deleted" badge (no link) when the parent has been soft-deleted
- Numeric field validation errors only appeared on form submit; errors now also appear immediately when leaving an invalid number field (blur event)
- `Authorization: Bearer` header now takes priority over the `access_token` cookie in the auth middleware — correct semantics; browser sessions are unaffected (they never send an Authorization header)
- Inactive users now receive "Account is disabled. Contact an administrator." (401) instead of the generic wrong-password message
- Deactivate button in the user management table was rendered with a solid red background due to two conflicting `.btn-danger` CSS rules; consolidated to a single outline style
- Login page password field was unstyled because `input[type="password"]` was missing from the global CSS input selector
- Audit log record links for `_system` schema entries (LOGIN/LOGOUT events) pointed to a non-existent UI route; system-schema record IDs are now rendered as plain text

### Security
- Rate limiting: 10 requests/minute per IP on the login and import endpoints to prevent brute-force and API abuse attacks (`slowapi`)
- Session cookie changed from `SameSite=lax` to `SameSite=strict` to prevent cross-site request forgery
- File upload size limit: import endpoint now rejects files larger than `MAX_UPLOAD_SIZE` (default 10 MB) with HTTP 413
- Minimum password length of 12 characters enforced on user creation and password change
- Token revocation on logout: JWTs now carry a `jti` claim; logout writes the JTI to `_system.token_blocklist` so the token is rejected immediately on subsequent requests even if it has not yet expired; expired blocklist entries are cleaned up at startup
- Login `?next=` redirect target is now validated to be a relative path; external URLs are rejected and replaced with `/` to prevent open redirect attacks
- Auth middleware now checks `is_active` against the database on every authenticated request; tokens belonging to deactivated users are rejected immediately rather than remaining valid until expiry
- `/admin/audit` page now requires admin access; previously any authenticated user could reach the URL directly
- A startup error is logged when `SECRET_KEY` is set to the default placeholder value, prompting operators to configure a secure key before deploying

## [0.1.2] – 2026-03-14

### Fixed
- Column headers in record list misaligned with values when reference attributes appear in the attribute list: Jinja2 header loop now uses a namespace counter that skips references before applying the 6-column cap, matching the JavaScript rendering logic
- Parent FK columns (e.g. `_division_id`) were silently dropped on create and update because `_filter_columns` excluded all `_`-prefixed keys; fixed by enumerating system columns explicitly
- Non-numeric text typed into a number input was silently discarded (browser sets `value=""` but `validity.badInput=true`); validation now checks `badInput` so an error is shown instead
- Audit log datetime filter sent unencoded `+` characters in timezone offsets, which URL parsers decoded as spaces causing `fromisoformat()` to fail silently; the filter is now sent via `params=` (httpx) and converted to UTC ISO before the API call (UI)
- Audit log datetime inputs used the system UI font instead of the page font; fixed by adding `input[type="datetime-local"]` and `font-family: inherit` to the CSS input rule

### Added
- Upsert support for bulk import: select a key attribute in the import UI (or pass `upsert_key` to the API) to match incoming rows against existing records and update them in place instead of always inserting; the response reports inserted and updated counts separately
- "Show deleted" toggle on the record list page: displays soft-deleted records with a strikethrough style; clicking a deleted row navigates to its history page where it can be reverted
- Attribute snapshot on the history page: each version entry now shows the full set of attribute values recorded at that point in time, making it straightforward to compare versions and decide which one to revert to
- Audit log UI page at `/admin/audit`: paginated, filterable table of all changes (schema, object, action, record link, reason); accessible from the header navigation on every page; object filter is a cascading dropdown; From/To datetime inputs filter by time window
- Deleted reference indicator on the record detail page: reference fields now resolve to a clickable display name; if the referenced record has been soft-deleted the name is shown with a red "deleted" badge
- Numeric field validation: client-side validation highlights invalid number inputs with a red border and field-level error message before submission; integer fields carry `step="1"`; server 422 detail arrays are rendered as readable text
- Collapsible related-objects panels on the record detail page: child records are shown in collapsible panels below the main card with a record count and View links; panels are open by default
- `GET /api/records/{schema}/{obj}/{record_id}` now accepts `include_deleted=true` to fetch soft-deleted records (used for the deleted-reference indicator)
- `GET /api/records/{schema}/{obj}` now accepts `parent_id` to filter records by their parent FK column (used for the related-objects panels)

### Added (tests)
- API integration tests covering the full CRUD lifecycle, search, pagination, soft-delete, `include_deleted` listing, history, revert (including reverting a deleted record), and all import/export formats with upsert; requires `TEST_DATABASE_URL` and is skipped otherwise
- Template rendering tests asserting that every page type returns 200, the new-record form no longer raises a 500, attribute column headers appear in config order, and the embedded `objConfig` JSON preserves insertion order
- Parent-child relationship tests: parent FK persisted on create, parent FK persisted on update, and `parent_id` filter returns only the correct parent's children

## [0.1.1] – 2026-03-11

### Fixed
- Edit form never loaded (spinning circle): Jinja2 template produced `\"uuid\"` (invalid JS) instead of `"uuid"` for the record ID argument
- Export and import URLs returned "Invalid record ID": FastAPI matched `/export` against the `/{record_id}` wildcard because the import/export router was registered after the objects router
- Search field always returned "Failed to load records": Python operator-precedence bug caused wrong columns to be passed to SQLAlchemy's `ilike()`
- Config reload did not apply new attributes to the database: `sync_schema` now resets its in-memory table cache on each call and issues `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for any new columns found in the config

### Changed
- Clicking a row in the record list now navigates directly to the record detail page
- Parent record is shown with a clickable link in the detail view
- Reference and parent dropdowns show the first two non-reference attributes (e.g. "S001 – Acme Ltd") instead of just the first

## [0.1.0] – 2026-03-11

### Added
- Core MDM web application built with FastAPI and PostgreSQL
- Dynamic object/table creation from YAML or JSON config files
- Web interface (Jinja2 templates, vanilla CSS and JS) with full responsive layout
- CRUD operations for records (create, read, update, soft-delete) via API and UI
- Full-text search across string columns within a single object
- Record versioning with complete history stored in per-object `_history` tables
- Ability to view all previous versions and revert a record to any version
- System-wide audit log recording every change (what, who, when, where, why)
- Bulk import from CSV, TSV, and JSON files
- Bulk export to CSV, TSV, and JSON files
- Auto-generated OpenAPI / Swagger documentation at `/docs`
- Paginated record listing with configurable page size
- Multi-object navigation: sidebar lists all schemas and objects
- Cross-object reference support (foreign-key style attribute linking)
- Parent-child hierarchy support between objects within a schema
- Config hot-reload via `POST /api/config/reload`
- Unit tests for schema loader and table manager
- Documentation: README, installation guide, quickstart, reference, software list, troubleshooting
- Example config files in YAML and JSON formats
