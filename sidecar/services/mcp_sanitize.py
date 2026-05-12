"""Sanitize MCP tool schemas for OpenAI function-calling compatibility."""

import copy
import logging

logger = logging.getLogger("vanilla.mcp_sanitize")

_UNSUPPORTED_TOP_LEVEL = (
    "$id", "$schema", "$ref", "$comment", "patternProperties",
    "additionalProperties", "if", "then", "else",
)

_UNSUPPORTED_PROP_KEYS = ("$ref", "default", "examples", "const")


def sanitize_tool_schema(schema: dict) -> dict:
    """Transform a JSON Schema to conform to OpenAI function-calling strict subset.

    Fixes:
    - Missing "type" on properties → defaults to "string"
    - anyOf/oneOf containing null → collapses to first non-null type
    - Missing "required" → adds empty list
    - Removes unsupported keywords at top level and within properties
    """
    schema = copy.deepcopy(schema)

    for key in _UNSUPPORTED_TOP_LEVEL:
        schema.pop(key, None)

    if "required" not in schema:
        schema["required"] = []

    if "type" not in schema:
        schema["type"] = "object"

    for prop_name, prop in schema.get("properties", {}).items():
        _fix_property(prop, prop_name)

    return schema


def _fix_property(prop: dict, name: str) -> None:
    """Fix a single property definition in-place."""
    for combiner in ("anyOf", "oneOf"):
        if combiner in prop:
            types = prop.pop(combiner)
            non_null = [t for t in types if t.get("type") != "null"]
            has_null = any(t.get("type") == "null" for t in types)

            if non_null:
                prop.update(non_null[0])
                if has_null and "type" in prop:
                    desc = prop.get("description", "")
                    if "optional" not in desc.lower() and "null" not in desc.lower():
                        prop["description"] = (
                            desc + " (optional, may be null)" if desc else "Optional"
                        )
            else:
                prop["type"] = "string"
                logger.warning(
                    "Property '%s' had %s with only null types, defaulting to string",
                    name, combiner,
                )

    if "type" not in prop and "enum" not in prop:
        prop["type"] = "string"
        logger.warning("Property '%s' had no type, defaulting to string", name)

    for key in _UNSUPPORTED_PROP_KEYS:
        prop.pop(key, None)

    if prop.get("type") == "object" and "properties" in prop:
        if "required" not in prop:
            prop["required"] = []
        for sub_name, sub_prop in prop["properties"].items():
            _fix_property(sub_prop, f"{name}.{sub_name}")

    if prop.get("type") == "array" and "items" in prop:
        _fix_property(prop["items"], f"{name}[]")


def sanitize_all_tools(tools: list[dict]) -> list[dict]:
    """Sanitize a list of MCP tool definitions."""
    sanitized = []
    for tool in tools:
        try:
            if "function" in tool and "parameters" in tool["function"]:
                tool = copy.deepcopy(tool)
                tool["function"]["parameters"] = sanitize_tool_schema(
                    tool["function"]["parameters"]
                )
            sanitized.append(tool)
        except Exception as e:
            logger.error(
                "Failed to sanitize tool '%s': %s",
                tool.get("function", {}).get("name", "?"), e,
            )
            sanitized.append(tool)  # pass through rather than drop
    return sanitized
