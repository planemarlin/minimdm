# Changelog

All notable changes to miniMDM are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Tests
- **`can_publish` permission boundary now covered**: 8 new tests in `tests/test_api_permissions.py` exercise `require_publish_access()` as a non-admin for the first time — every existing publish/retire test ran as admin, which short-circuits the permission check entirely, so an Editor's inability to publish/retire had never actually been verified; new cases cover a user with no permission, an Editor (`can_write`, no `can_publish`) blocked from both `/publish` and `/retire`, a granted Publisher succeeding at both, `set_permission`'s "publish implies write" rule, and a real Publisher still being blocked by `allow_direct_active_import: false` (role doesn't override the object-level flag); flagged in the 2026-07-14 codebase analysis as the highest-priority test gap and skipped ahead of both v0.7.1 and v0.7.3 before being closed here

### Removed
- **Dead `Settings.host`/`Settings.port` config fields**: neither field was read anywhere in the codebase — the actual `--host`/`--port` uvicorn flags are hardcoded on three separate command lines (Dockerfile `CMD`, `docker-compose.yml`'s `command:`, and the manual invocation in `docs/installation.md`), so setting `HOST`/`PORT` in `.env` had no effect and no error. Removed rather than wired up: no deployment path has a demonstrated need for `.env`-based bind control — bare-metal users already pass `--host`/`--port` directly, and the container's internal port never needs to change for Docker users ([known_issues.md](docs/known_issues.md))

### Docs
- **`can_publish` coverage reflected in `docs/testing.md`**: the "Publish/retire authorization" entry in Known test gaps is removed (fully closed) and the `test_api_permissions.py` summary section updated to match the new tests
- **Quickstart UTF-8 import note**: `docs/quickstart.md`'s Bulk Import section now mentions the UTF-8 encoding requirement (already documented in `docs/reference.md` and `docs/troubleshooting.md`, but missing from a first-time user's likely entry point)

## [0.7.3] – 2026-08-22

### Fixed
- **Docker Compose startup crashed when `APP_PORT`/`POSTGRES_PORT` were set in `.env`**: `docker-compose.yml` bind-mounts the project directory into the app container, so `app/config.py`'s `Settings(env_file=".env")` parses the very same `.env` file `docker-compose.yml` reads for host-port substitution; pydantic-settings' dotenv source loads the whole file as a flat dict (unlike its env-var source, which looks up only known fields), so the two Compose-only keys reached model validation as unrecognized fields and crashed the app at import time under the pydantic-settings default `extra="forbid"` — meaning the port parameterization shipped in v0.7.2 (#49, #50) crashed on first real use, and a fresh install following `docs/docker-setup.md`'s `cp .env.docker .env` step crashed immediately since `.env.docker` already sets both keys; `Settings.model_config` now sets `extra="ignore"`; regression test `test_ignores_docker_compose_only_env_vars` in new `tests/test_config.py` ([#49](../../issues/49))
- **`scripts/init-db.sh` committed without the executable bit**: PostgreSQL's official image entrypoint refuses to run a non-executable `.sh` init script, so `docker compose up` failed on the `postgres` container on every fresh clone, on every released version since Docker support was added — never caught because nothing exercised the Docker Compose startup path end-to-end; file mode corrected to `755`

### Added
- **Dockerfile `HEALTHCHECK`**: polls the existing `GET /health` endpoint every 30s (5s timeout, 10s start period, 3 retries); verified against the same test setup used for the two fixes above — `docker inspect` now reports the `minimdm-app` container as `healthy` rather than leaving its health status unset

### Changed
- **CI jobs now set `timeout-minutes`**: `lint` and `security` at 10, `test` at 15, `browser-test` at 20 — previously all four fell back to GitHub Actions' 360-minute platform default, so a hung runner (as happened on the v0.7.1 merge's `browser-test` job) idled for hours instead of failing fast

### Removed
- **Four dead table-bootstrap helpers**: `app/core/auth.py`'s `ensure_token_blocklist_table()`, `ensure_password_reset_tokens_table()`, `ensure_users_table()`, and `app/core/permissions.py`'s `ensure_permissions_table()` — all superseded by Alembic migration `0001` and confirmed to have zero call sites anywhere in `app/` or `tests/`

## [0.7.2] – 2026-08-19

### Changed
- **`docker-compose.yml` host ports are now configurable via `.env`**: `APP_PORT` (default `8000`) and `POSTGRES_PORT` (default `5432`) replace the hardcoded port mappings, so a local port customization no longer means hand-editing a tracked file — and no longer conflicts with `git pull`/`git checkout` on the next upgrade; `docker-compose.override.yml` is now gitignored as the supported place for any other host-specific Compose customization (extra volumes, resource limits, additional services); `docs/docker-setup.md` updated accordingly

### Docs
- **Upgrade guide**: new `docs/upgrading.md` documents how to upgrade an existing installation — git-tag-based upgrades for both bare-metal and Docker deployments (no versioned container image is published yet), a pre-upgrade backup/Changelog checklist, and how to carry `docker-compose.yml` customizations across an upgrade using the new `APP_PORT`/`POSTGRES_PORT` env vars and `docker-compose.override.yml`, including a one-time migration path for installs that edited `docker-compose.yml` directly before this pattern existed ([#49](../../issues/49))
- **Container image backlog item**: `docs/known_issues.md` now tracks publishing versioned container images to a registry (e.g. GHCR) as a possible future addition — not started; Docker deployments still build from source

## [0.7.1] – 2026-08-18

### Fixed
- **Unique constraint ignored soft-deleted records**: attributes marked `unique: true` are enforced via a partial index scoped to `_state = 'active'`, but soft-deleted records keep `_state = 'active'` (only `_deleted_at` is set), so deleting a record and re-creating one with the same value raised a duplicate-key error; the index predicate now also requires `_deleted_at IS NULL`, and `_ensure_constraints()` detects indexes built under the old predicate and rebuilds them on startup so existing deployments self-heal without a manual migration; new regression test `test_unique_constraint_allows_reuse_after_delete` in `tests/test_api_records.py` ([#44](../../issues/44))
- **Import hung on "Importing…" forever for non-UTF-8 files**: uploading a CSV/TSV file that wasn't valid UTF-8 (e.g. Excel's Windows-1252 CSV export, or its UTF-16 "Unicode Text" export) raised an unhandled `UnicodeDecodeError` on the backend, producing a non-JSON 500 response; the frontend's unguarded `res.json()` call then threw and left the import UI stuck showing "Importing…" indefinitely with no error; the backend now catches the decode failure and returns a clear `400` explaining the file must be UTF-8, and the frontend catches any fetch/parse failure so the UI always surfaces an error instead of hanging; new tests `test_import_non_utf8_csv_returns_400` and `test_import_utf16_tsv_returns_400` in `tests/test_api_import_export.py`, and `test_import_non_json_error_response_shows_message` and `test_import_non_utf8_file_shows_error` in `tests/browser/test_import_export.py` ([#45](../../issues/45))

### Docs
- **Codebase analysis backlog**: `docs/known_issues.md` now tracks a punch list of dead code, tooling gaps (missing `mypy`/`pyright`, minimal `ruff` rule selection, no CI coverage gate, missing Dockerfile `HEALTHCHECK`), and architecture cleanups (duplicated lifecycle-transition logic in `app/api/objects.py`, unsplit `app.js`, business logic embedded in `app/main.py` route handlers) identified during a full 2026 architecture/best-practices review
- **Test coverage gap audit**: `docs/testing.md` now documents known gaps ahead of the next release, found by cross-checking the v0.5.0 manual test plan and a broader sweep against the automated suite — most notably that the publish/retire permission boundary (`can_publish`) has zero test coverage anywhere, plus a set of UI-only gaps (behavior tested at the API level but never driven through a browser) and untested backend behaviors (rate limiting, security headers, the webhook SSRF guard, config-reload validation errors); also corrects a stale claim that `test_api_permissions.py` covered "Editors cannot publish"

## [0.7.0] – 2026-07-09

### Added
- **Inbound webhook receiver**: external source systems can push records into miniMDM via `POST /api/inbound/{schema}/{object}` authenticated with an API key (`X-Api-Key` header); all inbound records always land as **drafts** — the lifecycle is never bypassed; field mapping between the source payload and miniMDM attributes is declared in the YAML config per object under `inbound_sources`
- **`inbound_sources` config block**: new optional object-level config key; each entry has a `name` (used as `_source_system`), a `field_map` dict mapping source field names to miniMDM attribute keys, and an optional `match_key`; at least one mapping to `_source_id` is required (validated at startup) to enable compound upsert matching; source names must be unique within an object and valid identifiers
- **`match_key` fallback matching**: an optional attribute name on each `inbound_sources` entry; when the primary lookup by `_source_system` + `_source_id` finds no record, miniMDM falls back to matching on this business-key attribute (e.g. `code`); if exactly one record matches it is **claimed** — `_source_system` and `_source_id` are stamped onto the active record immediately so future pushes use the fast primary path; if more than one record matches the fallback is skipped and a new draft is created; using a `unique: true` attribute as `match_key` eliminates ambiguity entirely
- **Partial field update semantics for inbound pushes**: only the fields present in the `field_map` are written on an upsert; any attributes the publisher has enriched that are outside the mapping (e.g. contact email, rating) are preserved on the draft without being overwritten by the source; `_source_system` is always forced to the config `name` and cannot be overridden by the payload
- **Inbound API key management**: API keys are generated as 43-character `secrets.token_urlsafe(32)` values, stored as SHA-256 hashes in the new `_system.inbound_keys` table, and scoped to a schema and source name; the raw key is shown **once** at generation time; `hmac.compare_digest` is used for constant-time comparison; keys can be revoked (soft-deleted) at any time
- **Inbound Keys admin UI**: new tab on the Users admin page (`/admin/users`) lists all API keys with schema, source name, key prefix, last-used timestamp, and status; Generate Key button opens a modal to select schema, source, and optional description; raw key shown once in a copyable modal after generation; Revoke button per row
- **Inbound Key Management API** (Admin only): `GET /api/admin/inbound-keys` (list all keys), `GET /api/admin/inbound-keys/sources` (list configured sources from YAML), `POST /api/admin/inbound-keys` (generate and store key, returns raw key once), `DELETE /api/admin/inbound-keys/{key_id}` (revoke)
- **Alembic migration 0003**: creates `_system.inbound_keys` with `CREATE TABLE IF NOT EXISTS` for idempotency — safe to run against databases where `sync_schema` created the table at app startup before the migration was applied
- **`GET /api/pending-count`** endpoint: returns the total number of pending draft records across all schemas accessible to the current user; used by the publisher notification badge
- **Publisher pending-draft badge**: top navigation bar shows a count of pending draft records for all authenticated users with access to at least one schema; badge is hidden when the count is zero; links to the new Pending Drafts page
- **Pending Drafts page** (`/pending`): server-rendered list of all draft records across all accessible schemas; records are grouped by object type with the first three attributes, source system, and last-updated timestamp shown; each row is clickable and links to the record detail page; empty state shown when no drafts exist
- **Logo clickable and dual-colour**: the miniMDM brand in the sidebar now links to the home page; "mini" is rendered bold white and "MDM" in a muted tone matching the minimdm.dev brand treatment; hover underline suppressed
- **Audit log filter row**: the three filter dropdowns (All Schemas, All Objects, All Actions) on the Data Changes tab now sit in a single inline flex row instead of stacking full-width, giving more vertical space to the log table
- **Inbound call audit events**: every successful inbound push now writes an `INBOUND_CALL` entry to the Auth Events audit log (`_system`/`inbound`) recording the target schema, object, and outcome (`created`/`updated`); failed authentication attempts write `INBOUND_CALL_FAILED` so revoked keys or misconfigured clients are visible to admins without checking server logs
- **Expanded audit log action filters**: the Data Changes action filter now lists all seven record lifecycle actions (`INSERT`, `UPDATE`, `DELETE`, `PUBLISH`, `RETIRE`, `DRAFT_CREATED`, `REVERT`) each with a short description; the Auth Events action filter lists all thirteen auth/admin actions grouped into Session, User management, Permissions, and Inbound keys sections; all action badges are colour-coded
- **Key scope note in Generate Key modal**: when a source name is selected in the Inbound Keys generation modal, a scope note appears showing exactly which objects that source name has push access to in the chosen schema
- **Quick Reference card layout**: the help modal (? button) is redesigned as a two-column card grid; each topic (Records, Lifecycle states, Source & provenance, History & Revert, Reason for change, Import & Export, Audit log, Access control) is its own card with a blue left-border accent and blue title

### Security
- **Rate limiting on inbound endpoint**: `POST /api/inbound/{schema}/{obj}` is now limited to 120 requests per minute per IP using the same SlowAPI limiter applied to other write endpoints; requests over the limit receive `429 Too Many Requests`
- **Request body size limit on inbound endpoint**: body size is checked against `MAX_UPLOAD_SIZE` (default 10 MB) before JSON parsing — oversized requests receive `413` immediately, preventing memory exhaustion from large payloads
- **`source_name` identifier validation in key creation API**: `POST /api/admin/inbound-keys` now validates that `source_name` matches the same `^[a-zA-Z_][a-zA-Z0-9_]*$` identifier pattern enforced by the YAML parser, closing a stored-XSS gap in the admin UI
- **Revoke button XSS hardening**: the Revoke button in the Inbound Keys table now uses `data-key-id` / `data-source-name` attributes instead of interpolating values directly into an `onclick` string, eliminating the injection vector for attacker-controlled `source_name` values
- **Row-level lock on `match_key` candidate query**: the `SELECT` that finds records by business key in the match_key fallback path now uses `WITH FOR UPDATE`, preventing a TOCTOU race where two concurrent pushes could both see zero candidates and create duplicate drafts
- **DB index on `inbound_keys (schema_name, is_active)`**: key verification no longer requires a full table scan as the number of keys grows
- **`X-Forwarded-For` spoofing**: IP address recording in the audit log is now controlled by `TRUSTED_PROXY` (default `false`); when `false` the direct TCP peer address is used and the header is ignored, preventing callers from injecting arbitrary IPs into audit log entries; set `TRUSTED_PROXY=true` when running behind a trusted reverse proxy
- **Shared API key hash and IP utilities**: `hash_api_key()` extracted to `app/core/keys.py` (previously duplicated in `admin_api.py` and `inbound.py`); `client_ip()` extracted to `app/core/network.py` (previously duplicated in `objects.py`, `admin_api.py`, and `auth_api.py`) and now respects the `TRUSTED_PROXY` setting

### Tests
- **6 new inbound security tests**: `test_generate_key_invalid_source_name`, `test_inbound_oversized_body` (413), `test_inbound_invalid_json` (400), `test_inbound_non_object_json` (400), `test_inbound_call_audit_event`, `test_inbound_call_failed_audit_event` — `tests/test_api_inbound.py` now has 29 cases

### Fixed
- **`table_manager.py` server_default regex**: the injection guard `^'[a-z_]+'$` did not allow the SQL boolean literal `true`, causing an `AssertionError` on startup when the new `is_active` column (with `server_default="true"`) was encountered; regex widened to `^(?:'[a-z_]+'|true|false)$`
- **Inbound audit log test**: `GET /api/audit` returns a paginated envelope `{"records": [...], "total": ...}` — the test was iterating over the top-level dict keys (strings) instead of unwrapping `["records"]`

## [0.6.3] – 2026-06-27

### Security
- **pydantic-settings 2.13.1 → 2.14.2**: resolves GHSA-4xgf-cpjx-pc3j — `NestedSecretsSettingsSource` followed symbolic links outside `secrets_dir` when `secrets_nested_subdir=True`, enabling unintended local file reads and bypassing `secrets_dir_max_size` (CVSS 5.3 Medium); miniMDM does not use `NestedSecretsSettingsSource` and is not directly affected, but the package is upgraded for hygiene

## [0.6.2] – 2026-06-17

### Added
- **SECURITY.md**: security policy documenting the preferred reporting channel (GitHub private vulnerability reporting), fallback contact (minimdmsecurity@gmail.com), 5-day response target, supported versions, and coordinated disclosure process

### Security
- **python-multipart 0.0.27 → 0.0.32**: resolves four CVEs — quadratic-time querystring parsing with semicolon separators causing CPU DoS (GHSA-r7v4-jwx9-wx43, **high**), negative `Content-Length` in `parse_form` buffering the entire body in memory (GHSA-59g4-hpg3-3gfx), semicolon-separated querystring field smuggling (GHSA-2jv5-9r88-3w3p), and `Content-Disposition` parameter smuggling via RFC 2231/5987 extended parameters (GHSA-hxf5-99xg-86hw)
- **starlette 1.2.1 → 1.3.1**: resolves two CVEs — `request.form()` per-field and total size limits silently ignored for `application/x-www-form-urlencoded` bodies, enabling DoS (GHSA-qxjg-jhgw-qhrv, **high**), and unvalidated request path concatenated into the authority component poisoning `request.url.hostname` (GHSA-f96h-pmfr-66vw)

## [0.6.1] – 2026-06-06

### Added
- **UI facelift — new design system**: comprehensive visual refresh across all pages; introduces `tokens.css` as a design token layer (colours, spacing, typography, shadows, component tokens) and `mdm-*` CSS classes used throughout; updated pages include the record list, record detail, edit form, history, user management, and audit log; the sidebar and top bar are rebuilt with a flex-layout shell
- **Playwright browser test suite**: 31 end-to-end tests across 7 files in `tests/browser/` verify the full UI from a real browser perspective — authentication flows, record CRUD, edit/delete with reason, the complete draft → publish → retire lifecycle, history and revert, CSV/TSV import and export download, the user management page, and the audit log; tests run headlessly by default and are skipped when `TEST_DATABASE_URL` is not set; `playwright` and `pytest-playwright` added to the `dev` dependency group; run `uv run playwright install chromium` once to install the browser binary; see `docs/testing.md` for full details
- **Favicons**: added browser and PWA favicons (16, 32, 180, 192, and 512 px) wired up in `base.html`

### Changed
- **Inline scripts extracted to external JS files**: page-level JavaScript for the record list, login, and password-reset pages is now in `app.js` and the new `auth.js`; template script blocks are reduced to single bootstrap calls passing Jinja2 variables; the only remaining inline scripts are config-passing calls that require template variables and the FOUC-prevention theme snippet that must run synchronously before render
- **CI trigger**: GitHub Actions no longer fires on every branch push; jobs now run on `push` to `main` and on `pull_request` events only, eliminating duplicate parallel runs when a feature branch has an open PR

### Fixed
- **JSON export 500 on numeric fields**: `numeric`-type attribute values (Python `Decimal`) were not JSON-serialisable, causing a 500 error on JSON export for any object with a numeric column; `Decimal` values are now converted to `float` before serialisation; CSV and TSV export were unaffected
- **Deleted-record history button**: the History icon button on deleted rows in the record list was mis-rendered because `mdm-rowact` was applied as a class directly on the `<a>` tag instead of a wrapper `<div>`; button now renders with correct icon and hover styling
- **Reference dropdowns full-width on edit form**: reference attribute dropdowns spanned the full card width instead of fitting into the two-column attribute grid alongside regular fields
- **`Object-Level Flags` example misplaced in `docs/reference.md`**: the YAML example block for `require_change_reason`, `requires_draft`, `allow_retire`, and `allow_direct_active_import` appeared after the Governance Metadata section; moved to directly follow the flags table
- **Missing `check_permission` import in record list route**: a `NameError` was raised at runtime when a non-admin user navigated to any record list page because `check_permission` was used but not imported at the top of the `object_list` route handler

### Security
- **HTML escaping in import error display**: row-level error messages from the import API are now HTML-escaped before rendering in the UI status panel, preventing self-XSS via crafted CSV cell values
- Upgraded `pyjwt` to 2.13.0 to resolve PYSEC-2026-175, PYSEC-2026-177, PYSEC-2026-178, and PYSEC-2026-179
- Pinned `starlette >= 1.0.1` to resolve Dependabot alert #5
- Upgraded `idna` 3.11 → 3.16 to resolve GHSA-65pc-fj4g-8rjx (CVE-2024-3651, bypass of the IDNA encoding fix via crafted input); not directly exploitable in miniMDM but patched for hygiene

## [0.6.0] – 2026-05-16

### Added
- **Data ownership & stewardship**: `owner` and `steward` are new optional free-text fields at the object level in the schema YAML config; both are informational only with no enforcement logic; when set, they are displayed near the object name and description on the records list page
- **`?role=` MDM alias on record list**: `GET /api/records/{schema}/{obj}` now accepts `?role=master` (maps to `state=active`) and `?role=draft` (maps to `state=draft`) as MDM-native vocabulary; passing an invalid role value returns HTTP 400 with a list of valid values; combining `?role=` and `?state=` in the same request returns HTTP 400
- **OpenAPI MDM vocabulary**: all record endpoint summaries, descriptions, and tags updated to use MDM-native language — "master record", "golden record", "draft candidate", "promote to master"; the records router tag is now `MDM Records`; schema and import/export endpoints also received descriptions

### Fixed
- Auth login endpoint now documents its request body (`username`, `password`) in the Swagger UI; replaced raw `request.json()` parsing with a Pydantic model ([#27](../../issues/27))
- Web UI routes (`/`, `/login`, `/admin/users`, etc.) no longer appear in the Swagger API documentation; `include_in_schema=False` added to all HTML-returning routes ([#28](../../issues/28))
- `app_version` in `app/config.py` was behind `pyproject.toml` by one version; both are now aligned at `0.6.0`

### Security
- **Config reload restricted to admins**: `POST /api/config/reload` previously allowed any authenticated user to trigger a schema sync; now requires Admin role
- **Webhook URLs hidden from non-admins**: `GET /api/config` no longer returns the `webhooks` list, which could contain API keys embedded in URLs; response is now limited to schema definitions
- **SSRF guard on webhook URLs**: webhook URLs pointing to private or loopback IP ranges (`127.x`, `10.x`, `172.16.x`, `192.168.x`, `169.254.x`) are now rejected at config load time
- **Constant-time login**: bcrypt verification now runs even when a username does not exist, closing a timing-based username enumeration channel
- **No default admin password in Docker Compose**: removed the `admin` fallback default for `ADMIN_PASSWORD`; operators must now explicitly set the variable, preventing accidental deployment with trivially guessable credentials
- **Startup warning for `SECURE_COOKIE=false`**: the application now logs a warning at boot when `SECURE_COOKIE` is disabled, consistent with the existing `SECRET_KEY` placeholder warning
- **Docker container runs as non-root**: the production image now creates and uses a dedicated `app` system user, following container security best practices

## [0.5.0] – 2026-05-10

### Added
- **record.created webhook**: `record.created` fires when a new record is created directly as active; completes full lifecycle webhook coverage alongside `record.published` and `record.retired`
- **Audit log user filter**: text input on both the Data Changes and Auth Events tabs filters entries by username (case-insensitive partial match); `GET /api/audit` accepts a `?user=` query parameter
- **Golden record semantics**: active records are now explicitly identified as the golden/master record throughout the UI (detail view badge shows "Active · Master", list filter shows "Active (Master)"), OpenAPI descriptions, and docs; a new "miniMDM as an MDM system" section in `docs/reference.md` explains the single-source-of-truth model
- **Source & provenance**: two new system columns `_source_system` (e.g. `"erp"`, `"crm"`) and `_source_id` record where each golden record originated; settable via the API body, via per-column CSV/TSV/JSON import, or via the `?source_system=` import query parameter (query param applies to all rows; per-row column values take precedence); provenance is shown in the record detail view and preserved in history; `GET /api/records` accepts `?source_system=` to filter by origin
- **Lifecycle policy flags**: three new object-level config flags enforce governance rules without code changes — `requires_draft: true` forces all new records through draft regardless of role; `allow_retire: false` blocks retirement of stable reference data; `allow_direct_active_import: false` prevents bulk import directly as active, requiring draft review even for Publishers

### Fixed
- **Sidebar highlight collision**: the active-item highlight in the left nav now uses an exact path match, preventing a false highlight when one object key is a prefix of another (e.g. `product` incorrectly highlighted when viewing `product_category`)
- **History snapshot provenance**: `_source_system` and `_source_id` are now shown in each history snapshot entry on the record history page
- **CSV header whitespace**: trailing spaces in CSV column headers (produced by Excel and LibreOffice) are now stripped before matching against the object schema, preventing silent row failures
- **Source system list filter**: a source system input on the record list toolbar filters records by `_source_system` via the existing `?source_system=` API parameter; was previously added only to the API
- **Date-only formatting**: date-type attribute values are now displayed without a time component in the record list, record detail view, and history snapshots; a new `fmtDateOnly()` helper is used wherever the attribute type is `date`
- **Show deleted excludes draft artifacts**: edit drafts that were soft-deleted by the publish workflow (those with `_draft_of_id` set) no longer appear when "Show deleted" is toggled; only records explicitly deleted by a user are shown
- **`_created_by` populated on creation**: the `_created_by` system column is now populated from the authenticated username when a record is created (it was always populated in history; the main record was missing it)
- **Import reason input in UI**: the import dialog now includes a reason text input; the value is passed to the API as `?reason=`, and the reason appears in the record history as expected
- **`_reason` clarified as not a per-row import column**: `docs/reference.md` now explicitly notes that `_reason` is not supported as a column in CSV/TSV/JSON import files; set the reason via the `?reason=` query parameter instead
- **403 access-denied message**: attempting to view a record list for a schema the user cannot access now shows a clear "You don't have access to this schema" message instead of the generic "Failed to load records" error

### Security
- Upgraded `mako` from 1.3.11 to 1.3.12 to resolve CVE-2026-44307
- Upgraded `python-multipart` from 0.0.26 to 0.0.27 to resolve CVE-2026-42561

## [0.4.0] – 2026-05-01

### Added
- **Lifecycle states**: every record now carries a `_state` field with three values — `draft`, `active`, and `retired`; new records are created as `active`; history tables also snapshot the state
- **Draft copy on edit**: editing an `active` record no longer modifies it in place; instead a new `draft` copy is created alongside the active record (`_draft_of_id` links them); the active record remains fully visible to API consumers while the draft is being prepared; editing a draft updates it in place
- **Publish endpoint** (`POST /api/records/{schema}/{obj}/{draft_id}/publish`): promotes a `draft` to `active` by copying its data back to the stable master record and soft-deleting the draft; requires Publisher or Admin role
- **Retire endpoint** (`POST /api/records/{schema}/{obj}/{record_id}/retire`): transitions an `active` record to `retired`; retired records are excluded from default API responses; requires Publisher or Admin role
- **Publisher role**: `schema_permissions` table gains a `can_publish` column; four roles are now supported — Viewer (read), Editor (read + write), Publisher (read + write + publish lifecycle transitions), and Admin (everything); role label shown in the permissions panel
- **State filtering** on `GET /api/records/{schema}/{obj}` and export: default is `active`; use `?state=draft`, `?state=retired`, or `?state=all` to broaden the filter
- **State filter dropdown** in the record list UI (Active / Draft / Retired / All states)
- **State badge** in record list rows and record detail metadata: draft records show an amber "draft" badge; retired records show a grey "retired" badge
- **Publish and Retire buttons** on the record detail page: Publish appears for draft records (Publisher/Admin only); Retire appears for active records (Publisher/Admin only); Edit and Delete are hidden for retired records
- **Import initial state**: `POST /api/records/{schema}/{obj}/import` accepts `initial_state=active` (default) or `initial_state=draft`; importing as `active` requires Publisher or Admin role — Editors can import as `draft` and publish later
- **Required reason for change**: objects can set `require_change_reason: true` in the config; when set, all write operations (create, update, delete, revert, publish, retire) return HTTP 422 if `_reason` is absent or empty; the UI marks the Reason field with a red asterisk and blocks submission
- **Webhooks on state transitions**: configure HTTP POST callbacks in the config under `webhooks:`; `record.published` fires when a draft is promoted to active, `record.retired` fires when an active record is retired; delivery is asynchronous (after the API response) so a slow or unreachable endpoint never affects the caller; failures are logged as warnings

### Fixed
- Export now respects the active state filter dropdown: exporting while viewing drafts exports drafts, not active records
- Import now passes `initial_state=draft` automatically when the state filter is set to Draft, so imported records land in the correct state without manual API configuration
- Import upsert with `initial_state=draft` now correctly follows the draft-copy-on-edit flow when the matched record is `active`: a draft copy is created (or the existing draft updated) rather than modifying the active record directly
- Users page account-type column renamed from "Role" to "Type" to avoid confusion with the per-schema role (Viewer / Editor / Publisher) shown in the permissions panel

## [0.3.1] – 2026-04-17

### Security
- Upgraded `mako` from 1.3.10 to 1.3.11 to resolve a path traversal vulnerability via double-slash URI prefix in `TemplateLookup` (GHSA); `mako` is a transitive dependency pulled in by Alembic — miniMDM does not use Mako templates directly

## [0.3.0] – 2026-04-16

### Added
- `config/minimdm.example.yaml`: example config file showcasing all key features — required/unique attributes, parent relationships, cross-object references, and all attribute types
- Sorting on parent and reference columns is intentionally not supported; column headers are non-clickable to reflect this; documented in `docs/reference.md` and `docs/known_issues.md`
- Light/dark mode toggle (☾/☀) in header; follows OS preference (`prefers-color-scheme`) on first visit; choice persisted in `localStorage`; no flash of wrong theme on page load
- In-app help: `?` button in header opens a Quick Reference modal covering records, history/revert, reason for change, import/upsert, audit log, and access control
- Tooltips on non-obvious UI elements: Show deleted, upsert dropdown, Import, History, Delete, Revert, and Reset link buttons
- Cookie notice on login page; browser storage section added to `docs/reference.md` documenting the `access_token` cookie and `theme` localStorage key
- `config/minimdm.yaml` and `config/minimdm.json` added to `.gitignore` — these are deployment-specific and should not be committed
- GitHub Actions CI workflow (`.github/workflows/ci.yml`): three jobs run on every push — `Lint` (ruff), `Dependency security audit` (pip-audit against the OSV database), and `Test` (pytest against a real PostgreSQL 16 instance, matrix on Python 3.11 and 3.12)
- `SecurityHeadersMiddleware`: every response now carries `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and a `Content-Security-Policy` header; headers are skipped for `/docs`, `/redoc`, and `/openapi.json` to allow Swagger UI to load its CDN assets
- `SECURE_COOKIE` environment variable (default `false`): when set to `true`, the `access_token` session cookie is issued with the `Secure` flag so browsers only transmit it over HTTPS; enable this in all production deployments; documented in `docs/deployment.md` and `docs/reference.md`
- `LICENSE`: miniMDM is released under the MIT License
- `demo/` folder: sample import data for the `nordkraft` demo schema (a fictional furniture distribution company) with CSV files for Supplier, Product Category, Product, and Customer; the `nordkraft` schema is also included in `config/minimdm.example.yaml` as a second-schema example
- Import audit log entries now include an automatic reason (`Import of file <filename>`) when no explicit reason is provided via the `reason` query parameter

### Fixed
- `docs/installation.md`: config file copy command used `minimdm.yaml` as both source and destination; corrected to `minimdm.example.yaml`
- `docs/deployment.md`: health check example showed stale version `0.1.0`; updated to `0.2.0`; added missing `LOG_FORMAT` environment variable to the env vars table
- `README.md`: docs table was missing `docker-setup.md`, `logging.md`, `migrations.md`, and `testing.md`
- Audit log Auth Events tab: pagination buttons called `loadAuditLog` instead of `loadAuthLog`, causing the Data Changes tab to reload on page navigation
- Import of records with `boolean`, `integer`, `numeric`, or `date` columns failed with a database type mismatch; CSV values are now coerced to the correct Python type before insertion; the same coercion is applied to the record create/update API so string values from any client are handled correctly
- Import error display showed `[object Object]` when strict-mode rolled back a batch; the error panel now shows the rollback message and a per-row error list
- Date fields in the edit form were not pre-populated: the API returns full ISO 8601 timestamps but `<input type="date">` requires `YYYY-MM-DD`; the value is now sliced to the date portion before populating the field
- Boolean fields in the edit form were rendered as free-text inputs requiring the user to type `true` or `false`; they are now rendered as checkboxes, pre-checked based on the stored value, and submitted as JSON booleans

### Security
- Upgraded `pygments` from 2.19.2 to 2.20.0 to resolve CVE-2026-4539 (ReDoS via crafted input); `pygments` is a transitive dev dependency pulled in by pytest
- Upgraded `pytest` from 9.0.2 to 9.0.3 to resolve CVE-2025-71176; dev dependency only
- Upgraded `python-multipart` from 0.0.22 to 0.0.26 to resolve CVE-2026-40347; used for file upload handling in the import endpoint
- All five bandit findings were assessed as intentional design decisions and annotated with `#nosec` with explanations: two `try/except/pass` guards that prevent audit log failures from blocking operations (B110), a `0.0.0.0` bind address controlled by the operator (B104), a `try/except/continue` for tables not yet created (B112), and a placeholder `SECRET_KEY` that already triggers a startup warning (B105)

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
