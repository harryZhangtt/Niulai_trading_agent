import ast
import importlib
import json
import sys
import unittest
from pathlib import Path
from types import MappingProxyType

from shared.job_runtime.candidates.isolated_canary_q1_v2.harness import (
    HarnessV2Error,
    build_harness_config,
    expected_bindings,
)


ROOT = Path(__file__).parents[5]
CANDIDATE = ROOT / "shared/job_runtime/candidates/isolated_canary_q1_v2"
FIXTURE = ROOT / "shared/job_runtime/tests/fixtures/isolated_canary_q1_v2/harness-v2.expected.json"
SCHEMA = CANDIDATE / "harness-v2.schema.json"
HARNESS = CANDIDATE / "harness.py"


def thaw(value):
    if isinstance(value, MappingProxyType):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def assert_exact_schema(test, value, schema):
    if "const" in schema:
        test.assertEqual(value, schema["const"])
        test.assertIs(type(value), type(schema["const"]))
        return
    test.assertEqual(schema.get("type"), "object")
    test.assertIs(type(value), dict)
    properties = schema["properties"]
    test.assertFalse(schema["additionalProperties"])
    test.assertEqual(set(value), set(schema["required"]))
    test.assertEqual(set(value), set(properties))
    for key, child in properties.items():
        assert_exact_schema(test, value[key], child)


class HarnessV2Tests(unittest.TestCase):
    def bindings(self):
        return dict(expected_bindings())

    def test_exact_fixture_and_schema(self):
        with FIXTURE.open(encoding="utf-8") as handle:
            fixture = json.load(handle)
        with SCHEMA.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        actual = thaw(build_harness_config(self.bindings()))
        self.assertEqual(actual, fixture)
        assert_exact_schema(self, fixture, schema)

    def test_every_binding_mutation_is_rejected(self):
        for key in self.bindings():
            with self.subTest(key=key), self.assertRaises(HarnessV2Error):
                build_harness_config({**self.bindings(), key: "0" * 64})

    def test_missing_extra_and_type_errors(self):
        base = self.bindings()
        values = [
            {key: value for key, value in base.items() if key != "payload_sha256"},
            {**base, "extra": "0" * 64},
            {**base, "payload_sha256": b"0" * 64},
            MappingProxyType(base),
            [],
        ]
        for value in values:
            with self.subTest(value=type(value).__name__), self.assertRaises(HarnessV2Error):
                build_harness_config(value)

    def test_nested_output_is_immutable(self):
        value = build_harness_config(self.bindings())
        with self.assertRaises(TypeError):
            value["enabled"] = True
        for key in ("bindings", "execution", "retries", "capabilities", "live", "effects"):
            with self.subTest(key=key), self.assertRaises(TypeError):
                value[key][next(iter(value[key]))] = None

    def test_disabled_closed_bounded_and_effect_none(self):
        value = build_harness_config(self.bindings())
        self.assertFalse(value["enabled"])
        self.assertFalse(value["capabilities"]["capability_open"])
        self.assertEqual(dict(value["execution"]), {"max_workers": 1, "max_attempts": 1})
        self.assertEqual(dict(value["retries"]), {"request": 0, "stream": 0})
        self.assertTrue(all(flag is False for flag in value["live"].values()))
        self.assertTrue(all(flag is False for flag in value["effects"].values()))

    def test_import_is_inert_and_has_no_execution_dependencies(self):
        tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertEqual(imported, {"__future__", "types", "typing"})
        before = set(sys.modules)
        module = importlib.import_module("shared.job_runtime.candidates.isolated_canary_q1_v2.harness")
        self.assertIsNotNone(module)
        added = {name.split(".")[0] for name in set(sys.modules) - before}
        self.assertTrue(added.isdisjoint({"socket", "subprocess", "requests", "http", "urllib"}))

    def test_v1_coexists_without_harness_mutation(self):
        v1 = ROOT / "shared/job_runtime/candidates/isolated_canary_q1"
        self.assertTrue((v1 / "__init__.py").is_file())
        self.assertTrue((v1 / "canonical.py").is_file())
        self.assertFalse((v1 / "harness.py").exists())
        self.assertNotIn("build_harness_config", (v1 / "__init__.py").read_text(encoding="utf-8"))

    def test_no_absolute_or_private_paths(self):
        with FIXTURE.open(encoding="utf-8") as handle:
            serialized = json.dumps(json.load(handle), sort_keys=True)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn("/Users/", serialized)
        self.assertNotIn("niulai-private", serialized)

    def test_schema_all_nested_objects_are_exact_and_closed(self):
        with SCHEMA.open(encoding="utf-8") as handle:
            schema = json.load(handle)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        for key in ("bindings", "execution", "retries", "capabilities", "live", "effects"):
            node = schema["properties"][key]
            self.assertFalse(node["additionalProperties"])
            self.assertEqual(set(node["required"]), set(node["properties"]))
            self.assertTrue(all("const" in child for child in node["properties"].values()))


if __name__ == "__main__":
    unittest.main()
