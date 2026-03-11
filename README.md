# miniMDM

A minimal, lightweight, open-source **Master Data Management** application with a web interface, REST API, and PostgreSQL backend.

## Features

- Define data objects (tables) in a YAML or JSON config file
- Create, read, update, and delete records through the web UI or API
- Full record versioning with the ability to view and revert to any historical version
- Complete audit log: what changed, who changed it, when, and why
- Bulk import/export (CSV, TSV, JSON)
- Full-text search within any object
- Cross-object references and parent-child hierarchies
- Auto-generated OpenAPI documentation
- Responsive web interface (desktop and mobile)

## Quick Start

See [docs/quickstart.md](docs/quickstart.md) for a step-by-step guide.

## Requirements

- Python 3.11+
- PostgreSQL 14+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

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
cp config/minimdm.yaml config/minimdm.yaml

# Start the server
uv run uvicorn app.main:app --reload
```

The application is then available at `http://localhost:8000` and the API documentation at `http://localhost:8000/docs`.

## Running Tests

```bash
uv run pytest
```

## Documentation

| Document | Description |
|---|---|
| [docs/installation.md](docs/installation.md) | System requirements and installation |
| [docs/quickstart.md](docs/quickstart.md) | Getting started guide |
| [docs/reference.md](docs/reference.md) | Feature and API reference |
| [docs/software.md](docs/software.md) | Open-source software used |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common errors and solutions |

## License

This project is open source. See [LICENSE](LICENSE) for details.
