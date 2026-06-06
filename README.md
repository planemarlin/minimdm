# miniMDM

A minimal, lightweight, open-source **Master Data Management** application with a web interface, REST API, and PostgreSQL backend.

## Features

- Define data objects (tables) in a YAML or JSON config file
- Create, read, update, and delete records through the web UI or API
- **Lifecycle states**: records progress through `draft` → `active` → `retired`; editing an active record creates a draft copy, keeping the live record stable until a Publisher approves the change
- **Lifecycle policy flags**: per-object config flags (`requires_draft`, `allow_retire`, `allow_direct_active_import`) enforce governance rules without code changes
- Full record versioning with the ability to view and revert to any historical version
- Complete audit log: what changed, who changed it, when, and why
- **Data ownership & stewardship**: optional `owner` and `steward` fields on each object type for governance metadata; displayed in the UI alongside the object name
- JWT-based authentication with four roles: Viewer, Editor, Publisher, and Admin
- Schema-based access control: grant read, write, and publish access per schema per user
- User management UI and API for creating and managing accounts
- Bulk import/export (CSV, TSV, JSON) with optional upsert by key; import directly as `active` or as `draft`
- Full-text search within any object
- Cross-object references and parent-child hierarchies
- Related-record panels on the detail view: child records and back-references displayed inline
- Sortable column headers in the record list; sorted dropdowns on forms
- MDM-native API vocabulary: `?role=master` and `?role=draft` as readable aliases for the state filter
- Auto-generated OpenAPI documentation
- Responsive web interface (desktop and mobile)

## Quick Start

See [docs/quickstart.md](docs/quickstart.md) for a step-by-step guide, or [docs/docker-setup.md](docs/docker-setup.md) to get started with Docker.

## Requirements

- Python 3.11+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

Or use Docker (no local Python or PostgreSQL installation required) — see [docs/docker-setup.md](docs/docker-setup.md).

## Installation

See [docs/installation.md](docs/installation.md) for full instructions.

```bash
# Clone the repo
git clone <repository-url>
cd minimdm

# Create environment and install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your PostgreSQL connection string

# Copy and edit the config file
cp config/minimdm.example.yaml config/minimdm.yaml

# Start the server
uv run uvicorn app.main:app --reload
```

The application is then available at `http://localhost:8000` and the API documentation at `http://localhost:8000/docs`.

## Running Tests

**API and unit tests** (integration tests require `TEST_DATABASE_URL`):

```bash
TEST_DATABASE_URL=postgresql://minimdm:password@localhost/minimdm_test uv run pytest
```

**Browser end-to-end tests** (Playwright — install the browser binary once first):

```bash
uv run playwright install chromium
TEST_DATABASE_URL=postgresql://minimdm:password@localhost/minimdm_test uv run pytest tests/browser/
```

Add `--headed` to watch the browser, or `--headed --slowmo 500` to step through slowly. See [docs/testing.md](docs/testing.md) for the full test suite overview.

## Documentation

| Document | Description |
|---|---|
| [docs/installation.md](docs/installation.md) | System requirements and installation |
| [docs/quickstart.md](docs/quickstart.md) | Getting started guide |
| [docs/docker-setup.md](docs/docker-setup.md) | Running miniMDM with Docker Compose |
| [docs/deployment.md](docs/deployment.md) | Production deployment (TLS, reverse proxy, security checklist) |
| [docs/logging.md](docs/logging.md) | Log formats, request IDs, and log aggregator setup |
| [docs/migrations.md](docs/migrations.md) | Database migrations and Alembic usage |
| [docs/backup-restore.md](docs/backup-restore.md) | Database backup and restore procedures |
| [docs/reference.md](docs/reference.md) | Feature and API reference |
| [docs/testing.md](docs/testing.md) | Running tests and test suite overview |
| [docs/software.md](docs/software.md) | Open-source software used |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors and solutions |

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the process, coding conventions, and PR requirements. See [CONTRIBUTORS.md](CONTRIBUTORS.md) for the list of contributors.

## License

miniMDM is released under the [MIT License](LICENSE).
