import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from shared.job_runtime.candidates.claude_next_phase_v1 import (
    CAPABILITIES, PREREQUISITES, IntegrationContractError, load_manifest, verify_source_closure)

ROOT = Path(__file__).resolve().parents[5]
PACKAGE = ROOT / "shared/job_runtime/candidates/claude_next_phase_v1"
FIXTURES = ROOT / "shared/job_runtime/tests/fixtures/claude_next_phase_v1"

class ManifestTests(unittest.TestCase):
    def test_exact_component_hashes_are_current(self):
        observed = verify_source_closure(ROOT)
        expected = sum(len(group) for group in load_manifest()["source_bindings"].values())
        self.assertEqual(len(observed), expected)

    def test_mutated_component_is_rejected(self):
        manifest = load_manifest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for group in manifest["source_bindings"].values():
                for relative in group:
                    target=root/relative; target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT/relative, target)
            first = next(iter(next(iter(manifest["source_bindings"].values()))))
            (root/first).write_bytes((root/first).read_bytes()+b"\n")
            with self.assertRaises(IntegrationContractError): verify_source_closure(root)

    def test_stale_missing_component_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises((FileNotFoundError, IntegrationContractError)):
                verify_source_closure(Path(directory))

    def test_all_capabilities_are_inert(self):
        for key in ("enabled", "capability_open", "live_authority", "intended_runtime",
                    "provider_access", "network_access", "process_access", "host_access",
                    "email_access", "cli_enabled", "cli_materialized"):
            self.assertIs(CAPABILITIES[key], False)
        self.assertIs(CAPABILITIES["promotion_blocked"], True)
        self.assertIn("same-process", CAPABILITIES["promotion_block_reason"])

    def test_r9_r10_are_descriptors_not_materialized(self):
        self.assertEqual(set(PREREQUISITES), {"R9", "R10"})
        for descriptor in PREREQUISITES.values():
            self.assertFalse(descriptor["enabled"]); self.assertFalse(descriptor["materialized"])
        self.assertEqual(PREREQUISITES["R10"]["producer_review"], "PENDING_SEPARATE_REVIEW")

    def test_closed_fixtures_are_exact_and_private(self):
        names={p.name for p in FIXTURES.glob("*.json")}
        self.assertEqual(names, {"nominal.json", "pre-forward-502.json", "forwarded-502.json", "cut.json"})
        forbidden=("api_key", "authorization", "bearer", "email", "credential", "private_state")
        for path in FIXTURES.glob("*.json"):
            text=path.read_text().lower(); json.loads(text)
            self.assertFalse(any(word in text for word in forbidden))

    def test_candidate_has_no_external_execution_imports_or_live_activation_exports(self):
        text="\n".join(p.read_text() for p in PACKAGE.glob("*.py"))
        for forbidden in ("import socket", "import subprocess", "import requests", "import httpx",
                          "smtplib", "canonical_engine", "job_runtime.engine", "niulai-private",
                          "make_authenticated_summary"):
            self.assertNotIn(forbidden, text)

if __name__ == "__main__": unittest.main()
