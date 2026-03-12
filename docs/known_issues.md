# Known Issues

This document tracks confirmed bugs and design limitations found during testing.
Issues marked **Fixed** are resolved in the current codebase.

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

## Open Issues

### Column names do not match values in the record list table
**Status:** Fixed in 0.1.2
**Root cause:** The Jinja2 header loop used `loop.index <= 6` which counted all attributes (including references) toward the 6-column cap, while the JavaScript filtered out references before slicing. Fixed by using a Jinja2 namespace counter that increments only for non-reference attributes.

### Deleted records are not browsable from the UI
**Status:** Design limitation / future work
**Description:** Records are soft-deleted (`_deleted_at` is set) and their full history is preserved in the `_history` table and audit log. However, once a record is deleted it no longer appears in the object list, and the only way to reach its history page is to know its UUID directly.
**Workaround:** Query the audit log API (`GET /api/audit?schema=…&obj=…&action=DELETE`) to find the UUID, then open `/api/records/{schema}/{obj}/{id}/history` directly.
**Planned fix:** Add a "Show deleted" toggle to the record list page.

### A referenced record's ID still shows after the referenced record is deleted
**Status:** Cosmetic / future work
**Description:** If a Manager is assigned to a Cost Center and the Manager record is later deleted, the Cost Center detail page still shows the UUID of the deleted manager (since the FK column is not cleared on soft-delete).
**Planned fix:** Resolve references at display time and show a "deleted" indicator when the referenced record has `_deleted_at` set.

### Numeric fields accept non-numeric input without a visible error message
**Status:** Known limitation
**Description:** HTML `type="number"` inputs prevent non-numeric characters in most browsers but the error state is not styled, and some browsers may be more permissive. Server-side, PostgreSQL will reject invalid values but the error message surfaced in the UI is generic.
**Planned fix:** Add explicit client-side validation with styled error messages, and improve server-side error response formatting.

### Viewing the parent record inline in the detail view
**Status:** Partially fixed (parent is now shown with a link)
**Description:** The detail view shows a link to the parent record but does not display the parent's full data inline. The requirements specify that multiple related objects should be visible simultaneously (read-only), with only one editable at a time.
**Planned fix:** Add a collapsible "related objects" panel in the detail view.

### History page does not show historic attribute values
**Status:** Future work
**Description:** The history page lists versions with their action, timestamp, and optional reason, but does not display the actual attribute values for each snapshot. Without visible values (or a reason comment) it is difficult to decide which version to revert to.
**Planned fix:** Expand each version entry on the history page to show the full attribute snapshot for that version.

### Audit log has no dedicated UI page
**Status:** Future work
**Description:** The audit log is accessible via `GET /api/audit` but there is no web page for browsing it.
**Planned fix:** Add an `/admin/audit` page.
