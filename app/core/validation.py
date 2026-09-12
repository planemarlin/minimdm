"""Config-based "soft" validation rules — see docs/reference.md#validation-rules.

Unlike the hard `required`/`type`/`unique` constraints (enforced entirely by the
database, see app/core/table_manager.py), the rules here never block a write on
their own. `record_violations()` is a pure computation: it returns a list of
violations for the caller to act on (require confirmation, flag an import row,
etc.) and never raises.

Two Cerberus quirks shaped this module's shape:

- `dependencies` + `required` does not implement "required only if condition X
  holds" the way it might look — `required` is checked independently of
  `dependencies`. A genuinely conditional requirement (`required_if`) is
  implemented as a plain Python pre-pass instead of forcing it through
  Cerberus.
- `check_with` needs each attribute's own rule parameters (e.g. which
  `char_class`) available on `self.schema[field]`/`self.document`, which only
  works for named `_check_with_<rule>` methods on a `Validator` subclass, not
  a bare callable (which Cerberus invokes with just `(field, value, error)`,
  no document access). Storing a parameter like `char_class: "alpha"` as a
  sibling schema key requires a matching `_validate_<rule>` method to exist
  too — Cerberus's schema compiler otherwise rejects the key as an "unknown
  rule"; those `_validate_*` methods below are intentionally no-ops, since the
  actual check happens in `_check_with_*`.
"""

from __future__ import annotations

from cerberus import Validator

_COMPARE_OPS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
}


class _RuleValidator(Validator):
    def _validate_char_class(self, char_class, field, value):
        """{'type': 'string'}"""

    def _check_with_char_class(self, field, value):
        if value in (None, ""):
            return
        char_class = self.schema[field].get("char_class")
        ok = value.isalpha() if char_class == "alpha" else value.isalnum()
        if not ok:
            self._error(field, f"char_class:must contain only {char_class} characters")

    def _validate_forbidden_if_absent(self, other_field, field, value):
        """{'type': 'string'}"""

    def _check_with_forbidden_if_absent(self, field, value):
        if value in (None, ""):
            return
        other_field = self.schema[field].get("forbidden_if_absent")
        if self.document.get(other_field) in (None, ""):
            self._error(
                field, f"forbidden_if_absent:must be empty because '{other_field}' is empty"
            )

    def _validate_compare(self, compare, field, value):
        """{'type': 'dict'}"""

    def _check_with_compare(self, field, value):
        if value in (None, ""):
            return
        spec = self.schema[field].get("compare") or {}
        other_val = self.document.get(spec.get("field"))
        if other_val in (None, ""):
            return
        fn = _COMPARE_OPS[spec["op"]]
        if not fn(value, other_val):
            self._error(field, f"compare:must be {spec['op']} '{spec['field']}' ({other_val!r})")


def build_cerberus_schema(obj_config: dict) -> dict:
    """Build a Cerberus schema covering only attributes that declare a rule.

    Attributes with no rule keys are omitted entirely; combined with
    `allow_unknown=True` on the Validator, this keeps type/required/unique
    checks (already enforced by the database) fully out of Cerberus's scope.
    """
    schema: dict = {}
    for attr_key, attr in (obj_config.get("attributes") or {}).items():
        field_schema: dict = {}
        check_with = []

        if attr.get("min") is not None:
            field_schema["min"] = attr["min"]
        if attr.get("max") is not None:
            field_schema["max"] = attr["max"]
        if attr.get("char_class"):
            field_schema["char_class"] = attr["char_class"]
            check_with.append("char_class")
        if attr.get("forbidden_if_absent"):
            field_schema["forbidden_if_absent"] = attr["forbidden_if_absent"]
            check_with.append("forbidden_if_absent")
        if attr.get("compare"):
            field_schema["compare"] = attr["compare"]
            check_with.append("compare")

        if check_with:
            field_schema["check_with"] = check_with if len(check_with) > 1 else check_with[0]
        if field_schema:
            field_schema.setdefault("nullable", True)
            schema[attr_key] = field_schema
    return schema


def _required_if_violations(obj_config: dict, document: dict) -> list[dict]:
    violations = []
    for attr_key, attr in (obj_config.get("attributes") or {}).items():
        rule = attr.get("required_if")
        if not rule:
            continue

        other_val = document.get(rule["field"])
        if "equals" in rule:
            condition_met = other_val == rule["equals"]
            reason = f"'{rule['field']}' is '{rule['equals']}'"
        else:
            condition_met = other_val not in (None, "")
            reason = f"'{rule['field']}' is present"

        if condition_met and document.get(attr_key) in (None, ""):
            violations.append({
                "attribute": attr_key,
                "rule": "required_if",
                "message": f"required because {reason}",
            })
    return violations


def record_violations(obj_config: dict, document: dict) -> list[dict]:
    """Return `[{"attribute", "rule", "message"}, ...]` for every rule violated.

    `document` must be the full, merged record — existing values for an update,
    overlaid with the incoming change — not just the fields present in a given
    request, since cross-field rules (`compare`, `forbidden_if_absent`,
    `required_if`) need both sides even when only one is being edited.
    """
    violations = _required_if_violations(obj_config, document)

    schema = build_cerberus_schema(obj_config)
    if schema:
        doc = {k: (None if v == "" else v) for k, v in document.items()}
        validator = _RuleValidator(schema, allow_unknown=True)
        validator.validate(doc)
        for err in validator._errors:
            if err.rule == "min":
                rule, message = "min", f"must be >= {err.constraint}"
            elif err.rule == "max":
                rule, message = "max", f"must be <= {err.constraint}"
            elif err.info:
                info_msg = str(err.info[0])
                rule, message = (
                    info_msg.split(":", 1) if ":" in info_msg else ("check_with", info_msg)
                )
            else:
                rule, message = (err.rule or "rule"), str(err)
            violations.append({"attribute": err.field, "rule": rule, "message": message})

    return violations
