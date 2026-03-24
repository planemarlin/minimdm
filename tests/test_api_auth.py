"""Integration tests for authentication and user management endpoints.

Requires TEST_DATABASE_URL to be set; the entire module is skipped otherwise.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set – skipping integration tests",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_engine():
    from app.main import app as fastapi_app
    return fastapi_app.state.table_manager.engine


def _delete_user(engine, username: str):
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM _system.users WHERE username = :u"), {"u": username})
        conn.commit()


def _no_auth_headers():
    """Override the session auth header so the request is unauthenticated."""
    return {"Authorization": "invalid"}


def _non_admin_headers():
    """Return headers with a valid but non-admin token.

    Creates 'plain_user' in the database on first call so is_user_active() passes.
    """
    from app.core.auth import create_token, create_user, get_user_by_username
    engine = _get_engine()
    user = get_user_by_username(engine, "plain_user")
    if not user:
        result = create_user(engine, "plain_user", "plain_password")
        user_id = result["id"]
    else:
        user_id = str(user["id"])
    token = create_token(user_id, "plain_user", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

def test_unauthenticated_api_request_returns_401(client):
    """API routes must return 401 when no valid token is provided."""
    res = client.get("/api/records/test/company", headers=_no_auth_headers())
    assert res.status_code == 401


def test_login_page_is_publicly_accessible(client):
    """The login page must be reachable without a token."""
    # The middleware allows /login unconditionally; even with a valid token it
    # still returns 200 (no redirect) because it's a public path.
    res = client.get("/login")
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Login / logout
# ---------------------------------------------------------------------------

def test_login_success(client):
    """Create a user and verify login returns 200 with username."""
    engine = _get_engine()
    from app.core.auth import create_user
    create_user(engine, "auth_test_user", "correct_password")
    try:
        res = client.post(
            "/api/auth/login", json={"username": "auth_test_user", "password": "correct_password"}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["username"] == "auth_test_user"
        assert "is_admin" in data
    finally:
        _delete_user(engine, "auth_test_user")


def test_login_wrong_password_returns_401(client):
    engine = _get_engine()
    from app.core.auth import create_user
    create_user(engine, "auth_wp_user", "rightpass")
    try:
        res = client.post(
            "/api/auth/login", json={"username": "auth_wp_user", "password": "wrongpass"}
        )
        assert res.status_code == 401
    finally:
        _delete_user(engine, "auth_wp_user")


def test_login_unknown_user_returns_401(client):
    res = client.post("/api/auth/login", json={"username": "nobody_xyz", "password": "anything"})
    assert res.status_code == 401


def test_login_inactive_user_returns_401(client):
    engine = _get_engine()
    from app.core.auth import create_user, list_users, update_user
    create_user(engine, "auth_inactive", "pass123")
    users = list_users(engine)
    uid = next(u["id"] for u in users if u["username"] == "auth_inactive")
    update_user(engine, uid, is_active=False)
    try:
        res = client.post(
            "/api/auth/login", json={"username": "auth_inactive", "password": "pass123"}
        )
        assert res.status_code == 401
        assert "disabled" in res.json()["detail"].lower()
    finally:
        _delete_user(engine, "auth_inactive")


def test_logout_returns_200(client):
    res = client.post("/api/auth/logout")
    assert res.status_code == 200


def test_me_endpoint_returns_current_user(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 200
    data = res.json()
    assert data["username"] == "test_admin"
    assert data["is_admin"] is True


# ---------------------------------------------------------------------------
# Login writes to audit log
# ---------------------------------------------------------------------------

def test_successful_login_is_logged(client):
    engine = _get_engine()
    from sqlalchemy import text

    from app.core.auth import create_user
    create_user(engine, "audit_login_user", "pass123")
    try:
        client.post("/api/auth/login", json={"username": "audit_login_user", "password": "pass123"})
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT action FROM _system.audit_log "
                "WHERE object_name='users' AND user_name='audit_login_user' AND action='LOGIN' "
                "ORDER BY timestamp DESC LIMIT 1"
            )).fetchone()
        assert row is not None
    finally:
        _delete_user(engine, "audit_login_user")


def test_failed_login_is_logged(client):
    from sqlalchemy import text
    engine = _get_engine()
    client.post("/api/auth/login", json={"username": "nosuchuser_audit", "password": "x"})
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT action FROM _system.audit_log "
            "WHERE object_name='users' AND action='LOGIN_FAILED' AND user_name='nosuchuser_audit' "
            "ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
    assert row is not None


# ---------------------------------------------------------------------------
# User management API
# ---------------------------------------------------------------------------

def test_admin_can_list_users(client):
    res = client.get("/api/admin/users")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_admin_can_create_user(client):
    engine = _get_engine()
    res = client.post("/api/admin/users", json={
        "username": "new_api_user",
        "password": "secret123abc!",
        "is_admin": False,
    })
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == "new_api_user"
    assert data["is_admin"] is False
    _delete_user(engine, "new_api_user")


def test_create_user_short_password_returns_400(client):
    res = client.post("/api/admin/users", json={"username": "short_pw_user", "password": "tooshort"})
    assert res.status_code == 400
    assert "12 characters" in res.json()["detail"]


def test_create_duplicate_user_returns_409(client):
    engine = _get_engine()
    from app.core.auth import create_user
    create_user(engine, "dup_user_test", "pass123456789")
    try:
        res = client.post(
            "/api/admin/users", json={"username": "dup_user_test", "password": "pass123456789"}
        )
        assert res.status_code == 409
    finally:
        _delete_user(engine, "dup_user_test")


def test_admin_can_toggle_user_active(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_id, get_user_by_username
    create_user(engine, "toggle_user", "pass123")
    user = get_user_by_username(engine, "toggle_user")
    uid = str(user["id"])
    try:
        res = client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
        assert res.status_code == 200
        updated = get_user_by_id(engine, uid)
        assert updated["is_active"] is False
    finally:
        _delete_user(engine, "toggle_user")


def test_admin_can_toggle_admin_role(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_id, get_user_by_username
    create_user(engine, "role_user", "pass123", is_admin=False)
    user = get_user_by_username(engine, "role_user")
    uid = str(user["id"])
    try:
        res = client.patch(f"/api/admin/users/{uid}", json={"is_admin": True})
        assert res.status_code == 200
        updated = get_user_by_id(engine, uid)
        assert updated["is_admin"] is True
    finally:
        _delete_user(engine, "role_user")


def test_non_admin_cannot_access_user_management(client):
    res = client.get("/api/admin/users", headers=_non_admin_headers())
    assert res.status_code == 403


def test_patch_nonexistent_user_returns_404(client):
    res = client.patch(
        "/api/admin/users/00000000-0000-0000-0000-000000000099", json={"is_active": False}
    )
    assert res.status_code == 404


def test_logout_is_logged(client):
    """A logout must write a LOGOUT entry to the audit log."""
    from sqlalchemy import text
    engine = _get_engine()
    from app.core.auth import create_token, create_user, get_user_by_username
    create_user(engine, "audit_logout_user", "pass123")
    try:
        # The client fixture always sends the admin Bearer token, so we must
        # call logout with audit_logout_user's own token to log their LOGOUT.
        user = get_user_by_username(engine, "audit_logout_user")
        token = create_token(str(user["id"]), "audit_logout_user", is_admin=False)
        client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT action FROM _system.audit_log "
                "WHERE object_name='users' AND user_name='audit_logout_user' AND action='LOGOUT' "
                "ORDER BY timestamp DESC LIMIT 1"
            )).fetchone()
        assert row is not None
    finally:
        _delete_user(engine, "audit_logout_user")


def test_deactivated_user_token_is_rejected(client):
    """A valid JWT for a deactivated user must not grant access after deactivation."""
    engine = _get_engine()
    from app.core.auth import create_token, create_user, get_user_by_username, update_user
    create_user(engine, "deact_token_user", "pass123")
    user = get_user_by_username(engine, "deact_token_user")
    uid = str(user["id"])
    try:
        # Create a valid token for the user while still active.
        active_token = create_token(uid, "deact_token_user", is_admin=False)
        # Confirm token works before deactivation (requires schema permission — use admin).
        # Just verify /api/auth/me works since that doesn't need schema access.
        pre_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {active_token}"})
        assert pre_res.status_code == 200

        # Deactivate the account server-side.
        update_user(engine, uid, is_active=False)

        # The same token must now be rejected.
        post_res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {active_token}"})
        assert post_res.status_code == 401
    finally:
        _delete_user(engine, "deact_token_user")


def test_audit_page_returns_403_for_non_admin(client):
    """The /admin/audit UI page must return 403 when accessed by a non-admin user."""
    res = client.get("/admin/audit", headers=_non_admin_headers())
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Audit log exclude_system filter
# ---------------------------------------------------------------------------

def test_audit_exclude_system_hides_auth_events(client):
    """exclude_system=true must omit _system schema rows (e.g. LOGIN events)."""
    # Trigger a LOGIN entry in the audit log.
    engine = _get_engine()
    from app.core.auth import create_user
    create_user(engine, "audit_excl_user", "pass123")
    try:
        client.post("/api/auth/login", json={"username": "audit_excl_user", "password": "pass123"})
        res = client.get("/api/audit?exclude_system=true&page_size=500")
        assert res.status_code == 200
        records = res.json()["records"]
        assert all(not r["schema_name"].startswith("_") for r in records), \
            "exclude_system=true returned a _system schema row"
    finally:
        _delete_user(engine, "audit_excl_user")


def test_audit_system_schema_filter_returns_auth_events(client):
    """schema=_system must return only _system rows (LOGIN/LOGOUT/etc.)."""
    res = client.get("/api/audit?schema=_system&page_size=500")
    assert res.status_code == 200
    records = res.json()["records"]
    assert all(r["schema_name"] == "_system" for r in records), \
        "schema=_system returned a non-system row"
    assert any(r["action"] in ("LOGIN", "LOGIN_FAILED", "LOGOUT") for r in records), \
        "No auth events found in _system schema"


# ---------------------------------------------------------------------------
# Audit log for user management actions
# ---------------------------------------------------------------------------

def _audit_row(engine, action: str, user_name: str):
    """Return the most recent audit row matching action and user_name, or None."""
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT action, reason FROM _system.audit_log "
            "WHERE object_name='users' AND action=:action AND user_name=:uname "
            "ORDER BY timestamp DESC LIMIT 1"
        ), {"action": action, "uname": user_name}).fetchone()


def test_user_created_is_logged(client):
    engine = _get_engine()
    res = client.post("/api/admin/users", json={"username": "log_created", "password": "pass123456789"})
    assert res.status_code == 201
    try:
        row = _audit_row(engine, "USER_CREATED", "test_admin")
        assert row is not None
    finally:
        _delete_user(engine, "log_created")


def test_user_deactivated_is_logged(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "log_deact", "pass")
    user = get_user_by_username(engine, "log_deact")
    uid = str(user["id"])
    try:
        client.patch(f"/api/admin/users/{uid}", json={"is_active": False})
        row = _audit_row(engine, "USER_DEACTIVATED", "test_admin")
        assert row is not None
    finally:
        _delete_user(engine, "log_deact")


def test_user_role_changed_is_logged(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "log_role", "pass", is_admin=False)
    user = get_user_by_username(engine, "log_role")
    uid = str(user["id"])
    try:
        client.patch(f"/api/admin/users/{uid}", json={"is_admin": True})
        row = _audit_row(engine, "USER_ROLE_CHANGED", "test_admin")
        assert row is not None
    finally:
        _delete_user(engine, "log_role")


def test_permission_granted_is_logged(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "log_perm", "pass")
    user = get_user_by_username(engine, "log_perm")
    uid = str(user["id"])
    try:
        client.put(f"/api/admin/users/{uid}/permissions/test",
                   json={"can_read": True, "can_write": False})
        row = _audit_row(engine, "PERMISSION_GRANTED", "test_admin")
        assert row is not None
    finally:
        _delete_user(engine, "log_perm")


def test_permission_revoked_is_logged(client):
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "log_revoke", "pass")
    user = get_user_by_username(engine, "log_revoke")
    uid = str(user["id"])
    try:
        client.put(f"/api/admin/users/{uid}/permissions/test",
                   json={"can_read": True, "can_write": False})
        client.delete(f"/api/admin/users/{uid}/permissions/test")
        row = _audit_row(engine, "PERMISSION_REVOKED", "test_admin")
        assert row is not None
    finally:
        _delete_user(engine, "log_revoke")
