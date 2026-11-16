"""Tiny dependency-free validator for the JSON Schema keywords used by fixtures."""
import re


class SchemaViolation(ValueError):
    pass


def _equal(left, right):
    # Draft 2020-12 treats mathematically equal JSON numbers as equal while
    # booleans remain a distinct instance type.
    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in (int, float) and type(right) in (int, float):
        return left == right
    return type(left) is type(right) and left == right


def validate(instance, schema, path="$", root=None):
    if root is None:
        root = schema
    errors = []
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate(instance, target, path, root)
    if "allOf" in schema:
        for child in schema["allOf"]:
            errors.extend(validate(instance, child, path, root))
    if "oneOf" in schema:
        matches = [not validate(instance, child, path, root) for child in schema["oneOf"]]
        if sum(matches) != 1:
            errors.append(path + ":oneOf")
    if "const" in schema and not _equal(instance, schema["const"]):
        errors.append(path + ":const")
    if "enum" in schema and not any(_equal(instance, item) for item in schema["enum"]):
        errors.append(path + ":enum")
    lexical = schema.get("x-canonical-json-type")
    if lexical == "integer" and type(instance) is not int:
        errors.append(path + ":x-canonical-json-type")
    kind = schema.get("type")
    valid_type = True
    if kind == "object": valid_type = type(instance) is dict
    elif kind == "array": valid_type = type(instance) is list
    elif kind == "string": valid_type = type(instance) is str
    elif kind == "integer": valid_type = (type(instance) is int or
                                            (type(instance) is float and instance.is_integer()))
    elif kind == "number": valid_type = type(instance) in (int, float)
    elif kind == "boolean": valid_type = type(instance) is bool
    elif kind == "null": valid_type = instance is None
    if not valid_type:
        errors.append(path + ":type")
        return errors
    if isinstance(instance, dict):
        required = schema.get("required", [])
        errors.extend(path + "." + key + ":required" for key in required if key not in instance)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors.extend(path + "." + key + ":additional" for key in instance if key not in properties)
        for key, child in properties.items():
            if key in instance:
                errors.extend(validate(instance[key], child, path + "." + key, root))
    if isinstance(instance, list):
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(path + ":maxItems")
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(path + ":minItems")
        if schema.get("uniqueItems") and len({repr(item) for item in instance}) != len(instance):
            errors.append(path + ":uniqueItems")
        if "items" in schema:
            for index, item in enumerate(instance):
                errors.extend(validate(item, schema["items"], "%s[%d]" % (path, index), root))
    if type(instance) is str and "pattern" in schema and re.fullmatch(schema["pattern"], instance) is None:
        errors.append(path + ":pattern")
    if type(instance) in (int, float):
        if "minimum" in schema and instance < schema["minimum"]: errors.append(path + ":minimum")
        if "maximum" in schema and instance > schema["maximum"]: errors.append(path + ":maximum")
    return errors


def require_valid(instance, schema):
    errors = validate(instance, schema)
    if errors:
        raise SchemaViolation(errors[0])
