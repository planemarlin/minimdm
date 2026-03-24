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

These issues must be resolved before miniMDM is suitable for a public-facing or multi-user production deployment.

### 1. Rate limiting
**Context:** No protection against brute-force login attacks, repeated failed authentication, or API abuse. A single client can hammer the login endpoint without restriction.
**Planned fix:** Add per-IP rate limits on the login endpoint and a per-user limit on authenticated API endpoints using `slowapi` or equivalent FastAPI middleware.

### 2. CSRF protection
**Context:** Mutating endpoints (create, update, delete, import, user management) accept cookie-authenticated requests with no CSRF token. A logged-in user could be tricked into making unintended state changes via a crafted page.
**Planned fix:** Add CSRF token middleware (e.g. `fastapi-csrf-protect`) to all non-GET endpoints, or enforce `SameSite=Strict` on the session cookie.

### 3. File upload size limit
**Context:** The import endpoint (`POST /api/records/{schema}/{obj}/import`) accepts files of unlimited size. A large file could exhaust server memory or disk.
**Planned fix:** Enforce a configurable `MAX_UPLOAD_SIZE` limit (default 10 MB) in the import endpoint.

### 4. Health check endpoint
**Context:** No `GET /health` or `GET /healthz` endpoint exists. Load balancers, Docker health checks, and monitoring systems have no way to verify the app is up and the database is reachable.
**Planned fix:** Implement `GET /health` returning 200 with a JSON body confirming database connectivity and app version.

### 5. Startup validation
**Context:** If `DATABASE_URL` is invalid or the database is unreachable at startup, the application starts without error and fails only on the first request. Required environment variables (`DATABASE_URL`, `SECRET_KEY`, `CONFIG_FILE`) are not validated at startup.
**Planned fix:** Validate all required environment variables and test database connectivity in the FastAPI lifespan hook before accepting requests. Fail fast with a clear error message.

### 6. Password policy
**Context:** No minimum password length, complexity, or expiration is enforced. The default admin password (`admin`) is plaintext in `.env.docker` and must be changed manually.
**Planned fix:** Enforce a minimum password length (12+ characters) at the API layer. Document the requirement to change the default admin password during initial setup.

### 7. History version atomicity
**Context:** The history version counter is incremented in Python (`current_version + 1`) after reading the current maximum from the database. Concurrent updates to the same record can produce duplicate version numbers.
**Planned fix:** Use a database-level sequence or a `SELECT … FOR UPDATE` lock on the history table during version increment to make the operation atomic.

### 8. Bulk import rollback
**Context:** The import endpoint processes rows one by one and commits incrementally. If a row fails midway through, all previously processed rows are already committed and cannot be rolled back. The response reports an error but the data is left in a partial state.
**Planned fix:** Wrap the entire import in a single transaction and roll back on the first error. Optionally support a `--strict` flag to choose between all-or-nothing and best-effort modes.

### 9. HTTPS / TLS
**Context:** miniMDM has no built-in TLS support and listens on plain HTTP. Credentials and data are transmitted in the clear.
**Decision:** miniMDM should not handle TLS directly; instead, the deployment documentation should require a reverse proxy (nginx, Caddy, or equivalent) with a valid certificate in front of the application.

---

## Production Readiness — High Priority

These issues should be addressed before the first deployment with live users.

### 10. Password reset flow
**Context:** There is no self-service password reset. If a user forgets their password, an admin must reset it manually via the user management UI. This is not viable for deployments with many users.
**Planned fix:** Implement a password reset flow — either email-based token or an admin-generated reset link.

### 11. Token revocation on logout
**Context:** JWT tokens remain valid until their expiry time even after the user logs out. If a token is stolen or an account is compromised, there is no way to immediately invalidate it short of changing `SECRET_KEY` (which invalidates all sessions).
**Planned fix:** Maintain a server-side token blocklist (in the database or a cache) that is checked on every authenticated request. Entries expire naturally after the token's TTL.

### 12. Database-level foreign key and unique constraints
**Context:** Referential integrity and uniqueness are enforced in the application layer only. Direct database access or a bug in the application can produce orphaned records or duplicates.
**Planned fix:** Add database-level `FOREIGN KEY` constraints for parent relationships and `NOT NULL` / `UNIQUE` constraints for required and unique attributes. Decide on cascade behaviour (restrict / set null) for parent deletes.

### 13. Export pagination
**Context:** Export endpoints load the entire result set into memory before streaming. On large tables this risks out-of-memory errors.
**Planned fix:** Add `limit` / `offset` query parameters to export endpoints and stream results using server-side cursors.

### 14. Structured logging with request IDs
**Context:** Logs are plain text with no correlation IDs. In production it is difficult to trace a single request through multiple log lines or aggregate logs from multiple instances.
**Planned fix:** Adopt JSON-structured logging; generate a unique request ID per request (via middleware) and include it in every log line.

### 15. Database migrations (Alembic)
**Context:** Schema changes are applied at runtime using `ALTER TABLE … ADD COLUMN IF NOT EXISTS`. There is no migration history, no rollback path, and no way to reproduce the exact database state from scratch other than running the application.
**Planned fix:** Introduce Alembic for managing `_system` schema migrations. Application-managed data tables (user schemas) will continue to be handled dynamically but system tables should be version-controlled.

### 16. Backup and restore documentation
**Context:** miniMDM stores all data in PostgreSQL. There is no built-in backup or restore functionality, and no documentation on how to back up and restore the database.
**Planned fix:** Add a `docs/backup-restore.md` guide covering `pg_dump` / `pg_restore` for full backups, point-in-time recovery considerations, and how to restore miniMDM from a backup including the `_system` schema.

---

## Open Issues

### Sorting by parent/reference columns is limited to the current page
**Context:** The record list table resolves parent and reference column values client-side using label maps. Clicking a parent or reference column header to sort would only sort the records already loaded on the current page — records on other pages would not be considered. True cross-page sorting requires a SQL JOIN to the referenced table at query time.
**Options:** (1) Client-side sort within the page — easy but potentially confusing since the sort does not apply globally. (2) Backend JOIN sort — correct behaviour across all pages but meaningfully more complex to implement.
**Decision needed:** Whether the simpler per-page sort is acceptable or whether the full JOIN-based approach is warranted.
