# Troubleshooting

## Server fails to start: `could not connect to server`

**Cause:** PostgreSQL is not running or the connection string in `.env` is incorrect.

**Solution:**
1. Verify PostgreSQL is running: `pg_isready`
2. Check `DATABASE_URL` in `.env` matches your PostgreSQL credentials and host
3. Verify the database exists: `psql -U minimdm -d minimdm -c "SELECT 1"`

---

## `FileNotFoundError: Config file not found`

**Cause:** The `CONFIG_FILE` path in `.env` does not point to an existing file.

**Solution:** Create the config file or correct the path. The default is `config/minimdm.yaml`.

---

## `ValueError: Unsupported config format`

**Cause:** The config file has an extension other than `.yaml`, `.yml`, or `.json`.

**Solution:** Rename the file to use a supported extension.

---

## Config validation errors on startup

**Cause:** A `parent` or `reference` in the config points to an object that does not exist in the same schema.

**Solution:** Check the error messages logged at startup. Ensure all `parent` and `reference` values match an object key defined in the same schema.

---

## `KeyError: Table 'schema.object' not found`

**Cause:** A request was made for an object that is not defined in the loaded config.

**Solution:** Verify the schema and object names in the URL match those in the config. Call `POST /api/config/reload` if you recently updated the config file.

---

## Import fails with encoding errors

**Cause:** The CSV/TSV file uses a non-UTF-8 encoding.

**Solution:** Convert the file to UTF-8 before importing. On Linux/macOS:

```bash
iconv -f latin1 -t utf-8 input.csv > output.csv
```

---

## Records deleted in the UI but still visible in the database

**Cause:** miniMDM uses **soft delete**. Deleted records have `_deleted_at` set and are excluded from the UI and API, but remain in the database to preserve the audit trail.

**Solution:** This is by design. To permanently remove records, delete them directly from the database and clear the related history rows.

---

## The web page shows a spinner indefinitely

**Cause:** A JavaScript error or API call failure.

**Solution:** Open the browser developer tools console (F12) and check for error messages. The API response may contain a descriptive error that the UI did not surface.

---

## `sqlalchemy.exc.ProgrammingError: schema "..." does not exist`

**Cause:** The PostgreSQL user does not have permission to create schemas, or the schema was dropped.

**Solution:** Grant the miniMDM database user the `CREATE` privilege on the database, then call `POST /api/config/reload` to recreate the schema.

```sql
GRANT CREATE ON DATABASE minimdm TO minimdm;
```
