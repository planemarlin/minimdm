# Changelog

All notable changes to miniMDM are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Column headers in record list misaligned with values when reference attributes appear in the attribute list: Jinja2 header loop now uses a namespace counter that skips references before applying the 6-column cap, matching the JavaScript rendering logic

### Added
- Upsert support for bulk import: select a key attribute in the import UI (or pass `upsert_key` to the API) to match incoming rows against existing records and update them in place instead of always inserting; the response reports inserted and updated counts separately

### Planned
- Historic values visible on the history page: expand each version entry to show the full attribute snapshot so users can compare versions and make informed revert decisions

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
