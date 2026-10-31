import os

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_ADMIN_USER = "browser_admin"
_NEW_USER = "temp-browser-user"
_NEW_PASS = "TempPass123!secret"


@pytest.fixture
def cleanup_temp_user(_db_engine):
    """Delete the temp test user after each test that creates one."""
    yield
    from sqlalchemy import text
    with _db_engine.connect() as conn:
        conn.execute(text(f"DELETE FROM _system.users WHERE username = '{_NEW_USER}'"))
        conn.commit()


# ── Users page ───────────────────────────────────────────────────────────────


def test_users_page_loads(logged_in_page):
    """User Management page renders with the correct heading."""
    logged_in_page.goto("/admin/users")
    assert "User Management" in logged_in_page.locator("h1.mdm-page-title").inner_text()


def test_users_table_shows_admin(logged_in_page):
    """The browser_admin user appears in the users table."""
    logged_in_page.goto("/admin/users")
    logged_in_page.wait_for_selector(f"#users-tbody td:has-text('{_ADMIN_USER}')")


def test_users_summary_has_visible_separators(logged_in_page):
    """The "N users · N active · N admins" line keeps its parts apart."""
    logged_in_page.goto("/admin/users")
    logged_in_page.wait_for_selector("#users-meta .dot")
    parts = logged_in_page.locator("#users-meta > span:not(.dot)")
    assert parts.count() == 3
    boxes = [parts.nth(i).bounding_box() for i in range(3)]
    for left, right in zip(boxes, boxes[1:]):
        assert right["x"] - (left["x"] + left["width"]) >= 8
    assert logged_in_page.locator("#users-meta .dot").first.bounding_box()["width"] > 0


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(fg, bg):
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rgb(css_color):
    return [int(float(v)) for v in css_color[css_color.index("(") + 1 : -1].split(",")[:3]]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_admin_pill_is_readable(logged_in_page, theme):
    """The blue Admin pill keeps WCAG AA text contrast in both themes."""
    logged_in_page.goto("/admin/users")
    if logged_in_page.locator("html").get_attribute("data-theme") != theme:
        logged_in_page.click("#theme-btn")
    expect(logged_in_page.locator("html")).to_have_attribute("data-theme", theme)
    pill = logged_in_page.locator("#users-tbody .mdm-pill-blue", has_text="Admin").first
    pill.wait_for()
    colors = pill.evaluate(
        "el => [getComputedStyle(el).color, getComputedStyle(el).backgroundColor]"
    )
    assert _contrast(_rgb(colors[0]), _rgb(colors[1])) >= 4.5


def test_create_user_via_modal(logged_in_page, cleanup_temp_user):
    """Creating a user via the New user modal makes it appear in the table."""
    logged_in_page.goto("/admin/users")
    logged_in_page.wait_for_selector(f"#users-tbody td:has-text('{_ADMIN_USER}')")

    logged_in_page.click("button:has-text('New user')")
    logged_in_page.wait_for_selector("#new-user-modal:visible")
    logged_in_page.fill("#nu-username", _NEW_USER)
    logged_in_page.fill("#nu-password", _NEW_PASS)
    logged_in_page.click("button:has-text('Create user')")

    # Modal closes and the table reloads with the new user.
    logged_in_page.wait_for_selector(f"#users-tbody td:has-text('{_NEW_USER}')")


# ── Audit log page ────────────────────────────────────────────────────────────


def test_audit_log_page_loads(logged_in_page):
    """Audit Log page renders with the correct heading."""
    logged_in_page.goto("/admin/audit")
    assert "Audit Log" in logged_in_page.locator("h1.mdm-page-title").inner_text()


def test_audit_log_shows_data_changes(logged_in_page, api_client):
    """After creating a record, its INSERT entry appears in the audit log."""
    api_client.post(
        "/api/records/browser/company",
        json={"code": "AUDIT-1", "name": "Audit Test Co"},
    ).raise_for_status()

    logged_in_page.goto("/admin/audit")
    # Filter to the browser schema so results are deterministic.
    logged_in_page.select_option("#filter-schema", "browser")
    expect(logged_in_page.locator("#audit-total")).not_to_have_text("…")
    # The schema pill and INSERT badge should both be visible in the table.
    logged_in_page.wait_for_selector("#audit-tbody td:has-text('BROWSER')")
    assert "INSERT" in logged_in_page.locator("#audit-tbody").inner_text()


def test_audit_log_auth_events_tab(logged_in_page):
    """The Auth Events tab shows login activity for the browser_admin user."""
    logged_in_page.goto("/admin/audit")
    logged_in_page.click("button:has-text('Auth Events')")
    expect(logged_in_page.locator("#audit-total")).not_to_have_text("…")
    logged_in_page.wait_for_selector(f"#auth-tbody td:has-text('{_ADMIN_USER}')")
