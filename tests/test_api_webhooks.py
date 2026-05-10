"""Tests for webhook delivery on publish and retire transitions.

Requires TEST_DATABASE_URL; skipped otherwise.
httpx.post is mocked — no real HTTP calls are made.
"""
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.usefixtures("clean_records")

WEBHOOK_URL = "https://example.com/hooks/test"


def _set_webhooks(client, webhooks):
    from app.main import app as fastapi_app
    fastapi_app.state.table_manager._config["webhooks"] = webhooks


def _clear_webhooks(client):
    from app.main import app as fastapi_app
    fastapi_app.state.table_manager._config.pop("webhooks", None)


def _create_company(client, code="W001", name="Webhook Co"):
    res = client.post("/api/records/test/company", json={"code": code, "name": name})
    assert res.status_code == 201
    return res.json()["id"]


def _create_draft(client, active_id):
    res = client.put(f"/api/records/test/company/{active_id}", json={"name": "Updated"})
    assert res.status_code == 200
    return res.json()["id"]


# ---------------------------------------------------------------------------
# Publish fires record.published webhook
# ---------------------------------------------------------------------------

def test_publish_fires_webhook(client):
    active_id = _create_company(client)
    draft_id = _create_draft(client, active_id)
    _set_webhooks(client, [{"event": "record.published", "url": WEBHOOK_URL}])
    try:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        with patch("app.core.webhooks.httpx.post", return_value=mock_response) as mock_post:
            res = client.post(f"/api/records/test/company/{draft_id}/publish")
            assert res.status_code == 200

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs[0][0] == WEBHOOK_URL
        payload = call_kwargs[1]["json"]
        assert payload["event"] == "record.published"
        assert payload["schema"] == "test"
        assert payload["object"] == "company"
        assert payload["record_id"] == active_id
    finally:
        _clear_webhooks(client)


# ---------------------------------------------------------------------------
# Retire fires record.retired webhook
# ---------------------------------------------------------------------------

def test_retire_fires_webhook(client):
    active_id = _create_company(client, code="W002")
    _set_webhooks(client, [{"event": "record.retired", "url": WEBHOOK_URL}])
    try:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        with patch("app.core.webhooks.httpx.post", return_value=mock_response) as mock_post:
            res = client.post(f"/api/records/test/company/{active_id}/retire")
            assert res.status_code == 200

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["event"] == "record.retired"
        assert payload["record_id"] == active_id
    finally:
        _clear_webhooks(client)


# ---------------------------------------------------------------------------
# Create fires record.created webhook
# ---------------------------------------------------------------------------

def test_create_fires_webhook(client):
    _set_webhooks(client, [{"event": "record.created", "url": WEBHOOK_URL}])
    try:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.status_code = 200
        with patch("app.core.webhooks.httpx.post", return_value=mock_response) as mock_post:
            res = client.post(
                "/api/records/test/company", json={"code": "W006", "name": "Created Co"}
            )
            assert res.status_code == 201
            record_id = res.json()["id"]

        mock_post.assert_called_once()
        payload = mock_post.call_args[1]["json"]
        assert payload["event"] == "record.created"
        assert payload["schema"] == "test"
        assert payload["object"] == "company"
        assert payload["record_id"] == record_id
    finally:
        _clear_webhooks(client)


def test_create_does_not_fire_published_webhook(client):
    _set_webhooks(client, [{"event": "record.published", "url": WEBHOOK_URL}])
    try:
        with patch("app.core.webhooks.httpx.post") as mock_post:
            res = client.post(
                "/api/records/test/company", json={"code": "W007", "name": "No Hook Co"}
            )
            assert res.status_code == 201
        mock_post.assert_not_called()
    finally:
        _clear_webhooks(client)


# ---------------------------------------------------------------------------
# Webhook not fired when no webhooks configured
# ---------------------------------------------------------------------------

def test_no_webhook_when_not_configured(client):
    active_id = _create_company(client, code="W003")
    draft_id = _create_draft(client, active_id)
    _clear_webhooks(client)
    with patch("app.core.webhooks.httpx.post") as mock_post:
        res = client.post(f"/api/records/test/company/{draft_id}/publish")
        assert res.status_code == 200
    mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Webhook event mismatch — publish does not fire record.retired and vice versa
# ---------------------------------------------------------------------------

def test_publish_does_not_fire_retired_webhook(client):
    active_id = _create_company(client, code="W004")
    draft_id = _create_draft(client, active_id)
    _set_webhooks(client, [{"event": "record.retired", "url": WEBHOOK_URL}])
    try:
        with patch("app.core.webhooks.httpx.post") as mock_post:
            res = client.post(f"/api/records/test/company/{draft_id}/publish")
            assert res.status_code == 200
        mock_post.assert_not_called()
    finally:
        _clear_webhooks(client)


# ---------------------------------------------------------------------------
# Failing webhook does not affect API response
# ---------------------------------------------------------------------------

def test_webhook_failure_does_not_affect_response(client):
    active_id = _create_company(client, code="W005")
    draft_id = _create_draft(client, active_id)
    _set_webhooks(client, [{"event": "record.published", "url": WEBHOOK_URL}])
    try:
        with patch("app.core.webhooks.httpx.post", side_effect=Exception("connection refused")):
            res = client.post(f"/api/records/test/company/{draft_id}/publish")
            assert res.status_code == 200
            assert res.json()["published"] is True
    finally:
        _clear_webhooks(client)
