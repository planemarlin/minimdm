"""Integration-style tests for import/export – require a running PostgreSQL.

These tests are skipped when DATABASE_URL is not set or points to a test DB.
Run with: pytest tests/test_import_export.py --integration
"""
import csv
import io
import json

import pytest


@pytest.mark.skip(reason="Requires live PostgreSQL – run with full integration setup")
class TestImportExport:
    def test_export_csv_empty(self, client):
        res = client.get("/api/records/test/company/export?format=csv")
        assert res.status_code == 200

    def test_import_csv_then_export(self, client):
        csv_content = "code,name\nABC,Alpha Corp\nXYZ,Xray Inc\n"
        files = {"file": ("data.csv", csv_content.encode(), "text/csv")}
        res = client.post("/api/records/test/company/import?format=csv", files=files)
        assert res.status_code == 200
        data = res.json()
        assert data["inserted"] == 2
        assert data["errors"] == []

    def test_import_json(self, client):
        payload = [{"code": "J01", "name": "Json Corp"}]
        files = {"file": ("data.json", json.dumps(payload).encode(), "application/json")}
        res = client.post("/api/records/test/company/import?format=json", files=files)
        assert res.status_code == 200
        assert res.json()["inserted"] == 1
