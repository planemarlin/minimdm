# Quickstart Guide

This guide walks you through setting up miniMDM and managing your first master data object in under 10 minutes.

## 1. Start miniMDM

Follow the [installation guide](installation.md) then run:

```bash
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000` in your browser. You will be redirected to the login page.

On first run, a default admin account is created automatically:

| Username | Password |
|---|---|
| `admin` | `admin` |

Log in and immediately change the password via **Users** in the header navigation.

## 2. Define Your Data Model

Create `config/minimdm.yaml`:

```yaml
minimdm:
  schemas:
    mycompany:
      objects:
        supplier:
          name: Supplier
          description: External suppliers
          attributes:
            code:
              name: Supplier Code
              type: string
              required: true
            name:
              name: Supplier Name
              type: string
              required: true
            country:
              name: Country
              type: string
            email:
              name: Contact Email
              type: email
```

Restart the server (or call `POST /api/config/reload` if you want zero downtime).

## 3. Add Records

Navigate to **mycompany → Supplier** in the sidebar. Click **+ New record** and fill in the form.

The number next to each object in the sidebar (and on the home page) is its count of active records. If you are a Publisher or Admin, a blue pill beside it shows how many drafts are waiting to be published.

Alternatively, use the API directly:

```bash
curl -X POST http://localhost:8000/api/records/mycompany/supplier \
  -H "Content-Type: application/json" \
  -d '{"code":"S001","name":"Acme Ltd","country":"US","_reason":"Initial load"}'
```

## 4. Bulk Import

Not sure what columns to use? Click **Need a template?** in the Import dialog to download a blank CSV, TSV, or JSON template with the correct column names for the object — optionally with one example row filled in.

Prepare a CSV file `suppliers.csv`:

```csv
code,name,country,email
S001,Acme Ltd,US,acme@example.com
S002,Globex Corp,DE,info@globex.example
```

Import via the UI: on the object list page select **Insert only** (or choose an attribute to upsert on) from the dropdown next to the **Import** button, then click **Import** and pick the file.

To upsert (update existing records instead of always inserting), select the matching attribute in the dropdown. Rows whose value for that attribute matches an existing record are updated; unmatched rows are inserted as new records. The response shows separate inserted and updated counts.

Import via the API:

```bash
# Insert only
curl -X POST "http://localhost:8000/api/records/mycompany/supplier/import?format=csv" \
  -F "file=@suppliers.csv"

# Upsert on 'code'
curl -X POST "http://localhost:8000/api/records/mycompany/supplier/import?format=csv&upsert_key=code" \
  -F "file=@suppliers.csv"
```

> **Note:** import files must be UTF-8 encoded. If Excel is your source, save as "CSV UTF-8" rather than plain "CSV" or "Unicode Text" — see `docs/troubleshooting.md` if you hit an encoding error.

## 5. Search and Browse

Use the search bar on the object list page to filter records. Results update as you type.

The state tabs above the list (Active, Draft, Retired, All states) each show how many records they hold, so you can see at a glance whether anything is waiting as a draft. To view soft-deleted records, check the **Show deleted** checkbox in the toolbar; the number in brackets is how many deleted records it will add to the current tab. Deleted rows appear with a strikethrough style and link directly to their history page, where they can be reverted.

## 6. View History and Revert

Click any row in the record list to open the detail page, then click **History** to see all versions. Click **Revert** next to any version to restore it.

## 7. Export Data

Click **Export CSV**, **Export TSV**, or **Export JSON** on the list page.

## 8. Audit Log

The full audit log is available in the UI at **Audit Log** in the header (admin only), or via the API:

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/api/audit?schema=mycompany&obj=supplier
```

## 9. Find Duplicates

miniMDM can flag records that look like duplicates of each other, such as the same email written in two ways. Add a `duplicates:` block with rules to an object in your config file:

```yaml
        supplier:
          name: Supplier
          attributes:
            name:    {name: Supplier Name, type: string}
            country: {name: Country, type: string}
            email:   {name: Contact Email, type: email}
          duplicates:
            rules:
              - name: Same contact email
                fields: [email]
              - name: Same name and country
                fields: [name, country]
```

Restart miniMDM (or reload the config as an admin). The first start scans the existing records in the background. From then on every create, edit, import and inbound push is checked as it is saved. Nothing is ever blocked or merged: a record that matches another is simply flagged.

To see it work, create two suppliers with the emails `Anna@x.com` and `anna@x.com ` (case and spacing are ignored). You will then see:

- a **Duplicates** link in the top bar and an amber number beside *Supplier* in the sidebar (for anyone with write access),
- a yellow notice at the top of each of the two records, and
- both records, side by side, on the **Duplicates** page.

There, click **Not duplicates** if they really are different records, or open one of them and retire or delete it if they are the same. A dismissal holds until one of the values changes or a third matching record appears. See [Duplicate Detection](reference.md#duplicate-detection) for the rules, the options and what is compared.

## API Documentation

Explore all endpoints interactively at `http://localhost:8000/docs`.
