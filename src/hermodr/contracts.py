"""Versioned JSON Schema loading and deterministic validation."""

from dataclasses import dataclass
from importlib import resources
import json
import math
from pathlib import Path
import re


CONTRACT_ROOT = Path(__file__).resolve().parents[2] / "contracts" / "v1"


@dataclass(frozen=True)
class ContractViolation:
    path: str
    code: str


def load_schema(name: str) -> dict[str, object]:
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ValueError("schema_name_invalid")
    checkout_path = CONTRACT_ROOT / f"{name}.schema.json"
    if checkout_path.is_file():
        content = checkout_path.read_text(encoding="utf-8")
    else:
        content = resources.files("hermodr").joinpath("contracts", "v1", f"{name}.schema.json").read_text(encoding="utf-8")
    return json.loads(content)


def _type_matches(expected: str, value: object) -> bool:
    return {
        "array": isinstance(value, list),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
        "number": isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }[expected]


def validate(schema: dict[str, object], value: object, path: str = "$") -> tuple[ContractViolation, ...]:
    errors: list[ContractViolation] = []
    expected = schema.get("type")
    types = [expected] if isinstance(expected, str) else expected
    if types and not any(_type_matches(item, value) for item in types):
        return (ContractViolation(path, "type"),)
    if "const" in schema and value != schema["const"]:
        errors.append(ContractViolation(path, "const"))
    if "enum" in schema and value not in schema["enum"]:
        errors.append(ContractViolation(path, "enum"))
    if isinstance(value, str):
        if "pattern" in schema and re.fullmatch(str(schema["pattern"]), value) is None:
            errors.append(ContractViolation(path, "pattern"))
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(ContractViolation(path, "minLength"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(ContractViolation(path, "minimum"))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(ContractViolation(path, "maximum"))
    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(ContractViolation(path, "minItems"))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate(item_schema, item, f"{path}[{index}]"))
    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(ContractViolation(f"{path}.{key}", "required"))
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value.keys() - properties.keys():
                errors.append(ContractViolation(f"{path}.{key}", "additionalProperties"))
        for key in value.keys() & properties.keys():
            errors.extend(validate(properties[key], value[key], f"{path}.{key}"))
    return tuple(errors)
