import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "mentor/references/llm-engineering/candidates/1.0.2"
SPEC = importlib.util.spec_from_file_location("candidate_102", CANDIDATE / "validate.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Candidate102Tests(unittest.TestCase):
    def test_real_frozen_candidate_validates_and_is_inactive(self):
        result = MODULE.validate_package()
        self.assertEqual(result["candidate_version"], "1.0.2")
        self.assertFalse(result["active"])

    def test_projection_strips_identity_but_preserves_semantics(self):
        cards = MODULE.strict_load(MODULE.BASE / "knowledge-cards.json")
        card = cards["cards"][0]
        projected = MODULE.project_card(card)
        text = json.dumps(projected)
        self.assertNotIn(card["card_id"], text)
        self.assertNotIn("source_claim_ids", text)
        self.assertNotIn("owner_route", text)
        self.assertIn(card["procedure"][0]["action"], text)
        views, byte_count, proxy = MODULE.build_model_view([card["card_id"]], cards)
        self.assertEqual(len(views), 1)
        self.assertLessEqual(byte_count, 8192)
        self.assertLessEqual(proxy, 2048)
        self.assertEqual(MODULE.build_model_view([], cards), ([], 0, 0))

    def valid_output(self):
        return {"decision": "Measure the failure before changing the system.", "next_actions": ["Freeze a matched baseline."], "evidence_basis": [{"kind": "engineering_principle", "statement": "Comparable inputs are required."}], "allowed_claim": "Only the measured scope is supported."}

    def test_identifier_free_output_passes(self):
        result = MODULE.validate_output(self.valid_output())
        self.assertEqual(result["word_count"], 22)

    def test_every_identity_class_is_rejected(self):
        import base64
        literal = "KC-EVIDENCE-001"
        cases = [literal, "Use K-C Evidence 001", "Use K​C Evidence 001", "Use КC Evidence 001", "Follow development-discipline", "The selected guidance packet applies", "The route outcome is MATCH", "Mentor router assigns evaluation-design", "Inactive cards are advisory guidance", "Candidate guidance is explicitly inactive", "The supplied guidance is inactive", "candidate_active=false", "selected_card_bodies", "O1", "Read catalog.json", "a" * 64, base64.b64encode(literal.encode()).decode(), literal.encode().hex()]
        for text in cases:
            value = self.valid_output()
            value["decision"] = text
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "OUTPUT_IDENTITY_LEAK"):
                MODULE.validate_output(value)

    def test_generic_route_and_business_card_are_not_false_positives(self):
        value = self.valid_output()
        value["decision"] = "Route network traffic and verify the business card record."
        MODULE.validate_output(value)

    def test_nested_evidence_leak_is_rejected(self):
        value = self.valid_output()
        value["evidence_basis"][0]["statement"] = "The candidate guidance metadata says so."
        with self.assertRaisesRegex(ValueError, "OUTPUT_IDENTITY_LEAK"):
            MODULE.validate_output(value)

    def test_component_drift_breaks_package(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / "candidate"
            shutil.copytree(CANDIDATE, copy)
            path = copy / "solver-system-prompt.md"
            path.write_text(path.read_text() + " changed")
            with self.assertRaisesRegex(ValueError, "COMPONENT_HASH_MISMATCH"):
                MODULE.validate_package(copy)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x.json"
            path.write_text('{"a":1,"a":2}')
            with self.assertRaisesRegex(ValueError, "DUPLICATE_JSON_KEY"):
                MODULE.strict_load(path)


if __name__ == "__main__":
    unittest.main()
