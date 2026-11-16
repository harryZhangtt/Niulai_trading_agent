from pathlib import Path
import tempfile
import unittest

from investment.research.acquisition_review import (
    record_reviewer_decision, review_payload_sha256,
)
from investment.research.acquisition_runner import HostedAcquisitionRunner, HostedProviderResponse
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity, DispatchIdentity, ExactArguments, RunIdentity,
)
from investment.research.acquisition_trace import (
    check_acquisition_trace, reconcile_terminal_ledgers,
)
from shared.research_sources.artifacts import SOURCE_STATE, read, save
from shared.research_sources.host_adapter_contracts import (
    AdapterId, HostInvocationReceipt, NON_CRYPTO_LIMITATION,
    OperationalEvidenceSource, OperationalTerminalStatus,
    OperationalTrustPolicy, ReviewerSessionReceipt,
)


class AcquisitionTraceTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ids = {"experiment_id": "experiment-1", "execution_id": "execution-1",
                    "trace_id": "trace-1"}
        self.question_id = "adoption.v1:issuer"
        self.operation_id = "open-html"
        self.attempt_id = "open-html:1"
        self.arguments = {"open": [{"ref_id": "https://example.com/report.html"}],
                          "response_length": "long"}
        raw = save(self.root, {"raw": "synthetic provider bytes"})
        text = "Synthetic canonical disclosure says customer adoption expanded during the bounded period."
        text_ref = save(self.root, text.encode(), suffix="txt")
        self.source_ref = save(self.root, {
            "schema_version": 1,
            "access_level": "document",
            "source_url": "https://example.com/report.html",
            "source_version": raw["sha256"],
            "raw": raw,
            "text": text_ref,
        })
        self.assessment_ref = save(self.root, {
            "kind": "acquisition_quote_assessment", **self.ids,
            "operation_id": self.operation_id,
            "attempt_id": self.attempt_id,
            "question_id": self.question_id,
            "source_ref": self.source_ref,
            "source_version": raw["sha256"],
            "raw_sha256": raw["sha256"],
            "text_sha256": text_ref["sha256"],
            "quote": "customer adoption expanded",
            "assessment_author_id": "assessment-author",
            "operator_id": "live-operator",
        })
        self.unit_ref = save(self.root, {
            "kind": "acquisition_candidate_unit", **self.ids,
            "unit_id": "unit-1",
            "question_id": self.question_id,
            "assessment_ref": self.assessment_ref,
            "source_ref": self.source_ref,
            "quote": "customer adoption expanded",
        })
        self.review_ref = record_reviewer_decision(
            self.root,
            assessment_ref=self.assessment_ref,
            unit_ref=self.unit_ref,
            reviewer_id="independent-reviewer",
            assessment_author_id="assessment-author",
            operator_id="live-operator",
            disposition="approve",
            checks={"question_relevance": True, "literal_support": True,
                    "canonical_lineage": True},
            reason="The bounded question, literal quote and canonical source lineage agree.",
        )
        self.proposal_ref = save(self.root, {
            "kind": "acquisition_proposal",
            "operation_id": self.operation_id,
            "question_ids": [self.question_id],
            "arguments": self.arguments,
        })
        request_ref = save(self.root, {"items": self.arguments["open"],
                                      "arguments": self.arguments})
        receipt_ref = save(self.root, {
            "kind": "acquisition_operation_receipt",
            "execution_id": self.ids["execution_id"],
            "operation_id": self.operation_id,
            "operation": "open",
            "fetch_executed": True,
            "provider_items": 1,
            "request_ref": request_ref,
            "source_sha256s": [self.source_ref["sha256"]],
        })
        exposure_event = save(self.root, {
            "operation_id": self.operation_id,
            "exposed_source_refs": [self.source_ref],
        })
        exposure_ref = save(self.root, {"event_refs": [exposure_event]})
        self.host_ref = save(self.root, {
            "kind": "acquisition_eval_run",
            "execution_id": self.ids["execution_id"],
            "backend": "native_tools.web__run",
            "search_receipt_refs": [],
            "open_receipt_refs": [receipt_ref],
            "exposure_ref": exposure_ref,
            "usage": {"provider_items": 1},
        })
        manifest_ref = save(self.root, {"questions": [{
            "id": self.question_id,
            "question": "What bounded adoption evidence is supported?",
        }]})
        transition_ref = save(self.root, {
            "decision": "capture", "operation_id": self.operation_id,
        })
        self.controller_ref = save(self.root, {
            "manifest_ref": manifest_ref,
            "transition_refs": [transition_ref],
            "usage": {"provider_items": 1},
        })
        self.driver_ref = save(self.root, {
            "kind": "acquisition_driver_run", **self.ids,
            "controller_summary_ref": self.controller_ref,
            "host_run_ref": self.host_ref,
            "assessment_refs": [self.assessment_ref],
            "unit_refs": [self.unit_ref],
            "operation_states": {self.operation_id: [
                {"sequence": 0, "state": "reserved"},
                {"sequence": 1, "state": "finalized"},
            ]},
        })
        runner = HostedAcquisitionRunner(
            self.root / "runner", provider=lambda *_: HostedProviderResponse(
                [b"synthetic"], observed_backend="native_tools.web__run"),
            configured_backend="native_tools.web__run", run_deadline=100,
            raw_byte_limit=1024, monotonic=lambda: 1,
        )
        runner.prepare(AcquisitionIdentity(
            RunIdentity(**self.ids),
            DispatchIdentity(self.operation_id, self.attempt_id, "dispatch-1"),
        ), ExactArguments.from_mapping(self.arguments))
        runner.claim("dispatch-1")
        self.dispatch_ref = runner.invoke("dispatch-1", call_deadline=50)["dispatch_ref"]

    def check(self, **updates):
        values = {
            "driver_ref": self.driver_ref,
            "dispatch_refs": [self.dispatch_ref],
            "review_refs": [self.review_ref],
            "proposal_refs": [self.proposal_ref],
            "expected_dispatches": 1,
        }
        values.update(updates)
        return check_acquisition_trace(**values)

    def test_independent_checker_reopens_complete_chain(self):
        verdict = self.check()
        self.assertEqual(verdict["status"], "pass")
        self.assertEqual((verdict["complete_chains"], verdict["credited_units"]), (1, 1))
        self.assertTrue(all(row["reasons"] for row in verdict["gates"]))
        self.assertIn("not_provider_quality", verdict["scope"])

    def test_hand_authored_dispatch_receipt_is_rejected(self):
        forged = save(self.root, {
            "kind": "acquisition_dispatch_receipt", "version": "acquisition-runner-1",
            **self.ids, "operation_id": self.operation_id, "attempt_id": self.attempt_id,
            "dispatch_id": "forged", "invocation_started": True,
            "status": "captured", "provider_items": 1,
        })
        verdict = self.check(dispatch_refs=[forged])
        self.assertEqual(verdict["status"], "fail")
        self.assertEqual(verdict["gates"][0]["gate"], "artifacts_reopened")

    def test_missing_proposal_fails_with_per_gate_reason(self):
        verdict = self.check(proposal_refs=[])
        self.assertEqual(verdict["status"], "fail")
        chain = next(row for row in verdict["gates"] if row["gate"] == "complete_chains")
        self.assertFalse(chain["passed"])
        self.assertIn("proposal_missing_or_unbound", chain["reasons"][0])
        self.assertIn("exact_arguments_mismatch", chain["reasons"][0])

    def test_reconciliation_is_recomputed_and_checker_does_not_trust_status(self):
        result = reconcile_terminal_ledgers(
            self.root,
            driver_ref=self.driver_ref,
            dispatch_refs=[self.dispatch_ref],
            review_refs=[self.review_ref],
            expected_dispatches=1,
        )
        self.assertEqual(result["reconciliation"]["status"], "pass")
        self.assertTrue(all(row["reasons"] for row in result["reconciliation"]["gates"]))
        verdict = self.check(reconciliation_ref=result["reconciliation_ref"])
        self.assertEqual(verdict["status"], "pass")

        fake = save(self.root, {
            **read(result["reconciliation_ref"]),
            "status": "pass",
            "driver_ref": {"path": "not-authoritative", "sha256": "0" * 64},
        })
        failed = self.check(reconciliation_ref=fake)
        gate = next(row for row in failed["gates"]
                    if row["gate"] == "reconciliation_binding")
        self.assertFalse(gate["passed"])
        self.assertEqual(failed["status"], "fail")

    def test_operational_receipts_are_bound_but_synthetic_is_not_live_eligible(self):
        dispatch = read(self.dispatch_ref)
        invocation = HostInvocationReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            configured_backend="native_tools.web__run",
            observed_tool_identity="native_tools.web__run",
            host_session_id="synthetic-host-session",
            operational_event_id="event-dispatch-1", event_id_unavailable_reason=None,
            dispatch_id="dispatch-1",
            acquisition_arguments_sha256=dispatch["arguments_sha256"],
            tool_input_sha256=dispatch["arguments_sha256"],
            result_sha256=dispatch["evidence_sha256"],
            started_at="2026-11-05T01:00:00+00:00",
            finished_at="2026-11-05T01:00:01+00:00",
            adapter_dispatch_count=1, tool_invocation_count=1,
            underlying_request_observation="unknown",
            underlying_http_request_count=None, host_retry_count=None,
            terminal_status=OperationalTerminalStatus.CAPTURED, terminal_code=None,
            source=OperationalEvidenceSource.SYNTHETIC,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        invocation_ref = save(self.root, {
            "kind": "acquisition_host_invocation_receipt",
            "receipt": invocation.to_public_dict()})
        checks = {"question_relevance": True, "literal_support": True,
                  "canonical_lineage": True}
        reason = "The bounded question, literal quote and canonical source lineage agree."
        payload_hash = review_payload_sha256(
            assessment_ref=self.assessment_ref, unit_ref=self.unit_ref,
            reviewer_id="independent-reviewer", assessment_author_id="assessment-author",
            operator_id="live-operator", disposition="approve", checks=checks, reason=reason)
        reviewer = ReviewerSessionReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            host_session_id="synthetic-review-session", principal_ref="independent-reviewer",
            review_artifact_sha256=payload_hash, checked_at="2026-11-05T01:02:00+00:00",
            source=OperationalEvidenceSource.SYNTHETIC,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        review_ref = record_reviewer_decision(
            self.root, assessment_ref=self.assessment_ref, unit_ref=self.unit_ref,
            reviewer_id="independent-reviewer", assessment_author_id="assessment-author",
            operator_id="live-operator", disposition="approve", checks=checks, reason=reason,
            reviewer_session_receipt=reviewer.to_public_dict(),
            trust_policy="operational_host_evidence")
        verdict = self.check(
            review_refs=[review_ref], host_invocation_refs=[invocation_ref],
            trust_policy="operational_host_evidence", host_session_id="synthetic-host-session",
            host_adapter="codex_native_web")
        self.assertEqual(verdict["status"], "pass")
        self.assertFalse(verdict["live_acceptance_eligible"])
        gate = next(row for row in verdict["gates"]
                    if row["gate"] == "operational_invocation_receipts")
        self.assertTrue(gate["passed"])


if __name__ == "__main__":
    unittest.main()
