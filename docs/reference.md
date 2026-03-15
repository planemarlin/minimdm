# Feature and API Reference

## Config File Format

miniMDM is driven by a YAML or JSON config file. Both formats are fully equivalent.

### Top-Level Structure

```yaml
minimdm:
  schemas:
    <schema_name>:
      objects:
        <object_key>:
          name: <display name>
          description: <optional description>
          parent: <object_key of parent object, optional>
          attributes:
            <attribute_key>:
              name: <display name>
              type: <string|numeric|integer|boolean|email|date>
              required: <true|false>
            <ref_attribute_key>:
              name: <display name>
              reference: <object_key of referenced object>
```

### Attribute Types

| Type | PostgreSQL column | Notes |
|---|---|---|
| `string` | `TEXT` | Default type |
| `text` | `TEXT` | Alias for string |
| `numeric` | `NUMERIC` | Decimal numbers |
| `integer` | `INTEGER` | Whole numbers |
| `boolean` | `BOOLEAN` | true/false |
| `email` | `TEXT` | Stored as text; type hint for UI |
| `date` | `TIMESTAMP WITH TIME ZONE` | ISO 8601 format |

### Parent Relationships

Setting `parent: <object_key>` adds a `_{parent}_id` UUID column to the table. Use this to model hierarchical structures (e.g., division belongs to company).

### Cross-Object References

Use `reference: <object_key>` instead of `type` to create a foreign-key style link. The column stored is `{attribute_key}_id` (UUID). The UI renders a dropdown populated from the referenced object.

## System Columns

Every object table includes these system-managed columns (not in the config):

| Column | Type | Description |
|---|---|---|
| `_id` | UUID | Primary key |
| `_created_at` | TIMESTAMPTZ | Record creation time |
| `_updated_at` | TIMESTAMPTZ | Last update time |
| `_created_by` | TEXT | Username of the authenticated user who created the record |
| `_deleted_at` | TIMESTAMPTZ | Soft-delete timestamp |

## History Tables

For every object `{schema}.{obj}`, a history table `{schema}.{obj}_history` is created automatically with these extra columns:

| Column | Description |
|---|---|
| `_history_id` | History row primary key |
| `_version` | Version number (1, 2, 3…) |
| `_valid_from` | When this version became active |
| `_valid_to` | When this version was superseded (NULL = current) |
| `_changed_at` | Timestamp of the change |
| `_changed_by` | User who made the change |
| `_change_reason` | Optional reason string |
| `_action` | INSERT / UPDATE / DELETE / REVERT |

## Audit Log

All changes are recorded in `_system.audit_log`:

| Column | Description |
|---|---|
| `id` | UUID |
| `timestamp` | UTC timestamp |
| `user_name` | Authenticated username; `LOGIN` / `LOGIN_FAILED` / `LOGOUT` for auth events |
| `schema_name` | Schema of the changed object |
| `object_name` | Object key |
| `record_id` | UUID of the changed record |
| `action` | INSERT / UPDATE / DELETE / REVERT |
| `old_values` | JSON snapshot before change |
| `new_values` | JSON snapshot after change |
| `reason` | Optional reason provided by the user |
| `ip_address` | Client IP address |

## Authentication

All routes require authentication. The web UI uses an httpOnly cookie (`access_token`) set at login. API clients should pass `Authorization: Bearer <token>` on every request.

Tokens are JWTs signed with `SECRET_KEY` and expire after `TOKEN_EXPIRE_HOURS` (default: 24 hours).

On first startup, if no users exist, an admin account is created automatically from `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables (defaults: `admin` / `admin`). **Change the default password immediately after first login.**

## REST API Endpoints

### Auth

| Method | Path | Auth required | Description |
|---|---|---|---|
| `POST` | `/api/auth/login` | No | Log in with `{"username": "…", "password": "…"}`; returns username and sets cookie |
| `POST` | `/api/auth/logout` | No | Clear the session cookie |
| `GET` | `/api/auth/me` | Yes | Return the current user's username and `is_admin` flag |

### User Management (Admin only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin/users` | List all users |
| `POST` | `/api/admin/users` | Create a user (`{"username", "password", "is_admin"}`) |
| `PATCH` | `/api/admin/users/{user_id}` | Update a user (`is_admin`, `is_active`, `password`; any combination) |
| `GET` | `/api/admin/users/{user_id}/permissions` | List schema permissions for a user |
| `PUT` | `/api/admin/users/{user_id}/permissions/{schema_name}` | Grant or update access (`{"can_read": true, "can_write": false}`) |
| `DELETE` | `/api/admin/users/{user_id}/permissions/{schema_name}` | Revoke all access to a schema |

### Schema-Based Access Control

Non-admin users have **no access** to any schema unless explicitly granted. Admins always have full access.

| Permission | Effect |
|---|---|
| `can_read: true` | User can list records, get individual records, view history, export, and call `GET /api/schemas/{schema}` |
| `can_write: true` | User can additionally create, update, delete, revert, and import records |

Grants are managed in the User Management UI (`/admin/users`) via the inline permissions panel, or directly through the API.

### Records

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/records/{schema}/{obj}` | List records (paginated, searchable) |
| `POST` | `/api/records/{schema}/{obj}` | Create record |
| `GET` | `/api/records/{schema}/{obj}/{id}` | Get single record |
| `PUT` | `/api/records/{schema}/{obj}/{id}` | Update record |
| `DELETE` | `/api/records/{schema}/{obj}/{id}` | Soft-delete record |
| `GET` | `/api/records/{schema}/{obj}/{id}/history` | Get version history |
| `POST` | `/api/records/{schema}/{obj}/{id}/revert/{version}` | Revert to version |

### Import / Export

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/records/{schema}/{obj}/export` | Export (`?format=csv\|tsv\|json`) |
| `POST` | `/api/records/{schema}/{obj}/import` | Import (`?format=csv\|tsv\|json`; optional `?upsert_key=<attr>`) |

### Schemas

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/schemas` | List all schemas |
| `GET` | `/api/schemas/{schema}` | Get schema details |
| `GET` | `/api/schemas/{schema}/objects/{obj}` | Get object definition |
| `GET` | `/api/config` | Get current loaded config |
| `POST` | `/api/config/reload` | Reload config from disk |

### Audit

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/audit` | Query audit log (filterable by schema, object, action, time range) |

### Query Parameters (Audit Log)

| Parameter | Default | Description |
|---|---|---|
| `schema` | — | Filter by schema name (use `_system` for auth events) |
| `obj` | — | Filter by object key within the schema |
| `action` | — | Filter by action: `INSERT`, `UPDATE`, `DELETE`, `REVERT`, `LOGIN`, `LOGIN_FAILED`, `LOGOUT` |
| `from_time` | — | ISO 8601 datetime — include entries at or after this time |
| `to_time` | — | ISO 8601 datetime — include entries at or before this time |
| `exclude_system` | `false` | When `true`, omit entries from system schemas (schema name starts with `_`) |
| `page` | 1 | Page number |
| `page_size` | 100 | Entries per page (max 1000) |

### Query Parameters (List Records)

| Parameter | Default | Description |
|---|---|---|
| `page` | 1 | Page number |
| `page_size` | 50 | Records per page (max 500) |
| `search` | — | Full-text search across string columns |
| `include_deleted` | false | Include soft-deleted records in the results |

### Query Parameters (Import)

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | File format: `csv`, `tsv`, or `json` |
| `upsert_key` | — | Attribute key to match against existing records. If a non-deleted record with the same value exists, it is updated in place; otherwise a new record is inserted. |
| `reason` | — | Audit note attached to every inserted or updated record |

### Record Body Format

When creating or updating a record, send a JSON object with attribute keys as field names. Use `_reason` to attach an audit note:

```json
{
  "code": "ABC",
  "name": "Alpha Corp",
  "_reason": "Correcting typo in name"
}
```

For reference attributes, use `{attribute_key}_id` with the UUID of the referenced record.
