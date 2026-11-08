# Feature and API Reference

## miniMDM as an MDM System

miniMDM implements a **single-source-of-truth** master data model. Every object type has exactly one authoritative record per entity — the `active` record. This is the **golden record**: the version that downstream systems, integrations, and API consumers should read and trust.

The active record is never overwritten in place. When a change is needed, a `draft` copy is created and goes through a review-and-approve flow before being promoted. This means:

- **Consumers** always read from `state=active` (the default) and see only clean, approved master data.
- **Stewards** work in the draft layer — preparing, reviewing, and publishing changes without affecting the live record.
- **Publishers** control the promotion gate: a draft only becomes the master record when explicitly published.

The `retired` state preserves historical records that are no longer active without deleting them.

This model maps directly to standard MDM concepts: `active` = golden record, publish = mastering approval, draft = pending change in stewardship.

---

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
  duplicates:
    rescan: <on_rule_change|manual>      # optional, default on_rule_change
  schemas:
    <schema_name>:
      objects:
        <object_key>:
          name: <display name>
          description: <optional description>
          owner: <free-text owner, optional>
          steward: <free-text steward, optional>
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
          inbound_sources:
            - name: <source_system_name>
              field_map:
                <source_field>: <minimdm_field_or_system_column>
          duplicates:                    # optional, see Duplicate Detection
            dismissed_by: <editor|publisher>
            rules:
              - name: <rule name, optional>
                fields: [<attribute_key>, ...]
                normalize: <text|digits>
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
| `date` | `TIMESTAMP` (without time zone) | ISO 8601 format; stored without a timezone |

### Parent Relationships

Setting `parent: <object_key>` adds a `_{parent}_id` UUID column to the table. Use this to model hierarchical structures (e.g., division belongs to company).

### Cross-Object References

Use `reference: <object_key>` instead of `type` to create a foreign-key style link. The column stored is `{attribute_key}_id` (UUID). The UI renders a dropdown populated from the referenced object.

### Object-Level Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `require_change_reason` | `true`/`false` | `false` | When `true`, a non-empty `_reason` is required on every create, update, delete, revert, publish, and retire operation. The API returns HTTP 422 if the reason is missing. The UI marks the Reason field as required with a red asterisk. |
| `requires_draft` | `true`/`false` | `false` | When `true`, new records are always created as `draft` regardless of the caller's role. Editors and Publishers alike must go through the draft → publish workflow. Useful for high-governance objects where every new golden record needs explicit review. |
| `allow_retire` | `true`/`false` | `true` | When `false`, the retire endpoint returns HTTP 422 for this object. Use this to protect stable reference data (e.g. currency codes, country lists) that should never be retired. |
| `allow_direct_active_import` | `true`/`false` | `true` | When `false`, bulk import with `initial_state=active` is blocked for this object even for Publishers and Admins. All imported records must enter as `draft` and be published individually. |

Example:

```yaml
objects:
  product:
    name: Product
    require_change_reason: true
    requires_draft: true           # new products always start as draft
    attributes:
      code:
        name: Code
        type: string

  country:
    name: Country
    allow_retire: false            # reference data — cannot be retired
    allow_direct_active_import: false  # bulk imports must go through draft review
    attributes:
      code:
        name: ISO Code
        type: string
```

### Validation Rules

Beyond the hard `required`/`type`/`unique` constraints (enforced by the database and always
rejected outright with HTTP 422), an attribute can declare **soft** validation rules. A rule
violation never blocks a write on its own — the API asks the caller to confirm before saving,
and the record is saved either way with a `_validation_status` of `valid` or `invalid` (see
[System Columns](#system-columns)). This lets stewards capture data they know is imperfect
(e.g. bulk-importing legacy records) without losing visibility into what still needs fixing.

Rules are declared as extra keys directly on an attribute, alongside `type`/`required`/`unique`:

| Rule | Config key | Example |
|---|---|---|
| Value between min/max | `min`, `max` | `min: 0` / `max: 100000` |
| Letters only (Unicode-aware) | `char_class: alpha` | Accepts `"Renée"`, rejects `"abc123"` |
| Alphanumeric only (Unicode-aware) | `char_class: alnum` | Accepts `"AB12"`, rejects `"AB-12#"` |
| Field required if another field equals a value | `required_if: {field: <attr>, equals: <value>}` | `state` required when `country` is `US` |
| Field required if another field has any value | `required_if: {field: <attr>}` | `contact_phone` required whenever `contact_name` is set |
| Field must be empty if another field is empty | `forbidden_if_absent: <attr>` | `secondary_ref` may only be set if `primary_ref` is also set |
| One field's value compared to another | `compare: {op: gt\|gte\|lt\|lte\|eq\|ne, field: <attr>}` | `end_date` must be `gt` `start_date` |

`char_class` uses Python's Unicode-aware `str.isalpha()`/`str.isalnum()` — accented letters,
Cyrillic, CJK, and other non-ASCII scripts are all accepted, only digits/punctuation/symbols are
rejected for `alpha`, and only punctuation/symbols for `alnum`. It only applies to `string`,
`text`, and `email` attributes — putting it on any other type is rejected when the config loads.

`compare` needs both attributes to be the same kind of value: numbers (`integer` and `numeric`
compare with each other), dates, or text. A `compare` between different kinds (e.g. a `date` and
an `integer`) is rejected when the config loads, since it could never be evaluated. Dates are
stored without a timezone; if a client sends a timezone-aware timestamp (`2026-06-01T00:00:00Z`)
for one side, the naive side is treated as UTC for the comparison.

**Not yet supported** (see `docs/known_issues.md`'s Open Issues section for the full
rationale): a fixed allowed-value list for an attribute (needs a new schema-loader enum concept
plus a UI dropdown — tracked as a separate feature), and rules that check the state of a
*referenced* record (e.g. "preferred_supplier must be active" — requires a cross-object database
lookup mid-validation, a different implementation shape from the rules above).
`_validation_status` is binary (`valid`/`invalid`) for v1; a three-state `valid`/`invalid`/`warning`
model with per-rule severity is potential future work, not implemented.

Example:

```yaml
objects:
  order_line:
    name: Order Line
    attributes:
      country:
        name: Country
        type: string
      state:
        name: State
        type: string
        required_if: {field: country, equals: US}
      unit_price:
        name: Unit Price
        type: numeric
        min: 0
        max: 100000
      sku:
        name: SKU
        type: string
        char_class: alnum
      start_date:
        name: Start Date
        type: date
      end_date:
        name: End Date
        type: date
        compare: {op: gt, field: start_date}
      primary_contact:
        name: Primary Contact
        type: string
      backup_contact:
        name: Backup Contact
        type: string
        forbidden_if_absent: primary_contact
```

**API contract for create/update** (`POST`/`PUT` on `/api/records/{schema}/{obj}[/{id}]`):

- A request that violates one or more rules and does **not** pass `confirm_validation_override`
  gets back HTTP 422:
  ```json
  {
    "detail": "One or more validation rules failed. Confirm to override and save anyway.",
    "confirmation_required": true,
    "validation_rule_violations": [
      {"attribute": "unit_price", "rule": "min", "message": "must be >= 0"}
    ]
  }
  ```
- Resubmitting the same request with `?confirm_validation_override=true` (and, optionally,
  `?override_reason=<text>` for an audit note) saves the record with `_validation_status:
  "invalid"` and records a `VALIDATION_OVERRIDE` audit event.
- A request with no rule violations saves normally with `_validation_status: "valid"` — no
  extra query params needed.
- Hard constraint violations (missing `required` field, wrong `type`, duplicate `unique` value)
  are **never** affected by `confirm_validation_override` — they always return a plain
  `{"detail": "..."}` 422 with no `confirmation_required` key, regardless of the flag.
- Cross-field rules (`compare`, `forbidden_if_absent`, `required_if`) are evaluated against the
  **full record** — for an update, the existing record's values merged with the incoming
  change — so editing only one side of a compared pair (e.g. just `end_date`) is still checked
  against the other (e.g. the record's existing `start_date`).

**Import behavior**: bulk import (`POST /api/records/{schema}/{obj}/import`) never hard-fails a
row over a rule violation — every row is written, and rows that fail a rule are saved with
`_validation_status: "invalid"`. The response gains `imported` (total rows inserted or updated)
and `rows` (per-row detail including `_validation_status`) alongside the existing
`inserted`/`updated`/`errors`/`total` fields, so an operator can see which rows need review.

**Publish behavior**: `_validation_status` is never copied from the draft — publishing a draft
recomputes it fresh against the data being promoted to `active`. Publishing never blocks on an
invalid record; the status is informational, visible on the record everywhere it's displayed
(list view, detail view, Pending Drafts) so a publisher or steward can catch and fix it.

### Duplicate Detection

An object can declare rules that **flag records that look like duplicates of each other**. Duplicate detection only flags: it never blocks a write, merges records, or changes data. Flagged records are listed on the **Duplicates** page, where a user resolves them (retires or deletes the extra record) or marks them as *not a duplicate*.

```yaml
minimdm:
  duplicates:
    rescan: on_rule_change          # or: manual (see Scanning)
  schemas:
    crm:
      objects:
        contact:
          name: Contact
          attributes:
            email:      {name: Email, type: email}
            phone:      {name: Phone, type: string}
            first_name: {name: First name, type: string}
            last_name:  {name: Last name, type: string}
            country:    {name: Country, type: string}
          duplicates:
            dismissed_by: editor    # editor (default) or publisher
            rules:
              - name: Same email
                fields: [email]
              - name: Same phone
                fields: [phone]
                normalize: digits
              - name: Same name and country
                fields: [last_name, first_name, country]
```

**Object-level keys** (`duplicates:` on an object):

| Key | Default | Description |
|---|---|---|
| `rules` | none | List of rules. An object without rules does no duplicate detection and costs nothing. |
| `dismissed_by` | `editor` | Who may mark flags as *not a duplicate* and reopen them: `editor` means anyone with write access, `publisher` limits it to Publishers. Admins always may. |

**Rule keys:**

| Key | Default | Description |
|---|---|---|
| `fields` | required | One or more attribute keys. A rule with several fields matches only when **all** of them match. Reference attributes can be used and are compared by the record they point to. |
| `name` | the fields joined with ` + ` | Shown on the Duplicates page and in the audit log. Must be unique within the object. |
| `normalize` | `text` | How text values are made comparable, see below. |

An invalid block (an unknown field, an unknown `normalize` or `dismissed_by` value, a repeated field or rule name) is rejected when the config loads, like other config errors.

**What counts as a match.** Two records match under a rule when every field of the rule has a value and the values are equal after normalising. An empty value never matches, so two records that both lack an email are not duplicates of each other. Text fields (`string`, `text`, `email`) are normalised; every other type is compared exactly:

| Normalizer | Applies to | What it does |
|---|---|---|
| `text` (default) | text fields | Ignores case, surrounding and repeated spaces, and punctuation: `ACME  Ltd.` matches `acme ltd`. Punctuation becomes a space rather than disappearing, so `a@bc.com` and `ab@c.com` stay different. Non-ASCII letters are kept; how they are lower-cased follows the database's locale. |
| `digits` | text fields | Keeps only the digits: `070-123 45 67` matches `(0701) 234567`. For phone numbers and similar identifiers. A value with no digits is empty. |
| (exact) | integer, numeric, boolean, date, reference | Compared as stored. `1.0` and `1.00` are the same number; dates are compared including their time. |

In a rule that mixes text and other fields, the normalizer applies to the text fields only. To normalise different fields differently, use separate rules.

`unique: true` is not a substitute for a rule, and a rule on a unique field is still useful: `unique` rejects exact repeats among active records only, while a rule also catches `Anna@x.com` against `anna@x.com ` and a new draft whose value matches an active record (which `unique` only rejects when the draft is published).

**What is compared.** Records in state `active` or `draft` that are not deleted. `retired` and deleted records are left out. A golden record and its draft copy are **one record** for this purpose: they never match each other, and a pending draft is compared too, so a record is flagged if either its active version or its pending draft matches another record. New drafts are therefore checked against the active records before they are published.

**When flags are updated.** In the same transaction as the write, on every create, edit, revert, publish, retire, delete, bulk import and inbound push, so a flag is never out of step with the data. Creating or editing a record returns `possible_duplicates` when it matched something (see [Records](#records)).

**Reviewing.** Users with write access to a schema see the **Duplicates** link in the top bar (with the number of open groups), an amber pill beside the object in the sidebar, and a notice on the page of any flagged record. The Duplicates page lists each group with the rule that matched and the records in it; the columns the rule compares are marked in the table heading. From there a user can open a record to retire or delete it, or:

- **Not duplicates** dismisses every record in a group; in a group of three or more, **Not a duplicate of the others** dismisses just one record and keeps the others flagged. A reason is optional, or required when the object has `require_change_reason`.
- A dismissal holds until the record's matching value changes (the record is then judged on its new value) or another matching record turns up in the group (the new record was never reviewed against the dismissed ones, so they are flagged again).
- The **Dismissed** tab lists dismissed groups, and **Reopen** undoes a dismissal.

Dismissals and reopenings are recorded in the audit log.

**Scanning.** Flags are kept up to date as records are written, so a scan is only needed when the rules themselves change. A scan rebuilds all flags of an object from its data in one transaction. Dismissals survive it where the same record still matches.

| `minimdm.duplicates.rescan` | Behaviour |
|---|---|
| `on_rule_change` (default) | At startup and after `POST /api/config/reload`, every object whose rules changed since it was last scanned (including the first time rules are added) is scanned automatically in the background. Objects that need nothing cost nothing. |
| `manual` | Nothing is scanned automatically. The server logs which objects are out of date, the Duplicates page shows a banner, and an Admin presses **Rescan**. |

An Admin can start a scan at any time with the **Rescan** button on the Duplicates page, which shows how many records it will read and how long the last scan took (`POST /api/duplicates/{schema}/{obj}/rescan`). Other things to know:

- **Large imports.** A bulk import of up to 500 rows is checked row by row inside the import. A bigger one is committed first and one scan runs in the background afterwards, so the import itself stays short; the import response says which (`duplicate_check`). If the server stops before that scan has run, the request is remembered and picked up at the next start.
- **Interrupted scans.** A scan that is stopped part-way (the server is restarted or killed) changes nothing and still counts as outstanding, so it is repeated: automatically at the next start, or by the banner and button in `manual` mode.
- **One at a time.** Scans of the same object never run simultaneously.
- **Audit.** Every completed scan writes one `DUPLICATE_SCAN` audit entry (see [Audit Log](#audit-log)); the entry's time is when it finished.

**Storage and cost.** Flags live in `_system.duplicate_flags` (one row per flagged record, rule and match; managed by Alembic migration 0004), and the last scan of each object in `_system.duplicate_scans`. Matching uses one partial expression index per rule on the object's own table (named `ix_dup_<hash>`, created at startup and dropped again when a rule is removed or changed), plus an index on `_draft_of_id`. Measured on PostgreSQL 16 with two rules: creating the indexes takes about 0.7 s per 100,000 records and 8 s per million, and runs during startup; a full scan takes about 1 s per 100,000 records and 12 s per million; checking one written record takes about 10 to 25 ms. See [known_issues.md](known_issues.md#duplicate-detection-flags-matches-and-does-not-decide) for the limits of the design.

### Governance Metadata

Two optional free-text fields can be set at the object level to document data ownership:

| Field | Type | Description |
|---|---|---|
| `owner` | string (optional) | Who is responsible for this object type (e.g. a team name or email). Informational only — no enforcement or access control is applied. |
| `steward` | string (optional) | Who maintains data quality day-to-day. Informational only. |

When set, `owner` and `steward` are displayed on the records list page near the object name and description. When not set, the fields are hidden. They are not included in API record responses and have no effect on the MDM lifecycle.

```yaml
objects:
  customer:
    name: Customer
    owner: Sales Operations
    steward: alice@example.com
    attributes:
      code:
        name: Customer Code
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

### Inbound Sources

`inbound_sources` allows external systems to push records into miniMDM via HTTP POST. All inbound records always land as **drafts** — the lifecycle is never bypassed. Each source authenticates with an API key managed in the Admin UI.

```yaml
objects:
  supplier:
    name: Supplier
    attributes:
      code:
        name: Supplier Code
        type: string
      name:
        name: Supplier Name
        type: string
    inbound_sources:
      - name: erp_system          # becomes the _source_system value on every record
        field_map:                 # source_payload_field: minimdm_field
          erp_id: _source_id      # required — used to match incoming records for upsert
          company_name: name
          supplier_code: code
        match_key: code           # optional — fallback attribute for initial record matching
```

**How it works:**

1. An external system sends `POST /api/inbound/{schema}/{object}` with `X-Api-Key: <key>` and a JSON body.
2. miniMDM looks up the matching API key and `inbound_sources` entry for the schema.
3. The `field_map` is applied — source field names are renamed to miniMDM attribute names. Fields not in the map are ignored.
4. `_source_system` is set to the `name` from the config. Payload attempts to override it are silently discarded.
5. miniMDM looks for an existing record using a two-step lookup:
   - **Primary** — `_source_system = name` AND `_source_id = <mapped value>`. Fast and unambiguous.
   - **Fallback** (if `match_key` is configured and the primary lookup found nothing) — match on the business-key attribute (e.g. `code`). If exactly one record matches, it is **claimed**: `_source_system` and `_source_id` are written onto the active record immediately, so future pushes use the primary path. If more than one record matches the fallback is skipped and a new draft is created.
6. Once a match is found (via either path):
   - **Found, state = active** → a draft copy is created alongside the active record (draft-copy-on-edit semantics; any fields the publisher has enriched but that are not in the `field_map` are preserved on the draft).
   - **Found, state = draft** → the existing draft is updated in place. No duplicate draft is created.
   - **Not found** → a new draft is created.
7. The audit log records two entries: a **data change** entry (`user_name = inbound:<source_name>`) on the record table, and an **`INBOUND_CALL`** entry in the Auth Events audit log (schema `_system`, object `inbound`) with the schema, object, and outcome (`created` or `updated`). Failed authentication attempts are recorded as **`INBOUND_CALL_FAILED`** entries so revoked keys or misconfigured clients are visible to admins.

**Rules:**
- At least one `field_map` entry must map to `_source_id`. Without a stable source identifier, upsert matching is impossible and the config will be rejected at startup.
- `field_map` values may be any attribute key defined on the object, or `_source_id`. System columns other than `_source_id` cannot be targeted.
- `match_key` is optional. When set, it must be a user-defined attribute key (not `_source_id`). Using a `unique: true` attribute is recommended — it eliminates the ambiguous-match case entirely.
- Each `name` within an object's `inbound_sources` list must be unique.
- `name` must be a valid identifier (letters, digits, underscores; must start with a letter or underscore).

**Rate limiting and body size:**

The inbound endpoint is rate-limited to **120 requests per minute per IP address**. Requests exceeding the limit receive `429 Too Many Requests`. The request body must not exceed `MAX_UPLOAD_SIZE` (default 10 MB); oversized requests receive `413 Request Entity Too Large` before any DB work occurs.

**API key management:**

API keys are stored as SHA-256 hashes in `_system.inbound_keys`. Each key is scoped to a **schema and source name** — a key with `source_name = erp` grants push access to every object in that schema that has an `inbound_sources` entry with `name: erp`. The Generate Key modal in the Admin UI shows exactly which objects a source name covers before you confirm. Keys are generated and revoked in the Admin UI under **Users → Inbound Keys**. The raw key value is shown **once** at generation time and never stored in plaintext — copy it immediately. Keys can be revoked (soft-deleted) at any time; revoked keys are rejected immediately.

See the [Inbound Webhooks](#inbound-webhooks) section of the REST API reference for endpoint details and response codes.

---

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
| `_source_system` | TEXT | Name of the external system that originated this record (e.g. `"erp"`, `"crm"`) |
| `_source_id` | TEXT | Identifier of the record in the source system |
| `_validation_status` | TEXT | `valid` or `invalid` — whether the record currently satisfies every config-based [validation rule](#validation-rules) declared on its object. Defaults to `valid`; recomputed on every create, update, and publish. |

## Lifecycle States

Every record has a `_state` field that controls its visibility and transitions:

| State | Description |
|---|---|
| `active` | The **golden record** — the authoritative master version. Returned by default on all list and export calls. This is the record downstream systems and integrations should consume. |
| `draft` | A pending change to an active record, awaiting review and approval. Invisible to normal consumers until published. Editing an active record always creates a draft copy — the active record is never modified in place. New records created directly are always `active`; to require the draft flow for all new records, set `requires_draft: true` in the config (see Lifecycle Policy). |
| `retired` | A record that is no longer in use. Excluded from default responses but preserved for history and audit. |

**Transitions:**
- `POST ./{id}/publish` — promotes a `draft` to the active golden record (applies draft data onto the master, removes the draft). Requires Publisher or Admin.
- `POST ./{id}/retire` — transitions an `active` record to `retired`. Requires Publisher or Admin.

The `active` record is never touched directly when you edit it — a `draft` copy is created instead. This means API consumers always see stable, approved master data while changes are being prepared in the draft layer.

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
| `_validation_status` | `valid`/`invalid` snapshot at the time of this history entry |
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
| `action` | `INSERT` / `UPDATE` / `DELETE` / `REVERT` / `PUBLISH` / `RETIRE` / `VALIDATION_OVERRIDE` / `DUPLICATE_DISMISSED` / `DUPLICATE_REOPENED` / `DUPLICATE_SCAN` |
| `old_values` | JSON snapshot before change |
| `new_values` | JSON snapshot after change |
| `reason` | Optional reason provided by the user |
| `ip_address` | Client IP address |

The duplicate-detection actions record:

- `DUPLICATE_DISMISSED` and `DUPLICATE_REOPENED`: one entry per flag, with `record_id` set to the flagged record, `new_values` holding `status`, `rule` and the normalised `value` that matched, and the reason if one was given. They appear with the object's other data changes.
- `DUPLICATE_SCAN`: one entry per **completed** scan, a system event like the inbound-key actions (`schema_name` is `_system`, `object_name` is `duplicate_scan`, `record_id` is the all-zero UUID). `user_name` is the Admin who pressed Rescan, the user who ran the import, or `system`. `new_values` holds `schema`, `object`, `trigger` (`manual`, `startup`, `config_reload` or `import`), `record_count`, `groups` and `duration_ms`; `reason` is a readable summary. The entry's `timestamp` is when the scan finished, so it started `duration_ms` earlier. Scans that were interrupted or skipped write nothing. In the UI these appear on the Auth Events tab.

## Authentication

All routes require authentication. The web UI uses an httpOnly cookie (`access_token`) set at login. API clients should pass `Authorization: Bearer <token>` on every request.

**Inbound webhook routes** (`POST /api/inbound/{schema}/{obj}`) are the exception: they do not accept JWT tokens. Instead they require the `X-Api-Key: <key>` header. API keys are generated and managed in the Admin UI (Users → Inbound Keys tab) and stored as SHA-256 hashes — the raw value is shown once at creation and never retrievable afterwards.

## Browser storage

miniMDM stores the following data in the browser:

| Storage | Key | Value | Purpose |
|---|---|---|---|
| Cookie (`httpOnly`) | `access_token` | JWT authentication token | Maintains the login session. Set on login, cleared on logout. Required for the application to function — no consent banner is shown since this is a strictly necessary cookie under EU ePrivacy rules. The cookie carries the `Secure` flag when `SECURE_COOKIE=true` is set (recommended in production over HTTPS). |
| `localStorage` | `theme` | `"light"` or `"dark"` | Remembers your light/dark mode preference across sessions. Contains no personal data. Stays in the browser until you clear site data. |

No analytics, tracking, or advertising cookies or storage keys are used.

Tokens are JWTs signed with `SECRET_KEY` and expire after `TOKEN_EXPIRE_HOURS` (default: 8 hours).

A user's account state is checked against the database on **every** request, not read from the token, so changes take effect immediately rather than when the token expires: deactivating a user, removing their admin flag, or changing their password (an admin setting a new one, or a password reset link being used) all invalidate the sessions they already have open. They simply have to log in again.

On first startup, if no users exist, an admin account is created automatically from `ADMIN_USERNAME` / `ADMIN_PASSWORD` environment variables. Both must be set — if either is empty, no admin user is created and the application logs a warning. There are no built-in default credentials.

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

### Inbound Key Management (Admin only)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin/inbound-keys` | List all inbound API keys (key hash never returned) |
| `GET` | `/api/admin/inbound-keys/sources` | List all `inbound_sources` entries from the loaded config |
| `POST` | `/api/admin/inbound-keys` | Generate a new API key — returns the raw key **once** |
| `DELETE` | `/api/admin/inbound-keys/{key_id}` | Revoke a key (soft-delete; rejected immediately on next use) |

**Generate key request body:**
```json
{ "schema_name": "nordkraft", "source_name": "erp_system", "description": "ERP integration key" }
```

**Generate key response (201):**
```json
{
  "id": "<uuid>",
  "key": "<raw-43-char-key>",
  "key_prefix": "<first-8-chars>",
  "schema_name": "nordkraft",
  "source_name": "erp_system",
  "created_at": "2026-06-28T10:00:00Z"
}
```

The `key` field is **never returned again** after this response. Store it securely.

### Schema-Based Access Control

Non-admin users have **no access** to any schema unless explicitly granted. Admins always have full access and bypass all permission checks.

Four roles are supported, each building on the previous:

| Role | Permissions granted | Effect |
|---|---|---|
| **Viewer** | `can_read: true` | List records, get individual records, view history, export, and call `GET /api/schemas/{schema}` |
| **Editor** | `can_write: true` (implies read) | Additionally: create, update (creates a draft), delete, revert a **draft**, and import as `draft`. Editors cannot revert an active (golden) or retired record, or edit a retired record — those change the record in place, outside draft → publish, and need Publisher |
| **Publisher** | `can_publish: true` (implies write + read) | Additionally: publish drafts → active, retire active records, revert active or retired records, edit retired records, and import directly as `active` |
| **Admin** | Full access (bypasses all checks) | Everything, across all schemas |

Permission grants are managed in the User Management UI (`/admin/users`) via the inline permissions panel, or directly through the API.

When setting a permission, the body may include any combination of these flags. Higher roles imply lower ones — setting `can_publish: true` automatically enables `can_write` and `can_read` on the server side. Removing `can_read` also removes write and publish access.

```json
{ "can_read": true, "can_write": false, "can_publish": false }
```

### Records

| Method | Path | Role required | Description |
|---|---|---|---|
| `GET` | `/api/records/{schema}/{obj}` | Viewer | List master (golden) records (paginated, searchable); default `state=active`; supports `?role=master\|draft` as MDM-native alias |
| `POST` | `/api/records/{schema}/{obj}` | Editor | Create record (always `active`); accepts `?confirm_validation_override=` and `?override_reason=` — see [Validation Rules](#validation-rules) |
| `GET` | `/api/records/{schema}/{obj}/{id}` | Viewer | Get single record |
| `PUT` | `/api/records/{schema}/{obj}/{id}` | Editor | Update record — creates a `draft` copy if the record is `active`; updates in-place if already a `draft`; accepts `?confirm_validation_override=` and `?override_reason=` |
| `DELETE` | `/api/records/{schema}/{obj}/{id}` | Editor | Soft-delete record |
| `GET` | `/api/records/{schema}/{obj}/{id}/history` | Viewer | Get version history |
| `POST` | `/api/records/{schema}/{obj}/{id}/revert/{version}` | Editor (drafts) / Publisher (active or retired records) | Revert to version; recomputes `_validation_status` |
| `POST` | `/api/records/{schema}/{obj}/{draft_id}/publish` | Publisher | Promote a `draft` to `active`; accepts `?reason=` |
| `POST` | `/api/records/{schema}/{obj}/{id}/retire` | Publisher | Transition an `active` record to `retired`; accepts `?reason=` |

**Create/update response** — the full saved record, always including `_validation_status`
(`valid` or `invalid`), plus a top-level `id` for backward compatibility:
```json
{ "id": "<uuid>", "_id": "<uuid>", "code": "ABC", "_validation_status": "valid", "..." : "..." }
```

**PUT response when a draft is created:**
```json
{ "id": "<draft-uuid>", "draft": true, "_id": "<draft-uuid>", "_validation_status": "valid", "..." : "..." }
```
The returned `id` is the new draft's UUID. The original active record UUID is unchanged.

**Possible duplicates.** When the object has [duplicate rules](#duplicate-detection) and the saved record matched another record, the create and update responses also contain `possible_duplicates`. The key is absent when nothing matched, so existing clients see no change:
```json
{
  "id": "<uuid>", "...": "...",
  "possible_duplicates": [
    { "rule": "Same email", "value": "anna x com", "matches": ["<record-uuid>"] }
  ]
}
```
`matches` holds the ids of the other records in the group (for a record that has a draft copy, the id of its golden record); `value` is the normalised form that matched, kept for reference rather than display. The save is never refused because of a match.

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
| `GET` | `/api/records/{schema}/{obj}/import-template` | Viewer | Download a blank import template (`?format=csv\|tsv\|json`; `?examples=true` to include one example row) |
| `POST` | `/api/records/{schema}/{obj}/import` | Editor / Publisher | Import (`?format=csv\|tsv\|json`; optional `?upsert_key=<attr>`; `?initial_state=active\|draft`). Never hard-fails a row over a rule violation — see [Validation Rules](#validation-rules) |

### Schemas

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/schemas` | List all schemas |
| `GET` | `/api/schemas/{schema}` | Get schema details |
| `GET` | `/api/schemas/{schema}/objects/{obj}` | Get object definition |
| `GET` | `/api/config` | Get current loaded config (schema definitions only; webhook URLs are excluded). Non-admins only see the schemas they hold a read permission for, same as `GET /api/schemas` |
| `POST` | `/api/config/reload` | Reload config from disk and sync database schema — **Admin only** |
| `GET` | `/api/pending-count` | Return `{"total": n}`, the number of pending draft records in schemas where the current user can publish (all schemas for admins; Viewers and Editors always get `0`). Soft-deleted drafts are excluded. Used by the count on the top-bar Pending link, which is shown only to Publishers and Admins |
| `GET` | `/api/object-counts` | Return record counts per object for every schema the current user can read — used by the sidebar and the home page cards. See [Record counts](#record-counts) |

#### Record counts

`GET /api/object-counts` answers with one entry per object in each readable schema:

```json
{
  "schemas": {
    "mycompany": {
      "supplier": { "active": 1240, "pending": 3, "duplicates": 2 },
      "customer": { "active": 87,   "pending": 0 }
    }
  }
}
```

- `active` — records in state `active` (the golden records). Draft, retired and soft-deleted records are not counted.
- `pending` — records in state `draft` (soft-deleted ones excluded). **Only present for schemas where the caller has Publisher access** (admins have it everywhere); Viewers and Editors get `active` only.
- `duplicates` — the number of open [duplicate](#duplicate-detection) groups. **Only present for objects that have duplicate rules, and only for schemas where the caller has write access** (admins everywhere). Flags left over from rules that were later removed are not counted.
- Schemas the caller cannot read are omitted. Editing an active record creates a draft copy, so such an object counts once under `active` and once under `pending`.
- The UI formats the numbers with the browser's locale (so `1,240` or `1 240`, depending on the user) and abbreviates numbers above 99,999 (`250K`).

### State counts

`GET /api/records/{schema}/{object}/state-counts` returns the numbers shown on the state tabs and next to **Show deleted** on the object list page. Anyone with read access to the schema can call it (Viewer, Editor, Publisher, Admin alike); a user without access gets `403`, an unknown object `404`.

```json
{
  "states":  { "active": 12, "draft": 3, "retired": 1 },
  "deleted": { "active": 2,  "draft": 0, "retired": 1 }
}
```

- `states` — live (not deleted) records per lifecycle state. These are the numbers `GET /api/records/{schema}/{object}?state=<state>` returns as `total`; the **All states** tab is their sum.
- `deleted` — soft-deleted records per state (the state they had when deleted), i.e. what `include_deleted=true` adds to each state. Edit drafts that the publish workflow soft-deleted are not counted, matching what **Show deleted** reveals.
- The counts cover the whole object and ignore `search` and `source_system`. In the UI, **Show deleted (N)** shows the `deleted` number for the selected tab (the sum for **All states**).

### Duplicates

Endpoints behind the Duplicates page. They need **write access** to the schema (Editor, Publisher or Admin); Viewers and users without access get `403`, an unknown object `404`. See [Duplicate Detection](#duplicate-detection) for the rules and semantics.

| Method | Path | Role required | Description |
|---|---|---|---|
| `GET` | `/api/duplicates/{schema}/{obj}` | Editor | List flagged groups with their records |
| `GET` | `/api/duplicates/{schema}/{obj}/record/{id}` | Editor | The open groups one record is flagged in (a draft copy's id resolves to its golden record). Used for the notice on the record page |
| `POST` | `/api/duplicates/{schema}/{obj}/dismiss` | Editor, or Publisher if the object sets `dismissed_by: publisher` | Mark flags as *not a duplicate* |
| `POST` | `/api/duplicates/{schema}/{obj}/reopen` | same as dismiss | Undo a dismissal |
| `GET` | `/api/duplicates/{schema}/{obj}/scan` | Editor | Scan status |
| `POST` | `/api/duplicates/{schema}/{obj}/rescan` | Admin | Start a scan of the object in the background |

**List** (`GET /api/duplicates/{schema}/{obj}`) takes `status=open` (default) or `dismissed`, `limit` (1 to 200, default 50) and `offset`. `open` lists the groups that still have two or more open records; `dismissed` lists the groups that contain a dismissed record, so it can be reopened.

```json
{
  "status": "open",
  "rules": ["Same email", "Same phone"],
  "total": 1,
  "counts": { "open": 1, "dismissed": 0 },
  "limit": 50, "offset": 0,
  "can_dismiss": true,
  "groups": [
    {
      "rule": "Same email",
      "fields": ["email"],
      "value": "anna x com",
      "match_hash": "…",
      "members": [
        {
          "flag_id": "<uuid>", "entity_id": "<record-uuid>", "status": "open",
          "dismissed_by": null, "dismissed_at": null, "dismiss_reason": null,
          "has_draft": false,
          "record": { "_id": "<record-uuid>", "_state": "active", "email": "Anna@x.com", "...": "..." }
        }
      ]
    }
  ]
}
```

- `total` is the number of groups with the requested status; `counts` gives both numbers whichever status is listed.
- `fields` names the attributes the rule compares. `value` is the normalised form that matched (for reference, never for display); show the records' own values.
- `entity_id` is the record's id, or for a record that has a pending draft copy the golden record's id (`has_draft` is then true); open it at `/{schema}/{obj}/{entity_id}`. Members are ordered oldest first.
- `can_dismiss` says whether the caller may dismiss or reopen under the object's `dismissed_by`.
- Flags of rules that were removed from the config are left out.

**Dismiss and reopen** take `{"flag_ids": ["<uuid>", ...], "reason": "…"}` (1 to 500 ids; `reason` optional, or required when the object has `require_change_reason`) and return `{"changed": n}`. Pass one member's `flag_id` to dismiss just that record, or all of a group's. Flags that already have the requested status are not counted, so repeating a call returns `{"changed": 0}`. `404` means none of the ids belong to this object; `403` means the caller is not allowed to dismiss under `dismissed_by`. Each changed flag writes a `DUPLICATE_DISMISSED` or `DUPLICATE_REOPENED` audit entry.

**Scan status** (`GET .../scan`):

```json
{
  "has_rules": true,
  "running": false,
  "needs_rescan": false,
  "rescan_mode": "on_rule_change",
  "record_count": 873,
  "last_scan": { "scanned_at": "2026-11-08T13:00:30+00:00", "record_count": 870, "duration_ms": 8 }
}
```

`needs_rescan` is true when the object's rules changed since the last scan or a scan was requested but never finished. `record_count` is how many records a new scan would read (`null` while a scan is running, or for an object without rules). `last_scan` is `null` if the object was never scanned.

**Rescan** (`POST .../rescan`) answers `202 {"status": "started"}` and runs in the background; poll the status endpoint to follow it. It returns `409` if a scan of the object is already running and `422` if the object has no duplicate rules. The scan writes a `DUPLICATE_SCAN` audit entry when it completes.

### Inbound Webhooks

These endpoints accept pushes from external source systems. They use `X-Api-Key` authentication, not JWT. See [Inbound Sources](#inbound-sources) for configuration.

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/inbound/{schema}/{obj}` | `X-Api-Key` header | Push a record from an external source system |

**Request:**
```
POST /api/inbound/nordkraft/supplier
X-Api-Key: <api-key>
Content-Type: application/json

{ "erp_id": "ERP-001", "company_name": "Acme Corp", "supplier_code": "ACM" }
```

**Response — new draft created (201):**
```json
{ "status": "created", "id": "<draft-uuid>" }
```

**Response — existing record updated (200):**
```json
{ "status": "updated", "id": "<draft-uuid>" }
```

**Error codes:**

| Code | Meaning |
|---|---|
| 401 | Missing or invalid `X-Api-Key` |
| 403 | Key is valid but the target object has no `inbound_sources` entry matching this source |
| 404 | Schema or object not found |
| 422 | Payload missing required mapped fields |

### Audit

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/audit` | Query audit log (filterable by schema, object, action, time range) |

### Query Parameters (Audit Log)

| Parameter | Default | Description |
|---|---|---|
| `schema` | — | Filter by schema name (use `_system` for auth events) |
| `obj` | — | Filter by object key within the schema |
| `action` | — | Filter by action: `INSERT`, `UPDATE`, `DELETE`, `REVERT`, `PUBLISH`, `RETIRE`, `VALIDATION_OVERRIDE`, `DUPLICATE_DISMISSED`, `DUPLICATE_REOPENED`, `DUPLICATE_SCAN`, `LOGIN`, `LOGIN_FAILED`, `LOGOUT` |
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
| `state` | `active` | Lifecycle state filter: `active`, `draft`, `retired`, or `all`. Cannot be combined with `?role=`. |
| `role` | — | MDM-native alias for `?state=`: `master` → active (golden record), `draft` → draft candidate. Returns HTTP 400 for unrecognised values or when combined with `?state=`. |
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
| `limit` | *(all rows)* | Maximum number of rows to export (minimum 1) |
| `offset` | `0` | Number of rows to skip (minimum 0) |

Rows are ordered by creation time, so `limit` and `offset` page through the same sequence on repeated calls. Every response carries `X-Total-Count` (the number of rows matching `state`, ignoring `limit` and `offset`) and `X-Offset` headers, so a client can export a large object in batches until `offset` reaches the total. The rows of one request are built in memory before the response is sent, so use `limit` for very large objects.

> **Spreadsheet safety:** in CSV and TSV exports, a text value that starts with `=`, `+`, `-`, `@`, a tab, or a carriage return is written with a leading apostrophe (`'=SUM(A1)`), so Excel or Sheets shows it as text instead of executing it as a formula. Anyone able to write a record — or an inbound source system — could otherwise plant a formula that runs on whoever opens the export. The apostrophe is removed again when a CSV/TSV file is imported, so export → edit → re-import round-trips losslessly. JSON exports are never modified, and numbers (including negative ones) are unaffected.

### Query Parameters (Import Template)

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | File format: `csv`, `tsv`, or `json` |
| `examples` | `false` | Include one synthetic, clearly-fake example row (e.g. `EXAMPLE-code`) honoring each attribute's type and `min`/`max`/`char_class` constraints |

Column headers are the same attribute keys the importer matches on — a `reference` attribute is templated as `{attr}_id` (its actual FK column), left blank rather than filled with a fabricated UUID. Without `examples`, CSV/TSV return a headers-only file; JSON — which has no separate header row — returns one placeholder row instead, using `""` for text-like attributes and `null` for boolean/numeric/date/reference ones (an empty string isn't a real value for those types). With `examples`, boolean and numeric values are native JSON types (`true`, `1`), not quoted strings.

### Query Parameters (Import)

| Parameter | Default | Description |
|---|---|---|
| `format` | `csv` | File format: `csv`, `tsv`, or `json` |
| `upsert_key` | — | Attribute key to match against existing records. If a non-deleted record with the same value exists, it is updated in place; otherwise a new record is inserted. |
| `initial_state` | `active` | Lifecycle state to assign to imported records: `active` or `draft`. Importing as `active` requires Publisher or Admin role; Editors can import as `draft` and publish the records later. |
| `source_system` | — | Source system name applied to all imported records (sets `_source_system`). Per-row values in the file take precedence if the file includes a `_source_system` column. |
| `reason` | — | Audit note attached to every inserted or updated record |

**Import response** — in addition to the existing `inserted`/`updated`/`errors`/`total` fields,
the response includes `imported` (= `inserted + updated`) and `rows` (per-row detail, each
including `_validation_status`), so an operator can see which imported rows violate a
validation rule without a follow-up query:
```json
{
  "inserted": 2, "updated": 0, "errors": [], "total": 2,
  "imported": 2,
  "rows": [
    { "code": "AB12", "unit_price": 100, "_validation_status": "valid", "...": "..." },
    { "code": "CD34", "unit_price": -5, "_validation_status": "invalid", "...": "..." }
  ]
}
```

For an object with [duplicate rules](#duplicate-detection) the response also has `duplicate_check`: `"inline"` when the rows were checked one by one during the import (up to 500 rows), or `"rescan_scheduled"` when the import was committed first and a scan of the object runs in the background afterwards. The key is absent for objects without rules.

> **Note:** CSV/TSV/JSON import files must be UTF-8 encoded. Files in another encoding (e.g. Excel's Windows-1252 "CSV" or UTF-16 "Unicode Text" export) are rejected with HTTP 400 — re-save as "CSV UTF-8" or convert with `iconv` first. See `docs/troubleshooting.md`.

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

> **Note:** `_reason` in the request body applies only to single-record create and update operations. For bulk imports, use the `?reason=` query parameter instead — `_reason` as a column in the import file is not supported and will be ignored.
