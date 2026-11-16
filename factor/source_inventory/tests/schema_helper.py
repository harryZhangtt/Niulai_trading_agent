"""Small dependency-free Draft 2020-12 subset used by contract tests only."""
import json
import re


class SchemaFailure(AssertionError):
    pass


def _same(value, expected):
    return type(value) is type(expected) and value == expected


def _types(value):
    if value is None: return "null"
    if type(value) is bool: return "boolean"
    if type(value) is int: return "integer"
    if type(value) is float: return "number"
    if type(value) is str: return "string"
    if type(value) is list: return "array"
    if type(value) is dict: return "object"
    return "unknown"


def _resolve(root, reference):
    if not reference.startswith("#/"):
        raise SchemaFailure("external ref unsupported in this focused helper")
    value = root
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def accepts(instance, schema, root=None):
    root = root or schema
    try:
        validate(instance, schema, root)
        return True
    except SchemaFailure:
        return False


def validate(instance, schema, root=None):
    root = root or schema
    if "$ref" in schema:
        return validate(instance, _resolve(root, schema["$ref"]), root)
    if "const" in schema and not _same(instance, schema["const"]):
        raise SchemaFailure("const")
    if "enum" in schema and not any(_same(instance, item) for item in schema["enum"]):
        raise SchemaFailure("enum")
    if "type" in schema:
        allowed = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        actual = _types(instance)
        if actual == "integer" and "number" in allowed:
            actual = "number"
        if actual not in allowed:
            raise SchemaFailure("type")
    for option_key, expected in (("minLength", len(instance) if isinstance(instance, str) else None),
                                 ("maxLength", len(instance) if isinstance(instance, str) else None),
                                 ("minItems", len(instance) if isinstance(instance, list) else None),
                                 ("maxItems", len(instance) if isinstance(instance, list) else None),
                                 ("minProperties", len(instance) if isinstance(instance, dict) else None),
                                 ("maxProperties", len(instance) if isinstance(instance, dict) else None)):
        if option_key in schema and expected is not None:
            if option_key.startswith("min") and expected < schema[option_key]: raise SchemaFailure(option_key)
            if option_key.startswith("max") and expected > schema[option_key]: raise SchemaFailure(option_key)
    if "minimum" in schema and (type(instance) not in {int, float} or isinstance(instance, bool) or instance < schema["minimum"]):
        raise SchemaFailure("minimum")
    if "maximum" in schema and (type(instance) not in {int, float} or isinstance(instance, bool) or instance > schema["maximum"]):
        raise SchemaFailure("maximum")
    if "pattern" in schema and (not isinstance(instance, str) or re.fullmatch(schema["pattern"], instance) is None):
        raise SchemaFailure("pattern")
    if schema.get("uniqueItems") and isinstance(instance, list):
        encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
        if len(encoded) != len(set(encoded)): raise SchemaFailure("uniqueItems")
    if isinstance(instance, dict):
        required = schema.get("required", [])
        if not set(required) <= set(instance): raise SchemaFailure("required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and not set(instance) <= set(properties):
            raise SchemaFailure("additionalProperties")
        for key, child in properties.items():
            if key in instance: validate(instance[key], child, root)
    if isinstance(instance, list):
        prefix = schema.get("prefixItems", [])
        for index, child in enumerate(prefix):
            if index < len(instance): validate(instance[index], child, root)
        items = schema.get("items")
        if items is False and len(instance) > len(prefix): raise SchemaFailure("items")
        if isinstance(items, dict):
            for item in instance[len(prefix):]: validate(item, items, root)
        if "contains" in schema:
            count = sum(accepts(item, schema["contains"], root) for item in instance)
            if count < schema.get("minContains", 1) or count > schema.get("maxContains", len(instance)):
                raise SchemaFailure("contains")
    for child in schema.get("allOf", []): validate(instance, child, root)
    if "anyOf" in schema and not any(accepts(instance, child, root) for child in schema["anyOf"]):
        raise SchemaFailure("anyOf")
    if "oneOf" in schema and sum(accepts(instance, child, root) for child in schema["oneOf"]) != 1:
        raise SchemaFailure("oneOf")
    if "if" in schema and accepts(instance, schema["if"], root):
        if "then" in schema: validate(instance, schema["then"], root)
    return instance
