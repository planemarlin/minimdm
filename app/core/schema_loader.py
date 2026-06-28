import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

_PRIVATE_NETS = [
    ipaddress.ip_network(n) for n in (
        "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
        "169.254.0.0/16", "::1/128", "fc00::/7",
    )
]


def _is_private_ip(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
        return any(addr in net for net in _PRIVATE_NETS)
    except ValueError:
        return False  # hostname, not an IP literal — checked at config load time only

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


def _parse_inbound_sources(raw_list: list) -> list:
    """Parse and validate inbound_sources entries from raw YAML."""
    sources = []
    for entry in raw_list or []:
        name = entry.get("name", "")
        if not name:
            raise ValueError("Each inbound_sources entry must have a 'name' field.")
        _validate_identifier(name, "inbound_sources")
        field_map = entry.get("field_map")
        if not isinstance(field_map, dict) or not field_map:
            raise ValueError(
                f"inbound_sources entry '{name}' must have a non-empty 'field_map' dict."
            )
        match_key = entry.get("match_key")
        if match_key is not None:
            _validate_identifier(match_key, "inbound_sources.match_key")
        sources.append({"name": name, "field_map": dict(field_map), "match_key": match_key})
    return sources


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
                        "owner": str | None,
                        "steward": str | None,
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
                "owner": obj_body.get("owner"),
                "steward": obj_body.get("steward"),
                "parent": obj_body.get("parent"),
                "require_change_reason": bool(obj_body.get("require_change_reason", False)),
                "requires_draft": bool(obj_body.get("requires_draft", False)),
                "allow_retire": bool(obj_body.get("allow_retire", True)),
                "allow_direct_active_import": bool(
                    obj_body.get("allow_direct_active_import", True)
                ),
                "attributes": attributes,
                "inbound_sources": _parse_inbound_sources(
                    obj_body.get("inbound_sources", [])
                ),
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
        if _is_private_ip(parsed.hostname or ""):
            raise ValueError(
                f"Webhook URL '{url}' must not target private or loopback addresses."
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

            valid_targets = set(obj_body.get("attributes", {}).keys()) | {"_source_id"}
            seen_source_names = set()
            for src in obj_body.get("inbound_sources", []):
                src_name = src.get("name", "")
                if src_name in seen_source_names:
                    errors.append(
                        f"[{schema_name}.{obj_key}] duplicate inbound_sources name '{src_name}'"
                    )
                seen_source_names.add(src_name)
                field_map = src.get("field_map", {})
                has_source_id = False
                for target in field_map.values():
                    if target == "_source_id":
                        has_source_id = True
                    elif target not in valid_targets:
                        errors.append(
                            f"[{schema_name}.{obj_key}.inbound_sources.{src_name}]"
                            f" field_map target '{target}' is not a valid attribute"
                        )
                if not has_source_id:
                    errors.append(
                        f"[{schema_name}.{obj_key}.inbound_sources.{src_name}]"
                        f" field_map must map at least one field to '_source_id'"
                    )
                match_key = src.get("match_key")
                valid_attrs = set(obj_body.get("attributes", {}).keys())
                if match_key is not None and match_key not in valid_attrs:
                    errors.append(
                        f"[{schema_name}.{obj_key}.inbound_sources.{src_name}]"
                        f" match_key '{match_key}' is not a valid attribute key"
                    )

    return errors
