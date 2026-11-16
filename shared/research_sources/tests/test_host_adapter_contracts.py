from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from shared.research_sources.artifacts import SOURCE_STATE
from shared.research_sources.host_adapter_contracts import (
    AdapterId,
    Capability,
    CredentialReadinessReceipt,
    CredentialReadinessStatus,
    CredentialRef,
    CredentialSource,
    HostAdapterProfile,
    HostInvocationReceipt,
    HostBudget,
    HostContractError,
    HostExecutionBinding,
    MCPProfileRef,
    MCPTransport,
    NON_CRYPTO_LIMITATION,
    Operation,
    OperationalEvidenceSource,
    OperationalTerminalStatus,
    OperationalTrustPolicy,
    ReviewerSessionReceipt,
    RuntimeProfileRef,
    ToolBinding,
    WorkspaceFileRef,
    validate_execution_pair,
)


class HostAdapterContractTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.files = {}
        for name in (
            "runtime/python", "profiles/codex.json", "profiles/claude.json",
            "mcp/codex.json", "mcp/claude.json", "evidence/codex-cleanup.json",
            "evidence/claude-cleanup.json", "evidence/codex-rollback.json",
            "evidence/claude-rollback.json",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture:" + name)
            self.files[name] = self.ref(name)

    def ref(self, name):
        path = self.root / name
        return WorkspaceFileRef(name, hashlib.sha256(path.read_bytes()).hexdigest())

    def mcp(self, host):
        return MCPProfileRef(
            server_identity=f"{host}.candidate.market-data",
            transport=MCPTransport.STDIO,
            config_ref=self.files[f"mcp/{host}.json"],
            startup_timeout_seconds=5,
            query_timeout_seconds=15,
            cleanup_evidence_ref=self.files[f"evidence/{host}-cleanup.json"],
            rollback_evidence_ref=self.files[f"evidence/{host}-rollback.json"],
            enabled=False,
        )

    def profile(self, host):
        runtime = RuntimeProfileRef(
            runtime_identity=f"{host}.local-runtime",
            interpreter_ref=self.files["runtime/python"],
            profile_ref=self.files[f"profiles/{host}.json"],
        )
        if host == "codex":
            return HostAdapterProfile(
                adapter_id=AdapterId.CODEX_NATIVE_WEB,
                configured_backend="native_tools.web__run",
                tool_bindings=tuple(ToolBinding(op, "native_tools.web__run")
                                    for op in (Operation.SEARCH, Operation.OPEN, Operation.FIND)),
                capabilities=frozenset({Capability.SEARCH, Capability.OPEN, Capability.FIND,
                                        Capability.RAW_BODY_FIDELITY}),
                runtime=runtime,
                credential=CredentialRef("codex-owner", CredentialSource.CODEX_PROFILE,
                                         "codex.default", "a" * 64),
                mcp=self.mcp("codex"),
            )
        return HostAdapterProfile(
            adapter_id=AdapterId.CLAUDE_CODE_WEB,
            configured_backend="claude_code.web",
            tool_bindings=(
                ToolBinding(Operation.SEARCH, "claude_code.WebSearch"),
                ToolBinding(Operation.OPEN, "claude_code.WebFetch"),
            ),
            capabilities=frozenset({Capability.SEARCH, Capability.OPEN,
                                    Capability.RENDERED_EXTRACT}),
            runtime=runtime,
            credential=CredentialRef("claude-owner", CredentialSource.CLAUDE_PROFILE,
                                     "claude.user", "b" * 64),
            mcp=self.mcp("claude"),
        )

    def binding(self, host):
        return HostExecutionBinding(
            profile=self.profile(host),
            execution_id=str(uuid.uuid4()),
            trace_id=f"trace-{host}",
            dispatch_namespace=f"dispatch-{host}",
            artifact_root=f"state/{host}/artifacts",
            cache_root=f"state/{host}/cache",
            budget=HostBudget(1, 2, 3, 1, 60, 300),
        )

    def test_smoke_budget_allows_zero_open_items_and_round_trips(self):
        smoke = HostBudget(1, 0, 1, 1, 60, 300)
        self.assertEqual(smoke.open_items, 0)
        codex = replace(self.binding("codex"), budget=smoke)
        claude = replace(self.binding("claude"), budget=smoke)
        validated = validate_execution_pair(codex, claude, workspace_root=self.root)
        self.assertEqual(validated[0].to_public_dict()["budget"], {
            "search_items": 1,
            "open_items": 0,
            "provider_items": 1,
            "concurrency": 1,
            "call_timeout_seconds": 60,
            "run_timeout_seconds": 300,
        })
        # Operation item maxima are independently optional; the provider total
        # remains positive and covers every reserved operation.
        self.assertEqual(HostBudget(0, 1, 1, 1, 60, 300).search_items, 0)

    def test_budget_rejects_negative_bool_and_overflow(self):
        invalid = (
            (-1, 0, 1, 1, 60, 300),
            (0, -1, 1, 1, 60, 300),
            (0, 0, 0, 1, 60, 300),
            (True, 0, 1, 1, 60, 300),
            (1, False, 1, 1, 60, 300),
            (1, 0, True, 1, 60, 300),
            (1, 0, 1, True, 60, 300),
            (1, 0, 1, 1, True, 300),
            (1, 0, 1, 1, 60, False),
            (65, 0, 65, 1, 60, 300),
            (0, 65, 65, 1, 60, 300),
            (1, 0, 65, 1, 60, 300),
            (1, 0, 1, 1, 601, 601),
            (1, 0, 1, 1, 60, 601),
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaisesRegex(
                    HostContractError, "HOST_BUDGET_INVALID"):
                HostBudget(*values)

    def test_budget_preserves_concurrency_and_deadline_fences(self):
        with self.assertRaisesRegex(HostContractError,
                                    "HOST_CONCURRENCY_UNSUPPORTED"):
            HostBudget(1, 0, 1, 2, 60, 300)
        with self.assertRaisesRegex(HostContractError, "HOST_DEADLINE_INVALID"):
            HostBudget(1, 0, 1, 1, 301, 300)

    def test_valid_codex_and_claude_profiles_are_isolated_and_sanitized(self):
        codex, claude = validate_execution_pair(
            self.binding("codex"), self.binding("claude"), workspace_root=self.root)
        self.assertEqual(codex.profile.tool_for(Operation.FIND), "native_tools.web__run")
        self.assertEqual(claude.profile.tool_for(Operation.SEARCH), "claude_code.WebSearch")
        with self.assertRaisesRegex(HostContractError, "HOST_OPERATION_UNSUPPORTED"):
            claude.profile.tool_for(Operation.FIND)
        public = json.dumps({"codex": codex.to_public_dict(),
                             "claude": claude.to_public_dict()})
        self.assertNotIn("credential_value", public.replace('credential_value_present', ''))
        self.assertIn('"credential_value_present": false', public)
        self.assertIn('"enabled": false', public)
        self.assertEqual(len(codex.to_public_dict()["binding_sha256"]), 64)

    def test_secret_shaped_credential_references_are_rejected(self):
        invalid = (
            {"owner_ref": "Bearer abcdefghijklmnopqrstuvwxyz", "profile_ref": "codex.default"},
            {"owner_ref": "codex-owner", "profile_ref": "sk-ant-" + "A" * 32},
            {"owner_ref": "codex-owner", "profile_ref": "api_key=plaintext"},
        )
        for row in invalid:
            with self.subTest(row=row), self.assertRaises(HostContractError):
                CredentialRef(row["owner_ref"], CredentialSource.CODEX_PROFILE,
                              row["profile_ref"])

    def test_path_traversal_and_symlink_refs_fail_verification(self):
        outside = self.root.parent / (self.root.name + "-outside")
        outside.write_text("outside")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        bad = WorkspaceFileRef("../" + outside.name,
                               hashlib.sha256(outside.read_bytes()).hexdigest())
        with self.assertRaisesRegex(HostContractError, "HOST_FILE_REF_INVALID"):
            bad.verify(self.root)
        link = self.root / "profiles/link.json"
        link.symlink_to(self.root / "profiles/codex.json")
        linked = WorkspaceFileRef("profiles/link.json",
                                  hashlib.sha256(link.read_bytes()).hexdigest())
        with self.assertRaisesRegex(HostContractError, "HOST_FILE_REF_INVALID"):
            linked.verify(self.root)

    def test_adapter_identity_and_credential_source_mismatch_fail_closed(self):
        codex = self.profile("codex")
        with self.assertRaisesRegex(HostContractError, "HOST_CLAUDE_PROFILE_MISMATCH"):
            HostAdapterProfile(
                adapter_id=AdapterId.CLAUDE_CODE_WEB,
                configured_backend="native_tools.web__run",
                tool_bindings=codex.tool_bindings,
                capabilities=codex.capabilities,
                runtime=codex.runtime,
                credential=codex.credential,
            )

    def test_active_mcp_profile_is_rejected(self):
        candidate = self.mcp("codex")
        with self.assertRaisesRegex(HostContractError, "HOST_MCP_ACTIVE_REJECTED"):
            replace(candidate, enabled=True)

    def test_pair_rejects_shared_execution_trace_namespace_and_roots(self):
        codex = self.binding("codex")
        claude = self.binding("claude")
        mutations = (
            replace(claude, execution_id=codex.execution_id),
            replace(claude, trace_id=codex.trace_id),
            replace(claude, dispatch_namespace=codex.dispatch_namespace),
            replace(claude, artifact_root=codex.artifact_root),
            replace(claude, cache_root="state/codex/artifacts/nested"),
        )
        for changed in mutations:
            with self.subTest(changed=changed), self.assertRaises(HostContractError):
                validate_execution_pair(codex, changed, workspace_root=self.root)

    def test_pair_rejects_shared_runtime_or_mcp_profile(self):
        codex = self.binding("codex")
        claude = self.binding("claude")
        shared_runtime = replace(claude.profile.runtime,
                                 profile_ref=codex.profile.runtime.profile_ref)
        with self.assertRaisesRegex(HostContractError, "HOST_RUNTIME_PROFILE_SHARED"):
            validate_execution_pair(codex, replace(claude, profile=replace(
                claude.profile, runtime=shared_runtime)), workspace_root=self.root)

        shared_mcp = replace(claude.profile.mcp,
                             server_identity=codex.profile.mcp.server_identity,
                             config_ref=codex.profile.mcp.config_ref)
        with self.assertRaisesRegex(HostContractError, "HOST_MCP_PROFILE_SHARED"):
            validate_execution_pair(codex, replace(claude, profile=replace(
                claude.profile, mcp=shared_mcp)), workspace_root=self.root)

    def test_mutable_root_symlink_is_rejected(self):
        target = self.root / "actual"
        target.mkdir()
        link = self.root / "linked-state"
        link.symlink_to(target, target_is_directory=True)
        binding = replace(self.binding("codex"), artifact_root="linked-state/artifacts")
        with self.assertRaisesRegex(HostContractError, "HOST_MUTABLE_ROOT"):
            binding.verify(self.root)

    def test_operational_receipts_bind_host_inputs_and_disclose_trust_limit(self):
        invocation = HostInvocationReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            configured_backend="native_tools.web__run",
            observed_tool_identity="native_tools.web__run",
            host_session_id="codex-session-1",
            operational_event_id="tool-call-1",
            event_id_unavailable_reason=None,
            dispatch_id="dispatch-1",
            acquisition_arguments_sha256="a" * 64,
            tool_input_sha256="b" * 64,
            result_sha256="c" * 64,
            started_at="2026-11-05T01:00:00+00:00",
            finished_at="2026-11-05T01:00:01+00:00",
            adapter_dispatch_count=1, tool_invocation_count=1,
            underlying_request_observation="unknown",
            underlying_http_request_count=None, host_retry_count=None,
            terminal_status=OperationalTerminalStatus.CAPTURED,
            terminal_code=None,
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        self.assertTrue(invocation.live_acceptance_eligible)
        self.assertFalse(invocation.to_public_dict()["cryptographic_remote_attestation"])
        self.assertEqual(HostInvocationReceipt.from_public_dict(
            invocation.to_public_dict()), invocation)

        readiness = CredentialReadinessReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            owner_ref="codex-owner", profile_ref="codex.default",
            profile_fingerprint_sha256="a" * 64,
            host_session_id="codex-session-1",
            capability_observed="native-web-ready",
            checked_at="2026-11-05T00:59:00+00:00",
            status=CredentialReadinessStatus.READY,
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        self.assertTrue(readiness.live_acceptance_eligible)
        self.assertEqual(CredentialReadinessReceipt.from_public_dict(
            readiness.to_public_dict()), readiness)

        review = ReviewerSessionReceipt(
            adapter_id=AdapterId.CLAUDE_CODE_WEB,
            host_session_id="claude-review-session",
            principal_ref="review-principal",
            review_artifact_sha256="d" * 64,
            checked_at="2026-11-05T01:02:00+00:00",
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        self.assertTrue(review.live_acceptance_eligible)
        self.assertEqual(ReviewerSessionReceipt.from_public_dict(
            review.to_public_dict()), review)

    def test_synthetic_or_mismatched_operational_receipts_are_not_live_eligible(self):
        synthetic = HostInvocationReceipt(
            adapter_id=AdapterId.CLAUDE_CODE_WEB,
            configured_backend="claude_code.web",
            observed_tool_identity="claude_code.WebSearch",
            host_session_id="synthetic-session",
            operational_event_id=None,
            event_id_unavailable_reason="fixture host has no event id",
            dispatch_id="dispatch-synthetic",
            acquisition_arguments_sha256="a" * 64,
            tool_input_sha256="a" * 64,
            result_sha256="b" * 64,
            started_at="2026-11-05T01:00:00Z",
            finished_at="2026-11-05T01:00:01Z",
            adapter_dispatch_count=1, tool_invocation_count=1,
            underlying_request_observation="unknown",
            underlying_http_request_count=None, host_retry_count=None,
            terminal_status=OperationalTerminalStatus.CAPTURED,
            terminal_code=None,
            source=OperationalEvidenceSource.SYNTHETIC,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        self.assertFalse(synthetic.live_acceptance_eligible)
        with self.assertRaises(HostContractError):
            replace(synthetic, limitations=("missing trust limitation",))
        with self.assertRaises(HostContractError):
            replace(synthetic, operational_event_id="event", event_id_unavailable_reason="also set")
        with self.assertRaisesRegex(HostContractError, "HOST_INVOCATION_STATUS_CODE"):
            replace(synthetic, terminal_status=OperationalTerminalStatus.UNKNOWN,
                    terminal_code="SOURCE_HTTP_503")
        with self.assertRaisesRegex(HostContractError, "HOST_INVOCATION_STATUS_CODE"):
            replace(synthetic, terminal_status=OperationalTerminalStatus.FAILED,
                    terminal_code="HOST_WEB_RESULT_UNKNOWN")
        with self.assertRaisesRegex(HostContractError, "HOST_INVOCATION_CARDINALITY"):
            replace(synthetic, tool_invocation_count=2)
        reported = replace(synthetic, underlying_request_observation="reported",
                           underlying_http_request_count=1, host_retry_count=0)
        self.assertEqual(reported.underlying_http_request_count, 1)


if __name__ == "__main__":
    unittest.main()
