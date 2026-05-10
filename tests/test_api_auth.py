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


def test_health_endpoint_returns_ok(client):
    """GET /health is publicly accessible and returns status ok when DB is reachable."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_request_id_header_present(client):
    """Every response must carry an X-Request-Id header with a UUID value."""
    import uuid
    res = client.get("/health")
    assert "x-request-id" in res.headers
    # Must be a valid UUID
    uuid.UUID(res.headers["x-request-id"])


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


def test_login_sets_samesite_strict_cookie(client):
    """Session cookie must use SameSite=strict to prevent CSRF."""
    engine = _get_engine()
    from app.core.auth import create_user
    create_user(engine, "csrf_test_user", "correct_password")
    try:
        res = client.post(
            "/api/auth/login", json={"username": "csrf_test_user", "password": "correct_password"}
        )
        assert res.status_code == 200
        cookie_header = res.headers.get("set-cookie", "")
        assert "samesite=strict" in cookie_header.lower()
    finally:
        _delete_user(engine, "csrf_test_user")


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
    # Use a dedicated token so we don't revoke the shared admin session token.
    engine = _get_engine()
    from app.core.auth import create_token, create_user, get_user_by_username
    create_user(engine, "logout_200_user", "pass123")
    try:
        user = get_user_by_username(engine, "logout_200_user")
        token = create_token(str(user["id"]), "logout_200_user", is_admin=False)
        res = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 200
    finally:
        _delete_user(engine, "logout_200_user")


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
    res = client.post(
        "/api/admin/users", json={"username": "short_pw_user", "password": "tooshort"}
    )
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


def test_audit_user_filter_matches_partially(client):
    """?user= does a case-insensitive partial match on user_name."""
    res = client.get("/api/audit?schema=_system&user=test_admin&page_size=500")
    assert res.status_code == 200
    records = res.json()["records"]
    assert all("test_admin" in r["user_name"].lower() for r in records)


def test_audit_user_filter_returns_empty_for_unknown_user(client):
    """?user= with a name that has no entries returns an empty list."""
    res = client.get("/api/audit?user=zzz_no_such_user_zzz")
    assert res.status_code == 200
    assert res.json()["records"] == []


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
    res = client.post(
        "/api/admin/users", json={"username": "log_created", "password": "pass123456789"}
    )
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


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------

def test_revoked_token_is_rejected_after_logout(client):
    """After logout the same JWT must be rejected with 401."""
    engine = _get_engine()
    from app.core.auth import create_token, create_user, get_user_by_username
    create_user(engine, "revoke_test_user", "pass123")
    try:
        user = get_user_by_username(engine, "revoke_test_user")
        token = create_token(str(user["id"]), "revoke_test_user", is_admin=False)
        headers = {"Authorization": f"Bearer {token}"}

        # Token works before logout
        assert client.get("/api/auth/me", headers=headers).status_code == 200

        # Logout revokes the token
        client.post("/api/auth/logout", headers=headers)

        # Same token is now rejected
        assert client.get("/api/auth/me", headers=headers).status_code == 401
    finally:
        _delete_user(engine, "revoke_test_user")


def test_new_token_works_after_old_token_revoked(client):
    """After logout a freshly issued token for the same user must still work."""
    engine = _get_engine()
    from app.core.auth import create_token, create_user, get_user_by_username
    create_user(engine, "revoke_new_token_user", "pass123")
    try:
        user = get_user_by_username(engine, "revoke_new_token_user")
        uid = str(user["id"])
        old_token = create_token(uid, "revoke_new_token_user", is_admin=False)

        # Revoke old token via logout
        client.post("/api/auth/logout", headers={"Authorization": f"Bearer {old_token}"})

        # New token (different jti) must still authenticate
        new_token = create_token(uid, "revoke_new_token_user", is_admin=False)
        assert client.get("/api/auth/me",
                          headers={"Authorization": f"Bearer {new_token}"}).status_code == 200
    finally:
        _delete_user(engine, "revoke_new_token_user")


# ---------------------------------------------------------------------------
# Password reset flow
# ---------------------------------------------------------------------------

def test_generate_reset_link_returns_url(client):
    """Admin can generate a reset link for a user; response contains a URL with a token."""
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "reset_link_user", "pass123456789")
    try:
        user = get_user_by_username(engine, "reset_link_user")
        res = client.post(f"/api/admin/users/{user['id']}/reset-link")
        assert res.status_code == 200
        data = res.json()
        assert "reset_url" in data
        assert "/reset-password?token=" in data["reset_url"]
        assert "expires_at" in data
    finally:
        _delete_user(engine, "reset_link_user")


def test_reset_password_with_valid_token(client):
    """A valid reset token lets a user set a new password."""
    engine = _get_engine()
    from app.core.auth import create_reset_token, create_user, get_user_by_username, verify_password
    create_user(engine, "reset_pw_user", "oldpassword123!")
    try:
        user = get_user_by_username(engine, "reset_pw_user")
        token, _ = create_reset_token(engine, str(user["id"]))

        res = client.post("/api/auth/reset-password",
                          json={"token": token, "password": "newpassword456!"})
        assert res.status_code == 200

        # Verify the new password actually works
        updated = get_user_by_username(engine, "reset_pw_user")
        assert verify_password("newpassword456!", updated["password_hash"])
    finally:
        _delete_user(engine, "reset_pw_user")


def test_reset_token_can_only_be_used_once(client):
    """A reset token is invalidated after first use."""
    engine = _get_engine()
    from app.core.auth import create_reset_token, create_user, get_user_by_username
    create_user(engine, "reset_once_user", "oldpassword123!")
    try:
        user = get_user_by_username(engine, "reset_once_user")
        token, _ = create_reset_token(engine, str(user["id"]))

        client.post("/api/auth/reset-password",
                    json={"token": token, "password": "newpassword456!"})
        # Second use must fail
        res = client.post("/api/auth/reset-password",
                          json={"token": token, "password": "anotherpassword789!"})
        assert res.status_code == 400
    finally:
        _delete_user(engine, "reset_once_user")


def test_reset_invalid_token_returns_400(client):
    """A bogus token returns 400."""
    res = client.post("/api/auth/reset-password",
                      json={"token": "not-a-real-token", "password": "somepassword123!"})
    assert res.status_code == 400


def test_reset_short_password_returns_400(client):
    """Password shorter than 12 characters is rejected before the token is consumed."""
    engine = _get_engine()
    from app.core.auth import create_reset_token, create_user, get_user_by_username
    create_user(engine, "reset_short_user", "oldpassword123!")
    try:
        user = get_user_by_username(engine, "reset_short_user")
        token, _ = create_reset_token(engine, str(user["id"]))
        res = client.post("/api/auth/reset-password",
                          json={"token": token, "password": "short"})
        assert res.status_code == 400
        # Token must not have been consumed — a second attempt with a valid password works
        res2 = client.post("/api/auth/reset-password",
                           json={"token": token, "password": "validpassword123!"})
        assert res2.status_code == 200
    finally:
        _delete_user(engine, "reset_short_user")


def test_generate_reset_link_non_admin_returns_403(client):
    """Non-admin users cannot generate reset links."""
    engine = _get_engine()
    from app.core.auth import create_user, get_user_by_username
    create_user(engine, "reset_target_user", "pass123456789")
    try:
        user = get_user_by_username(engine, "reset_target_user")
        res = client.post(f"/api/admin/users/{user['id']}/reset-link",
                          headers=_non_admin_headers())
        assert res.status_code == 403
    finally:
        _delete_user(engine, "reset_target_user")


def test_reset_page_is_publicly_accessible(client):
    """The /reset-password page must not require authentication."""
    res = client.get("/reset-password?token=anytoken", headers=_no_auth_headers())
    assert res.status_code == 200
