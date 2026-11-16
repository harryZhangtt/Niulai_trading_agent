from pathlib import Path
import tempfile
import unittest

from investment.research.acquisition_orchestration import (
    AcquisitionController,
    classify_native_failure,
    compile_prefetch_manifest,
)
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save


PRIMARY = "https://example.com/report.pdf"
ALTERNATE = "https://example.com/report.html"
BODY = "Synthetic source body describing a customer adoption mechanism with enough bounded text for structural checking."


class AcquisitionOrchestrationTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        context = save(self.root, {"kind": "synthetic_context"})
        self.plan = save(self.root, {
            "scope": "retrieval_plan_only",
            "context_ref": context,
            "proposal": {"questions": [
                self.question("required", "required", "issuer document"),
                self.question("optional", "optional", "customer case study"),
            ]},
        })
        self.manifest = compile_prefetch_manifest(
            self.plan, self.root, search_items=3, open_items=3,
            provider_items=4, reserve_provider_items=1,
        )
        self.controller = AcquisitionController(self.root / "controller", manifest_ref=self.manifest)

    @staticmethod
    def question(qid, priority, source_role):
        return {
            "id": qid,
            "facet": "adoption",
            "question": f"What resolves {qid}?",
            "evidence_to_seek": "A source-grounded observation.",
            "source_roles": [source_role],
            "capability_ids": ["web_search", "official_document"],
            "depends_on": [],
            "priority": priority,
            "stop_rule": "Stop after grounded evidence or an explicit blocked gap.",
        }

    @staticmethod
    def alternate(url=ALTERNATE, triggers=None):
        return {
            "representation_kind": "html",
            "exact_arguments": {"open": [{"ref_id": url}], "response_length": "long"},
            "source_role": "issuer document",
            "required_capability": "official_document",
            "required_access_level": "document",
            "canonical_disclosure_id": "synthetic-disclosure",
            "relationship_to_primary": "semantically_equivalent_representation",
            "semantic_equivalence_rationale": "Synthetic fixtures represent the same frozen disclosure.",
            "permitted_trigger_codes": triggers or ["HOST_WEB_BODY_TOO_LARGE", "HOST_WEB_SOURCE_INACCESSIBLE"],
            "budget_cost": 1,
        }

    @staticmethod
    def proposal(operation_id="open-primary", question="required", source_role="issuer document",
                 url=PRIMARY, alternates=None):
        return {
            "operation_id": operation_id,
            "question_ids": [question],
            "source_role": source_role,
            "reason": "Test the frozen evidence need with an original source.",
            "arguments": {"open": [{"ref_id": url}], "response_length": "long"},
            "alternates": ([{**AcquisitionOrchestrationTests.alternate(), "source_role": source_role}]
                           if alternates is None else alternates),
        }

    def test_manifest_is_frozen_projection_not_coverage_claim(self):
        manifest = read(self.manifest)
        self.assertEqual(manifest["scope"], "prefetch_manifest_not_retrieval_or_semantic_support")
        self.assertEqual([row["id"] for row in manifest["questions"]], ["required", "optional"])
        self.assertEqual(manifest["budget"]["reserve_provider_items"], 1)
        self.assertEqual(manifest["policy"]["proposal_owner"], "agent")

    def test_pdf_requires_declared_alternate_and_duplicate_is_rejected(self):
        with self.assertRaisesRegex(SourceError, "ACQ_PDF_ALTERNATE_REQUIRED"):
            self.controller.prepare(self.proposal(alternates=[]))
        search = {
            "operation_id": "search-required",
            "question_ids": ["required"],
            "source_role": "issuer document",
            "reason": "Find an original source.",
            "arguments": {"search_query": [{"q": "synthetic original source"}]},
            "alternates": [],
        }
        self.controller.prepare(search)
        self.controller.capture("search-required", {"status": "returned", "packet": {"urls": [ALTERNATE]}})
        with self.assertRaisesRegex(SourceError, "ACQ_DUPLICATE_OPERATION"):
            self.controller.prepare({**search, "operation_id": "search-again"})

    def test_required_reserve_prevents_optional_work_from_consuming_last_item(self):
        manifest = compile_prefetch_manifest(
            self.plan, self.root / "reserve", search_items=3, open_items=3,
            provider_items=1, reserve_provider_items=1,
        )
        controller = AcquisitionController(self.root / "reserve-controller", manifest_ref=manifest)
        optional = {
            "operation_id": "optional-search",
            "question_ids": ["optional"],
            "source_role": "customer case study",
            "reason": "Explore optional evidence.",
            "arguments": {"search_query": [{"q": "synthetic optional source"}]},
            "alternates": [],
        }
        with self.assertRaisesRegex(SourceError, "ACQ_REQUIRED_RESERVE"):
            controller.prepare(optional)
        required = {**optional, "operation_id": "required-search", "question_ids": ["required"],
                    "source_role": "issuer document"}
        self.assertEqual(controller.prepare(required)["operation_id"], "required-search")

    def test_oversized_pdf_queues_one_different_fallback_and_preserves_budget(self):
        dispatch = self.controller.prepare(self.proposal())
        self.assertEqual(dispatch["arguments"]["open"][0]["ref_id"], PRIMARY)
        result = self.controller.capture("open-primary", {
            "status": "failed",
            "code": "HOST_WEB_BODY_TOO_LARGE",
            "raw_text": "Failed: (400) Content length is too large: 15229853",
        })
        fallback = result["next_dispatch"]
        self.assertEqual(fallback["fallback_of"], "open-primary")
        self.assertEqual(fallback["arguments"]["open"][0]["ref_id"], ALTERNATE)
        with self.assertRaisesRegex(SourceError, "ACQ_PENDING"):
            self.controller.prepare({**self.proposal("other", url=ALTERNATE, alternates=[]),
                                     "arguments": {"open": [{"ref_id": ALTERNATE}]}})
        state = read(self.controller._head())
        self.assertEqual(state["usage"], {"search_items": 0, "open_items": 2, "provider_items": 2})
        self.assertIn(PRIMARY, state["failed_urls"])

    def test_optional_recovery_cannot_consume_required_reserve(self):
        manifest = compile_prefetch_manifest(
            self.plan, self.root / "fallback-reserve", search_items=2, open_items=2,
            provider_items=2, reserve_provider_items=1,
        )
        controller = AcquisitionController(self.root / "fallback-reserve-controller", manifest_ref=manifest)
        proposal = self.proposal(question="optional", source_role="customer case study",
                                 url="https://example.com/customer.html")
        controller.prepare(proposal)
        result = controller.capture("open-primary", {
            "status": "failed", "code": "HOST_WEB_SOURCE_INACCESSIBLE",
            "raw_text": "not accessible via this tool",
        })
        self.assertIsNone(result["next_dispatch"])
        state = read(controller._head())
        self.assertEqual(state["usage"]["provider_items"], 1)
        self.assertEqual(state["questions"]["optional"]["status"], "blocked")

    def test_successful_fallback_requires_literal_quote_and_remains_provisional(self):
        self.controller.prepare(self.proposal())
        fallback = self.controller.capture("open-primary", {
            "status": "failed", "code": "HOST_WEB_SOURCE_INACCESSIBLE", "raw_text": "not accessible via this tool",
        })["next_dispatch"]
        bad = {"status": "returned", "packet": {"documents": [{
            "source_ref": {"path": "synthetic", "sha256": "a" * 64},
            "url": ALTERNATE, "text": BODY,
        }]}, "assessments": [{"question_id": "required", "quote": "not an exact quote", "disposition": "candidate_support"}]}
        with self.assertRaisesRegex(SourceError, "ACQ_ASSESSMENT_INVALID"):
            self.controller.capture(fallback["operation_id"], bad)
        # Failed validation does not publish a state transition; the same pending
        # capture can be corrected without spending another provider item.
        quote = "describing a customer adoption mechanism"
        good = {**bad, "assessments": [{"question_id": "required", "quote": quote,
                                        "disposition": "candidate_support"}]}
        self.controller.capture(fallback["operation_id"], good)
        summary = self.controller.finish()["summary"]
        required = next(row for row in summary["questions"] if row["question_id"] == "required")
        self.assertEqual(required["status"], "supported_partial")
        self.assertEqual(required["attempts"], 2)
        self.assertIn("not_semantic_quality", summary["scope"])

    def test_no_compatible_fallback_yields_explicit_blocked_gap(self):
        proposal = self.proposal(url="https://example.com/page.html", alternates=[])
        self.controller.prepare(proposal)
        result = self.controller.capture("open-primary", {
            "status": "failed", "code": "HOST_WEB_BODY_UNPARSEABLE", "raw_text": "unparseable response",
        })
        self.assertIsNone(result["next_dispatch"])
        summary = self.controller.finish()["summary"]
        required = next(row for row in summary["questions"] if row["question_id"] == "required")
        self.assertEqual(required["status"], "blocked")
        self.assertEqual(required["gaps"], ["HOST_WEB_BODY_UNPARSEABLE"])
        self.assertEqual(summary["status"], "completed_with_gaps")

    def test_non_representation_failures_never_fallback(self):
        for code in ["SOURCE_HTTP_403", "SOURCE_HTTP_429", "NATIVE_TRANSPORT_FAILED",
                     "HOST_WEB_DEADLINE", "NATIVE_TRANSPORT_CIRCUIT_OPEN",
                     "HOST_WEB_RESULT_UNKNOWN"]:
            with self.subTest(code=code):
                controller = AcquisitionController(self.root / ("terminal-" + code.lower()),
                                                   manifest_ref=self.manifest)
                controller.prepare(self.proposal())
                status = "unknown" if code == "HOST_WEB_RESULT_UNKNOWN" else "failed"
                result = controller.capture("open-primary", {
                    "status": status, "code": code, "raw_text": "failure-like arbitrary body text",
                })
                self.assertIsNone(result["next_dispatch"])
                state = read(controller._head())
                self.assertEqual(state["questions"]["required"]["gaps"], [code])

    def test_shared_preflight_requires_role_compatibility_for_every_question(self):
        proposal = self.proposal()
        proposal["question_ids"] = ["required", "optional"]
        with self.assertRaisesRegex(SourceError, "ACQ_SOURCE_ROLE"):
            self.controller.prepare(proposal)
        self.assertEqual(read(self.controller._head())["usage"]["provider_items"], 0)

    def test_shared_preflight_rejects_incompatible_capability_and_host_url(self):
        plan = read(self.plan)
        plan["proposal"]["questions"][0]["capability_ids"] = ["web_search"]
        plan_ref = save(self.root / "capability", plan)
        manifest = compile_prefetch_manifest(
            plan_ref, self.root / "capability", search_items=2, open_items=2,
            provider_items=2, reserve_provider_items=0,
        )
        controller = AcquisitionController(self.root / "capability-controller", manifest_ref=manifest)
        with self.assertRaisesRegex(SourceError, "ACQ_CAPABILITY_OPERATION"):
            controller.prepare(self.proposal())
        with self.assertRaisesRegex(SourceError, "ACQ_URL_INVALID"):
            self.controller.prepare(self.proposal(url="https://localhost/report.html", alternates=[]))
        self.assertEqual(read(controller._head())["usage"]["provider_items"], 0)
        self.assertEqual(read(self.controller._head())["usage"]["provider_items"], 0)

    def test_question_ids_share_catalog_grammar_but_operation_ids_remain_dispatch_safe(self):
        plan = read(self.plan)
        plan["proposal"]["questions"][0]["id"] = "required.v1:issuer"
        plan_ref = save(self.root / "ids", plan)
        manifest = compile_prefetch_manifest(
            plan_ref, self.root / "ids", search_items=2, open_items=2,
            provider_items=2, reserve_provider_items=0,
        )
        controller = AcquisitionController(self.root / "ids-controller", manifest_ref=manifest)
        proposal = self.proposal(question="required.v1:issuer")
        self.assertEqual(controller.prepare(proposal)["requirement_ids"], ["required.v1:issuer"])
        with self.assertRaisesRegex(SourceError, "ACQ_OPERATION_ID"):
            self.controller.prepare({**self.proposal("bad.operation", question="optional",
                                                     source_role="customer case study",
                                                     url="https://example.com/page.html", alternates=[]),
                                     "operation_id": "bad.operation"})

    def test_native_failure_classifier_uses_structured_code_not_body_text(self):
        self.assertEqual(classify_native_failure("HOST_WEB_BODY_UNPARSEABLE",
            "Content length is too large: 15229853"), "HOST_WEB_BODY_UNPARSEABLE")
        self.assertEqual(classify_native_failure("HOST_WEB_SOURCE_INACCESSIBLE",
            "arbitrary unrelated text"), "HOST_WEB_SOURCE_INACCESSIBLE")
        with self.assertRaisesRegex(SourceError, "ACQ_FAILURE_CODE_INVALID"):
            classify_native_failure("INVENTED_FROM_BODY", "too large")


if __name__ == "__main__":
    unittest.main()
