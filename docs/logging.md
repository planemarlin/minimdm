# Logging

miniMDM emits structured log output that can be read by a human in a terminal or ingested by a log aggregator in production.

## Log formats

The format is controlled by the `LOG_FORMAT` environment variable.

| Value | When to use | Output |
|---|---|---|
| `text` (default) | Local development | Human-readable timestamped lines |
| `json` | Production / log aggregators | One JSON object per line |

### Text format (default)

```
2026-03-25T10:12:34 INFO     [a1b2c3d4-...] app.main: Loaded config from config/minimdm.yaml
2026-03-25T10:12:35 INFO     [a1b2c3d4-...] uvicorn.access: POST /api/records/test/company 200
```

### JSON format

```json
{"timestamp": "2026-03-25T10:12:34", "level": "INFO", "logger": "app.main", "request_id": "a1b2c3d4-...", "message": "Loaded config from config/minimdm.yaml"}
{"timestamp": "2026-03-25T10:12:35", "level": "INFO", "logger": "uvicorn.access", "request_id": "a1b2c3d4-...", "message": "POST /api/records/test/company 200"}
```

Set `LOG_FORMAT=json` in your `.env` file or environment to enable JSON output.

## Request IDs

Every HTTP request is assigned a unique UUID at the point it enters the application. This ID is:

- Added to every log line produced while handling that request
- Returned to the caller as the `X-Request-Id` response header

If a user or monitoring system reports a problem, the request ID from the response header can be used to find the exact log lines for that request:

```bash
# Find all log lines for a specific request (JSON format)
grep '"request_id": "a1b2c3d4-..."' /var/log/minimdm.log

# Or using jq
jq 'select(.request_id == "a1b2c3d4-...")' /var/log/minimdm.log
```

## Log levels

The log level is set by the `DEBUG` environment variable.

| Variable | Level |
|---|---|
| `DEBUG=false` (default) | INFO |
| `DEBUG=true` | DEBUG |

At DEBUG level, SQLAlchemy query logs are also emitted, which is useful during development.

## Configuring log collection

### systemd / journald

When running under systemd, logs go to the journal automatically. Retrieve them with:

```bash
journalctl -u minimdm -f
```

For JSON format the output is already structured; journald adds its own metadata fields alongside the miniMDM JSON payload.

### Docker

Logs written to stdout are captured by Docker's logging driver. The default `json-file` driver stores them at `/var/lib/docker/containers/<id>/<id>-json.log`. Use `docker logs` to tail them:

```bash
docker compose logs -f minimdm
```

### Forwarding to a log aggregator

Set `LOG_FORMAT=json` and pipe or ship the output to your aggregator of choice (Datadog, Grafana Loki, AWS CloudWatch, etc.). Each line is a valid JSON object with consistent fields:

| Field | Type | Description |
|---|---|---|
| `timestamp` | string | ISO 8601 datetime (UTC) |
| `level` | string | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `logger` | string | Python logger name (e.g. `app.api.objects`) |
| `request_id` | string | UUID for the current HTTP request (absent for startup/shutdown messages) |
| `message` | string | Log message |
| `exc_info` | string | Formatted exception traceback (only present on errors) |
