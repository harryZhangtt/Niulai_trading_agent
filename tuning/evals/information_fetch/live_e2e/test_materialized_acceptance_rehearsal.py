"""Provider-free rehearsal from host materialization through acceptance readback."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import uuid

from investment.research.acquisition_acceptance_cli import publish, verify
from investment.research.tests import test_acquisition_live_session as live_fixture
from shared.research_sources.live_session_custody import build_live_session_custody
from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    CredentialReadinessReceipt,
    CredentialReadinessStatus,
    NON_CRYPTO_LIMITATION,
    OperationalEvidenceSource,
    OperationalTrustPolicy,
)
from tuning.evals.information_fetch.live_e2e.materialize_host import (
    INPUT_VERSION,
    materialize,
)
from tuning.evals.information_fetch.live_e2e.readiness import load_and_validate
from tuning.evals.information_fetch.live_e2e import (
    test_provider_free_rehearsal as provider_fixture,
)

ROOT = Path(__file__).resolve().parents[4]


class MaterializedAcceptanceRehearsalTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".job-runtime/tests"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent.chmod(0o700)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name)
        self.private.chmod(0o700)
        self.now = datetime.now(timezone.utc)
        runtime_parent = ROOT / "runtime"
        profiles_parent = ROOT / "profiles"
        for parent in (runtime_parent, profiles_parent):
            created = not parent.exists()
            parent.mkdir(mode=0o700, exist_ok=True)
            parent.chmod(0o700)
            if created:
                self.addCleanup(lambda value=parent: value.rmdir() if value.exists() and not any(value.iterdir()) else None)
        runtime_temp = tempfile.TemporaryDirectory(prefix="materializede2e", dir=runtime_parent)
        profiles_temp = tempfile.TemporaryDirectory(prefix="materializede2e", dir=profiles_parent)
        self.addCleanup(runtime_temp.cleanup)
        self.addCleanup(profiles_temp.cleanup)
        runtime_file = Path(runtime_temp.name) / "python.ref"
        codex_file = Path(profiles_temp.name) / "codex.json"
        claude_file = Path(profiles_temp.name) / "claude.json"
        for path, value in ((runtime_file, "runtime"), (codex_file, "codex"),
                            (claude_file, "claude")):
            path.write_text(value)
            path.chmod(0o600)
        self.refs = {
            "python": self.ref(runtime_file),
            "codex": self.ref(codex_file),
            "claude": self.ref(claude_file),
        }

    @staticmethod
    def ref(path):
        return {
            "path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    def host(self, host, run_kind, session_root):
        codex = host == "codex"
        adapter = AdapterId.CODEX_NATIVE_WEB if codex else AdapterId.CLAUDE_CODE_WEB
        backend = "native_tools.web__run" if codex else "claude_code.web"
        token = uuid.uuid4().hex
        owner = f"{host}-owner-{run_kind}"
        profile = f"{host}.profile.{run_kind}"
        fingerprint = hashlib.sha256(f"{host}:{run_kind}:{token}".encode()).hexdigest()
        session = f"{host}-session-{run_kind}-{token[:8]}"
        receipt = CredentialReadinessReceipt(
            adapter_id=adapter,
            owner_ref=owner,
            profile_ref=profile,
            profile_fingerprint_sha256=fingerprint,
            host_session_id=session,
            capability_observed=backend,
            checked_at=self.now.isoformat(),
            status=CredentialReadinessStatus.READY,
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        relative = session_root.relative_to(ROOT)
        return {
            "host": host,
            "host_session_id": session,
            "runtime_identity": f"{host}.runtime.{run_kind}",
            "interpreter_ref": self.refs["python"],
            "runtime_profile_ref": self.refs[host],
            "credential": {
                "owner_ref": owner,
                "source": f"{host}_profile",
                "profile_ref": profile,
                "fingerprint_sha256": fingerprint,
            },
            "execution": {
                "execution_id": str(uuid.uuid4()),
                "trace_id": f"trace-{host}-{run_kind}-{token[:12]}",
                "dispatch_namespace": f"dispatch-{host}-{run_kind}-{token[:12]}",
                "artifact_root": str(relative / "artifacts"),
                "cache_root": str(relative / "cache"),
                "budget": {
                    "search_items": 1,
                    "open_items": 0 if run_kind == "smoke" else 2,
                    "provider_items": 1 if run_kind == "smoke" else 3,
                    "concurrency": 1,
                    "call_timeout_seconds": 60,
                    "run_timeout_seconds": 300,
                },
            },
            "observation": receipt,
        }

    def bundle(self, run_kind, sessions):
        output = self.private / run_kind / "materialized-hosts"
        output.parent.mkdir(parents=True, mode=0o700)
        output.parent.chmod(0o700)
        value = {
            "schema_version": INPUT_VERSION,
            "output_directory": str(output.relative_to(ROOT)),
            "mcp": "not_used",
            "hosts": [self.host("codex", run_kind, sessions["codex"]),
                      self.host("claude", run_kind, sessions["claude"])],
        }
        result = materialize(value, workspace_root=ROOT, now=self.now)
        return result

    def new_live_fixture(self):
        fixture = live_fixture.LiveSessionTests(
            methodName="test_full_cooperative_cli_path_has_three_dispatches_and_checker_1_of_1")
        fixture.operational_source = OperationalEvidenceSource.HOST_RETURNED
        allowed_state = ROOT / ".research-sources/test-tmp"
        allowed_state.mkdir(parents=True, exist_ok=True, mode=0o700)
        allowed_state.chmod(0o700)
        with mock.patch.object(live_fixture, "SOURCE_STATE", allowed_state):
            fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def live(self, host, run_kind, materialized, fixture):
        rows = materialized["hosts"][host]
        profile_ref = rows["profile"]
        credential_ref = rows["credential_readiness"]
        binding_ref = rows["binding"]
        profile = json.loads((ROOT / profile_ref["path"]).read_text())
        credential = json.loads((ROOT / credential_ref["path"]).read_text())
        binding = json.loads((ROOT / binding_ref["path"]).read_text())
        spec = fixture.v2_spec(run_kind)
        spec.update({
            "identities": {
                "experiment_id": f"materialized-{host}-{run_kind}-v1",
                "execution_id": binding["execution_id"],
                "trace_id": binding["trace_id"],
            },
            "host_adapter": profile["adapter_id"],
            "host_identity": credential["host_session_id"],
            "tool_identity": profile["configured_backend"],
            "host_profile_ref": {"path": profile_ref["path"],
                                 "sha256": profile_ref["sha256"]},
            "credential_readiness_ref": {"path": credential_ref["path"],
                                         "sha256": credential_ref["sha256"]},
            "host_binding_ref": {"path": binding_ref["path"],
                                 "sha256": binding_ref["sha256"]},
            "host_materialization_manifest_ref": {
                "path": materialized["manifest"]["path"],
                "sha256": materialized["manifest"]["sha256"]},
        })
        # Identities and host refs changed after the fixture custody was sealed;
        # rebuild the exact custody artifact from the final materialized spec.
        spec.pop("custody_ref", None)
        custody = build_live_session_custody(
            ROOT, spec_core=spec, host=host,
            future_root=str(fixture.session.relative_to(ROOT)))
        custody_path = fixture.write(fixture.root / f"materialized-{host}-{run_kind}-custody.json", custody)
        spec["custody_ref"] = {"path": str(custody_path.relative_to(ROOT)),
                               "sha256": hashlib.sha256(custody_path.read_bytes()).hexdigest()}
        if host == "codex":
            fixture.capture_identity = lambda: {
                "host_adapter": "codex_native_web",
                "host_identity": credential["host_session_id"],
                "tool_identity": "native_tools.web__run",
            }
        else:
            fixture.claude_identity = lambda call: {
                "host_adapter": "claude_code_web",
                "host_identity": credential["host_session_id"],
                "tool_identity": call["tool_identity"],
                "actual_tool_input": call["tool_input"],
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
        readiness = load_and_validate(Path(spec["readiness_envelope"]))
        self.assertTrue(readiness["ready_for_provider_authorization_request"])
        envelope = json.loads(Path(spec["readiness_envelope"]).read_text())
        self.assertEqual(envelope["packet"]["run_kind"], run_kind)
        self.assertEqual(spec["identities"]["execution_id"], binding["execution_id"])
        return fixture, spec

    def smoke(self, fixture, spec):
        initialized = fixture.cli("init", payload=spec)
        self.assertEqual(initialized["run_kind"], "smoke")
        call = fixture.cli("next")
        blocked = fixture.cli("next", expect=1)
        self.assertEqual(blocked["code"], "ACQ_LIVE_CAPTURE_REQUIRED")
        identity = fixture.capture_identity()
        captured = fixture.operational_capture(
            call,
            {**identity, "status": "returned",
             "observed_backend": "native_tools.web__run"},
            "one bounded provider-free smoke result",
        )
        self.assertEqual(captured["next"], "ready_to_finalize_smoke")
        final = fixture.cli("finalize")
        self.assertEqual((final["run_kind"], final["complete_chains"],
                          final["credited_units"]), ("smoke", 0, 0))
        return final

    def test_materialized_dual_host_smoke_narrow_publish_verify(self):
        smoke_fixtures = {host: self.new_live_fixture()
                          for host in ("codex", "claude")}
        narrow_fixtures = {host: self.new_live_fixture()
                           for host in ("codex", "claude")}
        smoke_materialized = self.bundle(
            "smoke", {host: fixture.session
                      for host, fixture in smoke_fixtures.items()})
        narrow_materialized = self.bundle(
            "narrow", {host: fixture.session
                       for host, fixture in narrow_fixtures.items()})
        for materialized in (smoke_materialized, narrow_materialized):
            self.assertTrue(materialized["hosts"]["codex"]["ready_for_live"])
            self.assertTrue(materialized["hosts"]["claude"]["ready_for_live"])
            self.assertNotEqual(
                materialized["hosts"]["codex"]["binding"]["sha256"],
                materialized["hosts"]["claude"]["binding"]["sha256"],
            )

        smoke = smoke_fixtures["codex"]
        smoke, smoke_spec = self.live(
            "codex", "smoke", smoke_materialized, smoke)
        self.smoke(smoke, smoke_spec)

        completed = {}
        fixtures = {}
        executions = {}
        for host in ("codex", "claude"):
            fixture = narrow_fixtures[host]
            fixture, spec = self.live(
                host, "narrow", narrow_materialized, fixture)
            fixtures[host] = fixture
            executions[host] = spec["identities"]["execution_id"]
            completed[host] = provider_fixture.ProviderFreeRehearsalTests.complete(fixture, spec)
            status = fixture.cli("status")
            self.assertEqual(
                (completed[host]["checker_status"],
                 completed[host]["complete_chains"],
                 completed[host]["credited_units"],
                 status["dispatches_captured"],
                 status["operational_receipts"],
                 status["active_operation_id"], status["finalized"]),
                ("pass", 1, 1, 3, 3, None, True),
            )

        codex = fixtures["codex"]
        registry_root = codex.root / "acceptance-registry"
        publication_root = codex.root / "acceptance-publication"
        registry_root.mkdir(mode=0o700)
        publication_root.mkdir(mode=0o700)
        registry = registry_root / "registry.json"
        first = publish(
            session_root=codex.session,
            subject="SYN",
            expected_execution_id=executions["codex"],
            registry_path=registry,
            publication_root=publication_root,
        )
        replay = publish(
            session_root=codex.session,
            subject="SYN",
            expected_execution_id=executions["codex"],
            registry_path=registry,
            publication_root=publication_root,
        )
        checked = verify(
            session_root=codex.session,
            subject="SYN",
            expected_execution_id=executions["codex"],
            registry_path=registry,
        )
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["envelope_sha256"], replay["envelope_sha256"])
        self.assertEqual(
            (checked["status"], checked["checker_status"],
             checked["complete_chains"], checked["credited_units"],
             checked["actual_dispatches"]),
            ("verified", "pass", 1, 1, 3),
        )

        public = json.dumps({
            "materialized": narrow_materialized,
            "final": completed,
            "published": first,
            "verified": checked,
        }, sort_keys=True)
        for forbidden in (
            str(self.private), str(codex.root), "credential_value",
            "raw_result", "authorization", "cookie", "password", "prompt_text",
        ):
            self.assertNotIn(forbidden, public)
        self.assertLess(len(public.encode()), 64 * 1024)


if __name__ == "__main__":
    unittest.main()
