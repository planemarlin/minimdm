import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.table_manager import TableManager

# In-memory SQLite is not supported for PostgreSQL-specific features,
# so tests use a real PostgreSQL test database defined via env var.
# For unit tests that don't touch the DB we use fixtures below.

SAMPLE_CONFIG = {
    "schemas": {
        "test": {
            "objects": {
                "company": {
                    "name": "Company",
                    "description": "Test company",
                    "parent": None,
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "reference": None},
                        "name": {"name": "Name", "type": "string", "required": False, "reference": None},
                    },
                },
                "division": {
                    "name": "Division",
                    "description": "Test division",
                    "parent": "company",
                    "attributes": {
                        "code": {"name": "Code", "type": "string", "required": True, "reference": None},
                    },
                },
            }
        }
    }
}


@pytest.fixture
def sample_config():
    return SAMPLE_CONFIG
