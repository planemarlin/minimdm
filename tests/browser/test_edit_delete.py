import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_UUID = re.compile(r"/browser/company/[0-9a-f-]{36}$")


def test_edit_record_changes_values(logged_in_page, api_client):
    """Editing a record updates the values shown on the resulting draft detail page."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "EDIT-TEST", "name": "Original Name"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='name']", "Updated Name")
    logged_in_page.click("button[type='submit']")
    # Editing an active record creates a draft alongside; navigate to the draft.
    logged_in_page.wait_for_url(_UUID)
    logged_in_page.wait_for_selector("#detail-container .mdm-attrs")
    assert "Updated Name" in logged_in_page.locator("#detail-container").inner_text()


def test_edit_form_prepopulates_existing_values(logged_in_page, api_client):
    """The edit form pre-fills the current record values."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "PRE-FILL", "name": "Prefilled Name"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    assert logged_in_page.locator("input[name='code']").input_value() == "PRE-FILL"
    assert logged_in_page.locator("input[name='name']").input_value() == "Prefilled Name"


def test_delete_record_redirects_to_list(logged_in_page, api_client):
    """Confirming deletion in the modal redirects to the object list."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "DEL-ME", "name": "To Delete"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}")
    logged_in_page.wait_for_selector("#btn-delete:visible")
    logged_in_page.click("#btn-delete")
    logged_in_page.wait_for_selector("#delete-modal-backdrop:visible")
    logged_in_page.click("#delete-modal-backdrop .mdm-btn-danger")
    logged_in_page.wait_for_url("**/browser/company")


def test_deleted_record_hidden_from_default_list(logged_in_page, api_client):
    """A soft-deleted record does not appear in the default active list view."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "HIDE-ME", "name": "Hidden Co"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]
    api_client.delete(f"/api/records/browser/company/{record_id}")

    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("#total-count")).not_to_have_text("…")
    assert "HIDE-ME" not in logged_in_page.locator("#record-tbody").inner_text()


def test_delete_with_reason_appears_in_history(logged_in_page, api_client):
    """A reason supplied at deletion is stored and visible in the record history."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "REASON-DEL", "name": "Reason Co"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}")
    logged_in_page.wait_for_selector("#btn-delete:visible")
    logged_in_page.click("#btn-delete")
    logged_in_page.wait_for_selector("#delete-modal-backdrop:visible")
    logged_in_page.fill("#delete-reason", "No longer needed")
    logged_in_page.click("#delete-modal-backdrop .mdm-btn-danger")
    logged_in_page.wait_for_url("**/browser/company")

    # History endpoint works for deleted records — navigate directly.
    logged_in_page.goto(f"/browser/company/{record_id}/history")
    logged_in_page.wait_for_selector("#history-container .history-list")
    assert "No longer needed" in logged_in_page.locator("#history-container").inner_text()


def test_reason_required_shows_error_when_missing(logged_in_page, api_client):
    """Saving an audited_item without a reason returns a server error shown inline."""
    r = api_client.post(
        "/api/records/browser/audited_item",
        json={"code": "NO-REASON", "_reason": "initial creation"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/audited_item/{record_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    # Deliberately leave the _reason field empty and submit.
    logged_in_page.click("button[type='submit']")
    # Server returns 422; the JS shows an inline error and stays on the edit page.
    logged_in_page.wait_for_selector(".alert.alert-error")
    assert "/edit" in logged_in_page.url
