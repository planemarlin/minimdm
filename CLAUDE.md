# CLAUDE.md — miniMDM

## Project overview
miniMDM is a lightweight Master Data Management application. Every object type has exactly one authoritative `active` record per entity — the golden record. The draft → publish workflow governs how changes reach the golden record.

## Tech stack
- **Backend**: FastAPI + SQLAlchemy Core + PostgreSQL (psycopg2)
- **Frontend**: Jinja2 templates + vanilla JS (no build step)
- **Auth**: JWT cookies (PyJWT + bcrypt)
- **Package manager**: `uv` — always use `uv run <command>`, never `python` or `pip` directly

## Common commands
```bash
uv run uvicorn app.main:app --reload   # start dev server
uv run pytest                          # run full test suite (requires TEST_DATABASE_URL)
uv run pytest tests/browser/          # browser tests only (headless Chromium)
uv run pytest tests/browser/ --headed # browser tests with visible browser window
uv run ruff check .                    # lint
uv run ruff format .                   # format
```

Integration and browser tests are skipped unless `TEST_DATABASE_URL` is set (e.g. `postgresql://user:pass@localhost/minimdm_test`). Browser tests also require the Playwright Chromium binary — install once with `uv run playwright install chromium`.

## Git
- Remote is named `minimdm`, not `origin` — use `git push minimdm <branch>`
- PR target branch is `main`
- Commit messages follow conventional commits (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `security:`)

## Key architecture notes
- Tables are created dynamically from YAML config via `app/core/table_manager.py` — there is no static ORM model per object
- Schema config is loaded and normalized in `app/core/schema_loader.py`
- All write operations go through `app/api/objects.py`; import/export lives in `app/api/import_export.py`
- System columns (prefixed `_`) are managed by the app, not the user — e.g. `_id`, `_state`, `_created_at`, `_source_system`
- History tables mirror each object table with `_version`, `_action`, `_valid_from`, `_valid_to` columns

## Testing
- Tests live in `tests/` and use a real PostgreSQL database (no mocking the DB)
- `tests/conftest.py` defines the test app, client fixture, and `clean_records` fixture
- Test schemas are defined in `SAMPLE_CONFIG` in `conftest.py` — add new test object types there
- Browser tests live in `tests/browser/` and run a real uvicorn subprocess on port 8765; their schema is defined in `tests/browser/test_config.yaml`; add new objects there and extend `clean_browser_records` in `tests/browser/conftest.py` accordingly
