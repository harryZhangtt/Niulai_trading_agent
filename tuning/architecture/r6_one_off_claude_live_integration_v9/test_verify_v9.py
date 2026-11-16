"""Independent deterministic parity and closure checks for evidence-only v9."""
from __future__ import annotations

import copy
import importlib.util
import itertools
import json
import os
import pathlib
import tempfile
import types
import unittest

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parents[3]
ARCH = pathlib.Path(__file__).resolve().parent
SCHEMA = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v8/schemas/p0-output-v8.schema.json"

sys_path_added = False
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT)); sys_path_added = True

from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8 import runner
from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v8.contracts import blank_seal

spec = importlib.util.spec_from_file_location("verify_v9", ARCH / "verify_v9.py")
verify_v9 = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verify_v9)


class EvidenceOnlyV9Tests(unittest.TestCase):
    def test_real_recover_and_independent_288_case_parity(self):
        validator = Draft202012Validator(json.loads(SCHEMA.read_text()))
        with tempfile.TemporaryDirectory() as name:
            projection_root = pathlib.Path(name)
            (projection_root / "public").mkdir()
            (projection_root / runner.FENCE_PENDING_NAME).write_text("{}")
            fd = os.open(projection_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                recovered = runner._recover(types.SimpleNamespace(fd=fd, path=projection_root))
            finally:
                os.close(fd)
        self.assertIsNotNone(recovered)
        actual = runner._p0_output(recovered)
        validator.validate(actual)
        self.assertEqual(
            {key: actual[key] for key in ("status", "state_authority", "durability", "cell_id", "engine_provider", "engine_readback_digest")},
            {"status": "UNKNOWN", "state_authority": "ABSENT", "durability": "NON_DURABLE", "cell_id": None, "engine_provider": None, "engine_readback_digest": None},
        )

        template = runner._p0_output(blank_seal())
        valid = {
            ("PASS", "PASS", "NOT_APPLICABLE", True, True, True),
            ("STOP", "ABSENT", "NOT_APPLICABLE", False, False, False),
            ("UNKNOWN", "ABSENT", "NON_DURABLE", False, False, False),
            ("UNKNOWN", "UNKNOWN", "DURABLE", True, True, True),
            ("UNKNOWN", "POISONED", "DURABLE", True, True, True),
        }
        accepted = set()
        cases = 0
        for key in itertools.product(
            ("PASS", "STOP", "UNKNOWN"),
            ("ABSENT", "UNKNOWN", "PASS", "POISONED"),
            ("NOT_APPLICABLE", "DURABLE", "NON_DURABLE"),
            (False, True), (False, True), (False, True),
        ):
            status, authority, durability, has_cell, has_provider, has_digest = key
            candidate = copy.deepcopy(template)
            candidate.update(
                status=status, state_authority=authority, durability=durability,
                cell_id="cell/bound" if has_cell else None,
                engine_provider="claude_host" if has_provider else None,
                engine_readback_digest="a" * 64 if has_digest else None,
            )
            cases += 1
            schema_valid = validator.is_valid(candidate)
            self.assertEqual(schema_valid, key in valid, key)
            if schema_valid:
                accepted.add(key)
        self.assertEqual(cases, 288)
        self.assertEqual(accepted, valid)

    def test_complete_closure_and_zero_source_delta(self):
        summary = verify_v9.verify_all()
        self.assertEqual(summary["artifact_count"], 36)
        self.assertEqual(summary["semantic_source_delta_count"], 0)

    def test_exact_predecessor_review_and_corrected_v7_descriptor(self):
        closure = json.loads((ARCH / "source-closure-v9.json").read_text())
        self.assertEqual(closure["predecessor_review_binding"]["path"], verify_v9.V8_REVIEW_REL)
        self.assertEqual(closure["corrected_descriptor"]["from_v8_incorrect"], "v6 OPEN review")
        self.assertEqual(closure["corrected_descriptor"]["to_v9_exact"], "v7 OPEN review")
        self.assertEqual(closure["corrected_descriptor"]["exact_member"]["path"], verify_v9.V7_REVIEW_REL)

    def test_every_evidence_descriptor_version_path_and_hash_is_consistent(self):
        summary = verify_v9.verify_all()
        self.assertGreater(summary["descriptor_count"], 0)
        self.assertEqual(summary["status"], "PASS")

    def test_disabled_unregistered_open_and_p0_gate(self):
        for name in verify_v9.DOC_TYPES:
            doc = json.loads((ARCH / name).read_text())
            self.assertIs(doc["activation"], False, name)
            self.assertIs(doc["registration"], False, name)
            self.assertEqual(doc["p0_v10_reclosure"], "P0_V10_RECLOSURE_REQUIRED", name)
            self.assertIn("OPEN", doc["status"], name)
        decision = json.loads((ARCH / "decision-v9.json").read_text())
        self.assertIs(decision["fresh_independent_review"], False)
        self.assertEqual(decision["fresh_independent_review_status"], "PENDING")
        self.assertFalse(decision["countable"])


if __name__ == "__main__":
    unittest.main()
