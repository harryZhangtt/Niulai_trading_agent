from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2 import (
    ClaudeFixturePort, CodexFixturePort, DestinationSnapshot, FourCellFixtureOrchestrator,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2.authority import verify_authority

ROOT = Path(__file__).resolve().parents[5]
SCHEMAS = ROOT / "shared/job_runtime/candidates/r6_common_four_cell_orchestrator_v2/schemas"

class SchemaTests(unittest.TestCase):
    def test_every_object_schema_is_closed_and_required(self):
        files = sorted(SCHEMAS.glob("*.schema.json"))
        self.assertEqual(len(files), 5)
        for path in files:
            schema = json.loads(path.read_text())
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertEqual(schema["type"], "object")
            stack = [schema]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if node.get("type") == "object":
                        self.assertIs(node.get("additionalProperties"), False, path.name)
                        self.assertEqual(set(node.get("required", [])), set(node.get("properties", {})), path.name)
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema unavailable in this interpreter")
    def test_nominal_and_unknown_instances_validate_draft_2020_12(self):
        loaded = {path.name: json.loads(path.read_text()) for path in SCHEMAS.glob("*.schema.json")}
        for schema in loaded.values():
            Draft202012Validator.check_schema(schema)
        authority = verify_authority()
        nominal = FourCellFixtureOrchestrator(ClaudeFixturePort(), CodexFixturePort()).run(DestinationSnapshot.empty())
        unknown = FourCellFixtureOrchestrator(
            __import__("shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2", fromlist=["FixtureProfile"]).ClaudeFixturePort(
                __import__("shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2", fromlist=["FixtureProfile"]).FixtureProfile.UNKNOWN_FIRST
            ), CodexFixturePort()
        ).run(DestinationSnapshot.empty())
        Draft202012Validator(loaded["block-grant-v1.schema.json"]).validate(authority["grant"])
        for result in (nominal, unknown):
            Draft202012Validator(loaded["block-result-v2.schema.json"]).validate(result)
            Draft202012Validator(loaded["evaluation-runner-handoff-v2.schema.json"]).validate(result["evaluation_handoff"])
            for admission in result["admissions"]:
                Draft202012Validator(loaded["provider-result-v1.schema.json"]).validate(admission)
            for handoff in result["p0_handoffs"]:
                Draft202012Validator(loaded["p0-attempt-handoff-v2.schema.json"]).validate(handoff)

if __name__ == "__main__":
    unittest.main()
