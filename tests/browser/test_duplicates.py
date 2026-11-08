"""Duplicates UI in a real browser: top-bar link and counts, the review page (dismiss,
reopen, rescan), the notice on a record's page and the import message.

The browser suite only logs in as the admin, so who may dismiss or rescan is covered by the
API and template tests (test_api_duplicates_review.py, test_duplicates_page.py).
"""
import os

import pytest
from playwright.sync_api import expect
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_SECTION = "#browser-contact"
_SIDEBAR_PILL = ".mdm-side-item[href='/browser/contact'] .mdm-count-duplicates"
_TOP_COUNT = "#duplicates-badge-count"


def _contact(api_client, name, email=None, phone=None):
    res = api_client.post(
        "/api/records/browser/contact", json={"name": name, "email": email, "phone": phone}
    )
    res.raise_for_status()
    return res.json()["id"]


def _pair(api_client, email="anna@x.com"):
    return _contact(api_client, "Anna Berg", email), _contact(api_client, "Anna B.", email.upper())


def _confirm(page, label):
    """Click the confirm button of the open dialog."""
    dialog = page.locator("#mdm-dlg")
    expect(dialog).to_be_visible()
    expect(dialog.locator("#mdm-dlg-ok")).to_have_text(label)
    dialog.locator("#mdm-dlg-ok").click()
    expect(dialog).to_have_count(0)


def test_sidebar_and_top_bar_show_the_open_duplicate_count(logged_in_page, api_client):
    _pair(api_client)
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator(_SIDEBAR_PILL)).to_have_text("1")
    expect(logged_in_page.locator(_TOP_COUNT)).to_have_text("1")
    expect(logged_in_page.locator(_TOP_COUNT)).to_be_visible()


def test_no_pill_or_count_without_duplicates(logged_in_page, api_client):
    _contact(api_client, "Solo", "solo@x.com")
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator(
        ".mdm-side-item[href='/browser/contact'] .mdm-count-active")).to_have_text("1")
    expect(logged_in_page.locator(_SIDEBAR_PILL)).to_have_count(0)
    expect(logged_in_page.locator(_TOP_COUNT)).to_be_hidden()
    # ... but the link itself is always there
    expect(logged_in_page.locator("#duplicates-badge-link")).to_be_visible()


def test_the_top_bar_does_not_move_when_the_count_appears(logged_in_page, api_client):
    """Filling in the count must not shift any other top-bar item (the Pending link had
    this flicker once)."""
    page = logged_in_page
    items = ["#duplicates-badge-link", "#pending-badge-link", ".mdm-top-link[href='/admin/users']",
             ".mdm-top-link[href='/admin/audit']", "#theme-btn", ".mdm-top-logout"]

    def boxes():
        return [page.locator(sel).bounding_box() for sel in items]

    page.goto("/browser/company")
    expect(page.locator("#duplicates-badge-link")).to_be_visible()
    expect(page.locator(
        ".mdm-side-item[href='/browser/contact'] .mdm-count-active")).to_be_visible()
    without = boxes()
    assert all(b is not None for b in without)

    _pair(api_client)
    page.goto("/browser/company")
    expect(page.locator(_TOP_COUNT)).to_be_visible()
    assert boxes() == without


def test_review_page_lists_the_group_and_dismisses_and_reopens_it(logged_in_page, api_client):
    page = logged_in_page
    _pair(api_client)
    page.goto("/duplicates")

    group = page.locator(f"{_SECTION} .dup-group")
    expect(group).to_have_count(1)
    expect(group.locator(".dup-rule")).to_have_text("Same email")
    expect(group.locator(".dup-count")).to_have_text("2 records")
    # The header names the rule only: the normalised match key ("anna x com") is internal
    expect(group.locator(".dup-group-head")).not_to_contain_text("anna x com")
    expect(group.locator("tbody tr")).to_have_count(2)
    expect(group).to_contain_text("Anna Berg")
    expect(group).to_contain_text("ANNA@X.COM")        # values as entered
    # Only the column this rule compares is marked
    expect(group.locator("th.dup-rulecol")).to_have_count(1)
    expect(group.locator("th.dup-rulecol")).to_have_text("EMAIL")
    expect(page.locator(f"{_SECTION} .dup-section-count")).to_have_text("1 group")
    expect(page.locator("#dup-open-count")).to_have_text("1")
    expect(page.locator("#dup-dismissed-count")).to_have_text("")

    group.locator("[data-dup-act='dismiss']").click()
    page.fill("#mdm-dlg-reason", "Mother and daughter")
    _confirm(page, "Dismiss")
    expect(page.locator(f"{_SECTION} .dup-group")).to_have_count(0)
    expect(page.locator(f"{_SECTION} .dup-groups")).to_contain_text("No open duplicates")
    expect(page.locator(_TOP_COUNT)).to_be_hidden()
    expect(page.locator(_SIDEBAR_PILL)).to_have_count(0)
    expect(page.locator("#dup-open-count")).to_have_text("")
    expect(page.locator("#dup-dismissed-count")).to_have_text("1")

    page.click("#dup-status-seg button[data-status='dismissed']")
    dismissed = page.locator(f"{_SECTION} .dup-group")
    expect(dismissed).to_have_count(1)
    expect(dismissed).to_contain_text("Mother and daughter")
    expect(dismissed).to_contain_text("Dismissed by browser_admin")

    dismissed.locator("[data-dup-act='reopen']").click()
    _confirm(page, "Reopen")
    expect(page.locator(f"{_SECTION} .dup-groups")).to_contain_text("Nothing has been dismissed")
    expect(page.locator("#dup-dismissed-count")).to_have_text("")

    page.click("#dup-status-seg button[data-status='open']")
    expect(page.locator(f"{_SECTION} .dup-group")).to_have_count(1)
    expect(page.locator(_TOP_COUNT)).to_have_text("1")
    expect(page.locator("#dup-open-count")).to_have_text("1")


def test_section_headings_look_like_the_pending_page(logged_in_page, api_client):
    """Plain text schema tag and counts (no pills), and a title that is never underlined."""
    page = logged_in_page
    heading_style = "e => { const s = getComputedStyle(e); return [s.fontSize, s.fontWeight]; }"
    _pair(api_client)
    page.goto("/duplicates")
    head = page.locator(f"{_SECTION} .dup-section-head")
    expect(head.locator(".schema")).to_have_text("BROWSER")
    expect(head.locator(".mdm-pill")).to_have_count(0)
    expect(page.locator(f"{_SECTION} .dup-group-head .mdm-pill")).to_have_count(0)

    title = head.locator(".dup-section-title a")
    title.hover()
    expect(title).to_have_css("text-decoration-line", "none")
    own_style = page.locator(f"{_SECTION} .dup-section-title").evaluate(heading_style)

    # The Pending page's section headings, for comparison
    api_client.post(
        "/api/records/browser/governed_item", json={"code": "PEND-1"}
    ).raise_for_status()
    page.goto("/pending")
    pending_title = page.locator("h2 a").first
    pending_title.hover()
    expect(pending_title).to_have_css("text-decoration-line", "none")
    assert page.locator("h2").first.evaluate(heading_style) == own_style


def test_rescan_now_is_the_primary_button_only_in_the_stale_banner(
        logged_in_page, api_client, _db_engine):
    page = logged_in_page
    _pair(api_client)
    page.goto("/duplicates")
    expect(page.locator(f"{_SECTION} .dup-rescan-btn")).not_to_have_class("mdm-btn-primary")
    with _db_engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM _system.duplicate_scans "
            "WHERE schema_name = 'browser' AND object_name = 'contact'"))
    page.goto("/duplicates")
    expect(page.locator(f"{_SECTION} [data-dup-act='rescan']")).to_have_class(
        "mdm-btn mdm-btn-primary")
    page.locator(f"{_SECTION} [data-dup-act='rescan']").click()
    _confirm(page, "Rescan")      # leave the object scanned for the tests that follow


def test_cancelling_the_dialog_changes_nothing(logged_in_page, api_client):
    page = logged_in_page
    _pair(api_client)
    page.goto("/duplicates")
    page.locator(f"{_SECTION} [data-dup-act='dismiss']").click()
    expect(page.locator("#mdm-dlg")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#mdm-dlg")).to_have_count(0)
    expect(page.locator(f"{_SECTION} .dup-group")).to_have_count(1)


def test_a_group_of_three_can_dismiss_one_record(logged_in_page, api_client):
    page = logged_in_page
    _contact(api_client, "One", "same@x.com")
    _contact(api_client, "Two", "SAME@x.com")
    _contact(api_client, "Three", " same@x.com ")
    page.goto("/duplicates")

    own = page.locator(f"{_SECTION} [data-dup-act='dismiss'][title]")
    expect(own).to_have_count(3)             # one per row, only offered for 3+ records
    own.first.click()
    _confirm(page, "Dismiss")
    expect(page.locator(f"{_SECTION} .dup-group tbody tr")).to_have_count(3)
    expect(page.locator(f"{_SECTION} .dup-row--dismissed")).to_have_count(1)
    expect(own).to_have_count(0)             # two open records left: group-level action only


def test_record_page_shows_the_notice_and_can_dismiss_it(logged_in_page, api_client):
    page = logged_in_page
    first, _second = _pair(api_client)
    page.goto(f"/browser/contact/{first}")

    banner = page.locator("#duplicate-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Possible duplicate")
    # The rule, the record's own email as entered (not the normalised "anna x com"), and
    # who else has it
    expect(banner).to_contain_text("Same email: anna@x.com")
    expect(banner).not_to_contain_text("anna x com")
    expect(banner).to_contain_text("Anna B. (Active)")
    expect(banner.locator("a:has-text('Review duplicates')")).to_have_attribute(
        "href", "/duplicates#browser-contact")

    banner.locator("#dup-banner-dismiss").click()
    _confirm(page, "Dismiss")
    expect(banner).to_be_hidden()


def test_record_page_without_duplicates_has_no_notice(logged_in_page, api_client):
    solo = _contact(api_client, "Solo", "solo@x.com")
    logged_in_page.goto(f"/browser/contact/{solo}")
    expect(logged_in_page.locator(".mdm-attrs")).to_be_visible()
    expect(logged_in_page.locator("#duplicate-banner")).to_be_hidden()


def test_rescan_from_the_review_page(logged_in_page, api_client):
    page = logged_in_page
    _pair(api_client)
    page.goto("/duplicates")
    expect(page.locator(f"{_SECTION} .dup-group")).to_have_count(1)

    page.locator(f"{_SECTION} .dup-rescan-btn").click()
    dialog = page.locator("#mdm-dlg")
    expect(dialog).to_contain_text("Rescan Contact for duplicates")
    expect(dialog).to_contain_text("Reads 2 records")
    expect(dialog).to_contain_text("Last scan:")
    dialog.locator("#mdm-dlg-ok").click()
    expect(dialog).to_have_count(0)

    expect(page.locator(f"{_SECTION} .dup-section-meta")).to_contain_text("2 records")
    expect(page.locator(f"{_SECTION} .dup-scan-banner .dup-banner")).to_have_count(0)
    expect(page.locator(f"{_SECTION} .dup-group")).to_have_count(1)


def test_stale_flags_banner_offers_a_rescan(logged_in_page, api_client, _db_engine):
    page = logged_in_page
    _pair(api_client)
    with _db_engine.begin() as conn:     # as if the rules had changed since the last scan
        conn.execute(text(
            "DELETE FROM _system.duplicate_scans "
            "WHERE schema_name = 'browser' AND object_name = 'contact'"))
    page.goto("/duplicates")

    banner = page.locator(f"{_SECTION} .dup-scan-banner .dup-banner")
    expect(banner).to_contain_text("Flags may be out of date")
    expect(page.locator(f"{_SECTION} .dup-section-meta")).to_have_text("Not scanned yet")

    banner.locator("[data-dup-act='rescan']").click()
    expect(page.locator("#mdm-dlg")).to_contain_text("has not been scanned yet")
    _confirm(page, "Rescan")
    expect(page.locator(f"{_SECTION} .dup-scan-banner .dup-banner")).to_have_count(0)
    expect(page.locator(f"{_SECTION} .dup-section-meta")).to_contain_text("Last scan")


def test_scan_events_and_dismissals_show_in_the_audit_log(logged_in_page, api_client):
    page = logged_in_page
    _pair(api_client)
    page.goto("/duplicates")
    page.locator(f"{_SECTION} .dup-rescan-btn").click()
    page.locator("#mdm-dlg-ok").click()
    expect(page.locator(f"{_SECTION} .dup-section-meta")).to_contain_text("2 records")

    page.goto("/admin/audit")
    page.click("#tab-auth-btn")
    page.select_option("#auth-filter-action", "DUPLICATE_SCAN")
    row = page.locator("#auth-tbody tr").first
    expect(row).to_contain_text("DUPLICATE_SCAN")
    expect(row).to_contain_text("browser.contact")
    expect(row).to_contain_text("2 records")


def test_import_message_links_to_the_duplicates_page(logged_in_page):
    page = logged_in_page
    page.goto("/browser/contact")
    expect(page.locator("#total-count")).not_to_have_text("…")
    page.click("#tools-btn")
    page.click("button:has-text('Import…')")
    page.wait_for_selector("#import-modal:visible")
    page.set_input_files("#import-file", files=[{
        "name": "contacts.csv", "mimeType": "text/csv",
        "buffer": b"name,email\nA,x@x.com\nB,X@x.com\n"}])

    status = page.locator("#import-status")
    expect(status).to_contain_text("inserted")
    expect(status.locator("a:has-text('Review possible duplicates')")).to_have_attribute(
        "href", "/duplicates#browser-contact")
    expect(page.locator(_SIDEBAR_PILL)).to_have_text("1")
