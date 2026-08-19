# Upgrading

miniMDM is upgraded by pulling newer source code and restarting — there's no separate installer, package manager, or (yet) a published container image. This applies to both deployment modes documented in this project ([installation.md](installation.md) and [docker-setup.md](docker-setup.md)); the two differ only in how you rebuild after pulling.

---

## Before you upgrade

1. **Read the [Changelog](../Changelog.md)** for every version between what you're running and the version you're upgrading to. Note anything that mentions a new required environment variable or a breaking change.
2. **Back up the database.** See [backup-restore.md](backup-restore.md) for `pg_dump` commands (native and Docker). Do this even for patch releases — migrations are not designed to be reversed in normal operation.
3. **Check for local edits to tracked files.** `.env`, `config/minimdm.yaml`, and `docker-compose.override.yml` are gitignored and meant to be edited locally — pulling a new version never touches them. Anything else you've hand-edited (most commonly `docker-compose.yml`) can conflict with the upgrade; see the callout near the bottom of this page if that applies to you.

---

## Get the new version

Pick a specific release tag rather than tracking a moving branch, so you always know exactly what's deployed:

```bash
git fetch --tags
git checkout vX.Y.Z   # see https://github.com/planemarlin/minimdm/releases for available tags
```

No git available? Download the "Source code (zip)" or "(tar.gz)" asset from the same release page and extract it over your existing installation directory. Everything gitignored — `.env`, `config/minimdm.yaml`, `docker-compose.override.yml`, and of course the database itself — lives outside the archive, so extracting over the top is safe either way.

> miniMDM doesn't currently publish a versioned container image to a registry (e.g. GHCR) — Docker deployments also build from source, as shown below. A published image is a possible future addition; see [known_issues.md](known_issues.md).

---

## Bare-metal / systemd

```bash
git fetch --tags && git checkout vX.Y.Z
uv sync
```

Migrations run automatically the next time the app starts (see [migrations.md](migrations.md)) — there's nothing to run manually. Restart the process:

```bash
sudo systemctl restart minimdm   # if running as a systemd service
```

or re-run the `uvicorn` command yourself if you start it manually.

---

## Docker Compose

```bash
git fetch --tags && git checkout vX.Y.Z
docker compose build
docker compose up -d
```

The `app` container runs migrations automatically on startup, same as bare-metal. `docker compose build` picks up any `Dockerfile` or dependency changes; if a release touches neither, `docker compose up -d --force-recreate app` is enough.

### Keeping local customizations across upgrades

`docker-compose.yml` is tracked in the repo so that upgrades — bug fixes, new services, healthcheck changes — apply cleanly with a plain `git checkout`. Don't edit it directly for local tweaks; anything changed there will conflict with the next upgrade, the same way editing `config/minimdm.example.yaml` instead of `config/minimdm.yaml` would. Two supported ways to customize instead:

1. **Environment variables**, for anything already parameterized. Host ports are the common case: `APP_PORT` (default `8000`) and `POSTGRES_PORT` (default `5432`). Set them in `.env`:

   ```env
   APP_PORT=8001
   POSTGRES_PORT=5433
   ```

2. **`docker-compose.override.yml`**, for anything not covered by an environment variable — extra volumes, resource limits, additional services. Compose merges it automatically; no flags needed. It's gitignored, so it survives every future upgrade untouched. This is [Docker Compose's own standard mechanism](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge/) for host-specific overrides — nothing miniMDM-specific about how it works, beyond which values are already exposed as env vars above.

### If you already edited docker-compose.yml directly

If you customized `docker-compose.yml` before this pattern existed — most commonly a changed port mapping — git will refuse to fast-forward, or will report a conflict on that file, the next time you try to upgrade. To move to the parameterized version without losing your customization or hand-merging anything:

```bash
git diff docker-compose.yml   # note what you changed — usually just a ports line
git checkout -- docker-compose.yml
git fetch --tags && git checkout vX.Y.Z
```

Then re-apply the same customization the new way: set the equivalent variable in `.env` (e.g. `APP_PORT=8001` if you'd changed the app's `ports` mapping to `"8001:8000"`), or add it to `docker-compose.override.yml` if it isn't one of the parameterized values. `docker compose up -d` picks it up on the next start — no further edits to `docker-compose.yml` needed, this upgrade or any future one.

---

## Rolling back

If something goes wrong after an upgrade:

```bash
git checkout v<previous-version>
uv sync                      # or: docker compose build
```

then restore the database from the backup taken before upgrading — migrations may have changed the schema in ways the older code doesn't expect, so restarting on the old tag alone is not sufficient once a migration has run. `alembic downgrade -1` (see [migrations.md](migrations.md)) can reverse the most recent `_system`-schema migration, but a full restore from backup is the safer option if you're unsure how far to roll back.
