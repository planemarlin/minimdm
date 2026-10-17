# Known Issues

Design decisions that are deliberate, and open issues that are not fixed yet. Anything resolved is recorded in [Changelog.md](../Changelog.md) and does not stay here.

---

## Design Decisions

### Sorting on parent and reference columns is not supported
**Decision:** Parent and reference column headers are intentionally non-sortable. These values are resolved from other tables client-side; a correct global sort would require a SQL JOIN per relationship at query time, adding significant complexity for limited benefit. Sort on the underlying data attributes instead. This is documented in [reference.md](reference.md).

### Validation rules: allowed-value lists and reference-state checks are deferred
**Decision:** The v0.8.0 config-based [validation rules](reference.md#validation-rules) feature deliberately does not cover two rule shapes from the original catalog:
- **A fixed allowed-value list per attribute** (e.g. `industry: [Manufacturing, Retail, Logistics]`). Cerberus supports this natively (`allowed: [...]`), but miniMDM's config has no enum concept today — an attribute only supports `name`/`type`/`required`/`unique`/`reference`. `reference` already renders as a dropdown in `app/static/js/app.js`, but that links to *another object's records*, not a fixed list of literal values. Building this properly needs a new schema-loader config key plus a matching UI change to render it as a dropdown — a schema-loader + frontend feature, not just a validator addition, so it's scoped as separate future work rather than bundled in.
- **Referenced-record state checks** (e.g. a product's `preferred_supplier` must be `active`). Architecturally distinct from every other validation rule: it requires fetching a *different* record from the database mid-validation, which neither Cerberus nor JSON Schema do natively (both validate a single document in isolation). A different implementation shape from same-record rules entirely — likely a later phase, not decided when.

Neither is scheduled to a version yet.

### In-place changes to golden records outside draft → publish
**Decision (v0.8.0):** Reverting an *active* (golden) or *retired* record, and editing a *retired* record, rewrite the record directly rather than going through a draft. Rather than let any Editor do that, these now require Publisher (the same rule reverting a retired record already had). Found by the pre-v0.8.0 security review.

**Future feature (not scheduled):** route these through draft-copy like an ordinary edit — a revert on an active record would create (or update) a draft carrying the historical values, and a Publisher promotes it — so Editors keep revert and the Publisher still approves the result. Related in-place paths to consider at the same time: soft-delete of an active record by an Editor (documented Editor capability today), and an upsert import as `active` (already Publisher-only).

### Default secrets are logged and documented, not enforced
**Decision:** With the placeholder `SECRET_KEY` still in place, miniMDM logs an `ERROR` at startup ("JWTs can be trivially forged") and keeps running, rather than refusing to start. Failing fast would break the zero-configuration local and Docker quickstarts for the sake of a situation that is already loudly reported in the server log and listed in the pre-launch checklist in [deployment.md](deployment.md#security-checklist-before-going-live). Changing `SECRET_KEY` and `ADMIN_PASSWORD` before exposing an instance is the operator's responsibility. Recorded by the pre-v0.8.0 security review.

---

## Open Issues

### Security review findings deferred from the pre-v0.8.0 review

Low-severity items found by the pre-v0.8.0 full-project security review and deliberately not fixed in that release. None is exploitable on its own; they are hardening opportunities.

- **`POST /api/auth/reset-password` returns 500 on a non-object JSON body** (e.g. a JSON array), and has no rate limit of its own (login is limited to 10/minute). Reset tokens are 256-bit random values, so guessing is not feasible; the 500 is a robustness issue only. Same unvalidated `await request.json()` pattern exists in the admin user endpoints.
- **Password reset tokens are stored in plaintext** in `_system.password_reset_tokens`. Someone with database read access could use an unused token, but database access already exposes everything else. Hashing them (as inbound API keys are) would be cheap defence in depth.
- **`GET /api/audit` relies solely on the auth middleware.** If `current_user` were ever `None` the handler applies no schema filter instead of denying. The middleware guarantees this cannot happen today.
- **Webhook SSRF guard is incomplete.** `_is_private_ip` in `app/core/schema_loader.py` only inspects IP *literals*, at config-load time: hostnames (including `localhost`), `0.0.0.0`, `::ffff:`-mapped IPv4 and `100.64.0.0/10` are not rejected, and it is not covered by any test. Webhook URLs come from the operator-controlled config file, so this is a misconfiguration guard, not a boundary against untrusted input.
- **`/docs`, `/redoc` and `/openapi.json` are public** (no authentication) so the full API surface can be read anonymously. Set-up is documented; consider gating them in production.
- **Inbound endpoint answers 404 for an unknown object before checking the API key**, so an unauthenticated caller can probe which `schema/object` names exist.
- **`override_reason` / `_reason` have no length limit.** Bounded in practice by the URL/body size limits, but they are written verbatim to the audit log.
- **CSP still allows `'unsafe-inline'` for scripts and styles** (tracked separately in the roadmap as the inline-script extraction backlog item).

### Dependabot alerts and the Docker image

- **The Docker image installs the `dev` dependency group** (the `Dockerfile` runs `uv export --frozen --no-emit-project` without `--no-dev`), so dev-only packages — including `urllib3`/`requests` via `pytest-playwright` — are present in the image although the app never imports them. This is deliberate: the full test suite is run inside the image against the compose database. If a slimmer production image is wanted, add `--no-dev` to the `uv export` and run Docker tests from a separate build target.

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

### Export builds the whole result in memory

`GET /api/records/{schema}/{obj}/export` accepts `limit` and `offset` (see [reference.md](reference.md)), but each request reads its rows into memory and builds the file as one string before sending it, so exporting a very large object without `limit` uses memory proportional to the object's size. Export in batches with `limit` and `offset` until then. Streaming the response row by row is not planned yet.

### Mobile and narrow-window layout is not yet usable

The interface is designed for desktop-width windows, and below 768px it does not behave as you would expect. For example, the sidebar is hidden with no way to open it, so the object pages cannot be reached, and the top bar wraps its labels onto two lines ("Audit Log" breaks in two). The mobile and narrow-window layout will be reviewed and updated in a future release.
