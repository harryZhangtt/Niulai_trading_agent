from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from shared.research_sources.live_session_custody import (
    LiveSessionCustodyError, build_terminal_custody, current_source_closure,
    publish_private_json_bundle, revalidate_source_closure,
    reopen_and_validate_materialized_bundle, validate_four_lane_isolation,
    validate_terminal_custody,
)


class LiveSessionCustodyTests(unittest.TestCase):
    def test_four_lane_identity_and_root_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rows = {}
            for index, name in enumerate(("codex_smoke", "claude_smoke", "codex_narrow", "claude_narrow")):
                base = f".research-sources/{name}"
                rows[name] = {
                    "experiment_id": f"experiment-{index}",
                    "execution_id": f"execution-{index}",
                    "trace_id": f"trace-{index}",
                    "dispatch_namespace": f"dispatch-{index}",
                    "host_session_id": f"session-{index}",
                    "session_root": f"{base}/session", "artifact_root": f"{base}/session/artifacts",
                    "cache_root": f"{base}/session/cache", "registry_root": f"{base}/registry",
                    "publication_root": f"{base}/publication",
                    "unknown_outcome_fence": f"{base}/unknown",
                }
            validate_four_lane_isolation(rows, root=root)
            rows["claude_smoke"]["trace_id"] = rows["codex_smoke"]["trace_id"]
            with self.assertRaisesRegex(LiveSessionCustodyError, "LIVE_CUSTODY_LANE_TRACE_ID"):
                validate_four_lane_isolation(rows, root=root)

    def test_setup_source_closure_detects_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/deployment").mkdir(parents=True)
            (root / "source.py").write_text("one")
            lock = {"schema_version": 1, "source_patterns": ["source.py"],
                    "documentation_patterns": [], "sources": {}, "documentation": {}}
            (root / "docs/deployment/setup-lock.json").write_text(json.dumps(lock))
            first = current_source_closure(root)
            (root / "source.py").write_text("two")
            second = current_source_closure(root)
            self.assertNotEqual(first["sources_sha256"], second["sources_sha256"])

    def test_source_closure_revalidation_and_terminal_immutability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs/deployment").mkdir(parents=True)
            (root / "source.py").write_text("one")
            lock = {"schema_version": 1, "source_patterns": ["source.py"],
                    "documentation_patterns": [], "sources": {}, "documentation": {}}
            (root / "docs/deployment/setup-lock.json").write_text(json.dumps(lock))
            closure = current_source_closure(root)
            revalidate_source_closure(root, closure)
            (root / "source.py").write_text("two")
            with self.assertRaisesRegex(LiveSessionCustodyError, "LIVE_CUSTODY_SOURCE_DRIFT"):
                revalidate_source_closure(root, closure)
        ref = {"path": "x", "sha256": "a" * 64}
        terminal = build_terminal_custody(
            custody_ref=ref, custody_sha256="b" * 64,
            readiness_packet_sha256="c" * 64, dispatch_namespace="dispatch.test",
            checker_ref=ref, reconciliation_ref=ref, result_ref=ref)
        validate_terminal_custody(terminal)
        terminal["dispatch_namespace"] = "changed"
        with self.assertRaisesRegex(LiveSessionCustodyError, "LIVE_TERMINAL_CUSTODY"):
            validate_terminal_custody(terminal)

    def test_canonical_head_and_failure_atomic_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".research-sources").mkdir(mode=0o700)
            refs = publish_private_json_bundle(
                root, ".research-sources/bundle", {"one.json": {"value": 1},
                                                   "two.json": {"value": 2}})
            self.assertEqual(set(refs), {"one.json", "two.json"})
            self.assertTrue((root / ".research-sources/bundle/one.json").is_file())
            with self.assertRaises(LiveSessionCustodyError):
                publish_private_json_bundle(root, ".research-sources/bad", {"../bad.json": {}})
            self.assertFalse((root / ".research-sources/bad").exists())

    def test_noncanonical_materialization_head_rejected_before_members(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".research-sources").mkdir(mode=0o700)
            head = {"kind": "host_profile_materialization_head",
                    "version": "host-profile-materializer-1", "mcp": "not_used",
                    "generation": "generation-wrong", "generation_sha256": "a" * 64,
                    "files": {}, "hosts": {"codex": {"ready_for_live": True}}}
            path = root / ".research-sources/head.json"
            path.write_text(json.dumps(head)); path.chmod(0o600)
            href = {"path": ".research-sources/head.json",
                    "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
            dummy = {"path": ".research-sources/missing.json", "sha256": "b" * 64}
            with self.assertRaisesRegex(LiveSessionCustodyError, "LIVE_CUSTODY_HEAD"):
                reopen_and_validate_materialized_bundle(
                    root, head_ref=href, profile_ref=dummy, credential_ref=dummy,
                    binding_ref=dummy, host="codex")


if __name__ == "__main__":
    unittest.main()
