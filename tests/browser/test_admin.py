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


def test_audit_log_search_box_is_not_a_nested_input(logged_in_page):
    """The user filter is a bare input inside the .mdm-search wrapper.

    The global ``input[type="text"]`` rule used to leak into it, which drew a
    second border, padding and focus ring inside the wrapper's own.
    """
    logged_in_page.goto("/admin/audit")
    box = logged_in_page.locator("#filter-user")
    box.focus()
    style = box.evaluate(
        """el => {
            const s = getComputedStyle(el);
            return {
                border: s.borderTopWidth,
                padding: s.paddingLeft,
                shadow: s.boxShadow,
                radius: s.borderTopLeftRadius,
            };
        }"""
    )
    assert style == {"border": "0px", "padding": "0px", "shadow": "none", "radius": "0px"}


def test_audit_log_auth_filters_share_one_row(logged_in_page):
    """The Auth Events action select keeps its natural width.

    The global ``select { width: 100% }`` rule used to stretch it across the
    whole toolbar and push the other filters onto their own rows.
    """
    logged_in_page.goto("/admin/audit")
    logged_in_page.click("button:has-text('Auth Events')")
    select = logged_in_page.locator("#auth-filter-action")
    search = logged_in_page.locator("#auth-filter-user")
    expect(select).to_be_visible()
    toolbar_width = select.evaluate("el => el.parentElement.getBoundingClientRect().width")
    select_box = select.bounding_box()
    search_box = search.bounding_box()
    assert select_box["width"] < toolbar_width * 0.8
    # Same row: the search box starts to the right of the select, not below it.
    assert search_box["x"] > select_box["x"] + select_box["width"]


@pytest.mark.parametrize("width", [700, 1000, 1400])
@pytest.mark.parametrize(
    "tab, prefix", [("Data Changes", "filter"), ("Auth Events", "auth-filter")]
)
def test_audit_log_date_range_has_its_own_row(logged_in_page, width, tab, prefix):
    """From and To share one row below the filters, at every window width.

    They used to be ordinary flex items of the toolbar, so resizing the window
    moved them between the filter row and a row of their own.
    """
    page = logged_in_page
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/admin/audit")
    page.click(f"button:has-text('{tab}')")
    boxes = {
        name: page.locator(f"#{prefix}-{name}").bounding_box()
        for name in ("user", "from", "to")
    }
    action = page.locator("#filter-action" if prefix == "filter" else "#auth-filter-action")
    boxes["action"] = action.bounding_box()
    # From and To are on the same row ...
    assert abs(boxes["from"]["y"] - boxes["to"]["y"]) < 2
    # ... and that row is below every filter control, never beside one.
    filters_bottom = max(
        boxes[name]["y"] + boxes[name]["height"] for name in ("user", "action")
    )
    assert boxes["from"]["y"] >= filters_bottom
