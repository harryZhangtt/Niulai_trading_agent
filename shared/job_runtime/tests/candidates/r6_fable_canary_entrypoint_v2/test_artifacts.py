import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

from shared.job_runtime.candidates.r6_fable_canary_entrypoint_v2 import entrypoint

ROOT = Path(__file__).resolve().parents[5]
PACKAGE = ROOT / "shared/job_runtime/candidates/r6_fable_canary_entrypoint_v2"
EVIDENCE = ROOT / "tuning/architecture/r6_fable_canary_entrypoint_v2"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FableCanaryV2ArtifactTests(unittest.TestCase):
    def test_source_closure_exact_members(self):
        closure = json.loads((PACKAGE / "source_closure.json").read_bytes())
        self.assertEqual(set(closure["members"]), set(entrypoint._SOURCE_PATHS))
        for name, path in entrypoint._SOURCE_PATHS.items():
            self.assertEqual(closure["members"][name], {
                "bytes": Path(path).stat().st_size, "sha256": sha(path)})

    def test_exact_external_bindings(self):
        self.assertEqual(entrypoint._EXPECTED_PREFLIGHT_SHA256,
                         "44f29e81f7c00374a9b540c9d768233b92e8c0dbf775c697a9ee682f985b330b")
        self.assertEqual(entrypoint._EXPECTED_RUNTIME_LOCK_SHA256,
                         "f6334dd1ef9b696ef397feeedf20c3777c8ab7e19cdd2d978876bb3abcdef9c5")
        self.assertEqual(entrypoint._EXPECTED_BRIDGE_SHA256,
                         "da48b5a9c521ce4463d96f633d6a8971a7735dca88aa4dc068077d13102233c3")

    def test_evidence_closure_and_producer_receipt_are_off(self):
        closure = json.loads((EVIDENCE / "evidence-closure-v1.json").read_bytes())
        receipt = json.loads((EVIDENCE / "producer-verification-v1.json").read_bytes())
        for value in (closure, receipt):
            self.assertFalse(value["activation"])
            self.assertFalse(value["production_enabled"])
        self.assertEqual(closure["independent_review"], "PENDING")
        self.assertEqual(receipt["independent_review"], "PENDING")
        self.assertEqual(receipt["effects"], {
            "activation": 0, "network_calls": 0, "provider_calls": 0,
            "schedules": 0, "sdk_imports": 0})

    def test_empty_authority_and_no_service_registration(self):
        authority = json.loads((PACKAGE / "review_authority.json").read_bytes())
        manifest = json.loads((PACKAGE / "future-once-manifest-v2.json").read_bytes())
        self.assertEqual(authority["expected_reviews"], {})
        self.assertFalse(manifest["normal_service_path_available"])
        self.assertTrue(manifest["invocation_prohibited"])

    def test_producer_check_is_reproducible_without_sdk_import(self):
        command = [sys.executable, "-B", str(EVIDENCE / "produce_evidence.py"), "--check-source-only"]
        completed = subprocess.run(command, cwd=str(ROOT), check=False,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   universal_newlines=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "PASS")
        self.assertNotIn("claude_agent_sdk", sys.modules)


if __name__ == "__main__":
    unittest.main()
