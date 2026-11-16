from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from investment.research.acquisition_acceptance import (
    AcquisitionAcceptanceError, publish_acquisition_acceptance,
)
from investment.research.acquisition_review import review_payload_sha256
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, read
from shared.research_sources.live_session_custody import build_live_session_custody
from shared.research_sources.host_adapter_contracts import (
    AdapterId, CredentialReadinessReceipt, CredentialReadinessStatus,
    HostInvocationReceipt, NON_CRYPTO_LIMITATION, OperationalEvidenceSource,
    OperationalTerminalStatus, OperationalTrustPolicy, ReviewerSessionReceipt,
)
from tuning.evals.information_fetch.live_e2e.readiness import canonical_effective_config, seal_packet


PDF_URL = "https://example.com/disclosure.pdf"
HTML_URL = "https://example.com/disclosure.html"
QUESTION_ID = "adoption.v1:issuer"
BODY = ("Synthetic canonical disclosure states that customer adoption expanded during "
        "the bounded period while commercial conversion remained explicitly uncertain.")
QUOTE = "customer adoption expanded during the bounded period"


class LiveSessionTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / ".research-sources/test-tmp"
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent.chmod(0o700)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.session = self.root / "session"
        self.execution_id = str(uuid.uuid4())
        self.readiness = self.ready_envelope()
        self.host_profile_ref, self.credential_readiness_ref = self.host_files(
            "codex_native_web")
        self.spec = self.root / "spec.json"
        self.write(self.spec, {
            "readiness_envelope": str(self.readiness),
            "identities": {
                "experiment_id": "live-session-test-v1",
                "execution_id": self.execution_id,
                "trace_id": "trace-live-session-test-v1",
            },
            "question": {
                "id": QUESTION_ID,
                "facet": "adoption",
                "question": "What bounded adoption evidence is literally supported?",
                "evidence_to_seek": "One literal source-grounded observation.",
                "source_roles": ["issuer document"],
                "capability_ids": ["web_search", "official_document"],
                "depends_on": [],
                "priority": "required",
                "stop_rule": "Stop after one reviewed candidate support unit.",
            },
            "model_sha256": "a" * 64,
            "host_adapter": "codex_native_web",
            "host_identity": "codex.test-session",
            "tool_identity": "native_tools.web__run",
            "host_profile_ref": self.host_profile_ref,
            "credential_readiness_ref": self.credential_readiness_ref,
            "run_wall_seconds": 300,
            "provider_call_seconds": 60,
            "proposals": [self.search_proposal(), self.primary_proposal()],
        })

    @staticmethod
    def write(path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(value))
        path.chmod(0o600)
        return path

    def host_files(self, adapter):
        source = "codex_profile" if adapter == "codex_native_web" else "claude_profile"
        backend = "native_tools.web__run" if adapter == "codex_native_web" else "claude_code.web"
        bindings = ([{"operation": name, "observed_tool_identity": "native_tools.web__run"}
                     for name in ("search", "open", "find")]
                    if adapter == "codex_native_web" else [
                        {"operation": "search", "observed_tool_identity": "claude_code.WebSearch"},
                        {"operation": "open", "observed_tool_identity": "claude_code.WebFetch"},
                    ])
        contract_path = ROOT / "shared/research_sources/acquisition_contracts.py"
        contract_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        contract_ref = {"path": str(contract_path.relative_to(ROOT)),
                        "sha256": contract_hash}
        profile_name = f"{adapter}-profile.json"
        profile_path = self.write(self.root / profile_name, {
            "version": "host-adapter-contracts-1",
            "adapter_id": adapter,
            "configured_backend": backend,
            "tool_bindings": bindings,
            "capabilities": (["find", "open", "raw_body_fidelity", "search"]
                             if adapter == "codex_native_web" else
                             ["open", "rendered_extract", "search"]),
            "runtime": {"runtime_identity": f"{adapter}.test-runtime",
                        "interpreter_ref": contract_ref,
                        "profile_ref": contract_ref},
            "credential": {"owner_ref": f"{adapter}.test-owner", "source": source,
                           "profile_ref": f"{adapter}.test-profile",
                           "fingerprint_sha256": "f" * 64,
                           "credential_value_present": False},
            "mcp": None,
        })
        adapter_id = (AdapterId.CODEX_NATIVE_WEB if adapter == "codex_native_web"
                      else AdapterId.CLAUDE_CODE_WEB)
        host_session_id = ("codex.test-session" if adapter == "codex_native_web"
                           else "claude-code.test-session")
        credential_path = self.write(
            self.root / f"{adapter}-credential.json",
            CredentialReadinessReceipt(
                adapter_id=adapter_id,
                owner_ref=f"{adapter}.test-owner",
                profile_ref=f"{adapter}.test-profile",
                profile_fingerprint_sha256="f" * 64,
                host_session_id=host_session_id,
                capability_observed=backend,
                checked_at=datetime.now(timezone.utc).isoformat(),
                status=CredentialReadinessStatus.READY,
                source=getattr(self, "operational_source", OperationalEvidenceSource.SYNTHETIC),
                trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
                limitations=(NON_CRYPTO_LIMITATION,),
            ).to_public_dict())
        def ref(path):
            return {"path": str(path.relative_to(ROOT)),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return ref(profile_path), ref(credential_path)

    def binding_files(self, spec, packet):
        host = "codex" if spec["host_adapter"] == "codex_native_web" else "claude"
        profile = json.loads((ROOT / spec["host_profile_ref"]["path"]).read_text())
        credential = json.loads((ROOT / spec["credential_readiness_ref"]["path"]).read_text())
        budget = packet["budgets"]
        unsigned = {
            "version": "host-adapter-contracts-1", "profile": profile,
            "execution_id": spec["identities"]["execution_id"],
            "trace_id": spec["identities"]["trace_id"],
            "dispatch_namespace": f"dispatch-{spec['identities']['execution_id']}",
            "artifact_root": str((self.session / "artifacts").relative_to(ROOT)),
            "cache_root": str((self.session / "cache").relative_to(ROOT)),
            "budget": {"search_items": budget["search_items"],
                       "open_items": budget["open_items"],
                       "provider_items": budget["provider_items"],
                       "concurrency": budget["concurrency"],
                       "call_timeout_seconds": budget["provider_call_seconds"],
                       "run_timeout_seconds": budget["run_wall_seconds"]},
        }
        binding = {**unsigned, "binding_sha256": hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()}
        encoded = {"profile": json.dumps(profile), "credential-readiness": json.dumps(credential),
                   "binding": json.dumps(binding)}
        file_hashes = {f"{host}-{name}.json": hashlib.sha256(raw.encode()).hexdigest()
                       for name, raw in encoded.items()}
        generation_index = {"version": "host-profile-materializer-1", "files": file_hashes}
        generation_sha = hashlib.sha256(json.dumps(
            generation_index, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        generation = self.root / f"generation-{generation_sha}"
        refs = {}
        for name, raw in encoded.items():
            path = generation / f"{host}-{name}.json"
            self.write(path, json.loads(raw))
            refs[name] = {"path": str(path.relative_to(ROOT)),
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        spec["host_profile_ref"] = refs["profile"]
        spec["credential_readiness_ref"] = refs["credential-readiness"]
        manifest = {"kind": "host_profile_materialization_head",
                    "version": "host-profile-materializer-1", "mcp": "not_used",
                    "generation": generation.name, "generation_sha256": generation_sha,
                    "files": file_hashes, "hosts": {host: {"ready_for_live": True}}}
        manifest_path = self.write(self.root / f"{host}-materialization-manifest.json", manifest)
        return refs["binding"], {"path": str(manifest_path.relative_to(ROOT)),
                                 "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}

    @staticmethod
    def search_proposal():
        return {
            "operation_id": "search-disclosure",
            "question_ids": [QUESTION_ID],
            "source_role": "issuer document",
            "reason": "Find the frozen disclosure pair.",
            "arguments": {"search_query": [{"q": "site:example.com synthetic disclosure"}],
                          "response_length": "long"},
            "alternates": [],
        }

    @staticmethod
    def capture_identity():
        return {"host_adapter": "codex_native_web",
                "host_identity": "codex.test-session",
                "tool_identity": "native_tools.web__run"}

    @staticmethod
    def primary_proposal():
        return {
            "operation_id": "open-primary",
            "question_ids": [QUESTION_ID],
            "source_role": "issuer document",
            "reason": "Open the exact frozen PDF representation.",
            "arguments": {"open": [{"ref_id": PDF_URL}], "response_length": "long"},
            "alternates": [{
                "representation_kind": "html",
                "exact_arguments": {"open": [{"ref_id": HTML_URL}], "response_length": "long"},
                "source_role": "issuer document",
                "required_capability": "official_document",
                "required_access_level": "public",
                "canonical_disclosure_id": "synthetic-disclosure-1",
                "relationship_to_primary": "semantically_equivalent_representation",
                "semantic_equivalence_rationale": "The PDF and HTML are one disclosure.",
                "permitted_trigger_codes": ["HOST_WEB_BODY_TOO_LARGE"],
                "budget_cost": 1,
            }],
        }

    def ready_envelope(self):
        source = ROOT / "shared/research_sources/acquisition_contracts.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        effective_config = canonical_effective_config(ROOT)
        cutoff = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
        packet = {
            "schema_version": "live-provider-readiness-1",
            "status": "ready",
            "unresolved": [],
            "case": {
                "case_id": "synthetic-live-session-test",
                "issuer_id": "SYN",
                "canonical_disclosure_id": "synthetic-disclosure-1",
                "question": "What bounded adoption evidence is literally supported?",
                "search_query": "site:example.com synthetic disclosure",
                "primary_pdf_url": PDF_URL,
                "alternate_html_url": HTML_URL,
                "selection_bias": "Synthetic provider-free test only.",
                "quote_preselected": False,
            },
            "url_policy": {"normalization": "exact_https_url_bytes",
                           "redirects": "reject_unless_frozen_target_matches",
                           "allowed_hosts": ["example.com"]},
            "equivalence_review": {
                "status": "approved", "reviewer_id": "independent-reviewer",
                "rationale": "Synthetic representations intentionally match.",
                "disclosure_date_match": True, "publisher_control": True,
                "release_identity_match": True, "representation_relationship": True,
                "title_match": True,
            },
            "artifacts": {
                "artifact_root": str(self.root / "artifacts"),
                "artifact_root_mode": "0700",
                "raw_retention": "retain through reconciliation",
                "reconciliation_owner": "test-reconciler",
                "retention_owner": "test-owner",
                "rollback_target": "delete isolated test root",
                "runtime_root": str(self.root / "runtime"),
            },
            "budgets": {"search_items": 1, "open_items": 2, "provider_items": 3,
                        "fallbacks": 1, "concurrency": 1, "cache_enabled": False,
                        "raw_result_limit_bytes": 65536, "run_wall_seconds": 300,
                        "provider_call_seconds": 60},
            "source_contract": {
                "cutoff": cutoff,
                "evidence_facet": "current issuer disclosure",
                "required_access_level": "document",
                "required_capability": "official_document",
                "source_role": "issuer document",
                "eligible_body_rules": ["exact URL", "screen before exposure"],
                "eligible_pdf_failure_codes": ["HOST_WEB_BODY_TOO_LARGE"],
                "unparseable_predeclared": False,
            },
            "stop_rules": ["no_find", "no_second_query", "no_unchanged_retry",
                           "no_second_alternate", "no_provider_switch",
                           "no_curl_substitution", "stop_on_unknown_outcome",
                           "stop_on_policy_transient_circuit_or_post_dispatch_deadline"],
            "effective_config": effective_config,
            "repository_evidence": [{"path": str(source.relative_to(ROOT)),
                                     "sha256": digest}],
        }
        path = self.root / "readiness.json"
        return self.write(path, seal_packet(packet))

    def v2_spec(self, run_kind="narrow"):
        if not hasattr(self, "operational_source"):
            self.operational_source = OperationalEvidenceSource.HOST_RETURNED
        adapter = json.loads(self.spec.read_text())["host_adapter"]
        profile_ref, credential_ref = self.host_files(adapter)
        envelope = json.loads(self.readiness.read_text())
        packet = envelope["packet"]
        packet["schema_version"] = "live-provider-readiness-2"
        packet["run_kind"] = run_kind
        packet["question_contract"] = {
            "id": QUESTION_ID, "facet": "adoption",
            "evidence_to_seek": "One literal source-grounded observation.",
            "source_roles": ["issuer document"],
            "capability_ids": ["web_search", "official_document"],
            "depends_on": [], "priority": "required",
            "stop_rule": "Stop after one reviewed candidate support unit.",
        }
        if run_kind == "smoke":
            packet["budgets"].update({"open_items": 0, "provider_items": 1, "fallbacks": 0})
        packet["artifacts"]["artifact_root"] = str(self.session / "artifacts")
        packet["artifacts"]["runtime_root"] = str(self.session)
        readiness = self.root / f"readiness-{run_kind}.json"
        self.write(readiness, seal_packet(packet))
        spec = json.loads(self.spec.read_text())
        spec["host_profile_ref"] = profile_ref
        spec["credential_readiness_ref"] = credential_ref
        for key in ("question", "proposals"):
            spec.pop(key)
        spec["schema_version"] = "acquisition-live-session-2"
        spec["readiness_envelope"] = str(readiness)
        binding_ref, manifest_ref = self.binding_files(spec, packet)
        spec["host_binding_ref"] = binding_ref
        spec["host_materialization_manifest_ref"] = manifest_ref
        host = "codex" if spec["host_adapter"] == "codex_native_web" else "claude"
        custody = build_live_session_custody(
            ROOT, spec_core=spec, host=host,
            future_root=str(self.session.relative_to(ROOT)))
        custody_path = self.write(self.root / f"{host}-custody.json", custody)
        spec["custody_ref"] = {"path": str(custody_path.relative_to(ROOT)),
                               "sha256": hashlib.sha256(custody_path.read_bytes()).hexdigest()}
        return spec

    def operational_capture(self, call, payload, raw, *, expect=0):
        raw_bytes = json.dumps(raw).encode()
        adapter = (AdapterId.CODEX_NATIVE_WEB
                   if call["host_adapter"] == "codex_native_web"
                   else AdapterId.CLAUDE_CODE_WEB)
        terminal_status = ({"returned": OperationalTerminalStatus.CAPTURED,
                            "failed": OperationalTerminalStatus.FAILED,
                            "unknown": OperationalTerminalStatus.UNKNOWN}[payload["status"]])
        receipt = HostInvocationReceipt(
            adapter_id=adapter,
            configured_backend=call["configured_backend"],
            observed_tool_identity=call["tool_identity"],
            host_session_id=call["host_identity"],
            operational_event_id=f"event-{call['dispatch_id']}",
            event_id_unavailable_reason=None,
            dispatch_id=call["dispatch_id"],
            acquisition_arguments_sha256=call["arguments_sha256"],
            tool_input_sha256=call["tool_input_sha256"],
            result_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            started_at=datetime.now(timezone.utc).isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
            adapter_dispatch_count=1, tool_invocation_count=1,
            underlying_request_observation="unknown",
            underlying_http_request_count=None, host_retry_count=None,
            terminal_status=terminal_status,
            terminal_code=payload.get("code") if payload["status"] != "returned" else None,
            source=getattr(self, "operational_source", OperationalEvidenceSource.SYNTHETIC),
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        state = json.loads((self.session / "session.json").read_text())
        if state.get("session_spec_version") == "acquisition-live-session-2":
            receipt_path = self.write(
                self.root / f"host-receipts/{call['dispatch_id']}.json", receipt)
            receipt_input = {"host_invocation_receipt_ref": {
                "path": str(receipt_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}}
        else:
            receipt_input = {"host_invocation_receipt": receipt}
        return self.cli("capture", payload={**payload, **receipt_input},
                        raw=raw, expect=expect)

    def operational_review(self, payload):
        state = json.loads((self.session / "session.json").read_text())
        driver_state = read(json.loads((self.session / "driver/state.json").read_text()))
        operation = driver_state["operations"][state["assessed_operation_id"]]
        review_hash = review_payload_sha256(
            assessment_ref=operation["assessment_refs"][0],
            unit_ref=operation["unit_refs"][0],
            reviewer_id=payload["reviewer_id"],
            assessment_author_id=payload["assessment_author_id"],
            operator_id=payload["live_operator_id"],
            disposition=payload["disposition"], checks=payload["checks"],
            reason=payload["reason"])
        adapter = (AdapterId.CODEX_NATIVE_WEB
                   if state["host_adapter"] == "codex_native_web"
                   else AdapterId.CLAUDE_CODE_WEB)
        receipt = ReviewerSessionReceipt(
            adapter_id=adapter,
            host_session_id=f"review-{state['host_identity']}",
            principal_ref=payload["reviewer_id"],
            review_artifact_sha256=review_hash,
            checked_at=datetime.now(timezone.utc).isoformat(),
            source=getattr(self, "operational_source", OperationalEvidenceSource.SYNTHETIC),
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        if state.get("session_spec_version") == "acquisition-live-session-2":
            receipt_path = self.write(
                self.root / f"review-receipts/{review_hash}.json", receipt)
            receipt_input = {"reviewer_session_receipt_ref": {
                "path": str(receipt_path.relative_to(ROOT)),
                "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}}
        else:
            receipt_input = {"reviewer_session_receipt": receipt}
        return self.cli("review", payload={**payload, **receipt_input,
            "trust_policy": "operational_host_evidence"})

    def cli(self, command, *, payload=None, raw=None, expect=0):
        options = [sys.executable, "-m", "investment.research.acquisition_live_session",
                   command, "--directory", str(self.session)]
        if payload is not None:
            path = self.write(self.root / f"{command}-{uuid.uuid4().hex}.json", payload)
            options += ["--input-file", str(path)]
        if raw is not None:
            path = self.write(self.root / f"raw-{uuid.uuid4().hex}.json", raw)
            options += ["--raw-result-file", str(path)]
        result = subprocess.run(options, cwd=ROOT, env={**os.environ,
                                "PYTHONDONTWRITEBYTECODE": "1",
                                "PYTHONPYCACHEPREFIX": str(self.root / "pycache")},
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, expect, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertNotIn(str(self.root), result.stdout)
        return value

    def test_full_cooperative_cli_path_has_three_dispatches_and_checker_1_of_1(self):
        initialized = self.cli("init", payload=json.loads(self.spec.read_text()))
        self.assertEqual(initialized["status"], "ready")
        self.assertEqual(initialized["mcp_status"], "not_used")
        self.assertRegex(initialized["host_profile_sha256"], r"^[a-f0-9]{64}$")
        self.assertRegex(initialized["credential_readiness_sha256"], r"^[a-f0-9]{64}$")

        search = self.cli("next")
        self.assertEqual(search["arguments"], self.search_proposal()["arguments"])
        found = self.operational_capture(search,
            {**self.capture_identity(), "status": "returned",
             "observed_backend": "native_tools.web__run"},
            f"Official results: {PDF_URL} and {HTML_URL}")
        self.assertEqual(found["next"], "dispatch")

        primary = self.cli("next")
        self.assertEqual(primary["arguments"], self.primary_proposal()["arguments"])
        failed = self.operational_capture(primary,
            {**self.capture_identity(), "status": "returned",
             "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"},
             "observed_backend": "native_tools.web__run"},
            {"diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}})
        self.assertEqual((failed["status"], failed["code"]),
                         ("failed", "HOST_WEB_BODY_TOO_LARGE"))

        alternate = self.cli("next")
        self.assertEqual(alternate["arguments"]["open"][0]["ref_id"], HTML_URL)
        opened = self.operational_capture(alternate,
            {**self.capture_identity(), "status": "returned",
             "observed_backend": "native_tools.web__run"},
            f"Synthetic source ({HTML_URL})\nL0: {BODY}")
        self.assertEqual(opened["next"], "await_assessment")
        self.assertEqual(opened["screened_packet"]["documents"][0]["text"], BODY)

        assessed = self.cli("assess", payload={
            "operation_id": alternate["operation_id"],
            "assessor_version": "assessment-author",
            "assessments": [{"question_id": QUESTION_ID, "quote": QUOTE,
                             "disposition": "candidate_support"}],
        })
        self.assertEqual(assessed["status"], "await_review")
        reviewed = self.operational_review({
            "reviewer_id": "independent-reviewer",
            "assessment_author_id": "assessment-author",
            "live_operator_id": "hosted-operator",
            "disposition": "approve",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True},
            "reason": "The bounded question, literal quote and lineage agree.",
        })
        self.assertEqual(reviewed["status"], "ready_to_finalize")
        final = self.cli("finalize")
        self.assertEqual((final["checker_status"], final["complete_chains"],
                          final["credited_units"]), ("pass", 1, 1))
        self.assertFalse(final["live_acceptance_eligible"])
        self.assertFalse(final["cryptographic_remote_attestation"])
        self.assertEqual(self.cli("finalize"), final)
        self.assertEqual(self.cli("status")["dispatches_captured"], 3)

    def test_reopen_never_reemits_claimed_arguments_and_unknown_fences(self):
        self.cli("init", payload=json.loads(self.spec.read_text()))
        first = self.cli("next")
        blocked = self.cli("next", expect=1)
        self.assertEqual(blocked["code"], "ACQ_LIVE_CAPTURE_REQUIRED")
        mismatch = self.operational_capture(first, {**self.capture_identity(),
            "host_identity": "codex.other-session", "status": "unknown",
            "code": "HOST_WEB_RESULT_UNKNOWN"}, "transport outcome unavailable", expect=1)
        self.assertEqual(mismatch["code"], "ACQ_LIVE_HOST_IDENTITY_MISMATCH")
        unknown = self.operational_capture(first,
            {**self.capture_identity(), "status": "unknown",
             "code": "HOST_WEB_RESULT_UNKNOWN"}, "transport outcome unavailable")
        self.assertEqual(unknown["next"], "blocked_unknown")
        again = self.cli("next", expect=1)
        self.assertIn(again["code"], {"ACQ_LIVE_ACTION_REQUIRED", "ACQ_LIVE_CAPTURE_REQUIRED"})
        status = self.cli("status")
        self.assertEqual(status["phase"], "blocked_unknown")
        self.assertEqual(status["dispatches_captured"], 0)

    @staticmethod
    def claude_identity(call):
        return {
            "host_adapter": "claude_code_web",
            "host_identity": "claude-code.test-session",
            "tool_identity": call["tool_identity"],
            "actual_tool_input": call["tool_input"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
        }

    def test_claude_code_uses_same_session_checker_with_operation_specific_tools(self):
        spec = json.loads(self.spec.read_text())
        claude_profile, claude_credential = self.host_files("claude_code_web")
        spec.update({
            "host_adapter": "claude_code_web",
            "host_identity": "claude-code.test-session",
            "tool_identity": "claude_code.web",
            "host_profile_ref": claude_profile,
            "credential_readiness_ref": claude_credential,
        })
        self.write(self.spec, spec)
        self.assertEqual(self.cli("init", payload=spec)["status"], "ready")

        search = self.cli("next")
        self.assertEqual(search["configured_backend"], "claude_code.web")
        self.assertEqual(search["tool_identity"], "claude_code.WebSearch")
        self.assertEqual(search["tool_input"], {
            "query": self.search_proposal()["arguments"]["search_query"][0]["q"]})
        found = self.operational_capture(search, {**self.claude_identity(search),
            "status": "returned"}, {"results": [
                {"title": "PDF", "url": PDF_URL},
                {"title": "HTML", "url": HTML_URL},
            ]})
        self.assertEqual(found["next"], "dispatch")

        primary = self.cli("next")
        self.assertEqual(primary["tool_identity"], "claude_code.WebFetch")
        self.assertEqual(primary["tool_input"]["url"], PDF_URL)
        failed = self.operational_capture(primary, {**self.claude_identity(primary),
            "status": "returned", "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}},
            {"message": "Structured oversized PDF diagnostic."})
        self.assertEqual((failed["status"], failed["code"]),
                         ("failed", "HOST_WEB_BODY_TOO_LARGE"))

        alternate = self.cli("next")
        self.assertEqual(alternate["tool_identity"], "claude_code.WebFetch")
        self.assertEqual(alternate["tool_input"]["url"], HTML_URL)
        opened = self.operational_capture(alternate, {**self.claude_identity(alternate),
            "status": "returned"}, {"result": BODY})
        self.assertEqual(opened["next"], "await_assessment")
        self.assertEqual(opened["screened_packet"]["documents"][0]["text"], BODY)

        self.cli("assess", payload={
            "operation_id": alternate["operation_id"],
            "assessor_version": "assessment-author",
            "assessments": [{"question_id": QUESTION_ID, "quote": QUOTE,
                             "disposition": "candidate_support"}],
        })
        self.operational_review({
            "reviewer_id": "independent-reviewer",
            "assessment_author_id": "assessment-author",
            "live_operator_id": "claude-hosted-operator",
            "disposition": "approve",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True},
            "reason": "The rendered extract contains the literal quote and bound lineage.",
        })
        final = self.cli("finalize")
        self.assertEqual((final["checker_status"], final["complete_chains"],
                          final["credited_units"]), ("pass", 1, 1))
        self.assertEqual(final["configured_backend"], "claude_code.web")
        self.assertEqual(final["observed_tool_identities"],
                         ["claude_code.WebFetch", "claude_code.WebSearch"])
        self.assertEqual(final["mcp_status"], "not_used")
        session_state = json.loads((self.session / "session.json").read_text())
        private_result = read(session_state["final_ref"])
        checker_gate = next(row for row in private_result["checker_verdict"]["gates"]
                            if row["gate"] == "host_credential_readiness")
        self.assertTrue(checker_gate["passed"])
        driver = read(private_result["driver_ref"])
        host = read(driver["host_run_ref"])
        document_sources = [read(ref) for ref in host["source_refs"]
                            if read(ref).get("access_level") == "document"]
        self.assertEqual(len(document_sources), 1)
        source = document_sources[0]
        self.assertEqual(source["provider"], "claude_code_web_fetch")
        self.assertEqual(source["representation_scope"],
                         "rendered_extracted_representation")
        self.assertIn("not publisher-original bytes", " ".join(source["limitations"]))

    def test_claude_code_rejects_tool_and_input_substitution(self):
        spec = json.loads(self.spec.read_text())
        claude_profile, claude_credential = self.host_files("claude_code_web")
        spec.update({"host_adapter": "claude_code_web",
                     "host_identity": "claude-code.test-session",
                     "tool_identity": "claude_code.web",
                     "host_profile_ref": claude_profile,
                     "credential_readiness_ref": claude_credential})
        self.cli("init", payload=spec)
        call = self.cli("next")
        wrong_tool = self.operational_capture(call, {**self.claude_identity(call),
            "tool_identity": "claude_code.WebFetch", "status": "returned"},
            {"results": [{"url": PDF_URL}]}, expect=1)
        self.assertEqual(wrong_tool["code"], "ACQ_LIVE_HOST_IDENTITY_MISMATCH")
        wrong_input = self.operational_capture(call, {**self.claude_identity(call),
            "actual_tool_input": {"query": "different"}, "status": "returned"},
            {"results": [{"url": PDF_URL}]}, expect=1)
        self.assertEqual(wrong_input["code"], "ACQ_CLAUDE_CAPTURE_ARGUMENT_MISMATCH")

    def test_init_requires_sanitized_ready_credential_binding(self):
        spec = json.loads(self.spec.read_text())
        credential_path = ROOT / spec["credential_readiness_ref"]["path"]
        value = json.loads(credential_path.read_text())
        value["status"] = "unknown"
        self.write(credential_path, value)
        spec["credential_readiness_ref"]["sha256"] = hashlib.sha256(
            credential_path.read_bytes()).hexdigest()
        failed = self.cli("init", payload=spec, expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")

    def test_init_rejects_stale_or_profile_mismatched_credential_receipt(self):
        spec = json.loads(self.spec.read_text())
        credential_path = ROOT / spec["credential_readiness_ref"]["path"]
        value = json.loads(credential_path.read_text())
        value["checked_at"] = "2020-01-01T00:00:00+00:00"
        value["profile_fingerprint_sha256"] = "0" * 64
        self.write(credential_path, value)
        spec["credential_readiness_ref"]["sha256"] = hashlib.sha256(
            credential_path.read_bytes()).hexdigest()
        failed = self.cli("init", payload=spec, expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_CREDENTIAL_READINESS_INVALID")

    def test_init_rejects_nonempty_runtime_root(self):
        (self.session / "cache").mkdir(parents=True)
        self.write(self.session / "cache/prior.json", {"prior": True})
        failed = self.cli("init", payload=json.loads(self.spec.read_text()), expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_RUNTIME_ROOT_NOT_EMPTY")

    def test_late_capture_is_fenced_before_credit(self):
        self.cli("init", payload=json.loads(self.spec.read_text()))
        call = self.cli("next")
        state = json.loads((self.session / "session.json").read_text())
        state["active"]["absolute_deadline"] = 0
        self.write(self.session / "session.json", state)
        late = self.operational_capture(call,
            {**self.capture_identity(), "status": "returned",
             "observed_backend": "native_tools.web__run"},
            f"Official results: {PDF_URL} and {HTML_URL}", expect=1)
        self.assertEqual(late["code"], "ACQ_LIVE_CAPTURE_DEADLINE")
        status = self.cli("status")
        self.assertEqual(status["dispatches_captured"], 0)


    def test_v2_smoke_is_one_call_and_not_full_acceptance(self):
        spec = self.v2_spec("smoke")
        initialized = self.cli("init", payload=spec)
        self.assertEqual(initialized["run_kind"], "smoke")
        call = self.cli("next")
        self.assertIn("search_query", call["arguments"])
        captured = self.operational_capture(
            call, {**self.capture_identity(), "status": "returned",
                   "observed_backend": "native_tools.web__run"},
            "one bounded smoke result")
        self.assertEqual((captured["status"], captured["next"]),
                         ("callable", "ready_to_finalize_smoke"))
        with self.assertRaises(AssertionError):
            self.cli("next")
        final = self.cli("finalize")
        self.assertEqual((final["status"], final["run_kind"], final["complete_chains"],
                          final["credited_units"]), ("callable", "smoke", 0, 0))
        with self.assertRaisesRegex(AcquisitionAcceptanceError,
                                    "ACQ_ACCEPTANCE_SMOKE_NOT_PUBLISHABLE"):
            publish_acquisition_acceptance(
                self.session, subject="SYN", registry_path=self.root / "registry.json",
                publication_directory=self.root / "publication")

    def test_v2_narrow_search_pair_miss_stops_before_open(self):
        spec = self.v2_spec("narrow")
        self.cli("init", payload=spec)
        search = self.cli("next")
        result = self.operational_capture(
            search, {**self.capture_identity(), "status": "returned",
                     "observed_backend": "native_tools.web__run"},
            f"Only one result: {PDF_URL}")
        self.assertEqual((result["status"], result["code"], result["next"]),
                         ("inconclusive", "ACQ_LIVE_SEARCH_PAIR_MISSING",
                          "blocked_inconclusive"))
        again = self.cli("next", expect=1)
        self.assertEqual(again["code"], "ACQ_LIVE_ACTION_REQUIRED")

    def test_v2_rejects_freeform_live_authority_and_uses_public_runner_only(self):
        spec = self.v2_spec("narrow")
        spec["proposals"] = [self.search_proposal(), self.primary_proposal()]
        failed = self.cli("init", payload=spec, expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_SPEC_INVALID")
        source = (ROOT / "investment/research/acquisition_live_session.py").read_text()
        for forbidden in ("runner._lock", "runner._append", "runner._save_dispatch_receipt"):
            self.assertNotIn(forbidden, source)

    def test_v2_smoke_unknown_never_emits_second_operation(self):
        spec = self.v2_spec("smoke")
        self.cli("init", payload=spec)
        call = self.cli("next")
        result = self.operational_capture(
            call, {**self.capture_identity(), "status": "unknown",
                   "code": "HOST_WEB_RESULT_UNKNOWN"}, "outcome unavailable")
        self.assertEqual(result["next"], "blocked_unknown")
        self.assertEqual(self.cli("next", expect=1)["code"], "ACQ_LIVE_ACTION_REQUIRED")


    def test_v2_smoke_late_capture_fences_unknown_and_never_emits_second_operation(self):
        spec = self.v2_spec("smoke")
        self.cli("init", payload=spec)
        call = self.cli("next")
        state = json.loads((self.session / "session.json").read_text())
        state["active"]["absolute_deadline"] = 0
        self.write(self.session / "session.json", state)
        late = self.operational_capture(
            call, {**self.capture_identity(), "status": "returned",
                   "observed_backend": "native_tools.web__run"},
            "late smoke result", expect=1)
        self.assertEqual(late["code"], "ACQ_LIVE_CAPTURE_DEADLINE")
        status = self.cli("status")
        self.assertEqual(status["phase"], "blocked_unknown")
        self.assertEqual(status["dispatches_captured"], 0)
        self.assertEqual(self.cli("next", expect=1)["code"], "ACQ_LIVE_ACTION_REQUIRED")


    def test_v2_binding_execution_root_and_manifest_drift_fail_closed(self):
        spec = self.v2_spec("narrow")
        binding_path = ROOT / spec["host_binding_ref"]["path"]
        binding = json.loads(binding_path.read_text())
        binding["execution_id"] = str(uuid.uuid4())
        unsigned = {key: value for key, value in binding.items() if key != "binding_sha256"}
        binding["binding_sha256"] = hashlib.sha256(json.dumps(
            unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.write(binding_path, binding)
        spec["host_binding_ref"]["sha256"] = hashlib.sha256(binding_path.read_bytes()).hexdigest()
        failed = self.cli("init", payload=spec, expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_HOST_BINDING_INVALID")
        if self.session.exists() and not any(self.session.iterdir()):
            self.session.rmdir()

        spec = self.v2_spec("narrow")
        manifest_path = ROOT / spec["host_materialization_manifest_ref"]["path"]
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["codex-binding.json"] = "0" * 64
        self.write(manifest_path, manifest)
        spec["host_materialization_manifest_ref"]["sha256"] = hashlib.sha256(
            manifest_path.read_bytes()).hexdigest()
        failed = self.cli("init", payload=spec, expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_MATERIALIZATION_MANIFEST_MISMATCH")

    def test_v1_direct_operational_json_cannot_self_promote_live_evidence(self):
        self.operational_source = OperationalEvidenceSource.HOST_RETURNED
        self.cli("init", payload=json.loads(self.spec.read_text()))
        call = self.cli("next")
        failed = self.operational_capture(
            call, {**self.capture_identity(), "status": "returned",
                   "observed_backend": "native_tools.web__run"},
            f"Official results: {PDF_URL} and {HTML_URL}", expect=1)
        self.assertEqual(failed["code"], "ACQ_LIVE_V1_OPERATIONAL_EVIDENCE_FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
