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

## Open Issues

### Column names do not match values in the record list table
**Status:** Fixed in 0.1.2
**Root cause:** The Jinja2 header loop used `loop.index <= 6` which counted all attributes (including references) toward the 6-column cap, while the JavaScript filtered out references before slicing. Fixed by using a Jinja2 namespace counter that increments only for non-reference attributes.

### Deleted records are not browsable from the UI
**Status:** Fixed (implemented "Show deleted" toggle)
**Root cause:** The record list API filtered out soft-deleted records and there was no UI path to reach their history. Fixed by adding an `include_deleted` query parameter to the list API and a "Show deleted" checkbox to the record list toolbar. Deleted rows are shown with strikethrough styling and link to their history page.

### A referenced record's ID still shows after the referenced record is deleted
**Status:** Fixed
**Description:** If a Manager is assigned to a Cost Center and the Manager record is later deleted, the Cost Center detail page now resolves the reference at display time. Active references show a clickable display name; deleted references show the display name with a red "deleted" badge. The single-record GET API was extended with `include_deleted=true` to support this lookup.

### Numeric fields accept non-numeric input without a visible error message
**Status:** Fixed
**Description:** Client-side validation now runs before submission. Invalid number inputs are highlighted with a red border and a field-level error message ("Must be a whole number." / "Must be a valid number."). Integer fields also receive `step="1"` so the browser's native number picker enforces whole numbers. Server-side 422 validation error arrays are now formatted into a readable sentence instead of `[object Object]`.

### Viewing the parent record inline in the detail view
**Status:** Partially fixed (parent is now shown with a link)
**Description:** The detail view shows a link to the parent record but does not display the parent's full data inline. The requirements specify that multiple related objects should be visible simultaneously (read-only), with only one editable at a time.
**Planned fix:** Add a collapsible "related objects" panel in the detail view.

### History page does not show historic attribute values
**Status:** Implemented
**Description:** Each version entry on the history page now shows the full attribute snapshot recorded at that point, making it easy to compare versions before reverting.

### Audit log has no dedicated UI page
**Status:** Implemented
**Description:** `/admin/audit` provides a paginated, filterable table of all audit log entries. Accessible from the "Audit Log" link in the header navigation on every page.
