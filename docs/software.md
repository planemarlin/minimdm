# Software Used

All software used in miniMDM is open source.

## Runtime Dependencies

| Package | Version | License | Purpose |
|---|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | ≥ 0.115 | MIT | Web framework and API |
| [uvicorn](https://www.uvicorn.org/) | ≥ 0.32 | BSD-3-Clause | ASGI server |
| [SQLAlchemy](https://www.sqlalchemy.org/) | ≥ 2.0 | MIT | ORM and database toolkit |
| [psycopg2-binary](https://www.psycopg.org/) | ≥ 2.9.9 | LGPL-3.0 | PostgreSQL driver |
| [PyYAML](https://pyyaml.org/) | ≥ 6.0 | MIT | YAML config parsing |
| [Jinja2](https://jinja.palletsprojects.com/) | ≥ 3.1 | BSD-3-Clause | HTML templating |
| [python-multipart](https://github.com/Kludex/python-multipart) | ≥ 0.0.12 | Apache-2.0 | File upload handling |
| [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | ≥ 2.0 | MIT | Settings management |
| [aiofiles](https://github.com/Tinche/aiofiles) | ≥ 24.0 | Apache-2.0 | Async file I/O |

## Development Dependencies

| Package | Version | License | Purpose |
|---|---|---|---|
| [pytest](https://pytest.org/) | ≥ 8.0 | MIT | Test framework |
| [pytest-asyncio](https://pytest-asyncio.readthedocs.io/) | ≥ 0.24 | Apache-2.0 | Async test support |
| [httpx](https://www.python-httpx.org/) | ≥ 0.27 | BSD-3-Clause | HTTP client for tests |
| [pytest-cov](https://pytest-cov.readthedocs.io/) | ≥ 5.0 | MIT | Test coverage reports |

## Infrastructure

| Software | License | Purpose |
|---|---|---|
| [PostgreSQL](https://www.postgresql.org/) | PostgreSQL License | Primary database |
| [uv](https://docs.astral.sh/uv/) | MIT / Apache-2.0 | Python package manager |
