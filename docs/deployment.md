# Deploying miniMDM

miniMDM is a standard ASGI application served by Uvicorn. For production use it must run behind a reverse proxy that handles TLS termination. Do not expose the Uvicorn process directly on a public interface.

## Requirements

- A reverse proxy with TLS support (nginx, Caddy, or equivalent)
- A valid TLS certificate (e.g. from Let's Encrypt)
- PostgreSQL 14+ running on a private interface

## Recommended architecture

```
Internet
   │  HTTPS (443)
   ▼
Reverse proxy (nginx / Caddy)
   │  HTTP (localhost:8000)
   ▼
miniMDM (Uvicorn)
   │  TCP (localhost:5432)
   ▼
PostgreSQL
```

## Environment variables

Set these in your `.env` file or via your process manager before starting miniMDM.

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | PostgreSQL connection string, e.g. `postgresql://user:pass@localhost:5432/minimdm` |
| `SECRET_KEY` | Yes | Long random string used to sign JWTs. Generate with `openssl rand -hex 32`. |
| `CONFIG_FILE` | Yes | Path to the miniMDM YAML config file |
| `ADMIN_USERNAME` | First run only | Username for the initial admin account |
| `ADMIN_PASSWORD` | First run only | Password for the initial admin account (min 12 chars) |
| `TOKEN_EXPIRE_HOURS` | No | JWT lifetime in hours (default: 8) |
| `MAX_UPLOAD_SIZE` | No | Max import file size in bytes (default: 10485760 = 10 MB) |
| `LOG_FORMAT` | No | Log output format: `text` (default, human-readable) or `json` (one JSON object per line, recommended for production) |
| `SECURE_COOKIE` | No | Set to `true` when serving over HTTPS to add the `Secure` flag to the session cookie (default: `false`). **Enable this in production.** |

## Nginx example

```nginx
server {
    listen 443 ssl http2;
    server_name mdm.example.com;

    ssl_certificate     /etc/letsencrypt/live/mdm.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mdm.example.com/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    # Forward real client IP to the application
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host $host;

    location / {
        proxy_pass http://127.0.0.1:8000;
    }
}

server {
    listen 80;
    server_name mdm.example.com;
    return 301 https://$host$request_uri;
}
```

## Caddy example

```caddy
mdm.example.com {
    reverse_proxy localhost:8000
}
```

Caddy automatically provisions and renews a Let's Encrypt certificate and redirects HTTP to HTTPS.

## Starting miniMDM

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Bind to `127.0.0.1`, not `0.0.0.0`, so the application is only reachable via the reverse proxy.

For production use a process manager such as systemd to keep the process running. See `docs/installation.md` for a systemd unit file template.

## Logging

By default miniMDM emits human-readable timestamped log lines. For production use set `LOG_FORMAT=json` in your environment to get one JSON object per line — suitable for log aggregators and easier to search.

Every response carries an `X-Request-Id` header. Include this ID when reporting issues so the corresponding log lines can be found immediately.

See [docs/logging.md](logging.md) for full details including field reference and log aggregator examples.

## Health check

`GET /health` returns HTTP 200 when the application and database are ready, or HTTP 503 if the database is unreachable. Use this endpoint for load balancer health checks and container readiness probes.

```bash
curl https://mdm.example.com/health
# {"status": "ok", "version": "0.2.0"}
```

## Docker

See [docs/docker-setup.md](docker-setup.md) for running miniMDM with Docker Compose. The same reverse proxy requirement applies for public-facing Docker deployments.

## Security checklist before going live

- [ ] `SECRET_KEY` is a long random value, not the default placeholder
- [ ] `ADMIN_PASSWORD` has been changed from the initial setup value
- [ ] miniMDM is behind a reverse proxy with a valid TLS certificate
- [ ] HTTP redirects to HTTPS
- [ ] `SECURE_COOKIE=true` is set in your `.env` file
- [ ] Uvicorn binds to `127.0.0.1`, not `0.0.0.0`
- [ ] PostgreSQL is not exposed on a public interface
- [ ] `.env` file is not readable by other system users (`chmod 600 .env`)
- [ ] Regular database backups are configured and verified (see [docs/backup-restore.md](backup-restore.md))
