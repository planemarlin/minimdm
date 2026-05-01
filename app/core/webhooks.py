import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 5.0


def fire_webhooks(config: dict, event: str, schema: str, obj: str,
                  record_id: str, triggered_by: str | None) -> None:
    """Send webhook POST to every URL configured for the given event.

    Called as a FastAPI background task — runs after the response is sent.
    Failures are logged and silently swallowed so a dead endpoint never
    affects the API caller.
    """
    webhooks = config.get("webhooks", [])
    matching = [w for w in webhooks if w.get("event") == event]
    if not matching:
        return

    payload = {
        "event": event,
        "schema": schema,
        "object": obj,
        "record_id": record_id,
        "triggered_by": triggered_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    for webhook in matching:
        url = webhook.get("url")
        if not url:
            continue
        try:
            response = httpx.post(url, json=payload, timeout=TIMEOUT)
            response.raise_for_status()
            logger.info("webhook %s delivered to %s (status %s)", event, url, response.status_code)
        except Exception as exc:
            logger.warning("webhook %s failed for %s: %s", event, url, exc)
