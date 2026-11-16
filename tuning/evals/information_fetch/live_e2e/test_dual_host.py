from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid

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
    DualHostError,
    HostRuntimeInput,
    PUBLIC_CASE_TEMPLATE,
    PUBLIC_PROTOCOL,
    build_dual_host_bundle,
    canonical_bytes,
    seal_case,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


class DualHostTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".research-sources" / "test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.refs = {}
        for name in ("runtime/python", "profiles/codex.json", "profiles/claude.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture: " + name)
            self.refs[name] = WorkspaceFileRef(
                name, hashlib.sha256(path.read_bytes()).hexdigest())
        self.budget = HostBudget(**PUBLIC_PROTOCOL["budgets"])

    def profile(self, host):
        runtime = RuntimeProfileRef(
            runtime_identity=f"{host}.runtime",
            interpreter_ref=self.refs["runtime/python"],
            profile_ref=self.refs[f"profiles/{host}.json"],
        )
        if host == "codex":
            return HostAdapterProfile(
                adapter_id=AdapterId.CODEX_NATIVE_WEB,
                configured_backend="native_tools.web__run",
                tool_bindings=tuple(ToolBinding(operation, "native_tools.web__run")
                                    for operation in (
                                        Operation.SEARCH, Operation.OPEN, Operation.FIND)),
                capabilities=frozenset({
                    Capability.SEARCH, Capability.OPEN, Capability.FIND,
                    Capability.RAW_BODY_FIDELITY,
                }),
                runtime=runtime,
                credential=CredentialRef(
                    "codex-runtime-owner", CredentialSource.CODEX_PROFILE,
                    "codex.acquisition", "a" * 64),
            )
        return HostAdapterProfile(
            adapter_id=AdapterId.CLAUDE_CODE_WEB,
            configured_backend="claude_code.web",
            tool_bindings=(
                ToolBinding(Operation.SEARCH, "claude_code.WebSearch"),
                ToolBinding(Operation.OPEN, "claude_code.WebFetch"),
            ),
            capabilities=frozenset({
                Capability.SEARCH, Capability.OPEN, Capability.RENDERED_EXTRACT,
            }),
            runtime=runtime,
            credential=CredentialRef(
                "claude-runtime-owner", CredentialSource.CLAUDE_PROFILE,
                "claude.acquisition", "b" * 64),
        )

    def host_input(self, host):
        binding = HostExecutionBinding(
            profile=self.profile(host),
            execution_id=str(uuid.uuid4()),
            trace_id=f"trace-{host}-{uuid.uuid4().hex[:8]}",
            dispatch_namespace=f"dispatch-{host}",
            artifact_root=f"private/{host}/artifacts",
            cache_root=f"private/{host}/cache",
            budget=self.budget,
        )
        return HostRuntimeInput(binding, f"private/{host}/unknown-fence")

    def bundle(self):
        return build_dual_host_bundle(
            case=PUBLIC_CASE_TEMPLATE,
            protocol=PUBLIC_PROTOCOL,
            codex=self.host_input("codex"),
            claude=self.host_input("claude"),
            workspace_root=self.root,
        )

    def test_one_case_and_protocol_derive_two_isolated_sealed_packets(self):
        bundle = self.bundle()
        codex, claude = bundle.packets()
        self.assertEqual(codex["case_ref"], claude["case_ref"])
        self.assertEqual(codex["protocol_ref"], claude["protocol_ref"])
        self.assertEqual(codex["binding"]["budget"], claude["binding"]["budget"])
        self.assertNotEqual(codex["binding"]["execution_id"],
                            claude["binding"]["execution_id"])
        self.assertNotEqual(codex["binding"]["trace_id"],
                            claude["binding"]["trace_id"])
        self.assertNotEqual(codex["binding"]["dispatch_namespace"],
                            claude["binding"]["dispatch_namespace"])
        self.assertNotEqual(codex["binding"]["artifact_root"],
                            claude["binding"]["artifact_root"])
        self.assertNotEqual(codex["binding"]["cache_root"],
                            claude["binding"]["cache_root"])
        self.assertNotEqual(codex["unknown_outcome_fence"],
                            claude["unknown_outcome_fence"])
        self.assertNotEqual(codex["binding"]["profile"]["credential"],
                            claude["binding"]["profile"]["credential"])
        for packet in (codex, claude):
            self.assertEqual(packet["mcp"], "not_used")
            self.assertFalse(packet["fallback"]["cross_host"])
            self.assertFalse(packet["fallback"]["provider_switch"])
            self.assertFalse(packet["credential_value_present"])
            self.assertIsNone(packet["binding"]["profile"]["mcp"])

    def test_all_hashes_recompute_and_host_envelopes_are_distinct(self):
        bundle = self.bundle()
        envelopes = (
            bundle.sealed_case, bundle.sealed_protocol,
            bundle.codex_envelope, bundle.claude_envelope,
        )
        for envelope in envelopes:
            expected = hashlib.sha256(canonical_bytes(envelope["packet"])).hexdigest()
            self.assertEqual(envelope["seal"]["packet_sha256"], expected)
        self.assertNotEqual(bundle.codex_envelope["seal"]["packet_sha256"],
                            bundle.claude_envelope["seal"]["packet_sha256"])

    def test_public_servicenow_template_has_approved_html_pdf_pair_and_no_quote(self):
        sealed = seal_case(PUBLIC_CASE_TEMPLATE)
        case = sealed["packet"]
        self.assertEqual(case["title"],
                         "ServiceNow Reports First Quarter 2025 Financial Results")
        self.assertEqual(case["publication_date"], "2025-04-23")
        self.assertEqual(case["primary_pdf_url"],
            "https://s205.q4cdn.com/537566246/files/doc_news/ServiceNow-Reports-First-Quarter-2025-Financial-Results-2025.pdf")
        self.assertEqual(case["alternate_html_url"],
            "https://newsroom.servicenow.com/press-releases/details/2025/ServiceNow-Reports-First-Quarter-2025-Financial-Results/default.aspx")
        self.assertEqual(case["equivalence_status"], "approved")
        self.assertIn("Q4 CDN", case["equivalence_caveat"])
        self.assertFalse(case["quote_preselected"])
        self.assertNotIn("quote", {key.lower() for key in case})
        serialized = json.dumps(case).lower()
        self.assertNotIn("selected_quote", serialized)
        self.assertNotIn("quote_text", serialized)

    def test_case_allows_synthetic_same_publisher_pair_but_rejects_cross_publisher(self):
        synthetic = deepcopy(PUBLIC_CASE_TEMPLATE)
        synthetic["primary_pdf_url"] = "https://example.com/disclosure.pdf"
        synthetic["alternate_html_url"] = "https://example.com/disclosure.html"
        self.assertEqual(seal_case(synthetic)["packet"], synthetic)

        synthetic["alternate_html_url"] = "https://other.example/disclosure.html"
        with self.assertRaisesRegex(DualHostError, "DUAL_HOST_CASE_URL_INVALID"):
            seal_case(synthetic)

    def test_shared_or_overlapping_fence_fails_closed(self):
        codex = self.host_input("codex")
        claude = self.host_input("claude")
        for changed in (
            replace(claude, unknown_outcome_fence=codex.unknown_outcome_fence),
            replace(claude, unknown_outcome_fence="private/codex/artifacts/fence"),
        ):
            with self.subTest(fence=changed.unknown_outcome_fence), self.assertRaisesRegex(
                    DualHostError, "DUAL_HOST_FENCE_SHARED"):
                build_dual_host_bundle(
                    case=PUBLIC_CASE_TEMPLATE, protocol=PUBLIC_PROTOCOL,
                    codex=codex, claude=changed, workspace_root=self.root)

    def test_cross_host_fallback_and_budget_drift_are_rejected(self):
        protocol = deepcopy(PUBLIC_PROTOCOL)
        protocol["fallback"]["cross_host"] = True
        with self.assertRaisesRegex(DualHostError,
                                    "DUAL_HOST_CROSS_HOST_FALLBACK_REJECTED"):
            build_dual_host_bundle(
                case=PUBLIC_CASE_TEMPLATE, protocol=protocol,
                codex=self.host_input("codex"), claude=self.host_input("claude"),
                workspace_root=self.root)

        claude = self.host_input("claude")
        drifted = replace(claude.binding, budget=replace(self.budget, provider_items=4))
        with self.assertRaisesRegex(DualHostError, "DUAL_HOST_BUDGET_MISMATCH"):
            build_dual_host_bundle(
                case=PUBLIC_CASE_TEMPLATE, protocol=PUBLIC_PROTOCOL,
                codex=self.host_input("codex"),
                claude=replace(claude, binding=drifted), workspace_root=self.root)

    def test_secret_values_and_secret_shaped_fields_are_rejected(self):
        cases = []
        bearer = deepcopy(PUBLIC_CASE_TEMPLATE)
        bearer["selection_bias"] = "Bearer abcdefghijklmnopqrstuvwxyz"
        cases.append(bearer)
        api_key = deepcopy(PUBLIC_CASE_TEMPLATE)
        api_key["api_key"] = "synthetic"
        cases.append(api_key)
        selected = deepcopy(PUBLIC_CASE_TEMPLATE)
        selected["selected_quote"] = "preselected output"
        cases.append(selected)
        for case in cases:
            with self.subTest(keys=set(case)), self.assertRaises(DualHostError):
                seal_case(case)

    def test_packet_schema_files_are_public_shape_only(self):
        for name in ("dual-host-input.schema.json", "dual-host-runtime-packet.schema.json"):
            schema = json.loads((HERE / "private-fixtures" / name).read_bytes())
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
            serialized = json.dumps(schema)
            self.assertNotIn('"api_key"', serialized)
            self.assertNotIn('"access_token"', serialized)
            self.assertNotIn('"password"', serialized)


if __name__ == "__main__":
    unittest.main()
