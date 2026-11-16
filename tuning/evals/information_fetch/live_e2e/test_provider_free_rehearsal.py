"""Provider-free integration rehearsal across the dual-host acceptance boundaries."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
import uuid

from investment.research.acquisition_acceptance import publish_acquisition_acceptance
from investment.research.tests import test_acquisition_live_session as live_fixture
from shared.research_sources.artifacts import ROOT, read
from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    Capability,
    CredentialRef,
    CredentialSource,
    HostAdapterProfile,
    HostBudget,
    HostExecutionBinding,
    Operation,
    RuntimeProfileRef,
    ToolBinding,
    WorkspaceFileRef,
)
from tuning.evals.information_fetch.live_e2e.dual_host import (
    HostRuntimeInput,
    PUBLIC_CASE_TEMPLATE,
    PUBLIC_PROTOCOL,
    build_dual_host_bundle,
)
from tuning.evals.information_fetch.live_e2e.email_sync import (
    build_summary,
    message_digest,
    reconcile_readback,
    send_once,
)
from tuning.evals.information_fetch.live_e2e.test_email_sync import FakeGmail, FakeOutbox


class ProviderFreeRehearsalTests(unittest.TestCase):
    def fixture(self, host):
        fixture = live_fixture.LiveSessionTests(
            methodName="test_full_cooperative_cli_path_has_three_dispatches_and_checker_1_of_1")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        spec = json.loads(fixture.spec.read_text())
        if host == "claude":
            profile, credential = fixture.host_files("claude_code_web")
            fixture.execution_id = str(uuid.uuid4())
            spec.update({
                "identities": {
                    "experiment_id": "live-session-claude-test-v1",
                    "execution_id": fixture.execution_id,
                    "trace_id": f"trace-claude-{uuid.uuid4().hex[:12]}",
                },
                "host_adapter": "claude_code_web",
                "host_identity": "claude-code.test-session",
                "tool_identity": "claude_code.web",
                "host_profile_ref": profile,
                "credential_readiness_ref": credential,
            })
            fixture.write(fixture.spec, spec)
        return fixture, spec

    @staticmethod
    def profile(spec):
        adapter = AdapterId(spec["host_adapter"])
        profile_path = ROOT / spec["host_profile_ref"]["path"]
        profile_ref = WorkspaceFileRef(
            spec["host_profile_ref"]["path"],
            hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        )
        source_path = ROOT / "shared/research_sources/acquisition_contracts.py"
        interpreter_ref = WorkspaceFileRef(
            str(source_path.relative_to(ROOT)), hashlib.sha256(source_path.read_bytes()).hexdigest())
        if adapter is AdapterId.CODEX_NATIVE_WEB:
            tools = tuple(ToolBinding(operation, "native_tools.web__run") for operation in (
                Operation.SEARCH, Operation.OPEN, Operation.FIND))
            capabilities = frozenset({Capability.SEARCH, Capability.OPEN, Capability.FIND,
                                      Capability.RAW_BODY_FIDELITY})
            credential = CredentialRef("codex-test-owner", CredentialSource.CODEX_PROFILE,
                                       "codex.test-profile", "a" * 64)
        else:
            tools = (ToolBinding(Operation.SEARCH, "claude_code.WebSearch"),
                     ToolBinding(Operation.OPEN, "claude_code.WebFetch"))
            capabilities = frozenset({Capability.SEARCH, Capability.OPEN,
                                      Capability.RENDERED_EXTRACT})
            credential = CredentialRef("claude-test-owner", CredentialSource.CLAUDE_PROFILE,
                                       "claude.test-profile", "b" * 64)
        return HostAdapterProfile(
            adapter_id=adapter,
            configured_backend=("native_tools.web__run" if adapter is AdapterId.CODEX_NATIVE_WEB
                                else "claude_code.web"),
            tool_bindings=tools,
            capabilities=capabilities,
            runtime=RuntimeProfileRef(f"{adapter.value}.integration", interpreter_ref, profile_ref),
            credential=credential,
        )

    @staticmethod
    def host_input(fixture, spec):
        relative = fixture.root.relative_to(ROOT)
        return HostRuntimeInput(
            HostExecutionBinding(
                profile=ProviderFreeRehearsalTests.profile(spec),
                execution_id=spec["identities"]["execution_id"],
                trace_id=spec["identities"]["trace_id"],
                dispatch_namespace=f"dispatch-{spec['host_adapter']}",
                artifact_root=str(relative / "dual-artifacts"),
                cache_root=str(relative / "dual-cache"),
                budget=HostBudget(**PUBLIC_PROTOCOL["budgets"]),
            ),
            str(relative / "unknown-fence"),
        )

    @staticmethod
    def complete(fixture, spec):
        fixture.cli("init", payload=spec)
        search = fixture.cli("next")
        if spec["host_adapter"] == "codex_native_web":
            identity = fixture.capture_identity()
            search_raw = f"Official results: {live_fixture.PDF_URL} and {live_fixture.HTML_URL}"
            backend = {"observed_backend": "native_tools.web__run"}
        else:
            identity = fixture.claude_identity(search)
            search_raw = {"results": [{"title": "PDF", "url": live_fixture.PDF_URL},
                                      {"title": "HTML", "url": live_fixture.HTML_URL}]}
            backend = {}
        fixture.operational_capture(search, {**identity, **backend, "status": "returned"}, search_raw)

        primary = fixture.cli("next")
        identity = (fixture.capture_identity() if spec["host_adapter"] == "codex_native_web"
                    else fixture.claude_identity(primary))
        fixture.operational_capture(primary, {**identity, **backend, "status": "returned",
                    "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}},
                    {"diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}})

        alternate = fixture.cli("next")
        identity = (fixture.capture_identity() if spec["host_adapter"] == "codex_native_web"
                    else fixture.claude_identity(alternate))
        raw = (f"Synthetic source ({live_fixture.HTML_URL})\nL0: {live_fixture.BODY}"
               if spec["host_adapter"] == "codex_native_web" else {"result": live_fixture.BODY})
        fixture.operational_capture(alternate, {**identity, **backend, "status": "returned"}, raw)
        fixture.cli("assess", payload={
            "operation_id": alternate["operation_id"],
            "assessor_version": f"assessment-{spec['host_adapter']}",
            "assessments": [{"question_id": live_fixture.QUESTION_ID,
                             "quote": live_fixture.QUOTE,
                             "disposition": "candidate_support"}],
        })
        fixture.operational_review({
            "reviewer_id": f"reviewer-{spec['host_adapter']}",
            "assessment_author_id": f"assessment-{spec['host_adapter']}",
            "live_operator_id": f"operator-{spec['host_adapter']}",
            "disposition": "approve",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True},
            "reason": "The synthetic bounded quote and lineage match.",
        })
        result = fixture.cli("finalize")
        assert fixture.cli("finalize") == result
        return result

    @staticmethod
    def email_result(host, publication):
        return {
            "execution_status": "passed",
            "scheduled_at": "provider-free rehearsal; not scheduled",
            "actual_timing": "synthetic local execution completed",
            "job_id": f"{host}-provider-free",
            "session_id": publication["execution_id"],
            "verified_outputs": ["checker pass", "one complete chain", "one credited unit"],
            "coverage": "synthetic provider-free integration only",
            "failure_codes": [],
            "recovery": "no external side effects to roll back",
            "evidence_refs": [f"publication:{host}:{publication['envelope_sha256'][:16]}"],
        }

    def test_cross_host_credential_receipt_substitution_is_rejected(self):
        codex, codex_spec = self.fixture("codex")
        claude, claude_spec = self.fixture("claude")
        substituted = deepcopy(claude_spec)
        substituted["credential_readiness_ref"] = codex_spec["credential_readiness_ref"]
        blocked = claude.cli("init", payload=substituted, expect=1)
        self.assertEqual(blocked["code"], "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")

    def test_dual_host_rehearsal_is_structural_and_live_publication_stays_blocked(self):
        codex, codex_spec = self.fixture("codex")
        claude, claude_spec = self.fixture("claude")
        case = deepcopy(PUBLIC_CASE_TEMPLATE)
        case.update({
            "case_id": "synthetic-live-session-test",
            "issuer_id": "SYN",
            "canonical_disclosure_id": "synthetic-disclosure-1",
            "question": "What bounded adoption evidence is literally supported?",
            "search_query": "site:example.com synthetic disclosure",
            "primary_pdf_url": live_fixture.PDF_URL,
            "alternate_html_url": live_fixture.HTML_URL,
            "selection_bias": "Synthetic provider-free integration test only.",
        })
        bundle = build_dual_host_bundle(
            case=case, protocol=PUBLIC_PROTOCOL,
            codex=self.host_input(codex, codex_spec),
            claude=self.host_input(claude, claude_spec), workspace_root=ROOT)
        codex_packet, claude_packet = bundle.packets()
        self.assertEqual(codex_packet["case_ref"], claude_packet["case_ref"])
        for field in ("execution_id", "trace_id", "dispatch_namespace", "artifact_root", "cache_root"):
            self.assertNotEqual(codex_packet["binding"][field], claude_packet["binding"][field])
        self.assertNotEqual(codex_packet["unknown_outcome_fence"],
                            claude_packet["unknown_outcome_fence"])
        self.assertNotEqual(codex_packet["binding"]["profile"]["credential"],
                            claude_packet["binding"]["profile"]["credential"])

        for fixture, spec in ((codex, codex_spec), (claude, claude_spec)):
            final = self.complete(fixture, spec)
            self.assertEqual((final["checker_status"], final["complete_chains"],
                              final["credited_units"]), ("pass", 1, 1))

        for fixture in (codex, claude):
            state = json.loads((fixture.session / "session.json").read_text())
            private_result = read(state["final_ref"])
            self.assertFalse(private_result["live_acceptance_eligible"])
            with self.assertRaisesRegex(Exception, "ACQ_ACCEPTANCE_V2_REQUIRED"):
                publish_acquisition_acceptance(
                    fixture.session, subject="SYN",
                    registry_path=fixture.root / "registry.json",
                    publication_directory=fixture.root / "publication")


if __name__ == "__main__":
    unittest.main()
