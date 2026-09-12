"""Browser coverage for the config-based validation rules confirm/override UI.

The backend contract (422 + confirmation_required, ?confirm_validation_override=true,
_validation_status) is fully covered by tests/test_validation_rules.py. This file
covers the piece only a real browser can exercise: the New/Edit record form's
banner, "Save anyway", and "Cancel" buttons in app.js's loadRecordForm().
"""

import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)


def test_violation_shows_banner_with_save_anyway_and_cancel(logged_in_page):
    logged_in_page.goto("/browser/governed_item/new")
    logged_in_page.wait_for_selector("#form-fields input[name='code']")
    logged_in_page.fill("input[name='code']", "GOV-BROWSER-1")
    logged_in_page.fill("input[name='unit_price']", "-5")
    logged_in_page.click("button[type='submit']")

    banner = logged_in_page.locator(".validation-override-banner")
    banner.wait_for(timeout=5000)
    assert "Unit Price" in banner.inner_text()
    assert "Save anyway" in banner.inner_text()

    # Cancel removes the banner and does not save the record.
    banner.locator("button[data-action='override-cancel']").click()
    assert logged_in_page.locator(".validation-override-banner").count() == 0
    assert "/new" in logged_in_page.url


def test_save_anyway_persists_record_and_shows_invalid_badge(logged_in_page):
    logged_in_page.goto("/browser/governed_item/new")
    logged_in_page.wait_for_selector("#form-fields input[name='code']")
    logged_in_page.fill("input[name='code']", "GOV-BROWSER-2")
    logged_in_page.fill("input[name='unit_price']", "-5")
    logged_in_page.click("button[type='submit']")

    banner = logged_in_page.locator(".validation-override-banner")
    banner.wait_for(timeout=5000)
    banner.locator("button[data-action='override-save']").click()

    logged_in_page.wait_for_url(re.compile(r"/browser/governed_item/[0-9a-f-]{36}$"))
    logged_in_page.wait_for_selector(".mdm-pill:has-text('Invalid')")
