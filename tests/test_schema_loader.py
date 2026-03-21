import json
import tempfile

import pytest
import yaml

from app.core.schema_loader import load_config, validate_config


def write_tmp(content: str, suffix: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8")
    f.write(content)
    f.close()
    return f.name


class TestLoadConfig:
    def test_load_yaml(self):
        data = {
            "minimdm": {
                "schemas": {
                    "dev": {
                        "objects": {
                            "company": {
                                "name": "Company",
                                "description": "A company",
                                "attributes": {
                                    "code": {"name": "Code", "type": "string", "required": True}
                                },
                            }
                        }
                    }
                }
            }
        }
        path = write_tmp(yaml.dump(data), ".yaml")
        config = load_config(path)
        assert "schemas" in config
        assert "dev" in config["schemas"]
        assert "company" in config["schemas"]["dev"]["objects"]
        obj = config["schemas"]["dev"]["objects"]["company"]
        assert obj["name"] == "Company"
        assert obj["attributes"]["code"]["required"] is True

    def test_load_json(self):
        data = {
            "minimdm": {
                "schemas": {
                    "prod": {
                        "objects": {
                            "item": {
                                "name": "Item",
                                "attributes": {
                                    "sku": {"name": "SKU", "type": "string", "required": True}
                                },
                            }
                        }
                    }
                }
            }
        }
        path = write_tmp(json.dumps(data), ".json")
        config = load_config(path)
        assert "prod" in config["schemas"]
        assert config["schemas"]["prod"]["objects"]["item"]["attributes"]["sku"]["required"] is True

    def test_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_unsupported_format(self):
        path = write_tmp("hello", ".toml")
        with pytest.raises(ValueError, match="Unsupported config format"):
            load_config(path)

    def test_defaults_filled(self):
        data = {
            "schemas": {
                "s": {
                    "objects": {
                        "obj": {
                            "attributes": {
                                "field": {}  # minimal attribute
                            }
                        }
                    }
                }
            }
        }
        path = write_tmp(yaml.dump(data), ".yml")
        config = load_config(path)
        attr = config["schemas"]["s"]["objects"]["obj"]["attributes"]["field"]
        assert attr["type"] == "string"
        assert attr["required"] is False
        assert attr["reference"] is None


class TestValidateConfig:
    def test_valid_config(self, sample_config):
        errors = validate_config(sample_config)
        assert errors == []

    def test_invalid_parent(self):
        config = {
            "schemas": {
                "s": {
                    "objects": {
                        "child": {
                            "name": "Child",
                            "parent": "nonexistent",
                            "attributes": {},
                        }
                    }
                }
            }
        }
        errors = validate_config(config)
        assert any("parent" in e for e in errors)

    def test_invalid_reference(self):
        config = {
            "schemas": {
                "s": {
                    "objects": {
                        "obj": {
                            "name": "Obj",
                            "parent": None,
                            "attributes": {
                                "mgr": {
                                    "name": "Manager",
                                    "type": "string",
                                    "required": False,
                                    "reference": "ghost",
                                }
                            },
                        }
                    }
                }
            }
        }
        errors = validate_config(config)
        assert any("reference" in e for e in errors)
