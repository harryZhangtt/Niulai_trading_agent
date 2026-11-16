from __future__ import annotations
import ast
import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
import sys

ROOT = pathlib.Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
PKG = ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v5"
SCHEMAS = PKG / "schemas"
FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1"
ARCH = ROOT / "tuning/architecture/r6_one_off_claude_live_integration_v1"
REVIEW = ROOT / "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v4-independent-review-20261111-001.json"


class ClosureV5Tests(unittest.TestCase):
    def test_candidate_is_inert_and_has_no_provider_sdk_registration_or_bytedcli(self):
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
            self.assertNotIn("bytedcli", text.lower())
        runtime = ROOT / "shared/job_runtime"
        self.assertFalse(any("r6_one_off_claude_live_integration_v5" in path.read_text()
                             for path in runtime.glob("*.py")))

    def test_v1_through_v4_history_and_exact_review_are_byte_preserved(self):
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
            "protocol-v4.json": (2942, "053b5aa0875c558fae98d858007d877f65788433f17d4ac817bfd27159f1a1a5"),
            "decision-v4.json": (2434, "62a0e97123a3e4f98f244a819d216faec952b43c6685cfe26ca82536e8b944c3"),
            "source-closure-v4.json": (12229, "23eb1182b9395140a3a83674c65b5824c76c2c3ca808afbcf21a1d3016024df3"),
            "producer-verification-v4-final.json": (6096, "030fb71dea665dd416b13fb3641fdf5b034cc1010baa1494ea64aff458434fe2"),
        }
        for name, identity in expected.items():
            raw = (ARCH / name).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), identity)
        raw = REVIEW.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()),
                         (11769, "e7eaf166d50a91a39d37cc043f1ee2932d633ca1688f5ab615efba3048720d96"))
        self.assertEqual(json.loads(raw)["verdict"], "OPEN")

    def test_draft_2020_12_recursive_strictness_instances_and_contradictions(self):
        from jsonschema import Draft202012Validator
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
        names = ("post-run-seal-v5.schema.json", "unknown-fence-v5.schema.json",
                 "pending-publication-v5.schema.json", "p0-output-v5.schema.json")
        for name in names:
            schema = json.loads((SCHEMAS / name).read_text())
            Draft202012Validator.check_schema(schema)
            walk(schema)
            schemas[name] = schema
        from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import (
            LocalOnlyProcessEffect, p0_output, run,
        )
        from shared.job_runtime.candidates.r6_one_off_claude_live_integration_v5 import runner
        with tempfile.TemporaryDirectory(dir=FIX) as temp:
            root = pathlib.Path(temp)
            passed = run(root / "pass", effect=LocalOnlyProcessEffect(True))
            unknown = run(root / "unknown", effect=LocalOnlyProcessEffect(True),
                          scenario="timeout")
            pass_pending = json.loads((root / "pass/public" / runner.PUBLIC_PENDING_NAME).read_text())
            fence_pending = json.loads((root / "unknown" / runner.FENCE_PENDING_NAME).read_text())
            fence_marker = json.loads((root / "unknown" / runner.FENCE_NAME).read_text())
        validators = {name: Draft202012Validator(schema) for name, schema in schemas.items()}
        validators["post-run-seal-v5.schema.json"].validate(passed)
        validators["post-run-seal-v5.schema.json"].validate(unknown)
        validators["unknown-fence-v5.schema.json"].validate(fence_marker)
        validators["pending-publication-v5.schema.json"].validate(pass_pending)
        validators["pending-publication-v5.schema.json"].validate(fence_pending)
        validators["p0-output-v5.schema.json"].validate(p0_output(unknown))

        seal_bad = []
        for path, value in ((('process','descendants_reaped'), False),
            (('process','cleanup_exception'), True),
            (('publication','readback_verified'), False),
            (('publication','directory_fsynced'), False),
            (('cleanup','exception_count'), 1),
            (('ferry','listener_closed'), False)):
            bad = copy.deepcopy(passed); bad[path[0]][path[1]] = value; seal_bad.append(bad)
        bad = copy.deepcopy(passed); bad["process"]["nested_extra"] = True; seal_bad.append(bad)
        bad = copy.deepcopy(unknown); bad["unknown_fence"] = {
            "durable": False, "durability": "NON_DURABLE", "retry": False,
            "replay": False, "status_calls": 0}; seal_bad.append(bad)
        bad = copy.deepcopy(unknown); bad["code"] += "_NON_DURABLE"; seal_bad.append(bad)
        bad = copy.deepcopy(unknown); bad["unknown_fence"] = {
            "durable": False, "durability": "NON_DURABLE", "retry": False,
            "replay": False, "status_calls": 0}; bad["code"] += "_NON_DURABLE";
        bad["publication"]["readback_verified"] = True; seal_bad.append(bad)
        for bad in seal_bad:
            self.assertFalse(validators["post-run-seal-v5.schema.json"].is_valid(bad), bad)
        bad_marker = copy.deepcopy(fence_marker); bad_marker["seal"]["extra"] = True
        self.assertFalse(validators["unknown-fence-v5.schema.json"].is_valid(bad_marker))
        bad_marker = copy.deepcopy(fence_marker); bad_marker["extra"] = True
        self.assertFalse(validators["unknown-fence-v5.schema.json"].is_valid(bad_marker))
        bad_pending = copy.deepcopy(pass_pending); bad_pending["authoritative"] = True
        self.assertFalse(validators["pending-publication-v5.schema.json"].is_valid(bad_pending))


if __name__ == "__main__":
    unittest.main()
