"""Production-component rehearsal with an injected counting fake; no network calls."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from investment.research import datasource as ds
from investment.research.acquisition_driver import AcquisitionDriver
from investment.research.acquisition_orchestration import (
    AcquisitionController,
    compile_prefetch_manifest,
)
from investment.research.acquisition_runner import (
    HostedAcquisitionRunner,
    HostedProviderResponse,
)
from investment.research.acquisition_review import (
    record_reviewer_decision, review_payload_sha256,
)
from investment.research.acquisition_trace import (
    check_acquisition_trace,
    reconcile_terminal_ledgers,
)
from shared.research_sources.host_adapter_contracts import (
    AdapterId, HostInvocationReceipt, NON_CRYPTO_LIMITATION,
    OperationalEvidenceSource, OperationalTerminalStatus,
    OperationalTrustPolicy, ReviewerSessionReceipt,
)
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    ExactArguments,
    RunIdentity,
)
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.host_web import HostWeb, freeze_config


PDF_URL = "https://example.com/disclosure.pdf"
HTML_URL = "https://example.com/disclosure.html"
QUESTION_ID = "adoption.v1:issuer"
BODY = (
    "Synthetic canonical disclosure states that customer adoption expanded during "
    "the bounded period while commercial conversion remained explicitly uncertain."
)
QUOTE = "customer adoption expanded during the bounded period"


class CountingFake:
    def __init__(self):
        self.calls = []

    def __call__(self, argument_bytes, absolute_deadline):
        arguments = json.loads(argument_bytes)
        self.calls.append((argument_bytes, absolute_deadline))
        if "search_query" in arguments:
            payload = f"Official results: {PDF_URL} and {HTML_URL}".encode()
        elif arguments["open"][0]["ref_id"] == PDF_URL:
            payload = json.dumps({
                "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"},
                "message": "Structured synthetic oversized-PDF diagnostic.",
            }, sort_keys=True).encode()
        else:
            payload = f"Synthetic source ({HTML_URL})\nL0: {BODY}".encode()
        return HostedProviderResponse([payload], observed_backend="native_tools.web__run")


class AcquisitionSyntheticE2ETests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.execution_id = str(uuid.uuid4())
        self.identities = {
            "experiment_id": "synthetic-provider-free-e2e",
            "execution_id": self.execution_id,
            "trace_id": "trace-synthetic-provider-free-e2e",
        }
        context = save(self.root, {"kind": "synthetic_context"})
        plan = save(self.root, {
            "scope": "retrieval_plan_only",
            "context_ref": context,
            "proposal": {"questions": [{
                "id": QUESTION_ID,
                "facet": "adoption",
                "question": "What bounded adoption evidence is literally supported?",
                "evidence_to_seek": "One literal source-grounded observation.",
                "source_roles": ["issuer document"],
                "capability_ids": ["web_search", "official_document"],
                "depends_on": [],
                "priority": "required",
                "stop_rule": "Stop after one reviewed candidate support unit.",
            }]},
        })
        manifest = compile_prefetch_manifest(
            plan, self.root, search_items=1, open_items=2,
            provider_items=3, reserve_provider_items=0,
        )
        self.controller = AcquisitionController(self.root / "controller", manifest_ref=manifest)
        config = freeze_config({
            "schema_version": 1,
            "execution_id": self.execution_id,
            "arm": "A",
            "question": "What bounded adoption evidence is literally supported?",
            "baseline_ref": context,
            "cutoff": "2026-11-04T12:10:00+00:00",
            "model_sha256": "a" * 64,
            "backend": "native_tools.web__run",
            "cohort": "fault",
            "cache_enabled": False,
            "cache_max_age_seconds": 0,
            "max_fallbacks": 1,
            "requirement_ids": [QUESTION_ID],
            "budget": {"search_items": 1, "open_items": 2,
                       "provider_items": 3, "wall_seconds": 600},
        })
        self.portal = HostWeb(
            self.root / "host", config=config, cache_directory=self.root / "cache",
            now=lambda: "2026-11-04T12:00:00+00:00",
        )
        self.driver = AcquisitionDriver(
            self.root / "driver", controller=self.controller, portal=self.portal,
            **self.identities,
        )
        self.provider = CountingFake()
        self.runner = HostedAcquisitionRunner(
            self.root / "runner", provider=self.provider,
            configured_backend="native_tools.web__run",
            run_deadline=200.0, raw_byte_limit=65536, monotonic=lambda: 100.0,
        )
        self.proposal_refs = []
        self.dispatch_refs = []
        self.host_invocation_refs = []

    @staticmethod
    def alternate():
        return {
            "representation_kind": "html",
            "exact_arguments": {"open": [{"ref_id": HTML_URL}], "response_length": "long"},
            "source_role": "issuer document",
            "required_capability": "official_document",
            "required_access_level": "public",
            "canonical_disclosure_id": "synthetic-disclosure-1",
            "relationship_to_primary": "semantically_equivalent_representation",
            "semantic_equivalence_rationale": "The synthetic PDF and HTML represent one disclosure.",
            "permitted_trigger_codes": ["HOST_WEB_BODY_TOO_LARGE"],
            "budget_cost": 1,
        }

    def dispatch(self, operation_id, arguments, *, diagnostic=None):
        claimed = self.driver.claim_dispatch(operation_id)
        exact = ExactArguments.from_mapping(arguments)
        self.assertEqual(ExactArguments.from_mapping(claimed).canonical_json, exact.canonical_json)
        identity = AcquisitionIdentity(
            RunIdentity(**self.identities),
            DispatchIdentity(operation_id, f"{operation_id}:1", f"dispatch-{len(self.dispatch_refs) + 1}"),
        )
        self.runner.prepare(identity, exact)
        self.assertEqual(self.runner.claim(identity.dispatch.dispatch_id), exact.canonical_json)
        self.driver.record_invocation_started(operation_id)
        receipt = self.runner.invoke(identity.dispatch.dispatch_id, call_deadline=150.0)
        self.dispatch_refs.append(receipt["dispatch_ref"])
        dispatch = read(receipt["dispatch_ref"])
        host_receipt = HostInvocationReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            configured_backend="native_tools.web__run",
            observed_tool_identity="native_tools.web__run",
            host_session_id="synthetic-counting-fake-session",
            operational_event_id=f"event-{identity.dispatch.dispatch_id}",
            event_id_unavailable_reason=None,
            dispatch_id=identity.dispatch.dispatch_id,
            acquisition_arguments_sha256=exact.sha256,
            tool_input_sha256=exact.sha256,
            result_sha256=dispatch["evidence_sha256"],
            started_at="2026-11-05T01:00:00+00:00",
            finished_at="2026-11-05T01:00:01+00:00",
            adapter_dispatch_count=1, tool_invocation_count=1,
            underlying_request_observation="unknown",
            underlying_http_request_count=None, host_retry_count=None,
            terminal_status=OperationalTerminalStatus.CAPTURED,
            terminal_code=None,
            source=OperationalEvidenceSource.SYNTHETIC,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        self.host_invocation_refs.append(save(self.root, {
            "kind": "acquisition_host_invocation_receipt",
            "receipt": host_receipt.to_public_dict(),
        }))
        raw = read(receipt["raw_ref"], json_value=False).decode()
        try:
            raw_result = json.loads(raw)
        except json.JSONDecodeError:
            raw_result = raw
        return self.driver.capture_host(operation_id, {
            "actual_arguments": arguments,
            "raw_result": raw_result,
            "status": "returned",
            **({"diagnostic": diagnostic} if diagnostic else {}),
        }, runner=self.runner, dispatch_id=identity.dispatch.dispatch_id,
            dispatch_ref=receipt["dispatch_ref"])

    def test_search_pdf_html_review_checker_and_projection(self):
        search = {
            "operation_id": "search-disclosure",
            "question_ids": [QUESTION_ID],
            "source_role": "issuer document",
            "reason": "Find the frozen synthetic disclosure pair.",
            "arguments": {"search_query": [{"q": "site:example.com synthetic disclosure"}],
                          "response_length": "long"},
            "alternates": [],
        }
        self.proposal_refs.append(save(self.root, {"kind": "acquisition_proposal", **search}))
        self.driver.reserve(search)
        self.driver.prepare_host(search["operation_id"])
        found = self.dispatch(search["operation_id"], search["arguments"])
        self.assertEqual(found["packet"]["urls"], [PDF_URL, HTML_URL])
        self.driver.commit_controller(search["operation_id"])

        primary = {
            "operation_id": "open-primary",
            "question_ids": [QUESTION_ID],
            "source_role": "issuer document",
            "reason": "Open the exact frozen PDF representation.",
            "arguments": {"open": [{"ref_id": PDF_URL}], "response_length": "long"},
            "alternates": [self.alternate()],
        }
        self.proposal_refs.append(save(self.root, {"kind": "acquisition_proposal", **primary}))
        self.driver.reserve(primary)
        self.driver.prepare_host(primary["operation_id"])
        failed = self.dispatch(
            primary["operation_id"], primary["arguments"],
            diagnostic={"code": "HOST_WEB_BODY_TOO_LARGE"},
        )
        self.assertEqual((failed["status"], failed["code"]),
                         ("failed", "HOST_WEB_BODY_TOO_LARGE"))
        recovery = self.driver.commit_controller(primary["operation_id"])["next_dispatch"]
        fallback_id = recovery["operation_id"]
        fallback_proposal = {
            "kind": "acquisition_proposal",
            "operation_id": fallback_id,
            "question_ids": [QUESTION_ID],
            "arguments": recovery["arguments"],
        }
        self.proposal_refs.append(save(self.root, fallback_proposal))
        self.driver.prepare_host(fallback_id)
        opened = self.dispatch(fallback_id, recovery["arguments"])
        self.assertEqual(opened["packet"]["documents"][0]["text"], BODY)
        self.driver.commit_controller(fallback_id, [{
            "question_id": QUESTION_ID,
            "quote": QUOTE,
            "disposition": "candidate_support",
        }])
        self.driver.save_assessments(fallback_id, assessor_version="assessment-author")
        self.driver.attach_units(fallback_id)
        state = read(self.driver._head())
        operation = state["operations"][fallback_id]
        checks = {"question_relevance": True, "literal_support": True,
                  "canonical_lineage": True}
        reason = "The bounded question, literal quote, and frozen lineage agree."
        payload_hash = review_payload_sha256(
            assessment_ref=operation["assessment_refs"][0],
            unit_ref=operation["unit_refs"][0],
            reviewer_id="independent-reviewer",
            assessment_author_id="assessment-author", operator_id="synthetic-operator",
            disposition="approve", checks=checks, reason=reason)
        reviewer = ReviewerSessionReceipt(
            adapter_id=AdapterId.CODEX_NATIVE_WEB,
            host_session_id="synthetic-review-session",
            principal_ref="independent-reviewer",
            review_artifact_sha256=payload_hash,
            checked_at="2026-11-05T01:02:00+00:00",
            source=OperationalEvidenceSource.SYNTHETIC,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        )
        review_ref = record_reviewer_decision(
            self.root, assessment_ref=operation["assessment_refs"][0],
            unit_ref=operation["unit_refs"][0], reviewer_id="independent-reviewer",
            assessment_author_id="assessment-author", operator_id="synthetic-operator",
            disposition="approve", checks=checks, reason=reason,
            reviewer_session_receipt=reviewer.to_public_dict(),
            trust_policy="operational_host_evidence")
        self.driver.import_reviews(fallback_id, [review_ref])

        first = self.driver.finish()
        second = self.driver.finish()
        self.assertEqual(first, second)
        calls_at_finish = len(self.provider.calls)
        reconciliation = reconcile_terminal_ledgers(
            self.root,
            driver_ref=first["final_ref"],
            dispatch_refs=self.dispatch_refs,
            host_invocation_refs=self.host_invocation_refs,
            review_refs=[review_ref], expected_dispatches=3,
            trust_policy="operational_host_evidence",
            host_session_id="synthetic-counting-fake-session",
            host_adapter="codex_native_web",
        )
        self.assertEqual(len(self.provider.calls), calls_at_finish)
        self.assertEqual(reconciliation["reconciliation"]["status"], "pass")
        verdict = check_acquisition_trace(
            driver_ref=first["final_ref"],
            dispatch_refs=self.dispatch_refs,
            host_invocation_refs=self.host_invocation_refs,
            review_refs=[review_ref], proposal_refs=self.proposal_refs,
            expected_dispatches=3,
            reconciliation_ref=reconciliation["reconciliation_ref"],
            trust_policy="operational_host_evidence",
            host_session_id="synthetic-counting-fake-session",
            host_adapter="codex_native_web",
        )
        self.assertEqual((verdict["status"], verdict["complete_chains"],
                          verdict["credited_units"]), ("pass", 1, 1))
        self.assertFalse(verdict["live_acceptance_eligible"])
        self.assertFalse(reconciliation["reconciliation"]["live_acceptance_eligible"])
        self.assertFalse(any(read(ref)["receipt"]["live_acceptance_eligible"]
                             for ref in self.host_invocation_refs))

        envelope = save(self.root, {
            "kind": "acquisition_driver_projection",
            "schema_version": 1,
            "subject": "SYN",
            "case_id": "synthetic-pdf-html-recovery",
            "driver_ref": first["final_ref"],
            "dispatch_refs": self.dispatch_refs,
            "host_invocation_refs": self.host_invocation_refs,
            "review_refs": [review_ref],
            "proposal_refs": self.proposal_refs,
            "expected_dispatches": 3,
            "reconciliation_ref": reconciliation["reconciliation_ref"],
            "trust_policy": "operational_host_evidence",
            "host_session_id": "synthetic-counting-fake-session",
            "host_adapter": "codex_native_web",
            "checker_verdict": verdict,
        })
        projected, _ = ds.acquisition_projection.project(
            ds.Reader(), envelope, "SYN", text=ds.text, identifier=ds.identifier,
            timestamp=ds.timestamp, sha=ds.sha, source_dto=ds.source_dto,
            numeric_metrics=ds.numeric_metrics, aggregate=ds.aggregate,
        )
        trace = projected["driver_trace"]
        self.assertEqual(trace["checker_verdict"], "pass")
        self.assertEqual(trace["accounting"], {
            "logical_operations": 3,
            "reserved_provider_items": 3,
            "actual_dispatches": 3,
            "cache_hits": 0,
            "fallbacks": 1,
            "complete_chains": 1,
            "credited_units": 1,
        })
        self.assertEqual(len(self.provider.calls), 3)
        self.assertEqual(
            [call[0] for call in self.provider.calls],
            [ExactArguments.from_mapping(proposal["arguments"]).canonical_json
             for proposal in (search, primary, fallback_proposal)],
        )
        public = json.dumps(projected)
        self.assertNotIn(str(self.root), public)
        self.assertNotIn("Structured synthetic oversized-PDF diagnostic", public)
        self.assertFalse(any(path.name.startswith(".raw-pending-")
                             for path in (self.root / "runner" / "raw").iterdir()))
        with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_FINISHED"):
            self.driver.reserve(search)


if __name__ == "__main__":
    unittest.main()
