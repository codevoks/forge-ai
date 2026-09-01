"""A narrow, bounded JSON Schema subset for dynamically discovered MCP tool contracts.

Forge cannot compile a static Pydantic model for a tool schema that is only known at
runtime (discovered from a remote MCP server). This module enforces a deliberately
small, deterministic schema dialect instead of depending on an external JSON Schema
library: object/array/string/integer/number/boolean, `properties`, `required`,
`additionalProperties`, `enum`, `minLength`/`maxLength`, `minimum`/`maximum`, and
`items`. `validate_schema_shape` bounds what a discovered schema is allowed to declare
(depth, property count, keyword set) before it is ever stored or trusted for
validation. `validate_payload` then enforces that bounded shape against real input or
output payloads.
"""

import re
from typing import Any

MAX_SCHEMA_DEPTH = 4
MAX_SCHEMA_PROPERTIES = 20
_PROPERTY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_SUPPORTED_TYPES = {"object", "array", "string", "integer", "number", "boolean"}
_SUPPORTED_KEYWORDS = {
    "type",
    "properties",
    "required",
    "additionalProperties",
    "enum",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "items",
    "description",
    "title",
}


def validate_schema_shape(schema: Any, *, depth: int = 0) -> list[str]:
    """Return shape violations, bounded; an empty list means the schema is safe to store."""
    if depth > MAX_SCHEMA_DEPTH:
        return ["schema_too_deep"]
    if not isinstance(schema, dict):
        return ["schema_not_an_object"]
    errors: list[str] = []
    unknown = sorted(set(schema.keys()) - _SUPPORTED_KEYWORDS)
    if unknown:
        errors.append(f"unsupported_keywords:{','.join(unknown)}")
    schema_type = schema.get("type")
    if depth == 0 and schema_type != "object":
        errors.append("root_type_must_be_object")
        return errors
    if schema_type not in _SUPPORTED_TYPES:
        errors.append(f"unsupported_type:{schema_type!r}")
        return errors
    if schema_type == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            errors.append("properties_must_be_object")
        else:
            if len(properties) > MAX_SCHEMA_PROPERTIES:
                errors.append("too_many_properties")
            for name, sub_schema in properties.items():
                if not isinstance(name, str) or not _PROPERTY_NAME.match(name):
                    errors.append(f"invalid_property_name:{name!r}")
                    continue
                errors.extend(validate_schema_shape(sub_schema, depth=depth + 1))
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            errors.append("required_must_be_a_string_list")
        additional = schema.get("additionalProperties", True)
        if not isinstance(additional, bool):
            errors.append("additional_properties_must_be_boolean")
    elif schema_type == "array":
        items = schema.get("items")
        if items is not None:
            errors.extend(validate_schema_shape(items, depth=depth + 1))
    return errors


def validate_payload(payload: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Validate `payload` against a schema already accepted by `validate_schema_shape`."""
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(payload, dict):
            return [f"{path}: expected object"]
        errors: list[str] = []
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []
        additional = schema.get("additionalProperties", True)
        for key in required:
            if key not in payload:
                errors.append(f"{path}: missing required property '{key}'")
        for key, value in payload.items():
            if key in properties:
                errors.extend(validate_payload(value, properties[key], path=f"{path}.{key}"))
            elif additional is False:
                errors.append(f"{path}: unexpected property '{key}'")
        return errors
    if schema_type == "array":
        if not isinstance(payload, list):
            return [f"{path}: expected array"]
        items_schema = schema.get("items")
        if items_schema is None:
            return []
        errors = []
        for index, item in enumerate(payload):
            errors.extend(validate_payload(item, items_schema, path=f"{path}[{index}]"))
        return errors
    if schema_type == "string":
        if not isinstance(payload, str):
            return [f"{path}: expected string"]
        errors = []
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(payload) < min_length:
            errors.append(f"{path}: shorter than minLength {min_length}")
        if isinstance(max_length, int) and len(payload) > max_length:
            errors.append(f"{path}: longer than maxLength {max_length}")
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and payload not in enum_values:
            errors.append(f"{path}: value not in enum")
        return errors
    if schema_type == "integer":
        if not isinstance(payload, int) or isinstance(payload, bool):
            return [f"{path}: expected integer"]
        return _numeric_range_errors(payload, schema, path)
    if schema_type == "number":
        if not isinstance(payload, int | float) or isinstance(payload, bool):
            return [f"{path}: expected number"]
        return _numeric_range_errors(payload, schema, path)
    if schema_type == "boolean":
        if not isinstance(payload, bool):
            return [f"{path}: expected boolean"]
        return []
    return [f"{path}: unsupported schema type {schema_type!r}"]


def _numeric_range_errors(value: float, schema: dict[str, Any], path: str) -> list[str]:
    errors: list[str] = []
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, int | float) and value < minimum:
        errors.append(f"{path}: below minimum {minimum}")
    if isinstance(maximum, int | float) and value > maximum:
        errors.append(f"{path}: above maximum {maximum}")
    return errors
