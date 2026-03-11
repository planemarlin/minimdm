# Quickstart Guide

This guide walks you through setting up miniMDM and managing your first master data object in under 10 minutes.

## 1. Start miniMDM

Follow the [installation guide](installation.md) then run:

```bash
uv run uvicorn app.main:app --reload
```

Open `http://localhost:8000` in your browser. You will see the home screen (empty until a config is loaded).

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

Alternatively, use the API directly:

```bash
curl -X POST http://localhost:8000/api/records/mycompany/supplier \
  -H "Content-Type: application/json" \
  -d '{"code":"S001","name":"Acme Ltd","country":"US","_reason":"Initial load"}'
```

## 4. Bulk Import

Prepare a CSV file `suppliers.csv`:

```csv
code,name,country,email
S001,Acme Ltd,US,acme@example.com
S002,Globex Corp,DE,info@globex.example
```

Import via the UI (click **Import** on the object list page) or via the API:

```bash
curl -X POST "http://localhost:8000/api/records/mycompany/supplier/import?format=csv" \
  -F "file=@suppliers.csv"
```

## 5. Search and Browse

Use the search bar on the object list page to filter records. Results update as you type.

## 6. View History and Revert

Click **View** on a record, then click **History** to see all versions. Click **Revert** next to any version to restore it.

## 7. Export Data

Click **Export CSV**, **Export TSV**, or **Export JSON** on the list page.

## 8. Audit Log

The full audit log is available via the API:

```bash
curl http://localhost:8000/api/audit?schema=mycompany&obj=supplier
```

## API Documentation

Explore all endpoints interactively at `http://localhost:8000/docs`.
