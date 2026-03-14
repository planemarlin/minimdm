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

## Open Issues

No open issues at this time. New findings can be added here as they are discovered.
