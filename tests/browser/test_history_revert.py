import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)


def test_history_page_shows_insert_version(logged_in_page, api_client):
    """A newly created record has a single Version 1 INSERT entry in its history."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "HIST-1", "name": "History Co"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}/history")
    logged_in_page.wait_for_selector("#history-container .history-list")
    history_text = logged_in_page.locator("#history-container").inner_text()
    assert "Version 1" in history_text
    assert "INSERT" in history_text


def test_history_shows_reason_from_edit(logged_in_page, api_client):
    """A reason supplied during an edit appears in the history entry."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "REASON-HIST", "name": "Before"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]
    # Edit via API with a reason — creates a draft alongside the active record.
    api_client.put(
        f"/api/records/browser/company/{record_id}",
        json={"name": "After", "_reason": "Correcting the name"},
    )

    # The draft has a different ID; view history on the original active record.
    logged_in_page.goto(f"/browser/company/{record_id}/history")
    logged_in_page.wait_for_selector("#history-container .history-list")
    # The INSERT entry for the active record should show the initial creation.
    # The draft has its own history (INSERT with the reason).
    # Fetch the draft ID from the API so we can check its history.
    drafts = api_client.get(
        "/api/records/browser/company",
        params={"state": "draft"},
    )
    drafts.raise_for_status()
    draft_records = drafts.json().get("records", [])
    assert draft_records, "Expected a draft record to exist"
    draft_id = draft_records[0]["_id"]

    logged_in_page.goto(f"/browser/company/{draft_id}/history")
    logged_in_page.wait_for_selector("#history-container .history-list")
    assert "Correcting the name" in logged_in_page.locator("#history-container").inner_text()


def test_revert_to_version_restores_values(logged_in_page, api_client):
    """Reverting to an earlier version restores the original attribute values."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "REVERT-ME", "name": "Original Name"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]
    # Edit via API to produce version 2 on the active record (direct update since state is draft).
    # Actually, editing an active record creates a separate draft. Use the draft flow
    # then publish to get the edit applied to the active record, creating a v2.
    edit_r = api_client.put(
        f"/api/records/browser/company/{record_id}",
        json={"name": "Edited Name"},
    )
    edit_r.raise_for_status()
    draft_id = edit_r.json().get("id") or edit_r.json().get("_id")
    # Publish the draft so the active record has version 2.
    api_client.post(f"/api/records/browser/company/{draft_id}/publish")

    # Now on the active record at version 2 ("Edited Name"). Revert to version 1.
    logged_in_page.goto(f"/browser/company/{record_id}/history")
    logged_in_page.wait_for_selector("#history-container .history-list")

    # revertToVersion uses window.prompt() for the reason — accept it via dialog handler.
    logged_in_page.on("dialog", lambda d: d.accept("restoring original"))
    # Click the Revert button for the earliest version (last in the list, desc order).
    revert_buttons = logged_in_page.locator("button:has-text('Revert')")
    revert_buttons.last.click()
    # After revert, navigates back to the detail page.
    logged_in_page.wait_for_url(re.compile(rf"/{record_id}$"))
    logged_in_page.wait_for_selector("#detail-container .mdm-attrs")
    assert "Original Name" in logged_in_page.locator("#detail-container").inner_text()
