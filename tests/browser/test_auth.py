import os
import re

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)

_ADMIN_USER = "browser_admin"
_ADMIN_PASS = "BrowserAdmin123!"


def test_login_page_renders(page):
    """Login page loads without authentication."""
    page.goto("/login")
    assert "Sign in" in page.title()
    assert page.is_visible("#username")
    assert page.is_visible("#password")
    assert page.is_visible("#login-btn")


def test_login_success(page):
    """Valid credentials redirect to home and show the username in the header."""
    page.goto("/login")
    page.fill("#username", _ADMIN_USER)
    page.fill("#password", _ADMIN_PASS)
    page.click("#login-btn")
    page.wait_for_url("**/")
    assert page.locator(".mdm-top-user").inner_text() == _ADMIN_USER


def test_login_wrong_password(page):
    """Wrong password shows an inline error and keeps the user on /login."""
    page.goto("/login")
    page.fill("#username", _ADMIN_USER)
    page.fill("#password", "definitely-wrong-password")
    page.click("#login-btn")
    error = page.locator("#login-error")
    error.wait_for(state="visible")
    assert error.inner_text().strip() != ""
    assert "/login" in page.url


def test_logout(logged_in_page):
    """Clicking Logout signs the user out and redirects to /login."""
    logged_in_page.click(".mdm-top-logout")
    logged_in_page.wait_for_url(re.compile(r"/login"))


def test_protected_redirect(page):
    """Navigating to / while logged out redirects to /login."""
    page.goto("/")
    page.wait_for_url(re.compile(r"/login"))
