# Installation

## System Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer
- [uv](https://docs.astral.sh/uv/) package manager

## Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Install miniMDM

```bash
# 1. Clone the repository
git clone <repository-url>
cd minimdm

# 2. Create a virtual environment and install dependencies
uv sync

# 3. Install dev/test dependencies (optional)
uv sync --group dev
```

## Configure PostgreSQL

Create a database and user for miniMDM:

```sql
CREATE USER minimdm WITH PASSWORD 'your_password';
CREATE DATABASE minimdm OWNER minimdm;
```

## Configure miniMDM

```bash
cp .env.example .env
```

Edit `.env`:

```env
DATABASE_URL=postgresql://minimdm:your_password@localhost:5432/minimdm
CONFIG_FILE=config/minimdm.yaml

# Secret key for signing JWT tokens — use a long random string in production
SECRET_KEY=change-me-to-a-long-random-secret
TOKEN_EXPIRE_HOURS=24

# First-run admin account (created automatically if no users exist)
# Password must be at least 12 characters
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change-me-now!
```

## Create a Config File

```bash
cp config/minimdm.yaml config/minimdm.yaml
# Edit to define your schemas and objects
```

See [reference.md](reference.md) for the full config format specification.

## Start the Server

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

For development with auto-reload:

```bash
uv run uvicorn app.main:app --reload
```

The web interface is available at `http://localhost:8000`.
API documentation is at `http://localhost:8000/docs`.

> **Production deployments** must run behind a reverse proxy with TLS. See [deployment.md](deployment.md) for nginx/Caddy configuration, required environment variables, and a security checklist.

## Running as a Service (systemd)

Create `/etc/systemd/system/minimdm.service`:

```ini
[Unit]
Description=miniMDM
After=network.target postgresql.service

[Service]
User=minimdm
WorkingDirectory=/opt/minimdm
EnvironmentFile=/opt/minimdm/.env
ExecStart=/opt/minimdm/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable minimdm
sudo systemctl start minimdm
```
