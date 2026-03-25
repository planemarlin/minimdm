# Backup and Restore

miniMDM stores all data in PostgreSQL. There is no built-in backup functionality — backups are handled at the database level using standard PostgreSQL tools.

---

## What to back up

All miniMDM data lives in two places:

| Location | Contents |
|---|---|
| PostgreSQL — `_system` schema | Users, permissions, audit log |
| PostgreSQL — user-defined schemas | All data objects, their records, and history tables |
| Filesystem — `.env` | Application secrets and configuration |
| Filesystem — `config/minimdm.yaml` | Schema and object definitions |

The database contains everything needed to restore a running instance. The config file is also important — without it miniMDM will start with an empty schema on the next reload.

---

## Full database backup

Use `pg_dump` to create a compressed backup of the entire miniMDM database:

```bash
pg_dump \
  --host localhost \
  --port 5432 \
  --username minimdm \
  --format custom \
  --compress 9 \
  --file minimdm_$(date +%Y%m%d_%H%M%S).dump \
  minimdm
```

`--format custom` produces a binary file that supports selective restore and parallel jobs. It is smaller than plain SQL and the recommended format for production backups.

To include the password non-interactively, set `PGPASSWORD` or use a [`.pgpass` file](https://www.postgresql.org/docs/current/libpq-pgpass.html).

---

## Restore from a full backup

```bash
# Create a clean target database first
createdb --host localhost --username postgres minimdm_restored

# Restore
pg_restore \
  --host localhost \
  --port 5432 \
  --username minimdm \
  --dbname minimdm_restored \
  --no-owner \
  --role minimdm \
  minimdm_20240101_120000.dump
```

Point miniMDM at the restored database by updating `DATABASE_URL` in `.env`, then restart.

---

## Docker deployments

When running with Docker Compose, the database lives in the `postgres_data` named volume. Back it up by running `pg_dump` inside the container:

```bash
docker compose exec postgres pg_dump \
  -U minimdm \
  --format custom \
  --compress 9 \
  minimdm > minimdm_$(date +%Y%m%d_%H%M%S).dump
```

Restore into a running container:

```bash
cat minimdm_20240101_120000.dump | docker compose exec -T postgres pg_restore \
  -U minimdm \
  --dbname minimdm \
  --no-owner \
  --clean
```

> **Warning:** `--clean` drops and recreates objects before restoring. Do not run this against a live database with active users.

---

## Automating backups

A simple cron job that keeps 7 daily backups:

```bash
# /etc/cron.d/minimdm-backup
0 2 * * * minimdm pg_dump -U minimdm --format custom --compress 9 minimdm \
  > /var/backups/minimdm/minimdm_$(date +\%Y\%m\%d).dump \
  && find /var/backups/minimdm -name "*.dump" -mtime +7 -delete
```

For Docker deployments, replace the `pg_dump` call with the `docker compose exec` form shown above.

Consider also backing up:
- The `.env` file (contains `SECRET_KEY` — needed to verify existing JWTs after a restore)
- The `config/minimdm.yaml` file

Store backups off-site (S3, object storage, remote server) so a disk failure does not take both the database and the backups.

---

## Verifying a backup

Always verify that a backup can be restored before relying on it in an emergency:

```bash
# Restore into a temporary database
createdb minimdm_verify
pg_restore --dbname minimdm_verify --no-owner minimdm_20240101_120000.dump

# Run a quick sanity check
psql minimdm_verify -c "SELECT COUNT(*) FROM _system.users;"
psql minimdm_verify -c "SELECT COUNT(*) FROM _system.audit_log;"

# Clean up
dropdb minimdm_verify
```

---

## Point-in-time recovery (PITR)

For production deployments where data loss of more than a few minutes is unacceptable, consider enabling PostgreSQL Write-Ahead Log (WAL) archiving. PITR allows restoring the database to any point in time between backups, down to the individual transaction.

PITR configuration is outside the scope of this guide. See the [PostgreSQL documentation on continuous archiving](https://www.postgresql.org/docs/current/continuous-archiving.html) for details.
