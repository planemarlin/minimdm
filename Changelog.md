# Changelog

All notable changes to miniMDM are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Column headers in record list misaligned with values when reference attributes appear in the attribute list: Jinja2 header loop now uses a namespace counter that skips references before applying the 6-column cap, matching the JavaScript rendering logic

### Added
- Upsert support for bulk import: select a key attribute in the import UI (or pass `upsert_key` to the API) to match incoming rows against existing records and update them in place instead of always inserting; the response reports inserted and updated counts separately
- "Show deleted" toggle on the record list page: displays soft-deleted records with a strikethrough style; clicking a deleted row navigates to its history page where it can be reverted
- Attribute snapshot on the history page: each version entry now shows the full set of attribute values recorded at that point in time, making it straightforward to compare versions and decide which one to revert to
- Audit log UI page at `/admin/audit`: paginated, filterable table of all changes (schema, object, action, record link, reason); accessible from the header navigation on every page
- Audit log datetime range filter: From/To datetime-local inputs allow narrowing entries to a specific time window; values are converted to UTC before querying so results match the local timestamps displayed in the table; object filter is now a cascading dropdown showing object display names
- Deleted reference indicator on the record detail page: reference fields now resolve to a display name with a link; if the referenced record has been soft-deleted the display name is shown with a red "deleted" badge instead of a link

### Added (tests)
- API integration tests covering the full CRUD lifecycle, search, pagination, soft-delete, `include_deleted` listing, history, revert (including reverting a deleted record), and all import/export formats with upsert; requires `TEST_DATABASE_URL` and is skipped otherwise
- Template rendering tests asserting that every page type returns 200, the new-record form no longer raises a 500, attribute column headers appear in config order, and the embedded `objConfig` JSON preserves insertion order

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
