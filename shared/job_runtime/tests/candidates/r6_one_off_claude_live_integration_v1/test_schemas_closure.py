from __future__ import annotations
import ast
import copy
import hashlib
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[5]
PKG = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v1"
SCHEMAS = PKG / "schemas"
FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"


class ClosureTests(unittest.TestCase):
    def test_candidate_is_additive_inert_and_has_no_provider_sdk_or_registration(self):
        for path in PKG.glob("*.py"):
            text = path.read_text()
            tree = ast.parse(text)
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports += [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports += [node.module or ""]
            self.assertFalse(any(item.startswith(("requests", "httpx", "anthropic"))
                                 for item in imports))
        runtime = ROOT / "shared/job_runtime"
        self.assertFalse(any("r6_one_off_claude_live_integration_v1" in path.read_text()
                             for path in runtime.glob("*.py")))

    def test_v1_v2_v3_open_history_is_byte_preserved(self):
        expected = {
            "protocol-v1.json": (3381, "b7cedfceb9430936c6aab0d6f0a3a8cfe5213bc71f3e0ff5261fe9c301ebc6c4"),
            "decision-v1.json": (1076, "b8915c0102b0e75dddbfb94a08c6dc5e414b3b6fb359d5230dc8fd382fa48913"),
            "producer-verification-v1-final.json": (3066, "7a2d053a8eb93c5ec60d2cf8bf1bd179637b3501db3bc3a0276e5ed98b66704e"),
            "protocol-v2.json": (1259, "62f3b05a96f5d54736a232926cde9508637e5458b9a3b8e8275a7485bec26765"),
            "decision-v2.json": (1057, "3d47ffd5b588fc9ad138d0f8538f42284c2108c451a143c49eac5fd3c9e6976e"),
            "producer-verification-v2-final.json": (3570, "be365e5b75ebe621ec98b0430c013518c12722f79b29f907199920dd0ab82ff4"),
            "protocol-v3.json": (722, "76d7c53ace07305b8c81958263ba8d253e5f31a701c7404e8fc6cfd006cba967"),
            "decision-v3.json": (620, "d8dd42a53cc3ca9403698b908d26bbdf1c639d42675f55239eddb15dc6525ce2"),
            "source-closure-v3.json": (7484, "f8554858dfcf442dc298d7c0779757b5e9124ce575cbd79ac36f795f855dc52e"),
            "producer-verification-v3-final.json": (2674, "3d551495380798099bb736af63414a510258f68067bef2ff399ae381d57757fa"),
        }
        base = ROOT / "tuning/architecture/r6_one_off_claude_live_integration_v1"
        for name, identity in expected.items():
            raw = (base / name).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), identity)

    def test_draft_2020_12_recursive_strictness_and_instances(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("Draft202012 unavailable")
        def walk(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        schemas = {}
        names = (
            "fixed-registry-v4.schema.json",
            "registry-independent-review-v4.schema.json",
            "pre-dispatch-grant-v4.schema.json",
            "grant-independent-review-v4.schema.json",
            "provider-free-scope-v4.schema.json",
            "post-run-seal-v4.schema.json",
            "unknown-fence-v4.schema.json",
            "p0-output-v4.schema.json",
        )
        for name in names:
            schema = json.loads((SCHEMAS / name).read_text())
            Draft202012Validator.check_schema(schema)
            walk(schema)
            schemas[name] = schema
        from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1 import (
            LocalOnlyProcessEffect, p0_output, run,
        )
        from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v1 import authority
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            seal = run(pathlib.Path(temp) / "pass", effect=LocalOnlyProcessEffect(True))
            unknown = run(pathlib.Path(temp) / "unknown", effect=LocalOnlyProcessEffect(True),
                          scenario="timeout")
            wrapper = json.loads((pathlib.Path(temp) / "unknown/unknown-fence-v4.json").read_text())
        instances = {
            "fixed-registry-v4.schema.json": authority._held(authority.REGISTRY_REF),
            "registry-independent-review-v4.schema.json": authority._held(authority.REGISTRY_REVIEW_REF),
            "pre-dispatch-grant-v4.schema.json": authority._held(authority.GRANT_REF),
            "grant-independent-review-v4.schema.json": authority._held(authority.GRANT_REVIEW_REF),
            "provider-free-scope-v4.schema.json": authority._held(authority.SCOPE_REF),
            "post-run-seal-v4.schema.json": seal,
            "unknown-fence-v4.schema.json": wrapper,
            "p0-output-v4.schema.json": p0_output(unknown),
        }
        for name, value in instances.items():
            Draft202012Validator(schemas[name]).validate(value)
        bad = copy.deepcopy(wrapper)
        del bad["seal"]["process"]["descendants_reaped"]
        self.assertFalse(Draft202012Validator(
            schemas["unknown-fence-v4.schema.json"]).is_valid(bad))


if __name__ == "__main__":
    unittest.main()
