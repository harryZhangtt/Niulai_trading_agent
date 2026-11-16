from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import unittest

from shared.job_runtime.candidates.r6_one_off_claude_adapter_v1.contracts import (
    FROZEN_REFS,
    stage_a_template,
)

ROOT = Path(__file__).resolve().parents[5]
SRC = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_adapter_v1"
FIXTURES = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_adapter_v1"
DESIGN = ROOT / FROZEN_REFS["design"]["path"]
REVIEW = ROOT / FROZEN_REFS["design_review"]["path"]


class InertnessAndSchemaTests(unittest.TestCase):
    def test_all_frozen_bindings_match_path_bytes_and_hash(self):
        for name, expected in FROZEN_REFS.items():
            with self.subTest(name=name):
                raw = (ROOT / expected["path"]).read_bytes()
                self.assertEqual(len(raw), expected["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])

    def test_imports_have_no_provider_network_process_or_blocked_generic_surface(self):
        forbidden_imports = {
            "anthropic", "socket", "subprocess", "urllib", "http", "smtplib",
            "requests", "httpx", "aiohttp",
        }
        allowed_composed = "shared.job_runtime.candidates.r6_one_off_evidence_v1"
        found_composed = False
        for path in SRC.glob("*.py"):
            tree = ast.parse(path.read_text())
            imports = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split(".")[0])
                    if node.module == allowed_composed:
                        found_composed = True
                    self.assertNotIn("codex_live_evidence_r6_live_v1", node.module)
            self.assertTrue(imports.isdisjoint(forbidden_imports), (path, imports & forbidden_imports))
        self.assertTrue(found_composed)

    def test_candidate_is_not_reachable_from_canonical_runtime(self):
        for path in (ROOT / "shared/job_runtime").glob("*.py"):
            self.assertNotIn("r6_one_off_claude_adapter_v1", path.read_text(), path)

    def test_three_schemas_are_draft_2020_12_and_recursively_closed(self):
        paths = sorted(SRC.glob("*.schema.json"))
        self.assertEqual(len(paths), 3)

        def walk(value, location="$"):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False, location)
                    self.assertEqual(set(value.get("required", [])), set(value.get("properties", {})), location)
                for key, child in value.items():
                    walk(child, location + "/" + key)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    walk(child, location + "/" + str(index))

        for path in paths:
            value = json.loads(path.read_text())
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
            walk(value)
            try:
                from jsonschema import Draft202012Validator
            except ImportError:
                continue
            Draft202012Validator.check_schema(value)

    def test_stage_a_schema_accepts_template_and_rejects_authority_widening(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema unavailable")
        schema = json.loads((SRC / "stage-a-template-v1.schema.json").read_text())
        value = stage_a_template("a" * 64, "opaque-ref://claude/current")
        Draft202012Validator(schema).validate(value)
        value["provider_authorized"] = True
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(value)))

    def test_r5_is_historical_identity_only_and_unchanged(self):
        self.assertEqual(FROZEN_REFS["r5_runner_historical_only"]["sha256"], "d199fd079b7f94ca17d9fd1d6bb9e5b2339178403948d8173dabebd948b33d78")
        self.assertEqual(FROZEN_REFS["r5_result_historical_only"]["sha256"], "ae7914cf59b61d3dc915b86d364cebafd3da09827219f6154d179d35442cd9c7")


if __name__ == "__main__":
    unittest.main()
