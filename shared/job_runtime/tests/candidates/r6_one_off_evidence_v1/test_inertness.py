"""AC-O1-006 source isolation, closure, and removability checks."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[5]
CANDIDATE = ROOT / "shared" / "job_runtime" / "candidates" / "r6_one_off_evidence_v1"
TESTS = ROOT / "shared" / "job_runtime" / "tests" / "candidates" / "r6_one_off_evidence_v1"
ARCH = ROOT / "tuning" / "architecture" / "r6_one_off_evidence_v1"


class InertnessTests(unittest.TestCase):
    def test_frozen_engine_source_is_unchanged(self):
        engine = ROOT / "shared" / "job_runtime" / "engine.py"
        raw = engine.read_bytes()
        self.assertEqual(len(raw), 71795)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "42721bf751ebe50cc0720138bfb66509cababd2b873e41192ee50d9cf8df10be")

    def test_exact_candidate_modules_and_four_schemas(self):
        self.assertEqual({path.name for path in CANDIDATE.glob("*.py")}, {
            "__init__.py", "contracts.py", "custody.py", "runner.py",
            "publication.py",
        })
        self.assertEqual({path.name for path in CANDIDATE.glob("*.schema.json")}, {
            "one-off-grant-v1.schema.json",
            "engine-execution-binding-v1.schema.json",
            "r6-evidence-v1.schema.json",
            "publication-receipt-v1.schema.json",
        })

    def test_blocked_package_and_external_effect_modules_are_not_imported(self):
        blocked = "codex_" + "live_evidence_r6_" + "live_v1"
        forbidden_modules = {"socket", "subprocess", "smtplib", "http", "urllib"}
        for root in (CANDIDATE, ARCH):
            for path in root.glob("*.py"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn(blocked, text, path)
                tree = ast.parse(text, filename=str(path))
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imports.add(node.module.split(".")[0])
                self.assertTrue(imports.isdisjoint(forbidden_modules),
                                (path, imports & forbidden_modules))

    def test_candidate_removal_isolated_from_canonical_runtime(self):
        token = "r6_" + "one_off_evidence_v1"
        runtime = ROOT / "shared" / "job_runtime"
        referenced = []
        for path in runtime.glob("*.py"):
            if token in path.read_text(encoding="utf-8"):
                referenced.append(path)
        self.assertEqual(referenced, [])
        package_init = (runtime / "__init__.py").read_text(encoding="utf-8")
        self.assertNotIn(token, package_init)

    def test_candidate_has_no_activation_or_live_authority_entrypoint(self):
        exported = (CANDIDATE / "__init__.py").read_text(encoding="utf-8")
        for forbidden in ("activate", "authorize_live", "provider_call", "send_email"):
            self.assertNotIn(forbidden, exported)


if __name__ == "__main__":
    unittest.main()
