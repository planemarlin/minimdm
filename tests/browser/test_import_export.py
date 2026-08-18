import os

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_CSV = b"code,name\nIMP-A,Import Co A\nIMP-B,Import Co B\n"
_TSV = b"code\tname\nIMP-C\tImport Co C\nIMP-D\tImport Co D\n"


def test_export_csv_triggers_download(logged_in_page, api_client):
    """Clicking Export CSV in the Tools menu triggers a .csv file download."""
    api_client.post(
        "/api/records/browser/company",
        json={"code": "EXP-1", "name": "Export Co"},
    ).raise_for_status()

    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("#total-count")).not_to_have_text("…")

    with logged_in_page.expect_download() as dl_info:
        logged_in_page.click("#tools-btn")
        logged_in_page.click("button:has-text('Export CSV')")
    download = dl_info.value
    assert download.suggested_filename.endswith(".csv")


def test_import_csv_adds_records(logged_in_page):
    """Importing a CSV file via the import modal adds records visible in the list."""
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("#total-count")).not_to_have_text("…")

    # Open import modal via the Tools menu.
    logged_in_page.click("#tools-btn")
    logged_in_page.click("button:has-text('Import…')")
    logged_in_page.wait_for_selector("#import-modal:visible")

    # Set the file on the hidden input — triggers the onchange → importFile().
    logged_in_page.set_input_files(
        "#import-file",
        files=[{"name": "records.csv", "mimeType": "text/csv", "buffer": _CSV}],
    )

    # importFile closes the modal and writes a success message to #import-status.
    expect(logged_in_page.locator("#import-status")).to_contain_text("inserted")
    # Both records should now appear in the list.
    logged_in_page.wait_for_selector("td:has-text('IMP-A')")
    logged_in_page.wait_for_selector("td:has-text('IMP-B')")


def test_import_tsv_adds_records(logged_in_page):
    """Importing a TSV file adds records the same as CSV."""
    logged_in_page.goto("/browser/company")
    logged_in_page.click("#tools-btn")
    logged_in_page.click("button:has-text('Import…')")
    logged_in_page.wait_for_selector("#import-modal:visible")

    logged_in_page.set_input_files(
        "#import-file",
        files=[{"name": "records.tsv", "mimeType": "text/tab-separated-values", "buffer": _TSV}],
    )

    expect(logged_in_page.locator("#import-status")).to_contain_text("inserted")
    logged_in_page.wait_for_selector("td:has-text('IMP-C')")
    logged_in_page.wait_for_selector("td:has-text('IMP-D')")


def test_import_non_json_error_response_shows_message(logged_in_page):
    """If the server ever answers an import with a non-JSON error body (e.g. a
    proxy timeout page or an unhandled 500), the UI must show an error instead
    of hanging on 'Importing…' forever."""
    logged_in_page.route(
        "**/api/records/browser/company/import**",
        lambda route: route.fulfill(
            status=500, content_type="text/plain", body="Internal Server Error"
        ),
    )

    logged_in_page.goto("/browser/company")
    logged_in_page.click("#tools-btn")
    logged_in_page.click("button:has-text('Import…')")
    logged_in_page.wait_for_selector("#import-modal:visible")

    logged_in_page.set_input_files(
        "#import-file",
        files=[{"name": "records.csv", "mimeType": "text/csv", "buffer": _CSV}],
    )

    status = logged_in_page.locator("#import-status")
    expect(status).not_to_contain_text("Importing…", timeout=10000)
    expect(status).to_contain_text("failed")


def test_import_non_utf8_file_shows_error(logged_in_page):
    """Uploading a non-UTF-8 CSV (e.g. Excel Windows-1252 export) must surface
    a clear error message rather than hanging on 'Importing…' forever."""
    bad_csv = "code,name\nIMP-E,Caf\xe9 Corp\n".encode("windows-1252")

    logged_in_page.goto("/browser/company")
    logged_in_page.click("#tools-btn")
    logged_in_page.click("button:has-text('Import…')")
    logged_in_page.wait_for_selector("#import-modal:visible")

    logged_in_page.set_input_files(
        "#import-file",
        files=[{"name": "records.csv", "mimeType": "text/csv", "buffer": bad_csv}],
    )

    status = logged_in_page.locator("#import-status")
    expect(status).not_to_contain_text("Importing…", timeout=10000)
    expect(status).to_contain_text("utf-8", ignore_case=True)
