import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _validate_identifier(value: str, context: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid identifier '{value}' in {context}. "
            "Use only letters, digits, and underscores, starting with a letter or underscore."
        )


def load_config(config_path: str) -> dict:
    """Load a YAML or JSON config file and return a normalized config dict."""
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, encoding="utf-8") as f:
        if path.suffix in (".yaml", ".yml"):
            raw = yaml.safe_load(f)
        elif path.suffix == ".json":
            raw = json.load(f)
        else:
            raise ValueError(f"Unsupported config format: {path.suffix}. Use .yaml or .json")

    return _normalize(raw)


def _normalize(raw: dict) -> dict:
    """Normalize raw config into a consistent internal structure.

    Expected output:
    {
        "schemas": {
            "<schema_name>": {
                "objects": {
                    "<object_key>": {
                        "name": str,
                        "description": str,
                        "parent": str | None,
                        "attributes": {
                            "<attr_key>": {
                                "name": str,
                                "type": str,          # string|numeric|integer|boolean|email|date
                                "required": bool,
                                "reference": str | None,  # object key in same schema
                            }
                        }
                    }
                }
            }
        }
    }
    """
    if "minimdm" in raw:
        raw = raw["minimdm"]

    schemas_raw = raw.get("schemas", {})
    schemas = {}

    for schema_name, schema_body in schemas_raw.items():
        _validate_identifier(schema_name, "schemas")
        objects_raw = schema_body.get("objects", {})
        objects = {}

        for obj_key, obj_body in objects_raw.items():
            _validate_identifier(obj_key, f"schemas.{schema_name}.objects")
            attrs_raw = obj_body.get("attributes", {})
            attributes = {}

            for attr_key, attr_body in attrs_raw.items():
                _validate_identifier(
                    attr_key, f"schemas.{schema_name}.objects.{obj_key}.attributes"
                )
                attributes[attr_key] = {
                    "name": attr_body.get("name", attr_key),
                    "type": attr_body.get("type", "string"),
                    "required": bool(attr_body.get("required", False)),
                    "unique": bool(attr_body.get("unique", False)),
                    "reference": attr_body.get("reference"),
                }

            objects[obj_key] = {
                "name": obj_body.get("name", obj_key),
                "description": obj_body.get("description", ""),
                "parent": obj_body.get("parent"),
                "require_change_reason": bool(obj_body.get("require_change_reason", False)),
                "attributes": attributes,
            }

        schemas[schema_name] = {"objects": objects}

    webhooks = []
    for entry in raw.get("webhooks", []):
        event = entry.get("event")
        url = entry.get("url")
        if not event or not url:
            continue
        parsed = urlparse(str(url))
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"Webhook URL '{url}' must use http or https scheme."
            )
        webhooks.append({"event": str(event), "url": str(url)})

    return {"schemas": schemas, "webhooks": webhooks}


def validate_config(config: dict) -> list[str]:
    """Validate config references and return a list of error strings (empty = valid)."""
    errors = []
    schemas = config.get("schemas", {})

    for schema_name, schema_body in schemas.items():
        objects = schema_body.get("objects", {})

        for obj_key, obj_body in objects.items():
            parent = obj_body.get("parent")
            if parent and parent not in objects:
                errors.append(
                    f"[{schema_name}.{obj_key}] parent '{parent}' not found in schema"
                )

            for attr_key, attr_body in obj_body.get("attributes", {}).items():
                ref = attr_body.get("reference")
                if ref and ref not in objects:
                    errors.append(
                        f"[{schema_name}.{obj_key}.{attr_key}]"
                        f" reference '{ref}' not found in schema"
                    )

    return errors
