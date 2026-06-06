import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)


def test_object_list_loads(logged_in_page):
    """Company list page renders the correct title and finishes loading records."""
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("#total-count")).not_to_have_text("…")
    assert "Company" in logged_in_page.locator("h1.mdm-page-title").inner_text()


def test_new_record_button_visible(logged_in_page):
    """Admin sees the New record button on the list page."""
    logged_in_page.goto("/browser/company")
    logged_in_page.wait_for_selector("a.mdm-btn-primary")
    assert logged_in_page.is_visible("a.mdm-btn-primary")


def test_create_record_navigates_to_detail(logged_in_page):
    """Submitting the new record form redirects to the record detail page."""
    logged_in_page.goto("/browser/company/new")
    # Form fields are rendered by JS — wait for first input to appear.
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='code']", "ACME-01")
    logged_in_page.fill("input[name='name']", "Acme Corporation")
    logged_in_page.click("button[type='submit']")
    # After a successful save the app navigates to /{schema}/{obj}/{id}.
    # UUID pattern ensures we don't match "/new" itself
    logged_in_page.wait_for_url(re.compile(r"/browser/company/[0-9a-f-]{36}$"))


def test_created_record_appears_in_list(logged_in_page, api_client):
    """A record created via the API is visible in the browser list view."""
    r = api_client.post(
        "/api/records/browser/company",
        json={"code": "LIST-TEST", "name": "List Test Co"},
    )
    r.raise_for_status()

    logged_in_page.goto("/browser/company")
    logged_in_page.wait_for_selector("td:has-text('LIST-TEST')")
