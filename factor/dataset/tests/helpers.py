import copy
import hashlib
import json
from pathlib import Path
import shutil

from factor.dataset.contract import canonical, digest, loads


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "factor/dataset/fixtures/synthetic-pit-v1"


def fixture_copy(base):
    target = Path(base) / "snapshot"
    shutil.copytree(FIXTURE, target)
    return target


def descriptor(root):
    return loads((Path(root) / "dataset.json").read_bytes())


def write_descriptor(root, value):
    (Path(root) / "dataset.json").write_bytes(canonical(value) + b"\n")


def read_artifact(root, name):
    value = descriptor(root)
    ref = value["artifacts"][name]
    raw = (Path(root) / ref["path"]).read_bytes()
    if ref["path"].endswith(".jsonl"):
        return [loads(line) for line in raw.splitlines()]
    return loads(raw)


def rewrite_artifact(root, name, value):
    root = Path(root)
    description = descriptor(root)
    ref = description["artifacts"][name]
    if ref["path"].endswith(".jsonl"):
        raw = b"".join(canonical(row) + b"\n" for row in value)
        rows = len(value)
    else:
        raw = canonical(value) + b"\n"
        rows = 1
    (root / ref["path"]).write_bytes(raw)
    ref.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw), rows=rows)
    write_descriptor(root, description)


def semantic_labels(root):
    roster = read_artifact(root, "label_roster")
    values = {row["sample_id"]: row for row in read_artifact(root, "label_values")}
    semantics = {}
    committed = {}
    for row in roster:
        semantic = {key: row[key] for key in ("target_definition_sha256", "entity_id",
                                               "origin_session", "window_start_session",
                                               "window_end_session", "maturity_at")}
        identity = digest(semantic)
        semantics[identity] = semantic
        value = values[row["sample_id"]]
        committed[identity] = {"semantic_sample_sha256": identity,
                               "value": value["value"], "unit": value["unit"]}
    return semantics, committed


def refresh_label_authority(root):
    semantics, committed = semantic_labels(root)
    authority = read_artifact(root, "label_authority")
    authority["label_roster_sha256"] = digest([semantics[key] for key in sorted(semantics)])
    authority["label_commitment_sha256"] = digest(
        {"synthetic_fixture_values": [committed[key] for key in sorted(committed)]})
    rewrite_artifact(root, "label_authority", authority)


def validate_schema(instance, schema, root=None):
    root = schema if root is None else root
    if "$ref" in schema:
        target = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        return validate_schema(instance, target, root)
    if "const" in schema:
        assert type(instance) is type(schema["const"]) and instance == schema["const"]
    expected = schema.get("type")
    if expected == "object":
        assert type(instance) is dict
        required = set(schema.get("required", [])); assert required <= set(instance)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False: assert set(instance) <= set(properties)
        for key, value in instance.items():
            if key in properties: validate_schema(value, properties[key], root)
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(value, schema["additionalProperties"], root)
        if "minProperties" in schema: assert len(instance) >= schema["minProperties"]
    elif expected == "array":
        assert type(instance) is list
        if "minItems" in schema: assert len(instance) >= schema["minItems"]
        for value in instance: validate_schema(value, schema.get("items", {}), root)
    elif expected == "string":
        import re
        assert type(instance) is str
        if "minLength" in schema: assert len(instance) >= schema["minLength"]
        if "maxLength" in schema: assert len(instance) <= schema["maxLength"]
        if "pattern" in schema: assert re.fullmatch(schema["pattern"], instance)
        if schema.get("format") == "date":
            from datetime import date
            date.fromisoformat(instance)
        if schema.get("format") == "date-time":
            from datetime import datetime
            assert instance.endswith("Z")
            datetime.fromisoformat(instance[:-1] + "+00:00")
    elif expected == "integer":
        assert type(instance) is int
        if "minimum" in schema: assert instance >= schema["minimum"]
        if "maximum" in schema: assert instance <= schema["maximum"]


def clone(value):
    return copy.deepcopy(value)
