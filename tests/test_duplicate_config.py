"""Config parsing and validation for duplicate detection (`duplicates:` blocks).

Pure unit tests — no database needed.
"""
import tempfile

import pytest
import yaml

from app.core.schema_loader import load_config, validate_config


def _load(data: dict) -> dict:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(yaml.dump(data))
    f.close()
    return load_config(f.name)


def _contact(object_duplicates=None, **extra) -> dict:
    """Config with one `contact` object. `object_duplicates` is the object's
    `duplicates:` block; `extra` keys (e.g. `duplicates=`) go on the top level."""
    obj = {
        "name": "Contact",
        "attributes": {
            "email": {"name": "Email", "type": "email"},
            "phone": {"name": "Phone", "type": "string"},
            "last_name": {"name": "Last name", "type": "string"},
            "country": {"name": "Country", "type": "string"},
        },
    }
    if object_duplicates is not None:
        obj["duplicates"] = object_duplicates
    return {"minimdm": {**extra, "schemas": {"crm": {"objects": {"contact": obj}}}}}


def _dup(config: dict) -> dict:
    return config["schemas"]["crm"]["objects"]["contact"]["duplicates"]


def test_object_without_duplicates_block_gets_empty_defaults():
    config = _load(_contact())
    assert _dup(config) == {"dismissed_by": "editor", "rules": []}
    assert config["duplicates"] == {"rescan": "on_rule_change"}
    assert validate_config(config) == []


def test_rules_are_parsed_with_defaults():
    config = _load(_contact({
        "dismissed_by": "publisher",
        "rules": [
            {"name": "Same email", "fields": ["email"]},
            {"name": "Same phone", "fields": ["phone"], "normalize": "digits"},
            {"fields": ["last_name", "country"]},
        ],
    }))
    dup = _dup(config)
    assert dup["dismissed_by"] == "publisher"
    assert dup["rules"] == [
        {"name": "Same email", "fields": ["email"], "normalize": "text"},
        {"name": "Same phone", "fields": ["phone"], "normalize": "digits"},
        # An unnamed rule is named after its fields
        {"name": "last_name + country", "fields": ["last_name", "country"], "normalize": "text"},
    ]
    assert validate_config(config) == []


@pytest.mark.parametrize("mode", ["on_rule_change", "manual"])
def test_installation_wide_rescan_mode(mode):
    config = _load(_contact(duplicates={"rescan": mode}))
    assert config["duplicates"] == {"rescan": mode}
    assert validate_config(config) == []


def test_invalid_rescan_mode_is_a_validation_error():
    config = _load(_contact(duplicates={"rescan": "always"}))
    errors = validate_config(config)
    assert any("rescan 'always'" in e for e in errors)


def test_invalid_dismissed_by_is_a_validation_error():
    config = _load(_contact({"dismissed_by": "viewer", "rules": []}))
    errors = validate_config(config)
    assert any("dismissed_by 'viewer'" in e for e in errors)


def test_invalid_normalize_is_a_validation_error():
    config = _load(_contact({"rules": [
        {"name": "r", "fields": ["email"], "normalize": "fuzzy"},
    ]}))
    errors = validate_config(config)
    assert any("normalize 'fuzzy'" in e for e in errors)


def test_unknown_and_repeated_fields_and_duplicate_rule_names_are_validation_errors():
    config = _load(_contact({"rules": [
        {"name": "dup", "fields": ["email", "email"]},
        {"name": "dup", "fields": ["nope"]},
    ]}))
    errors = validate_config(config)
    assert any("field 'nope' not found" in e for e in errors)
    assert any("field 'email' is listed more than once" in e for e in errors)
    assert any("duplicate rule name 'dup'" in e for e in errors)


@pytest.mark.parametrize("bad", [
    "a string",
    {"rules": "email"},
    {"rules": ["email"]},
    {"rules": [{"name": "no fields"}]},
    {"rules": [{"fields": []}]},
    {"rules": [{"fields": "email"}]},
    {"rules": [{"fields": ["not a valid identifier!"]}]},
])
def test_structurally_invalid_duplicates_block_raises(bad):
    with pytest.raises(ValueError):
        _load(_contact(bad))


def test_top_level_duplicates_must_be_a_mapping():
    with pytest.raises(ValueError):
        _load(_contact(duplicates="manual"))
