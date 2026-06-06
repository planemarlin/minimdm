import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_UUID = re.compile(r"[0-9a-f-]{36}$")


def _wait_for_detail(page):
    """Wait for the detail page to finish loading (attributes rendered, action buttons set)."""
    page.wait_for_selector("#detail-container .mdm-attrs")
    # The JS sets button visibility in the same call that writes .mdm-attrs.
    # Waiting for the state pill to appear confirms the full render is done.
    page.wait_for_selector(".mdm-pill")


def _state_pill(page):
    """Return the text of the state pill on the current detail page."""
    return page.locator(".mdm-pill").first.inner_text()


def test_edit_active_creates_draft(logged_in_page, api_client):
    """Editing an active record creates a draft alongside it with a different ID."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "DRAFT-TEST", "name": "Active Co"},
    )
    r.raise_for_status()
    active_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{active_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='name']", "Edited Co")
    logged_in_page.click("button[type='submit']")
    logged_in_page.wait_for_url(_UUID)

    # The draft has a different UUID from the original active record.
    draft_id = logged_in_page.url.rstrip("/").split("/")[-1]
    assert draft_id != active_id

    _wait_for_detail(logged_in_page)
    assert _state_pill(logged_in_page) == "Draft"


def test_draft_shows_publish_button(logged_in_page, api_client):
    """A draft record's detail page shows the Publish button."""
    r = api_client.post("/api/records/browser/company", json={"code": "PUB-BTN", "name": "Co"})
    r.raise_for_status()
    active_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{active_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='name']", "Draft Co")
    logged_in_page.click("button[type='submit']")
    logged_in_page.wait_for_url(_UUID)
    _wait_for_detail(logged_in_page)

    expect(logged_in_page.locator("#btn-publish")).to_be_visible()


def test_publish_draft_restores_active_state(logged_in_page, api_client):
    """Publishing a draft navigates to the original active record (Retire button now visible)."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "PUB-FLOW", "name": "Original"},
    )
    r.raise_for_status()
    active_id = r.json()["id"]

    # Edit → draft
    logged_in_page.goto(f"/browser/company/{active_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='name']", "Updated")
    logged_in_page.click("button[type='submit']")
    logged_in_page.wait_for_url(_UUID)
    _wait_for_detail(logged_in_page)

    # Publish draft — wait for button to be visible before clicking (JS sets this async).
    logged_in_page.wait_for_selector("#btn-publish:visible")
    logged_in_page.click("#btn-publish")
    logged_in_page.wait_for_selector("#publish-modal-backdrop:visible")
    logged_in_page.fill("#publish-reason", "Approved change")
    # Use the modal-scoped selector to avoid matching the header Publish button.
    logged_in_page.click("#publish-modal-backdrop .mdm-btn-primary")

    # After publish, lands on the master record (original active_id).
    logged_in_page.wait_for_url(re.compile(rf"/{active_id}$"))
    _wait_for_detail(logged_in_page)
    assert _state_pill(logged_in_page) == "Active · Master"
    expect(logged_in_page.locator("#btn-retire")).to_be_visible()


def test_retire_active_record(logged_in_page, api_client):
    """Retiring an active record transitions it to Retired and hides Edit/Retire buttons."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "RETIRE-ME", "name": "Going Away"},
    )
    r.raise_for_status()
    record_id = r.json()["id"]

    logged_in_page.goto(f"/browser/company/{record_id}")
    # Wait explicitly for the Retire button to become visible (JS-driven, async after fetch).
    logged_in_page.wait_for_selector("#btn-retire:visible")
    logged_in_page.click("#btn-retire")
    logged_in_page.wait_for_selector("#retire-modal-backdrop:visible")
    logged_in_page.fill("#retire-reason", "End of life")
    # Use the modal-scoped selector to avoid ambiguity with the header button.
    logged_in_page.click("#retire-modal-backdrop .mdm-btn-danger")

    # submitRetire calls window.location.reload() on success. The page still has the old
    # "Active · Master" pill until the reload completes and JS re-renders — use expect()
    # to auto-retry until the pill transitions to "Retired".
    expect(logged_in_page.locator(".mdm-pill").first).to_have_text("Retired")
    expect(logged_in_page.locator("#btn-retire")).to_be_hidden()
    expect(logged_in_page.locator("#btn-edit")).to_be_hidden()


def test_governed_item_creates_as_draft(logged_in_page):
    """Creating a governed_item (requires_draft: true) produces a Draft record directly."""
    logged_in_page.goto("/browser/governed_item/new")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='code']", "GOV-001")
    logged_in_page.click("button[type='submit']")
    logged_in_page.wait_for_url(re.compile(r"/browser/governed_item/[0-9a-f-]{36}$"))
    _wait_for_detail(logged_in_page)

    assert _state_pill(logged_in_page) == "Draft"
    expect(logged_in_page.locator("#btn-publish")).to_be_visible()
