import os

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_SIDEBAR_COMPANY = ".mdm-side-item[href='/browser/company'] .mdm-counts"
_SIDEBAR_GOVERNED = ".mdm-side-item[href='/browser/governed_item'] .mdm-counts"


def test_sidebar_shows_active_count_per_object(logged_in_page, api_client):
    """Each sidebar entry carries the number of active records for that object."""
    for code in ("CNT-1", "CNT-2", "CNT-3"):
        api_client.post("/api/records/browser/company", json={"code": code}).raise_for_status()
    logged_in_page.goto("/browser/division")
    expect(logged_in_page.locator(f"{_SIDEBAR_COMPANY} .mdm-count-active")).to_have_text("3")
    expect(logged_in_page.locator(
        ".mdm-side-item[href='/browser/division'] .mdm-count-active"
    )).to_have_text("0")


def test_publisher_sees_pending_pill_in_sidebar(logged_in_page, api_client):
    """Admins (who may publish) get a pending-drafts pill next to the active count."""
    api_client.post("/api/records/browser/governed_item", json={"code": "PND-1"}).raise_for_status()
    api_client.post("/api/records/browser/governed_item", json={"code": "PND-2"}).raise_for_status()
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator(f"{_SIDEBAR_GOVERNED} .mdm-count-pending")).to_have_text("2")
    # no drafts on company → no pill
    expect(logged_in_page.locator(f"{_SIDEBAR_COMPANY} .mdm-count-active")).to_be_visible()
    expect(logged_in_page.locator(f"{_SIDEBAR_COMPANY} .mdm-count-pending")).to_have_count(0)


def test_home_page_cards_show_counts(logged_in_page, api_client):
    api_client.post("/api/records/browser/company", json={"code": "HOME-1"}).raise_for_status()
    api_client.post(
        "/api/records/browser/governed_item", json={"code": "HOME-2"}
    ).raise_for_status()
    logged_in_page.goto("/")
    company_row = logged_in_page.locator(".schema-card__objects li:has(a[href='/browser/company'])")
    expect(company_row.locator(".mdm-count-active")).to_have_text("1")
    governed_row = logged_in_page.locator(
        ".schema-card__objects li:has(a[href='/browser/governed_item'])"
    )
    expect(governed_row.locator(".mdm-count-pending")).to_have_text("1")


def test_count_is_formatted_with_browser_locale(logged_in_page):
    """Grouping follows the browser locale (the test browser runs as en-US)."""
    logged_in_page.goto("/")
    assert logged_in_page.evaluate("formatCount(1234)") == "1,234"
    assert logged_in_page.evaluate("formatCount(0)") == "0"
    # very large numbers are abbreviated
    assert logged_in_page.evaluate("formatCount(250000)") == "250K"


@pytest.mark.browser_context_args(locale="de-DE")
def test_count_grouping_follows_other_locale(logged_in_page):
    logged_in_page.goto("/")
    assert logged_in_page.evaluate("formatCount(1234)") == "1.234"


def test_hover_underlines_object_name_but_not_counts(logged_in_page, api_client):
    """Hovering a sidebar entry underlines the name only, never the counts beside it."""
    api_client.post("/api/records/browser/governed_item", json={"code": "HOV-1"}).raise_for_status()
    logged_in_page.goto("/browser/company")
    item = logged_in_page.locator(".mdm-side-item[href='/browser/governed_item']")
    expect(item.locator(".mdm-count-pending")).to_have_text("1")
    item.hover()

    def underlined(selector):
        return item.locator(selector).evaluate(
            "el => getComputedStyle(el).textDecorationLine"
        )

    assert underlined(".mdm-side-item-name") == "underline"
    assert underlined(".mdm-count-active") == "none"
    assert underlined(".mdm-count-pending") == "none"


def test_pending_link_is_first_in_top_bar_and_shows_count(logged_in_page, api_client):
    """The Pending link leads the top bar; its count is filled in without moving other items."""
    api_client.post("/api/records/browser/governed_item", json={"code": "TOP-1"}).raise_for_status()
    logged_in_page.goto("/browser/company")
    links = logged_in_page.locator(".mdm-top > a.mdm-top-link")
    expect(links.first).to_have_attribute("href", "/pending")
    count = logged_in_page.locator("#pending-badge-count")
    expect(count).to_have_text("1")
    users = logged_in_page.locator(".mdm-top-link[href='/admin/users']")
    before = users.bounding_box()["x"]
    api_client.post("/api/records/browser/governed_item", json={"code": "TOP-2"}).raise_for_status()
    logged_in_page.reload()
    expect(count).to_have_text("2")
    assert users.bounding_box()["x"] == before


def test_pending_link_stays_visible_without_drafts(logged_in_page):
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("#pending-badge-link")).to_be_visible()
    expect(logged_in_page.locator("#pending-badge-count")).to_be_hidden()
