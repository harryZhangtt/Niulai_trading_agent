from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tuning.evals.information_fetch.live_e2e import once_acceptance as acceptance


class OnceAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "docs/deployment").mkdir(parents=True)
        (self.root / ".job-runtime/config").mkdir(parents=True)
        (self.root / "src.txt").write_text("source")
        (self.root / "doc.txt").write_text("documentation")
        for relative in acceptance.SOURCE_PATHS:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"synthetic {relative}")
        (self.root / ".job-runtime/config/runtime.json").write_text(
            json.dumps({"synthetic": True}))
        self._write_setup_lock()
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
        self.codex_path = self._write_envelope("codex_native_web", "codex", 1)
        self.claude_path = self._write_envelope("claude_code_web", "claude", 2)

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _write_setup_lock(self):
        lock = {
            "schema_version": 1,
            "source_patterns": ["src.txt"],
            "documentation_patterns": ["doc.txt"],
            "sources": {"src.txt": self._hash((self.root / "src.txt").read_bytes())},
            "documentation": {"doc.txt": self._hash((self.root / "doc.txt").read_bytes())},
        }
        (self.root / "docs/deployment/setup-lock.json").write_text(json.dumps(lock))

    def _write_envelope(self, adapter: str, prefix: str, number: int) -> Path:
        profile = self.root / f"profiles/{prefix}.json"
        credential = self.root / f"profiles/{prefix}-credential.json"
        readiness = self.root / f"inputs/{prefix}-readiness.json"
        for path, value in ((profile, {"adapter": adapter}),
                            (credential, {"status": "ready", "credential_values_present": False}),
                            (readiness, {"packet": {
                                "schema_version": "live-provider-readiness-2",
                                "run_kind": "narrow",
                                "case": {"question": "Synthetic question", "search_query": "synthetic query",
                                         "primary_pdf_url": "https://example.com/a.pdf",
                                         "alternate_html_url": "https://example.com/a.html",
                                         "canonical_disclosure_id": "synthetic-disclosure"},
                                "question_contract": {"id": "synthetic:issuer", "facet": "test",
                                    "evidence_to_seek": "test", "source_roles": ["issuer document"],
                                    "capability_ids": ["web_search", "official_document"],
                                    "depends_on": [], "priority": "required", "stop_rule": "stop"},
                                "source_contract": {"required_capability": "official_document",
                                    "required_access_level": "public", "eligible_pdf_failure_codes": ["HOST_WEB_BODY_TOO_LARGE"]},
                                "equivalence_review": {"rationale": "Synthetic PDF and HTML are one disclosure."}},
                                "seal": {"packet_sha256": "a" * 64}})):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        def ref(path):
            return {"path": str(path.relative_to(self.root)),
                    "sha256": self._hash(path.read_bytes())}
        spec = {
            "readiness_envelope": str(readiness.relative_to(self.root)),
            "identities": {
                "experiment_id": f"{prefix}-experiment-{number}",
                "execution_id": f"00000000-0000-4000-8000-{number:012d}",
                "trace_id": f"{prefix}-trace-{number}",
            },
            "schema_version": "acquisition-live-session-2",
            "model_sha256": str(number) * 64,
            "host_adapter": adapter,
            "host_identity": f"{prefix}-host",
            "tool_identity": "native_tools.web__run" if adapter == "codex_native_web" else "claude_code.web",
            "host_profile_ref": ref(profile),
            "credential_readiness_ref": ref(credential),
            "run_wall_seconds": 300,
            "provider_call_seconds": 60,
        }
        session_root = f".research-sources/acceptance/live-acq-1/{prefix}-session"
        unsigned_binding = {
            "version": "host-adapter-contracts-1",
            "profile": {"adapter_id": adapter},
            "execution_id": spec["identities"]["execution_id"],
            "trace_id": spec["identities"]["trace_id"],
            "dispatch_namespace": f"dispatch-{prefix}-{number}",
            "artifact_root": f"{session_root}/artifacts",
            "cache_root": f"{session_root}/cache",
            "budget": {"search_items": 1, "open_items": 2, "provider_items": 3,
                       "concurrency": 1, "call_timeout_seconds": 60,
                       "run_timeout_seconds": 300},
        }
        binding_value = {**unsigned_binding, "binding_sha256": self._hash(
            acceptance.canonical_bytes(unsigned_binding))}
        binding = self.root / f"profiles/{prefix}-binding.json"
        binding.write_text(json.dumps(binding_value))
        binding_ref = ref(binding)
        host = "codex" if adapter == "codex_native_web" else "claude"
        files = {f"{host}-profile.json": spec["host_profile_ref"]["sha256"],
                 f"{host}-credential-readiness.json":
                     spec["credential_readiness_ref"]["sha256"],
                 f"{host}-binding.json": binding_ref["sha256"]}
        generation_value = {"version": "host-profile-materializer-1", "files": files}
        generation_sha = self._hash(acceptance.canonical_bytes(generation_value))
        manifest_value = {"kind": "host_profile_materialization_head",
                          "version": "host-profile-materializer-1", "mcp": "not_used",
                          "generation": f"generation-{generation_sha}",
                          "generation_sha256": generation_sha, "files": files,
                          "hosts": {host: {"ready_for_live": True}}}
        manifest = self.root / f"profiles/{prefix}-manifest.json"
        manifest.write_text(json.dumps(manifest_value))
        spec["host_binding_ref"] = binding_ref
        spec["host_materialization_manifest_ref"] = ref(manifest)
        closure = acceptance.current_source_closure(self.root)
        custody = {
            "version": "live-session-custody-1", "source_closure": closure,
            "materialization_head_ref": spec["host_materialization_manifest_ref"],
            "host_profile_ref": spec["host_profile_ref"],
            "credential_readiness_ref": spec["credential_readiness_ref"],
            "host_binding_ref": spec["host_binding_ref"],
            "future_root_admission": {"root": session_root,
                "execution_id": spec["identities"]["execution_id"],
                "expected_absent": True, "mode": "0700"},
            "session_spec_core_sha256": self._hash(acceptance.canonical_bytes(spec)),
            "four_lane_identity_sha256": None,
            "trust_policy": "operational_host_evidence",
            "limitations": ["Operational host evidence is locally retained and does not resist malicious same-user file forgery."],
        }
        custody["custody_sha256"] = acceptance._sha(acceptance.canonical_bytes(custody))
        custody_path = self.root / f"profiles/{prefix}-custody.json"
        custody_path.write_text(json.dumps(custody))
        spec["custody_ref"] = ref(custody_path)
        envelope = {
            "schema_version": acceptance.ENVELOPE_VERSION_V2,
            "session_spec": spec,
            "seal": {"algorithm": "sha256",
                     "session_spec_sha256": self._hash(acceptance.canonical_bytes(spec))},
        }
        path = self.root / f"inputs/{prefix}-session.json"
        path.write_text(json.dumps(envelope))
        return path

    def _validate_custody_fixture(self, root, custody, **_kwargs):
        current = acceptance.current_source_closure(root)
        if current != custody["source_closure"]:
            raise acceptance.LiveSessionCustodyError("LIVE_CUSTODY_SOURCE_DRIFT")
        return {"custody_sha256": custody["custody_sha256"],
                "source_closure_sha256": current["sources_sha256"]}

    @staticmethod
    def _synthetic_live_contract():
        question = {"id": "synthetic:issuer", "facet": "test",
                    "evidence_to_seek": "test", "source_roles": ["issuer document"],
                    "capability_ids": ["web_search", "official_document"],
                    "depends_on": [], "priority": "required", "stop_rule": "stop",
                    "question": "Synthetic question"}
        return {"run_kind": "narrow", "question": question,
                "proposals": [{"operation_id": "search-disclosure",
                    "question_ids": ["synthetic:issuer"], "source_role": "issuer document",
                    "reason": "Synthetic readiness contract.",
                    "arguments": {"search_query": [{"q": "synthetic query"}],
                                  "response_length": "long"}, "alternates": []}]}

    def _setup(self, **changes):
        values = {
            "change_id": "live-acq-1",
            "due": self.now + timedelta(minutes=5),
            "codex_envelope": self.codex_path,
            "claude_envelope": self.claude_path,
            "runtime_config": ".job-runtime/config/runtime.json",
            "codex_root": ".research-sources/acceptance/live-acq-1/codex-session",
            "claude_root": ".research-sources/acceptance/live-acq-1/claude-session",
            "model_profile": "research-source-acceptance",
            "now": self.now,
            "root": self.root,
        }
        values.update(changes)
        with patch.object(acceptance, "load_and_validate", return_value={
            "ready_for_provider_authorization_request": True,
            "packet_sha256": "b" * 64}), patch.object(
                acceptance, "derive_live_contract",
                return_value=self._synthetic_live_contract()), patch.object(
                acceptance, "validate_live_session_custody",
                side_effect=self._validate_custody_fixture):
            return acceptance.setup(**values)

    def _tree(self):
        return {str(path.relative_to(self.root)): self._hash(path.read_bytes())
                for path in self.root.rglob("*") if path.is_file()}

    def test_setup_returns_one_future_job_without_writing_or_staging(self):
        before = self._tree()
        result = self._setup()
        self.assertEqual(before, self._tree())
        self.assertFalse(result["staged"])
        self.assertFalse(result["provider_called"])
        self.assertFalse(result["scheduler_called"])
        self.assertFalse(result["email_sent"])
        self.assertEqual(result["mcp_status"], "not_used")
        jobs = result["materialize_later"]["codex_allocation"]["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["schedule"]["kind"], "once")
        self.assertFalse(jobs[0]["replay_safe"])
        self.assertTrue(result["criteria"]["one_attempt"])
        self.assertEqual(result["allowed_claim"],
                         "Provider-free setup description only; neither host has run and nothing is staged.")

    def test_codex_prompt_requires_exact_native_tool_stop_and_terminal_receipt(self):
        prompt = self._setup()["materialize_later"]["codex_prompt"]["value"]
        self.assertIn("tool_identity exactly `native_tools.web__run`", prompt)
        self.assertIn("invoke that tool exactly once", prompt)
        self.assertIn("capture status `unknown`", prompt)
        self.assertIn("STOP: no retry", prompt)
        self.assertIn("Run `finalize` once, then `status`", prompt)
        self.assertIn("independent trace checker", prompt)
        self.assertIn("Publish one sanitized terminal JSON receipt atomically", prompt)
        self.assertIn("MCP status: not_used", prompt)
        for label in ("Session spec SHA-256", "Readiness packet SHA-256",
                      "Run kind", "Exact calls SHA-256", "Identities SHA-256",
                      "Session root"):
            self.assertIn(label, prompt)
        self.assertNotIn("curl substitution", prompt.lower())

    def test_claude_packet_is_explicitly_unscheduled_and_pins_tool_inputs(self):
        packet = self._setup()["claude"]
        self.assertFalse(packet["scheduled"])
        self.assertTrue(packet["current_host_cooperative_only"])
        self.assertEqual([row["tool_identity"] for row in packet["tool_specs"]],
                         ["claude_code.WebSearch", "claude_code.WebFetch"])
        self.assertEqual(packet["tool_specs"][0]["exact_input"],
                         {"query": "<next.tool_input.query>"})
        self.assertEqual(packet["tool_specs"][1]["exact_input"]["prompt"],
                         acceptance.FETCH_PROMPT)
        self.assertIn("unknown_outcome", packet["stop_rules"])
        self.assertIn("not executed", packet["claim_limit"])

    def test_setup_sync_drift_blocks_before_acceptance_description(self):
        (self.root / "src.txt").write_text("changed")
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_SETUP_SYNC_REQUIRED"):
            self._setup()

    def test_mutated_envelope_and_profile_are_rejected(self):
        envelope = json.loads(self.codex_path.read_text())
        envelope["session_spec"]["run_wall_seconds"] = 301
        self.codex_path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_ENVELOPE_INVALID"):
            self._setup()

        self.codex_path = self._write_envelope("codex_native_web", "codex", 1)
        (self.root / "profiles/codex.json").write_text('{"changed":true}')
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_PROFILE_CHANGED"):
            self._setup()

    def test_distinct_ids_roots_and_future_window_are_enforced(self):
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_ROOTS_NOT_DISTINCT"):
            self._setup(claude_root=".research-sources/acceptance/live-acq-1/codex-session")
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_DUE_INVALID"):
            self._setup(due=self.now + timedelta(seconds=30))
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_ROOT_INVALID"):
            self._setup(codex_root=".job-runtime/acceptance/live-acq-1/codex-session")

        codex = json.loads(self.codex_path.read_text())
        claude = json.loads(self.claude_path.read_text())
        claude["session_spec"]["identities"] = codex["session_spec"]["identities"]
        claude["seal"]["session_spec_sha256"] = self._hash(
            acceptance.canonical_bytes(claude["session_spec"]))
        self.claude_path.write_text(json.dumps(claude))
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_BINDING_INVALID"):
            self._setup()

    def test_fingerprint_changes_when_source_or_runtime_config_changes(self):
        candidate = self._setup()["candidate"]
        self.assertRegex(candidate["sessions"]["codex_native_web"]["host_binding_sha256"], r"^[a-f0-9]{64}$")
        self.assertRegex(candidate["sessions"]["codex_native_web"]["materialization_manifest_sha256"], r"^[a-f0-9]{64}$")
        first = candidate["sha256"]
        source = self.root / "src.txt"
        original = source.read_text()
        source.write_text("changed implementation")
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_SETUP_SYNC_REQUIRED"):
            self._setup()
        source.write_text(original)
        (self.root / ".job-runtime/config/runtime.json").write_text('{"synthetic":2}')
        third = self._setup()["candidate"]["sha256"]
        self.assertNotEqual(first, third)
        with self.assertRaisesRegex(acceptance.OnceAcceptanceError,
                                    "ONCE_ACCEPTANCE_ROOT_ADMISSION_MISMATCH"):
            self._setup(codex_root=".research-sources/acceptance/live-acq-1/other-codex")

    def test_describe_makes_no_activation_claim(self):
        result = acceptance.describe()
        self.assertEqual(result["side_effects"], [])
        self.assertIn("scheduler_stage_or_reload", result["never_performed"])
        self.assertIn("credential_read", result["never_performed"])


    def test_codex_setup_does_not_require_claude_envelope(self):
        values = {
            "change_id": "live-acq-codex-only",
            "due": self.now + timedelta(minutes=5),
            "codex_envelope": self.codex_path,
            "runtime_config": ".job-runtime/config/runtime.json",
            "codex_root": ".research-sources/acceptance/live-acq-1/codex-session",
            "model_profile": "research-source-acceptance",
            "now": self.now, "root": self.root,
        }
        with patch.object(acceptance, "load_and_validate", return_value={
                "ready_for_provider_authorization_request": True,
            "packet_sha256": "b" * 64}), patch.object(
                acceptance, "derive_live_contract",
                return_value=self._synthetic_live_contract()), patch.object(
                acceptance, "validate_live_session_custody",
                side_effect=self._validate_custody_fixture):
            result = acceptance.setup(**values)
        self.assertIsNone(result["claude"])
        self.assertNotIn("claude_init", result["materialize_later"])
        self.assertEqual(len(result["materialize_later"]["codex_allocation"]["jobs"]), 1)


    def test_v2_session_envelope_has_no_freeform_question_or_proposals(self):
        envelope = json.loads(self.codex_path.read_text())
        envelope["schema_version"] = acceptance.ENVELOPE_VERSION_V2
        spec = envelope["session_spec"]
        envelope["seal"]["session_spec_sha256"] = self._hash(
            acceptance.canonical_bytes(spec))
        self.codex_path.write_text(json.dumps(envelope))
        with patch.object(acceptance, "load_and_validate", return_value={
                "ready_for_provider_authorization_request": True,
            "packet_sha256": "b" * 64}), patch.object(
                acceptance, "derive_live_contract",
                return_value=self._synthetic_live_contract()), patch.object(
                acceptance, "validate_live_session_custody",
                side_effect=self._validate_custody_fixture):
            loaded, observed = acceptance.load_session_envelope(
                self.codex_path, root=self.root, expected_adapter="codex_native_web")
        self.assertEqual(loaded["schema_version"], "acquisition-live-session-2")
        self.assertNotIn("question", loaded)
        self.assertNotIn("proposals", loaded)
        self.assertEqual(observed, envelope["seal"]["session_spec_sha256"])


if __name__ == "__main__":
    unittest.main()
