# CLAUDE.md — miniMDM

## Project overview
miniMDM is a lightweight Master Data Management application. Every object type has exactly one authoritative `active` record per entity — the golden record. The draft → publish workflow governs how changes reach the golden record.

## Tech stack
- **Backend**: FastAPI + SQLAlchemy Core + PostgreSQL (psycopg2), Python 3.11+
- **Frontend**: Jinja2 templates + vanilla JS (no build step)
- **Auth**: JWT cookies (PyJWT + bcrypt)
- **Validation rules**: Cerberus, configured per attribute in the YAML schema
- **Package manager**: `uv` — always use `uv run <command>`, never `python` or `pip` directly

## Common commands
```bash
uv run uvicorn app.main:app --reload   # start dev server
uv run pytest                          # run full test suite (requires TEST_DATABASE_URL)
uv run pytest --ignore=tests/browser   # API, unit and template tests only (what CI's "Test" job runs)
uv run pytest tests/browser/          # browser tests only (headless Chromium)
uv run ruff check .                    # lint (CI runs this)
uv run ruff format .                   # format
```

`TEST_DATABASE_URL` must be set in the environment (shell profile, direnv, or inline before the command) and point at a dedicated test database, never the development one. It is read from `os.environ`, **not** from `.env`, so a `.env` entry is silently ignored. Without it, integration and browser tests are skipped rather than failed, so a "green" run with many skips means it was not set. Browser tests also require the Playwright Chromium binary — install once with `uv run playwright install chromium`. See `docs/testing.md` for setup details.

CI additionally runs `pip-audit` on the dependencies and runs the non-browser tests on both Python 3.11 and 3.12 (browser tests run on one version).

## Git
- **Before editing any file for a task, create a feature branch first — never edit directly on `main` or on an old/stale branch.** Run `git branch --show-current` as your first action; if it's `main` (or a branch you didn't just create for this task), run `git fetch minimdm && git checkout -b <branch> minimdm/main` before making any Edit/Write call. This applies even to small changes and even mid-session after a `/clear`.
- Branch naming: `fix/...`, `feat/...`, `test/...`, `chore/...`, `docs/...`, `security/...` matching the conventional-commit type
- Remote is named `minimdm`, not `origin`. Push with an explicit upstream: `git push -u minimdm <branch>` — a branch cut from `minimdm/main` otherwise tracks `main`
- PR target branch is `main`
- Commit messages follow conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `security:`)
- **PR labels are part of creating the PR**: run `gh label list` and pass `--label` to `gh pr create`. Never create an unlabeled PR and add labels afterwards.
- **Never pass multi-line commit messages, PR bodies or issue comments inline via a heredoc.** A heredoc nested inside `$(...)` (the usual `--body "$(cat <<'EOF' ...)"` pattern) has executed backticks in the text as command substitution here (macOS bash 3.2), even with a quoted delimiter. Write the text to a file in the scratchpad first, then use `git commit -F <file>`, `gh pr create --body-file <file>` or `gh issue comment --body-file <file>`.
- If a chained shell command fails with a parse error, none of it ran. Re-check `git status` / `git diff --cached` before retrying instead of assuming the earlier parts succeeded.

## Definition of done
- Tests pass (`uv run pytest`, including `tests/browser/` for UI changes) and `uv run ruff check .` is clean. New behaviour and bug fixes come with tests.
- Add a line under `[Unreleased]` in `Changelog.md`. Released entries are a logbook and are not rewritten, so make each one self-contained and cite issue or PR numbers, not an entry in `docs/known_issues.md` that will be deleted once it is resolved.
- Update every doc surface the change touches: `docs/reference.md` (API and config contract), `docs/quickstart.md` / `docs/testing.md` where relevant, `README.md` for user-facing features, **and** the in-app Quick Reference (the `#help-modal` in `app/templates/base.html`, one `.help-card` per topic). The last one is easy to miss because it is not under `docs/`.
- `docs/known_issues.md` holds only open items: deliberate design decisions, and known bugs or limitations we do not plan to fix before the next release. A bug fix does **not** get an entry there; the `Changelog.md` line is its record. When a listed item is resolved, delete it from `known_issues.md` in the same change. Ideas and planned features do not go there; ask the user where to record them.
- Commit outcomes, not process: don't commit design or planning documents. Put the user-facing contract in `docs/reference.md` and the rationale for a deliberate decision in the Design Decisions section of `docs/known_issues.md`.

## Key architecture notes
- Tables for objects are created dynamically from YAML config via `app/core/table_manager.py` (`sync_schema()`) — there is no static ORM model per object. The fixed system tables (users, permissions, `inbound_keys`, `audit_log`) are managed by Alembic migrations in `alembic/versions/`, run at startup by `app/core/migrations.py`
- Schema config is loaded and normalized in `app/core/schema_loader.py`; the real config files (`config/minimdm.yaml`, `config/minimdm.json`) are git-ignored, only `config/minimdm.example.yaml` is tracked
- **Record writes are not in one place.** `app/api/objects.py` handles interactive create/update/delete/publish/retire/revert; `app/api/import_export.py` has its own insert/update paths for bulk import and upsert; `app/api/inbound.py` (`POST /api/inbound/{schema}/{obj}`, authenticated with hashed keys from `_system.inbound_keys`) writes through `_inbound_upsert` in `import_export.py`. A change to write rules (history, audit, validation, webhooks) must be applied to all of them
- Editing an `active` record creates a draft copy (`_state = 'draft'`, `_draft_of_id` pointing at the golden record); publishing applies the draft's data to the golden record and soft-deletes the draft. Unique constraints apply only to `active`, non-deleted rows so drafts can share values
- System columns (prefixed `_`) are managed by the app, not the user — e.g. `_id`, `_state`, `_created_at`, `_updated_at`, `_created_by`, `_deleted_at` (soft delete), `_draft_of_id`, `_source_system`, `_source_id`, `_validation_status`
- History tables mirror each object table with `_version`, `_action`, `_valid_from`, `_valid_to`, `_changed_at`, `_changed_by` and `_change_reason` columns
- Other building blocks: `app/core/permissions.py` (per-user, per-schema access with `can_publish`), `app/core/validation.py` (Cerberus rules, `_validation_status` is computed from them), `app/core/webhooks.py` (outbound events on create/publish/retire), `app/core/audit.py` (`_system.audit_log`)

## Testing
- Tests live in `tests/` and use a real PostgreSQL database (no mocking the DB)
- `tests/conftest.py` defines the test app, client fixture, and `clean_records` fixture
- Test schemas are defined in `SAMPLE_CONFIG` in `conftest.py` — add new test object types there
- The `client` fixture is session-scoped: never write a test that reloads the config or otherwise mutates app-wide state, it breaks every test that runs after it
- Browser tests live in `tests/browser/` and run a real uvicorn subprocess on port 8765 (hardcoded as `_TEST_PORT` in `tests/browser/conftest.py`, no environment override, so the port must be free and two browser test sessions can't run side by side); their schema is defined in `tests/browser/test_config.yaml`; add new objects there and extend `clean_browser_records` in `tests/browser/conftest.py` accordingly
- Browser tests only log in as the admin, so per-role behaviour is covered by API tests (`tests/test_api_permissions.py` and friends)
- Playwright pitfalls (CSP-blocked `wait_for_function`, ambiguous button text, `display:none` action buttons, stale DOM after reload) are listed in `docs/testing.md` under "Writing browser tests: gotchas" — read it before writing a browser test
