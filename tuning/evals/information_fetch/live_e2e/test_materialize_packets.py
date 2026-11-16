"""Provider-free tests for four-lane packet materialization."""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

from jsonschema import Draft202012Validator

from investment.research.acquisition_live_session import LiveAcquisitionSession
from tuning.evals.information_fetch.live_e2e.once_acceptance import load_session_envelope
from shared.research_sources.host_adapter_contracts import (
    AdapterId, CredentialReadinessReceipt, CredentialReadinessStatus,
    NON_CRYPTO_LIMITATION, OperationalEvidenceSource, OperationalTrustPolicy,
)
from tuning.evals.information_fetch.live_e2e.materialize_host import (
    INPUT_VERSION as HOST_INPUT_VERSION, materialize,
)
from tuning.evals.information_fetch.live_e2e.materialize_packets import (
    INPUT_VERSION, LANES, PacketMaterializationError, SMOKE_QUERY,
    main as packet_main,
    materialize_packets,
)
from tuning.evals.information_fetch.live_e2e.readiness import load_and_validate


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
SCHEMAS = HERE / "schemas"


class PacketMaterializerTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".research-sources/tests"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent.chmod(0o700)
        self.base = Path(tempfile.mkdtemp(prefix="packetbuilder-", dir=parent))
        self.base.chmod(0o700)
        self.addCleanup(self.cleanup)
        token = uuid.uuid4().hex
        self.runtime = ROOT / "runtime" / f"packetbuilder-{token}"
        self.profiles = ROOT / "profiles" / f"packetbuilder-{token}"
        for directory in (self.runtime, self.profiles):
            directory.mkdir(parents=True, mode=0o700)
            directory.chmod(0o700)
        self.runtime_file = self.private_file(self.runtime / "python.ref", b"runtime")
        self.profile_files = {
            host: self.private_file(self.profiles / f"{host}.json", host.encode())
            for host in ("codex", "claude")
        }
        self.now = datetime.now(timezone.utc)
        self.output_counter = 0
        self.materialized_inputs = {}
        self.materialized_results = {}
        for kind in ("smoke", "narrow"):
            value, result, result_ref = self.make_materialized(kind)
            self.materialized_inputs[kind] = value
            self.materialized_results[kind] = (result, result_ref)

    def cleanup(self):
        for root in (self.base, self.runtime, self.profiles):
            if not root.exists():
                continue
            for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
                try:
                    path.chmod(0o700 if path.is_dir() else 0o600)
                except OSError:
                    pass
            try:
                root.chmod(0o700)
                shutil.rmtree(root)
            except OSError:
                pass

    @staticmethod
    def private_file(path: Path, data: bytes) -> Path:
        path.write_bytes(data)
        path.chmod(0o600)
        return path

    @staticmethod
    def ref(path: Path) -> dict[str, str]:
        return {"path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def host(self, host: str, kind: str, *, smoke_open: int = 0) -> dict:
        codex = host == "codex"
        adapter = AdapterId.CODEX_NATIVE_WEB if codex else AdapterId.CLAUDE_CODE_WEB
        backend = "native_tools.web__run" if codex else "claude_code.web"
        token = uuid.uuid4().hex
        owner = f"{host}.owner.{kind}.{token[:8]}"
        profile = f"{host}.profile.{kind}.{token[:8]}"
        fingerprint = hashlib.sha256(f"{host}:{kind}:{token}".encode()).hexdigest()
        session = f"{host}.session.{kind}.{token[:8]}"
        receipt = CredentialReadinessReceipt(
            adapter_id=adapter, owner_ref=owner, profile_ref=profile,
            profile_fingerprint_sha256=fingerprint, host_session_id=session,
            capability_observed=backend, checked_at=self.now.isoformat(),
            status=CredentialReadinessStatus.READY,
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        lane = f"{host}_{kind}"
        session_root = self.base / "sessions" / lane
        relative = session_root.relative_to(ROOT)
        return {
            "host": host, "host_session_id": session,
            "runtime_identity": f"{host}.runtime.{kind}.{token[:8]}",
            "interpreter_ref": self.ref(self.runtime_file),
            "runtime_profile_ref": self.ref(self.profile_files[host]),
            "credential": {"owner_ref": owner,
                           "source": f"{host}_profile",
                           "profile_ref": profile,
                           "fingerprint_sha256": fingerprint},
            "execution": {
                "execution_id": str(uuid.uuid4()),
                "trace_id": f"trace-{host}-{kind}-{token[:12]}",
                "dispatch_namespace": f"dispatch-{host}-{kind}-{token[:12]}",
                "artifact_root": str(relative / "artifacts"),
                "cache_root": str(relative / "cache"),
                "budget": {"search_items": 1,
                           "open_items": smoke_open if kind == "smoke" else 2,
                           "provider_items": 1 if kind == "smoke" else 3,
                           "concurrency": 1, "call_timeout_seconds": 60,
                           "run_timeout_seconds": 300}},
            "observation": receipt,
        }

    def make_materialized(self, kind: str, *, smoke_open: int = 0, label: str | None = None):
        output = self.base / "host-materialized" / (label or kind)
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output.parent.chmod(0o700)
        value = {"schema_version": HOST_INPUT_VERSION,
                 "output_directory": str(output.relative_to(ROOT)),
                 "mcp": "not_used",
                 "hosts": [self.host("codex", kind, smoke_open=smoke_open),
                           self.host("claude", kind, smoke_open=smoke_open)]}
        result = materialize(value, workspace_root=ROOT, now=self.now)
        result_path = self.base / f"{kind}-materialized-result.json"
        self.private_file(result_path,
                          json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
        return value, result, self.ref(result_path)

    def input(self) -> dict:
        lanes = {}
        for lane in LANES:
            lanes[lane] = {
                "session_root": str((self.base / "sessions" / lane).relative_to(ROOT)),
                "registry_path": str((self.base / "registries" / lane / "registry.json").relative_to(ROOT)),
                "publication_root": str((self.base / "publication" / lane).relative_to(ROOT)),
                "unknown_outcome_fence": str((self.base / "fences" / lane).relative_to(ROOT)),
                "experiment_id": f"live-e2e-{lane}",
                "run_wall_seconds": 300,
                "provider_call_seconds": 60,
            }
        packet_parent = self.base / "packet-output"
        packet_parent.mkdir(mode=0o700, exist_ok=True)
        packet_parent.chmod(0o700)
        self.output_counter += 1
        return {
            "schema_version": INPUT_VERSION,
            "output_directory": str((packet_parent / f"sealed-{self.output_counter}").relative_to(ROOT)),
            "cutoff": self.now.isoformat(), "model_sha256": "d" * 64,
            "owners": {"raw_retention": "retain through reconciliation",
                       "reconciliation_owner": "live-reconciler",
                       "retention_owner": "evidence-custodian",
                       "rollback_target": "delete isolated lane roots"},
            "materialized": {kind: self.materialized_results[kind][1]
                             for kind in ("smoke", "narrow")},
            "lanes": lanes,
        }

    @staticmethod
    def schema(name: str):
        value = json.loads((SCHEMAS / name).read_text())
        Draft202012Validator.check_schema(value)
        return Draft202012Validator(value)

    def test_four_lanes_are_sealed_and_schema_valid(self):
        value = self.input()
        result = materialize_packets(value, workspace_root=ROOT)
        self.assertEqual(set(result["lanes"]), set(LANES))
        self.assertEqual(result["smoke_query"], SMOKE_QUERY)
        self.schema("packet-materialization-input.schema.json").validate(value)
        self.schema("packet-materialization-output.schema.json").validate(result)
        self.schema("../readiness.schema.json").validate(
            json.loads((HERE / "readiness-template.json").read_text()))
        self.schema("host-materialization-input.schema.json").validate(
            self.materialized_inputs["smoke"])
        self.schema("host-materialization-output.schema.json").validate(
            self.materialized_results["smoke"][0])
        for lane_name, lane in result["lanes"].items():
            readiness_path = ROOT / lane["readiness"]["path"]
            verdict = load_and_validate(readiness_path, root=ROOT)
            self.assertTrue(verdict["ready_for_provider_authorization_request"])
            readiness_value = json.loads(readiness_path.read_text())
            self.schema("../readiness.schema.json").validate(readiness_value)
            spec = json.loads((ROOT / lane["session_spec"]["path"]).read_text())
            envelope = json.loads((ROOT / lane["session_envelope"]["path"]).read_text())
            self.schema("live-session-v2.schema.json").validate(spec)
            self.schema("live-session-envelope-v2.schema.json").validate(envelope)
            expected_adapter = "codex_native_web" if lane["host"] == "codex" else "claude_code_web"
            loaded, observed_sha = load_session_envelope(
                ROOT / lane["session_envelope"]["path"], root=ROOT,
                expected_adapter=expected_adapter)
            self.assertEqual(loaded, spec)
            self.assertEqual(observed_sha, envelope["seal"]["session_spec_sha256"])
            initialized = LiveAcquisitionSession(ROOT / lane["session_root"]).initialize(spec)
            self.assertEqual(initialized["run_kind"], lane["run_kind"])
            self.assertEqual(spec["host_binding_ref"], lane["host_binding_ref"])
            self.assertEqual(spec["host_materialization_manifest_ref"],
                             result["materialized"][lane["run_kind"]]["manifest_ref"])
            if lane_name.endswith("smoke"):
                self.assertEqual(readiness_value["packet"]["budgets"]["open_items"], 0)
        self.schema("live-capture-envelope.schema.json").validate({
            "status": "returned", "host_adapter": "codex_native_web",
            "host_identity": "codex.test", "tool_identity": "native_tools.web__run",
            "host_invocation_receipt_ref": {"path": "x.json", "sha256": "a" * 64}})
        self.schema("live-assessment.schema.json").validate({
            "operation_id": "open-primary", "assessor_version": "assessor-v1",
            "assessments": [{"question_id": "now-q1", "quote": "literal evidence",
                             "disposition": "candidate_support"}]})
        self.schema("live-review.schema.json").validate({
            "reviewer_id": "reviewer", "assessment_author_id": "assessor",
            "live_operator_id": "operator", "disposition": "approved",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True}, "reason": "literal support",
            "reviewer_session_receipt_ref": {"path": "review.json", "sha256": "b" * 64},
            "trust_policy": "operational_host_evidence"})
        for lane in result["lanes"].values():
            for key in ("readiness", "session_spec", "session_envelope"):
                path = ROOT / lane[key]["path"]
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_public_cli_describe_and_materialize(self):
        describe_output = io.StringIO()
        with redirect_stdout(describe_output):
            self.assertEqual(packet_main(["describe"]), 0)
        described = json.loads(describe_output.getvalue())
        self.assertEqual(described["lanes"], list(LANES))
        self.assertFalse(described["provider_called"])
        value = self.input()
        input_path = self.private_file(
            self.base / "packet-builder-input.json",
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode())
        materialized_output = io.StringIO()
        with redirect_stdout(materialized_output):
            self.assertEqual(packet_main(["materialize", "--input-file", str(input_path)]), 0)
        result = json.loads(materialized_output.getvalue())
        self.assertEqual(set(result["lanes"]), set(LANES))
        self.assertTrue((ROOT / result["manifest"]["path"]).is_file())

    def test_root_sharing_and_substitution_fail_closed(self):
        value = self.input()
        value["lanes"]["claude_smoke"]["publication_root"] = value["lanes"]["codex_smoke"]["publication_root"]
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_ROOT_OVERLAP"):
            materialize_packets(value, workspace_root=ROOT)

        value = self.input()
        value["lanes"]["codex_smoke"]["session_root"] = ".job-runtime/not-allowed"
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_ROOT"):
            materialize_packets(value, workspace_root=ROOT)

        value = self.input()
        value["materialized"]["smoke"] = value["materialized"]["narrow"]
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_BUDGET"):
            materialize_packets(value, workspace_root=ROOT)

    def test_wrong_smoke_budget_manifest_and_extra_quote_fail(self):
        _value, _result, bad_ref = self.make_materialized(
            "smoke", smoke_open=1, label="smoke-bad-budget")
        value = self.input()
        value["materialized"]["smoke"] = bad_ref
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_BUDGET"):
            materialize_packets(value, workspace_root=ROOT)

        value = self.input()
        value["materialized"]["smoke"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_HOST_RESULT"):
            materialize_packets(value, workspace_root=ROOT)

        value = self.input()
        value["selected_quote"] = "forbidden"
        with self.assertRaisesRegex(PacketMaterializationError,
                                    "PACKET_MATERIALIZE_INPUT"):
            materialize_packets(value, workspace_root=ROOT)


if __name__ == "__main__":
    unittest.main()
