import os
import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_UUID = re.compile(r"[0-9a-f-]{36}$")


def _tab_count(page, state):
    return page.locator(f"#state-seg [data-count-state='{state}']")


def _create(api_client, code):
    r = api_client.post("/api/records/browser/company", json={"code": code, "name": code})
    r.raise_for_status()
    return r.json()["id"]


def _seed(api_client):
    """3 active, then one edited (→ draft copy) and one retired, one deleted."""
    a = _create(api_client, "ST-1")
    b = _create(api_client, "ST-2")
    c = _create(api_client, "ST-3")
    d = _create(api_client, "ST-4")
    api_client.put(
        f"/api/records/browser/company/{a}", json={"name": "edited"}
    ).raise_for_status()
    api_client.post(f"/api/records/browser/company/{b}/retire").raise_for_status()
    api_client.delete(f"/api/records/browser/company/{d}").raise_for_status()
    return c


def test_state_tabs_show_a_count_each(logged_in_page, api_client):
    _seed(api_client)
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("2")
    expect(_tab_count(logged_in_page, "draft")).to_have_text("1")
    expect(_tab_count(logged_in_page, "retired")).to_have_text("1")
    expect(_tab_count(logged_in_page, "all")).to_have_text("4")
    # hovering gives the exact value
    assert _tab_count(logged_in_page, "all").get_attribute("title") == "4 records"


def test_zero_counts_are_shown(logged_in_page):
    logged_in_page.goto("/browser/company")
    for state in ("active", "draft", "retired", "all"):
        expect(_tab_count(logged_in_page, state)).to_have_text("0")
    expect(logged_in_page.locator("#deleted-count")).to_have_text("(0)")


def test_counts_do_not_change_when_switching_tabs(logged_in_page, api_client):
    _seed(api_client)
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("2")
    logged_in_page.click("#state-seg button[data-state='retired']")
    expect(logged_in_page.locator("#total-count")).to_have_text("1")
    expect(_tab_count(logged_in_page, "active")).to_have_text("2")
    expect(_tab_count(logged_in_page, "draft")).to_have_text("1")


def test_show_deleted_count_follows_the_selected_tab(logged_in_page, api_client):
    """The number is what ticking the checkbox would add to the current tab."""
    _seed(api_client)  # one deleted record, it was active
    logged_in_page.goto("/browser/company")
    deleted = logged_in_page.locator("#deleted-count")
    expect(deleted).to_have_text("(1)")
    total = logged_in_page.locator("#total-count")
    logged_in_page.click("#state-seg button[data-state='draft']")
    expect(deleted).to_have_text("(0)")
    expect(total).to_have_text("1")
    logged_in_page.click("#state-seg button[data-state='all']")
    expect(deleted).to_have_text("(1)")
    expect(total).to_have_text("4")
    # and the number matches the rows actually revealed
    logged_in_page.click("#state-seg button[data-state='active']")
    expect(total).to_have_text("2")
    logged_in_page.check("#show-deleted-toggle")
    expect(logged_in_page.locator("#total-count")).to_have_text("3")


def test_checkbox_label_reads_show_deleted_with_count(logged_in_page, api_client):
    _seed(api_client)
    logged_in_page.goto("/browser/company")
    expect(logged_in_page.locator("label.mdm-check")).to_have_text(
        re.compile(r"^\s*Show deleted\s*\(1\)\s*$")
    )


def test_counts_update_after_deleting_from_the_list(logged_in_page, api_client):
    """Deleting a row refreshes the tab counts, the deleted count and the sidebar."""
    _create(api_client, "DEL-1")
    _create(api_client, "DEL-2")
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("2")
    sidebar = logged_in_page.locator(
        ".mdm-side-item[href='/browser/company'] .mdm-count-active"
    )
    expect(sidebar).to_have_text("2")

    logged_in_page.on("dialog", lambda d: d.accept(""))
    row = logged_in_page.locator("#record-tbody tr").first
    row.hover()
    row.locator("button.danger").click()

    expect(_tab_count(logged_in_page, "active")).to_have_text("1")
    expect(logged_in_page.locator("#deleted-count")).to_have_text("(1)")
    expect(sidebar).to_have_text("1")


def test_counts_update_after_edit_and_publish_in_the_ui(logged_in_page, api_client):
    """Editing creates a draft (Draft +1); publishing consumes it again."""
    record_id = _create(api_client, "FLOW-1")
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "draft")).to_have_text("0")

    logged_in_page.goto(f"/browser/company/{record_id}/edit")
    logged_in_page.wait_for_selector("#form-fields input")
    logged_in_page.fill("input[name='name']", "Changed")
    logged_in_page.click("button[type='submit']")
    logged_in_page.wait_for_url(_UUID)
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("1")
    expect(_tab_count(logged_in_page, "draft")).to_have_text("1")

    logged_in_page.click("#state-seg button[data-state='draft']")
    expect(logged_in_page.locator("#record-tbody .mdm-pill-amber")).to_be_visible()
    logged_in_page.locator("#record-tbody tr").first.click()
    logged_in_page.wait_for_selector("#btn-publish:visible")
    logged_in_page.click("#btn-publish")
    logged_in_page.wait_for_selector("#publish-modal-backdrop:visible")
    logged_in_page.click("#publish-modal-backdrop .mdm-btn-primary")
    logged_in_page.wait_for_url(re.compile(rf"/{record_id}$"))

    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("1")
    expect(_tab_count(logged_in_page, "draft")).to_have_text("0")
    # the superseded edit draft is a workflow artifact, not a deleted record
    expect(logged_in_page.locator("#deleted-count")).to_have_text("(0)")


def test_restored_page_refreshes_counts(logged_in_page, api_client):
    """A list page restored from the back/forward cache must not show stale counts."""
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("0")
    _create(api_client, "BF-1")
    logged_in_page.evaluate(
        "window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))"
    )
    expect(_tab_count(logged_in_page, "active")).to_have_text("1")


def test_counts_use_browser_locale_and_abbreviate_large_numbers(logged_in_page):
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("0")
    logged_in_page.evaluate("""() => {
        recordList.stateCounts = {
          states: { active: 1234, draft: 0, retired: 250000 },
          deleted: { active: 1234, draft: 0, retired: 0 },
        };
        recordList.renderStateCounts();
    }""")
    expect(_tab_count(logged_in_page, "active")).to_have_text("1,234")
    expect(_tab_count(logged_in_page, "retired")).to_have_text("250K")
    expect(logged_in_page.locator("#deleted-count")).to_have_text("(1,234)")
    assert _tab_count(logged_in_page, "retired").get_attribute("title") == "250,000 records"


@pytest.mark.browser_context_args(locale="de-DE")
def test_count_grouping_follows_other_locale(logged_in_page):
    logged_in_page.goto("/browser/company")
    expect(_tab_count(logged_in_page, "active")).to_have_text("0")
    logged_in_page.evaluate("""() => {
        recordList.stateCounts = {
          states: { active: 1234, draft: 0, retired: 0 },
          deleted: { active: 0, draft: 0, retired: 0 },
        };
        recordList.renderStateCounts();
    }""")
    expect(_tab_count(logged_in_page, "active")).to_have_text("1.234")
