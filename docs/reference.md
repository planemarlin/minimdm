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
| `_created_by` | TEXT | User (future auth feature) |
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
| `user_name` | User (null until auth is implemented) |
| `schema_name` | Schema of the changed object |
| `object_name` | Object key |
| `record_id` | UUID of the changed record |
| `action` | INSERT / UPDATE / DELETE / REVERT |
| `old_values` | JSON snapshot before change |
| `new_values` | JSON snapshot after change |
| `reason` | Optional reason provided by the user |
| `ip_address` | Client IP address |

## REST API Endpoints

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
| `GET` | `/api/records/{schema}/{obj}/export` | Export (`?format=csv|tsv|json`) |
| `POST` | `/api/records/{schema}/{obj}/import` | Import (`?format=csv|tsv|json`) |

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
| `GET` | `/api/audit` | Query audit log (filterable by schema, object, action) |

### Query Parameters (List Records)

| Parameter | Default | Description |
|---|---|---|
| `page` | 1 | Page number |
| `page_size` | 50 | Records per page (max 500) |
| `search` | — | Full-text search across string columns |

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
