# Docker Setup for miniMDM

This guide explains how to run miniMDM using Docker and Docker Compose.

## Prerequisites

- Docker (v20.10+)
- Docker Compose (v2.0+)

## Quick Start

### Option 1: Automated Setup (Recommended)

```bash
./scripts/docker-setup.sh
```

This script will:
1. Verify Docker and Docker Compose are installed
2. Copy `.env.docker` to `.env` (if `.env` doesn't exist)
3. Build Docker images
4. Start all services
5. Verify the database connection

### Option 2: Manual Setup

1. **Prepare the environment file:**
   ```bash
   cp .env.docker .env
   ```

   Edit `.env` to update security settings, especially:
   - `SECRET_KEY` - Change from the default
   - `ADMIN_USERNAME` and `ADMIN_PASSWORD` - Change from default credentials

2. **Build and start services:**
   ```bash
   docker compose up -d
   ```

3. **Verify services are running:**
   ```bash
   docker compose ps
   ```

## Service Details

### PostgreSQL
- **Container**: minimdm-postgres
- **Host**: postgres (within Docker network)
- **Port**: 5432 (exposed on localhost)
- **Database**: minimdm
- **User**: minimdm
- **Password**: minimdm
- **Volume**: `postgres_data` (persistent storage)

### miniMDM Application
- **Container**: minimdm-app
- **Host**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Depends on**: PostgreSQL service

## Common Tasks

### View Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f postgres
docker compose logs -f app
```

### Stop Services
```bash
# Stop but keep volumes
docker compose down

# Stop and remove volumes (destructive)
docker compose down -v
```

### Restart Services
```bash
docker compose restart
```

### Execute Commands in Running Container
```bash
# Run a command in the app container
docker compose exec app <command>

# Access PostgreSQL prompt
docker compose exec postgres psql -U minimdm -d minimdm
```

### Rebuild Images
```bash
docker compose build --no-cache
```

## Environment Variables

All environment variables can be set in `.env`. Key variables:

- `DATABASE_URL`: PostgreSQL connection string (default for Docker: `postgresql://minimdm:minimdm@postgres:5432/minimdm`)
- `CONFIG_FILE`: Path to miniMDM config file (default: `config/minimdm.yaml`)
- `SECRET_KEY`: JWT secret key (⚠️ Change in production!)
- `ADMIN_USERNAME`: Initial admin user (created on first run)
- `ADMIN_PASSWORD`: Initial admin password (⚠️ Change in production!)
- `DEBUG`: Enable debug logging (default: `false`)
- `PORT`: Application port (default: `8000`)

## Database Initialization

The PostgreSQL service automatically:
1. Creates the `minimdm` database
2. Creates the `minimdm` user with password `minimdm`

The miniMDM application automatically creates required tables and schemas on startup via SQLAlchemy.

## Troubleshooting

### "Cannot connect to database"
Ensure PostgreSQL has started:
```bash
docker compose logs postgres
docker compose ps postgres
```

The app service waits for a healthcheck, so if PostgreSQL isn't ready, the app won't start.

### "Permission denied" on `scripts/docker-setup.sh`
Make the script executable:
```bash
chmod +x scripts/docker-setup.sh
```

### "Port 5432 already in use"
PostgreSQL port is already taken. Either:
1. Stop the conflicting service
2. Change the port mapping in `docker-compose.yml` (e.g., `5433:5432`)

### "Port 8000 already in use"
Application port is already taken. Either:
1. Stop the conflicting service
2. Change the port mapping in `docker-compose.yml` (e.g., `8001:8000`)

## Development

For development with live code reload:
```bash
docker compose up app
```

The `app` service has code mounted as a volume with `--reload` enabled, so changes to Python files will automatically restart the server.

## Production Considerations

⚠️ **DO NOT use the defaults for production!**

Before deploying to production:
1. Change `SECRET_KEY` to a strong random value
2. Change `ADMIN_USERNAME` and `ADMIN_PASSWORD` to secure credentials
3. Set `DEBUG=false`
4. Use proper PostgreSQL credentials (not `minimdm:minimdm`)
5. Use a proper secret management system for sensitive values
6. Configure proper networking (don't expose all ports)
7. Enable HTTPS
8. Set up proper backups for the `postgres_data` volume
9. Review and configure resource limits in `docker-compose.yml`

## Network

Services communicate over the `minimdm-network` bridge network:
- PostgreSQL is accessible as `postgres:5432` from the app container
- The app exposes port `8000` on the host for external access
