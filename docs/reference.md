# Feature and API Reference

## Config File Format

miniMDM is driven by a YAML or JSON config file. Both formats are fully equivalent.

### Top-Level Structure

```yaml
minimdm:
  webhooks:
    - event: record.created
      url: https://example.com/hooks/minimdm
    - event: record.published
      url: https://example.com/hooks/minimdm
    - event: record.retired
      url: https://example.com/hooks/minimdm
  schemas:
    <schema_name>:
      objects:
        <object_key>:
          name: <display name>
          description: <optional description>
          parent: <object_key of parent object, optional>
          require_change_reason: <true|false>
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

### Object-Level Flags

| Flag | Type | Description |
|---|---|---|
| `require_change_reason` | `true`/`false` | When `true`, a non-empty `_reason` is required on every create, update, delete, revert, publish, and retire operation. The API returns HTTP 422 if the reason is missing. The UI marks the Reason field as required with a red asterisk. |

Example:

```yaml
objects:
  product:
    name: Product
    require_change_reason: true
    attributes:
      code:
        name: Code
        type: string
```

### Webhooks

miniMDM can notify external systems when lifecycle transitions occur. Webhooks are configured at the top level of the config file (not per-schema):

```yaml
minimdm:
  webhooks:
    - event: record.created
      url: https://example.com/hooks/minimdm
    - event: record.published
      url: https://example.com/hooks/minimdm
    - event: record.retired
      url: https://example.com/hooks/minimdm
```

Three events are supported:

| Event | Triggered when |
|---|---|
| `record.created` | A new record is created (always as `active`) |
| `record.published` | A draft is promoted to active via the publish endpoint |
| `record.retired` | An active record is transitioned to retired |

Note: `record.created` and `record.published` are distinct events. `record.created` fires when a brand-new record is created directly as active. `record.published` fires when a draft goes through the review-and-approve flow. Editing an existing record creates a draft copy — no webhook fires for draft creation.

**Payload** sent as JSON via HTTP POST:

```json
{
  "event": "record.published",
  "schema": "nordkraft",
  "object": "product",
  "record_id": "<uuid>",
  "triggered_by": "alice",
  "timestamp": "2026-05-01T10:00:00Z"
}
```

Webhooks are delivered asynchronously after the API response is sent, so a slow or unreachable endpoint never delays the caller. Failures are logged as warnings and silently swallowed — the API response is unaffected. Multiple URLs can be configured for the same event. The same URL can appear for multiple events; use the `event` field in the payload to distinguish them.

## System Columns

Every object table includes these system-managed columns (not in the config):

| Column | Type | Description |
|---|---|---|
| `_id` | UUID | Primary key |
| `_created_at` | TIMESTAMPTZ | Record creation time |
| `_updated_at` | TIMESTAMPTZ | Last update time |
| `_created_by` | TEXT | Username of the authenticated user who created the record |
| `_deleted_at` | TIMESTAMPTZ | Soft-delete timestamp |
| `_state` | TEXT | Lifecycle state: `active`, `draft`, or `retired` |
| `_draft_of_id` | UUID | For draft records only: UUID of the master active record this draft was copied from |

## Lifecycle States

Every record has a `_state` field that controls its visibility and transitions:

| State | Description |
|---|---|
| `active` | The live, published record. Returned by default on all list and export calls. |
| `draft` | A pending version of an active record. Invisible to normal consumers until published. Editing an active record creates a draft copy instead of modifying the active record in place. |
| `retired` | A record that is no longer in use. Excluded from default responses but still queryable. |

**Transitions:**
- `POST ./{id}/publish` — promotes a `draft` to `active` (copies draft data onto the master record, soft-deletes the draft). Requires Publisher or Admin.
- `POST ./{id}/retire` — transitions an `active` record to `retired`. Requires Publisher or Admin.

The `active` record is never touched directly when you edit it — a `draft` copy is created instead. This means API consumers always see the stable active record while changes are being prepared.

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
| `_state` | Lifecycle state at the time of this history entry |
| `_action` | `INSERT` / `UPDATE` / `DELETE` / `REVERT` / `PUBLISH` / `RETIRE` |

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
| `action` | `INSERT` / `UPDATE` / `DELETE` / `REVERT` / `PUBLISH` / `RETIRE` |
| `old_values` | JSON snapshot before change |
| `new_values` | JSON snapshot after change |
| `reason` | Optional reason provided by the user |
| `ip_address` | Client IP address |

## Authentication

All routes require authentication. The web UI uses an httpOnly cookie (`access_token`) set at login. API clients should pass `Authorization: Bearer <token>` on every request.

## Browser storage

miniMDM stores the following data in the browser:

| Storage | Key | Value | Purpose |
|---|---|---|---|
| Cookie (`httpOnly`) | `access_token` | JWT authentication token | Maintains the login session. Set on login, cleared on logout. Required for the application to function — no consent banner is shown since this is a strictly necessary cookie under EU ePrivacy rules. The cookie carries the `Secure` flag when `SECURE_COOKIE=true` is set (recommended in production over HTTPS). |
| `localStorage` | `theme` | `"light"` or `"dark"` | Remembers your light/dark mode preference across sessions. Contains no personal data. Stays in the browser until you clear site data. |

No analytics, tracking, or advertising cookies or storage keys are used.

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

Non-admin users have **no access** to any schema unless explicitly granted. Admins always have full access and bypass all permission checks.

Four roles are supported, each building on the previous:

| Role | Permissions granted | Effect |
|---|---|---|
| **Viewer** | `can_read: true` | List records, get individual records, view history, export, and call `GET /api/schemas/{schema}` |
| **Editor** | `can_write: true` (implies read) | Additionally: create, update (creates a draft), delete, revert, and import as `draft` |
| **Publisher** | `can_publish: true` (implies write + read) | Additionally: publish drafts → active, retire active records, and import directly as `active` |
| **Admin** | Full access (bypasses all checks) | Everything, across all schemas |

Permission grants are managed in the User Management UI (`/admin/users`) via the inline permissions panel, or directly through the API.

When setting a permission, the body may include any combination of these flags. Higher roles imply lower ones — setting `can_publish: true` automatically enables `can_write` and `can_read` on the server side. Removing `can_read` also removes write and publish access.

```json
{ "can_read": true, "can_write": false, "can_publish": false }
```

### Records

| Method | Path | Role required | Description |
|---|---|---|---|
| `GET` | `/api/records/{schema}/{obj}` | Viewer | List records (paginated, searchable); default `state=active` |
| `POST` | `/api/records/{schema}/{obj}` | Editor | Create record (always `active`) |
| `GET` | `/api/records/{schema}/{obj}/{id}` | Viewer | Get single record |
| `PUT` | `/api/records/{schema}/{obj}/{id}` | Editor | Update record — creates a `draft` copy if the record is `active`; updates in-place if already a `draft` |
| `DELETE` | `/api/records/{schema}/{obj}/{id}` | Editor | Soft-delete record |
| `GET` | `/api/records/{schema}/{obj}/{id}/history` | Viewer | Get version history |
| `POST` | `/api/records/{schema}/{obj}/{id}/revert/{version}` | Editor | Revert to version |
| `POST` | `/api/records/{schema}/{obj}/{draft_id}/publish` | Publisher | Promote a `draft` to `active`; accepts `?reason=` |
| `POST` | `/api/records/{schema}/{obj}/{id}/retire` | Publisher | Transition an `active` record to `retired`; accepts `?reason=` |

**PUT response when a draft is created:**
```json
{ "id": "<draft-uuid>", "draft": true }
```
The returned `id` is the new draft's UUID. The original active record UUID is unchanged.

**Publish response:**
```json
{ "id": "<active-uuid>", "published": true }
```

**Retire response:**
```json
{ "id": "<record-uuid>", "retired": true }
```

### Import / Export

| Method | Path | Role required | Description |
|---|---|---|---|
| `GET` | `/api/records/{schema}/{obj}/export` | Viewer | Export (`?format=csv\|tsv\|json`; `?state=active\|draft\|retired\|all`) |
| `POST` | `/api/records/{schema}/{obj}/import` | Editor / Publisher | Import (`?format=csv\|tsv\|json`; optional `?upsert_key=<attr>`; `?initial_state=active\|draft`) |

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
| `action` | — | Filter by action: `INSERT`, `UPDATE`, `DELETE`, `REVERT`, `PUBLISH`, `RETIRE`, `LOGIN`, `LOGIN_FAILED`, `LOGOUT` |
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
| `state` | `active` | Lifecycle state filter: `active`, `draft`, `retired`, or `all` |
| `include_deleted` | false | Include soft-deleted records in the results |
| `parent_id` | — | Filter records by parent UUID (requires `parent` to be set on the object) |
| `ref_field` | — | Attribute key of a reference field to filter by (use together with `ref_id`) |
| `ref_id` | — | UUID value to match against `ref_field`; returns only records where `{ref_field}_id` equals this value |
| `sort_by` | first non-reference attribute | Column key to sort by; must be a non-system, non-reference, non-parent attribute of the object |
| `sort_dir` | `asc` | Sort direction: `asc` or `desc` |

> **Note:** Sorting is intentionally not supported on parent or reference columns. These values are resolved from other tables client-side; a server-side sort would require a SQL JOIN per relationship, adding significant complexity. In the UI, parent and reference column headers are intentionally non-clickable to reflect this. Sort on the underlying data attributes instead.

### Query Parameters (Export)

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | File format: `csv`, `tsv`, or `json` |
| `state` | `active` | Lifecycle state filter: `active`, `draft`, `retired`, or `all` |

### Query Parameters (Import)

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | File format: `csv`, `tsv`, or `json` |
| `upsert_key` | — | Attribute key to match against existing records. If a non-deleted record with the same value exists, it is updated in place; otherwise a new record is inserted. |
| `initial_state` | `active` | Lifecycle state to assign to imported records: `active` or `draft`. Importing as `active` requires Publisher or Admin role; Editors can import as `draft` and publish the records later. |
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
