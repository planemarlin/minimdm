# Known Issues

This document tracks confirmed bugs and design limitations found during testing.
Issues marked **Fixed** are resolved in the current codebase. Issues marked **Implemented** are resolved features.

---

## Fixed in 0.1.1

### Edit form showed a spinning circle (never loaded)
**Root cause:** The Jinja2 template produced `\"uuid\"` (with backslashes) instead of `"uuid"` for the record ID argument in the inline JavaScript call. This was a syntax error that prevented the script from executing.

### Export/import URLs returned "Invalid record ID"
**Root cause:** FastAPI matched `/api/records/{schema}/{obj}/export` against the `/{record_id}` route (registered first), treating the literal string `"export"` as a record ID. Fixed by registering the import/export router before the objects router.

### Search field always returned "Failed to load records"
**Root cause:** A Python operator-precedence bug in the text-column filter caused an incorrect set of columns to be passed to SQLAlchemy's `ilike()`, resulting in a database error on every search request.

### Config reload did not apply new attributes to the database
**Root cause:** `TableManager.sync_schema()` short-circuited when tables were already cached, so new attributes added to the config were never added to the PostgreSQL table. Fixed by resetting the table cache on each call to `sync_schema` and issuing `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for any new columns.

---

## Fixed / Implemented in 0.1.2

### Column names do not match values in the record list table
**Root cause:** The Jinja2 header loop used `loop.index <= 6` which counted all attributes (including references) toward the 6-column cap, while the JavaScript filtered out references before slicing. Fixed by using a Jinja2 namespace counter that increments only for non-reference attributes.

### Deleted records are not browsable from the UI
**Root cause:** The record list API filtered out soft-deleted records and there was no UI path to reach their history. Fixed by adding an `include_deleted` query parameter to the list API and a "Show deleted" checkbox to the record list toolbar. Deleted rows are shown with strikethrough styling and link to their history page.

### A referenced record's ID still shows after the referenced record is deleted
**Root cause:** Reference fields were rendered as raw UUIDs with no lookup. The detail page now resolves references at display time: active references show a clickable display name; deleted references show the name with a red "deleted" badge. `GET /api/records/{schema}/{obj}/{id}` extended with `include_deleted=true` to support this lookup.

### Numeric fields accept non-numeric input without a visible error message
**Root cause:** No client-side validation existed; non-numeric text was silently dropped by the browser (`value=""` with `validity.badInput=true`). Fixed by checking `badInput` before submission and highlighting invalid inputs with a red border and field-level error message. Integer fields carry `step="1"`; server 422 detail arrays are now rendered as readable text.

### Parent FK silently dropped on create and update
**Root cause:** `_filter_columns` excluded all `_`-prefixed keys to block system columns, but parent FK columns (e.g. `_division_id`) also start with `_` and were dropped. Fixed by enumerating the known system columns explicitly.

### Parent / child records not visible from the detail view
**Root cause:** No UI existed to navigate to or display related records. Fixed by adding collapsible child-record panels below the main card for every object whose `parent` points to the current object. Each panel shows a record count and a table with View links; panels are open by default.

### History page does not show historic attribute values
**Root cause:** The history API returned version metadata only; attribute values were stored in `_history` tables but not rendered. Fixed by passing the full attribute snapshot to the history template and rendering it per version entry.

### Audit log has no dedicated UI page
**Root cause:** No UI existed to browse audit log entries. Fixed by adding `/admin/audit`: a paginated, filterable table (schema, object, action, record, reason, timestamp) with a cascading object dropdown and datetime range filter. Accessible from the header navigation on every page.

---

## Implemented

### Audit logging for user management actions
**Implemented in:** Unreleased (current branch).
`USER_CREATED`, `USER_ACTIVATED`, `USER_DEACTIVATED`, `USER_ROLE_CHANGED`, `USER_PASSWORD_CHANGED`, `PERMISSION_GRANTED`, and `PERMISSION_REVOKED` are now written to `_system.audit_log` and visible on the Auth Events tab.

---

## Production Readiness — Blockers

All blockers resolved in current branch.

### 1. Rate limiting — **Resolved**
10 req/min per IP on login; 10 req/min on import. Implemented with `slowapi`. Disabled in test environments via `RATE_LIMIT_ENABLED=false`.

### 2. CSRF protection — **Resolved**
Session cookie changed from `SameSite=lax` to `SameSite=strict`.

### 3. File upload size limit — **Resolved**
Import endpoint reads at most `MAX_UPLOAD_SIZE+1` bytes and rejects with HTTP 413 if exceeded. Default 10 MB, configurable via `MAX_UPLOAD_SIZE`.

### 4. Health check endpoint — **Resolved**
`GET /health` returns 200 `{"status": "ok", "version": "..."}` when DB is reachable, 503 otherwise. No authentication required.

### 5. Startup validation — **Resolved**
Database connectivity is verified in the lifespan hook before the app accepts requests. Fails fast with a clear error if the DB is unreachable.

### 6. Password policy — **Resolved**
Minimum 12-character password enforced on user creation and password change endpoints.

### 7. History version atomicity — **Resolved**
`SELECT … FOR UPDATE` added to the current open history row before reading its version number. Concurrent updates queue rather than racing.

### 8. Bulk import rollback — **Resolved**
`strict=true` (default): any row error rolls back the entire import and returns all errors. `strict=false`: savepoints isolate each row so valid rows are committed even when others fail.

### 9. HTTPS / TLS — **Resolved (documentation)**
`docs/deployment.md` added with nginx and Caddy examples, required environment variables, and a pre-launch security checklist.

---

## Production Readiness — High Priority

These issues should be addressed before the first deployment with live users.

### 10. Password reset flow — **Resolved**
Admins generate a one-time reset link from the User Management page (Reset link button). The link contains a URL-safe token valid for 24 hours. The user visits the link, enters a new password, and is redirected to the login page. Tokens are single-use; expired and used entries are pruned at startup.

### 11. Token revocation on logout — **Resolved**
Each JWT now carries a `jti` (UUID). On logout the JTI is written to `_system.token_blocklist` with the token's expiry timestamp. The auth middleware rejects any token whose JTI appears in the blocklist. Expired blocklist entries are pruned at startup.

### 12. Database-level foreign key and unique constraints — **Resolved**
`FOREIGN KEY (ON DELETE SET NULL)` constraints are created for parent and reference columns; `UNIQUE` constraints for attributes marked `unique: true`. `_ensure_constraints()` adds missing constraints to existing tables on each startup using `pg_constraint` checks. `IntegrityError` in create/update is caught and returned as 422.

### 13. Export pagination — **Resolved**
Export endpoints now accept `limit` and `offset` query parameters. Results are streamed using server-side cursors so large tables do not cause out-of-memory errors.

### 14. Structured logging with request IDs — **Resolved**
Each request is assigned a UUID in `RequestIdMiddleware`. The ID is injected into every log line via `RequestIdFilter` and returned as the `X-Request-Id` response header. `LOG_FORMAT=json` switches to single-line JSON output. See `docs/logging.md`.

### 15. Database migrations (Alembic) — **Resolved**
Alembic manages all `_system` schema tables. Migration `0001` creates the five system tables; future changes to system tables get new numbered migrations. Migrations run automatically at startup. Legacy installs (tables exist without Alembic) are detected and stamped to head transparently. See `docs/migrations.md`.

### 16. Backup and restore documentation — **Resolved**
`docs/backup-restore.md` added covering `pg_dump` / `pg_restore` for full backups, Docker volume backup, cron automation, backup verification, and a note on point-in-time recovery.

---

## Design Decisions

### Sorting on parent and reference columns is not supported
**Decision:** Parent and reference column headers are intentionally non-sortable. These values are resolved from other tables client-side; a correct global sort would require a SQL JOIN per relationship at query time, adding significant complexity for limited benefit. Sort on the underlying data attributes instead. This is documented in [reference.md](reference.md).

---

## Open Issues

### Improvements from 2026 codebase analysis

Identified during a full architecture/best-practices review (branch `chore/codebase-analysis-2026`). None are urgent — the codebase is already ahead of average on security and migrations — but these are worth doing deliberately.

**Dead code**

1. ~~Remove four orphaned table-bootstrap helpers in `app/core/`, superseded by Alembic migration `0001_initial_system_tables.py`: `auth.py`'s `ensure_token_blocklist_table()`, `ensure_password_reset_tokens_table()`, `ensure_users_table()`, and `permissions.py`'s `ensure_permissions_table()`. Verified zero call sites anywhere in `app/` or `tests/`.~~ **Done in v0.7.3.**

**Tooling — high value, low effort**

2. Expand the `ruff` rule selection beyond `E, F, W, I` to include `B` (bugbear), `UP` (pyupgrade), `SIM`, `C4` — cheap to adopt given the existing lint gate in CI.
3. Add `mypy`/`pyright` as a dev dependency and CI job. Type hints are already used throughout; nothing currently enforces them.
4. Add a coverage floor to the CI test job (`pytest --cov=app --cov-fail-under=NN`); `pytest-cov` is installed but unused in CI today.
5. ~~Add a `HEALTHCHECK` to the Dockerfile using the existing `/health` endpoint~~ **Done in v0.7.3.** Simplifying the install step to `uv sync --frozen --no-dev` is still open — left alone for now since it changes how dependencies are installed (venv-based vs. the current `uv export | pip install` into system site-packages), a bigger change than a patch release should carry.

**Architecture — medium effort**

6. Extract the repeated "close history row → write history → audit log → commit → webhook" sequence in `app/api/objects.py` (duplicated near-identically across create/update/delete/revert/publish/retire, ~500 lines) into a single internal helper.
7. Split `app/static/js/app.js` (1755 lines, ~77 global functions) into native ES modules (`<script type="module">`, no build step needed) — e.g. `list.js`, `detail.js`, `admin.js`, `audit.js`, shared `api.js`.
8. Move business logic currently embedded in `app/main.py` route handlers (e.g. `pending_drafts()`'s per-object DB query loop) into `table_manager.py` or a small service module, consistent with how `objects.py`/`import_export.py` are already separated out.

**Decisions worth making explicitly, not urgent**

9. Decide and document an API versioning stance (`/api/` has none today) before inbound webhook integrations proliferate.
10. `check_permission()` opens a fresh SQLAlchemy session per call, up to twice per request. Fine at current scale; revisit if permission checks become a hot path.

### Publish versioned container images

Raised via [#49](https://github.com/planemarlin/minimdm/issues/49). Docker deployments currently build from source (`docker compose build`) — there's no CI job that publishes tagged images to a registry (e.g. `ghcr.io/planemarlin/minimdm:vX.Y.Z`), so upgrading a Docker deployment still means a `git checkout` + rebuild, documented in [upgrading.md](upgrading.md). Adding one would need a new publish-on-tag GitHub Actions workflow; not started.

### `Settings.host`/`Settings.port` aren't wired to the actual server bind — **Resolved**

Found while adding the Dockerfile `HEALTHCHECK` in v0.7.3 (hardcoded to port `8000` — correct, since that's the container's fixed internal port; only `APP_PORT` varies the host-side mapping in `docker-compose.yml`). Investigating that hardcoded value surfaced a separate, unrelated gap: `app/config.py`'s `host` and `port` fields on `Settings` were read by nothing — the actual `--host`/`--port` uvicorn flags were hardcoded on three separate command lines instead (Dockerfile `CMD`, `docker-compose.yml`'s `command:`, and the manual `uvicorn` invocation in `docs/installation.md`). Not a functional bug (the container's internal port never needs to change for Docker users, and bare-metal users pass `--host`/`--port` directly on their own command line anyway), but the fields were dead config surface implying an option that didn't work. Resolved by removing both fields from `Settings` rather than wiring them up — no deployment path had a real need for `.env`-based host/port control, so the smaller, no-behavior-change fix was preferred over adding it across three files.
