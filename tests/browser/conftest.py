import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_TEST_PORT = 8765
_ADMIN_USER = "browser_admin"
_ADMIN_PASS = "BrowserAdmin123!"
_CONFIG_FILE = str(Path(__file__).parent / "test_config.yaml")

_skip_no_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping browser tests",
)


def _wait_for_server(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=1.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError(f"Server at {url} did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def live_server_url():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set – skipping browser tests")

    # Ensure _system schema + migrations exist and browser_admin user is present.
    from sqlalchemy import create_engine, text

    from app.core.auth import create_user, get_user_by_username
    from app.core.migrations import run_migrations

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS _system"))
        conn.commit()
    run_migrations(engine)
    if not get_user_by_username(engine, _ADMIN_USER):
        create_user(engine, _ADMIN_USER, _ADMIN_PASS, is_admin=True)
    engine.dispose()

    env = {
        **os.environ,
        "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
        "RATE_LIMIT_ENABLED": "false",
        "CONFIG_FILE": _CONFIG_FILE,
        "SECRET_KEY": "browser-test-secret-not-for-production",
    }
    proc = subprocess.Popen(
        [
            "uv", "run", "uvicorn", "app.main:app",
            "--host", "127.0.0.1",
            "--port", str(_TEST_PORT),
            "--log-level", "warning",
        ],
        cwd=str(_PROJECT_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base = f"http://127.0.0.1:{_TEST_PORT}"
    try:
        _wait_for_server(f"{base}/health")
    except RuntimeError:
        proc.terminate()
        pytest.fail("Browser test server did not become ready in time")

    yield base

    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(live_server_url):
    """Override pytest-playwright's base_url so page.goto('/path') resolves correctly."""
    return live_server_url


@pytest.fixture(scope="session")
def _db_engine(live_server_url):
    from sqlalchemy import create_engine
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_browser_records(_db_engine):
    """Truncate all browser-schema records before each test."""
    from sqlalchemy import text
    with _db_engine.connect() as conn:
        for tbl in (
            '"browser"."governed_item_history"',
            '"browser"."governed_item"',
            '"browser"."audited_item_history"',
            '"browser"."audited_item"',
            '"browser"."company_history"',
            '"browser"."company"',
        ):
            conn.execute(text(f"DELETE FROM {tbl}"))
        conn.execute(text("DELETE FROM _system.audit_log WHERE schema_name = 'browser'"))
        conn.commit()
    yield


@pytest.fixture(scope="session")
def api_client(live_server_url):
    """Authenticated httpx client for direct API calls in tests."""
    with httpx.Client(base_url=live_server_url) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": _ADMIN_USER, "password": _ADMIN_PASS},
        )
        r.raise_for_status()
        yield client


@pytest.fixture
def logged_in_page(page):
    """Return a Playwright page already authenticated as the browser admin."""
    page.goto("/login")
    page.fill("#username", _ADMIN_USER)
    page.fill("#password", _ADMIN_PASS)
    page.click("#login-btn")
    page.wait_for_url("**/")
    return page
