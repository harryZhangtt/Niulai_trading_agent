from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
import uuid

from investment.research.acquisition_driver import AcquisitionDriver
from investment.research.acquisition_orchestration import AcquisitionController, compile_prefetch_manifest
from investment.research.acquisition_runner import HostedAcquisitionRunner, HostedProviderResponse, RunnerError
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    ExactArguments,
    RunIdentity,
)
from shared.research_sources.artifacts import SOURCE_STATE, SourceError, read, save
from shared.research_sources.host_web import HostWeb, freeze_config


PRIMARY = "https://example.com/report.pdf"
ALTERNATE = "https://example.com/report.html"
BODY = ("Synthetic eligible issuer body describing a customer adoption mechanism "
        "and its bounded commercial limitations without claiming recognized revenue.")


class AcquisitionDriverTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)

    def stack(self, name="run"):
        directory = self.root / name
        context = save(directory, {"kind": "synthetic_context"})
        plan = save(directory, {
            "scope": "retrieval_plan_only",
            "context_ref": context,
            "proposal": {"questions": [{
                "id": "adoption.v1:issuer",
                "facet": "adoption",
                "question": "What adoption mechanism is supported?",
                "evidence_to_seek": "A literal source-grounded observation.",
                "source_roles": ["issuer document"],
                "capability_ids": ["official_document"],
                "depends_on": [],
                "priority": "required",
                "stop_rule": "Stop after support or an explicit blocked gap.",
            }]},
        })
        manifest = compile_prefetch_manifest(
            plan, directory, search_items=1, open_items=2,
            provider_items=2, reserve_provider_items=0,
        )
        controller = AcquisitionController(directory / "controller", manifest_ref=manifest)
        execution_id = str(uuid.uuid4())
        config = freeze_config({
            "schema_version": 1,
            "execution_id": execution_id,
            "arm": "A",
            "question": "What adoption mechanism is supported?",
            "baseline_ref": context,
            "cutoff": "2026-11-04T12:10:00+00:00",
            "model_sha256": "a" * 64,
            "backend": "native_tools.web__run",
            "cohort": "fault",
            "cache_enabled": False,
            "cache_max_age_seconds": 0,
            "max_fallbacks": 1,
            "requirement_ids": ["adoption.v1:issuer"],
            "budget": {"search_items": 1, "open_items": 2,
                       "provider_items": 2, "wall_seconds": 600},
        })
        portal = HostWeb(
            directory / "host", config=config, cache_directory=directory / "cache",
            now=lambda: self.clock.isoformat(),
        )
        driver = AcquisitionDriver(
            directory / "driver", controller=controller, portal=portal,
            experiment_id="synthetic-recovery-v1", execution_id=execution_id,
            trace_id="trace-synthetic-recovery-v1",
        )
        return driver, controller, portal

    @staticmethod
    def proposal():
        return {
            "operation_id": "open-primary",
            "question_ids": ["adoption.v1:issuer"],
            "source_role": "issuer document",
            "reason": "Open the frozen issuer representation.",
            "arguments": {"open": [{"ref_id": PRIMARY}], "response_length": "long"},
            "alternates": [{
                "representation_kind": "html",
                "exact_arguments": {"open": [{"ref_id": ALTERNATE}], "response_length": "long"},
                "source_role": "issuer document",
                "required_capability": "official_document",
                "required_access_level": "public",
                "canonical_disclosure_id": "synthetic-disclosure-1",
                "relationship_to_primary": "semantically_equivalent_representation",
                "semantic_equivalence_rationale": "Synthetic fixture representations share one disclosure.",
                "permitted_trigger_codes": ["HOST_WEB_BODY_TOO_LARGE"],
                "budget_cost": 1,
            }],
        }

    def run_dispatch(self, driver, operation_id, arguments, raw, suffix):
        runner = HostedAcquisitionRunner(
            driver.directory.parent / f"runner-{suffix}",
            provider=lambda *_: HostedProviderResponse([raw.encode()]),
            configured_backend="synthetic_backend", run_deadline=100,
            raw_byte_limit=65536, monotonic=lambda: 1,
        )
        identities = read(driver._head())["identities"]
        dispatch_id = f"dispatch-{suffix}"
        runner.prepare(AcquisitionIdentity(
            RunIdentity(**identities),
            DispatchIdentity(operation_id, f"{operation_id}:1", dispatch_id),
        ), ExactArguments.from_mapping(arguments))
        runner.claim(dispatch_id)
        driver.record_invocation_started(operation_id)
        receipt = runner.invoke(dispatch_id, call_deadline=50)
        return runner, dispatch_id, receipt

    def test_pdf_to_html_pipeline_persists_handoffs_assessment_and_unit(self):
        driver, _, _ = self.stack()
        dispatch = driver.reserve(self.proposal())
        self.assertEqual(dispatch["arguments"]["open"][0]["ref_id"], PRIMARY)
        self.assertTrue(driver.prepare_host("open-primary")["dispatch"])
        primary_args = driver.claim_dispatch("open-primary")
        diagnostic = "Synthetic oversized provider representation diagnostic"
        primary_runner, primary_dispatch_id, primary_receipt = self.run_dispatch(
            driver, "open-primary", primary_args, diagnostic, "primary")
        failed = driver.capture_host("open-primary", {
            "actual_arguments": primary_args,
            "raw_result": diagnostic,
            "status": "returned",
            "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"},
        }, runner=primary_runner, dispatch_id=primary_dispatch_id,
            dispatch_ref=primary_receipt["dispatch_ref"])
        self.assertEqual((failed["status"], failed["code"]),
                         ("failed", "HOST_WEB_BODY_TOO_LARGE"))
        with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_CAPTURE_REPLAY"):
            driver.capture_host("open-primary", {
                "actual_arguments": primary_args,
                "raw_result": "duplicate",
                "status": "returned",
            }, runner=primary_runner, dispatch_id=primary_dispatch_id,
                dispatch_ref=primary_receipt["dispatch_ref"])
        committed = driver.commit_controller("open-primary")
        fallback = committed["next_dispatch"]
        self.assertIsNotNone(fallback)
        fallback_id = fallback["operation_id"]
        self.assertTrue(driver.prepare_host(fallback_id)["dispatch"])
        fallback_args = driver.claim_dispatch(fallback_id)
        raw = f"Synthetic source ({ALTERNATE})\nL0: {BODY}"
        fallback_runner, fallback_dispatch_id, fallback_receipt = self.run_dispatch(
            driver, fallback_id, fallback_args, raw, "fallback")
        opened = driver.capture_host(fallback_id, {
            "actual_arguments": fallback_args,
            "raw_result": raw,
            "status": "returned",
        }, runner=fallback_runner, dispatch_id=fallback_dispatch_id,
            dispatch_ref=fallback_receipt["dispatch_ref"])
        self.assertEqual(opened["status"], "returned")
        quote = "describing a customer adoption mechanism"
        driver.commit_controller(fallback_id, [{
            "question_id": "adoption.v1:issuer",
            "quote": quote,
            "disposition": "candidate_support",
        }])
        with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_NOT_TERMINAL"):
            driver.finish()
        assessments = driver.save_assessments(fallback_id, assessor_version="assessment_author_1")
        units = driver.attach_units(fallback_id)
        review_ref = driver.save_review(
            fallback_id, reviewer_id="reviewer_1", assessment_author_id="assessment_author_1",
            live_operator_id="operator_1", disposition="approve",
            checks={"question_relevance": True, "literal_support": True,
                    "canonical_lineage": True},
            reason="The question, literal quote, and canonical lineage agree.",
        )
        finished = driver.finish()
        final = finished["final"]
        self.assertEqual(read(finished["final_ref"]), final)

        self.assertEqual(len(assessments), 1)
        self.assertEqual(len(units), 1)
        self.assertEqual(final["review_refs"], [review_ref])
        assessment = read(assessments[0])
        unit = read(units[0])
        for value in (assessment, unit, final):
            self.assertEqual(value["execution_id"], final["execution_id"])
            self.assertEqual(value["experiment_id"], "synthetic-recovery-v1")
            self.assertEqual(value["trace_id"], "trace-synthetic-recovery-v1")
        self.assertEqual(unit["assessment_ref"], assessments[0])
        self.assertEqual(unit["status"], "candidate_support_not_semantic_admission")
        histories = final["operation_states"]
        self.assertEqual([row["state"] for row in histories["open-primary"]], [
            "reserved", "host_intent", "dispatch_claimed", "invocation_started", "captured",
            "controller_committed", "finalized",
        ])
        self.assertEqual([row["state"] for row in histories[fallback_id]], [
            "reserved", "host_intent", "dispatch_claimed", "invocation_started", "captured",
            "controller_committed", "assessment_saved", "unit_attached", "review_saved", "finalized",
        ])
        self.assertIn("not_live_quality", final["scope"])

    def test_known_capture_rejected_until_matching_runner_receipt_exists(self):
        driver, _, _ = self.stack("capture-evidence")
        driver.reserve(self.proposal())
        driver.prepare_host("open-primary")
        arguments = driver.claim_dispatch("open-primary")
        runner = HostedAcquisitionRunner(
            driver.directory.parent / "runner-uninvoked", provider=lambda *_: self.fail("called"),
            configured_backend="synthetic_backend", run_deadline=100,
            raw_byte_limit=1024, monotonic=lambda: 1,
        )
        identities = read(driver._head())["identities"]
        runner.prepare(AcquisitionIdentity(
            RunIdentity(**identities),
            DispatchIdentity("open-primary", "open-primary:1", "dispatch-uninvoked"),
        ), ExactArguments.from_mapping(arguments))
        runner.claim("dispatch-uninvoked")
        with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_CAPTURE_REPLAY"):
            driver.capture_host("open-primary", {
                "actual_arguments": arguments, "raw_result": "forged", "status": "returned",
            }, runner=runner, dispatch_id="dispatch-uninvoked", dispatch_ref=None)

    def test_unknown_outcome_is_committed_once_and_never_replayed(self):
        driver, _, _ = self.stack("unknown")
        proposal = {**self.proposal(), "alternates": [],
                    "arguments": {"open": [{"ref_id": ALTERNATE}]}}
        driver.reserve(proposal)
        driver.prepare_host("open-primary")
        arguments = driver.claim_dispatch("open-primary")
        runner = HostedAcquisitionRunner(
            driver.directory.parent / "runner-unknown",
            provider=lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic")),
            configured_backend="synthetic_backend", run_deadline=100,
            raw_byte_limit=1024, monotonic=lambda: 1,
        )
        identities = read(driver._head())["identities"]
        dispatch_id = "dispatch-unknown"
        runner.prepare(AcquisitionIdentity(
            RunIdentity(**identities),
            DispatchIdentity("open-primary", "open-primary:1", dispatch_id),
        ), ExactArguments.from_mapping(arguments))
        runner.claim(dispatch_id)
        driver.record_invocation_started("open-primary")
        with self.assertRaises(RunnerError):
            runner.invoke(dispatch_id, call_deadline=50)
        driver.record_possibly_dispatched("open-primary")
        result = driver.capture_host("open-primary", {
            "actual_arguments": arguments,
            "raw_result": "Synthetic unknown provider outcome",
            "status": "unknown",
            "code": "HOST_WEB_RESULT_UNKNOWN",
        }, runner=runner, dispatch_id=dispatch_id)
        self.assertEqual(result["status"], "unknown")
        driver.commit_controller("open-primary")
        with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_CAPTURE_REPLAY"):
            driver.capture_host("open-primary", {
                "actual_arguments": arguments,
                "raw_result": "retry",
                "status": "returned",
            }, runner=runner, dispatch_id=dispatch_id)
        final = driver.finish()["final"]
        states = [row["state"] for row in final["operation_states"]["open-primary"]]
        self.assertEqual(states, ["reserved", "host_intent", "dispatch_claimed",
                                  "invocation_started", "possibly_dispatched", "unknown",
                                  "controller_committed", "finalized"])
        self.assertEqual(final["unit_refs"], [])

    def test_controller_reservation_can_be_recovered_after_driver_write_gap(self):
        driver, controller, _ = self.stack("resume")
        proposal = self.proposal()
        first = controller.prepare(proposal)
        recovered = driver.reserve(proposal)
        self.assertEqual(recovered, first)
        self.assertEqual(driver.reserve(proposal), first)

    def test_dispatch_ambiguity_is_fenced_until_authoritative_negative_evidence(self):
        for boundary in ("dispatch_claimed", "invocation_started"):
            with self.subTest(boundary=boundary):
                driver, _, _ = self.stack("fence-" + boundary)
                driver.reserve(self.proposal())
                driver.prepare_host("open-primary")
                expected = driver.claim_dispatch("open-primary")
                if boundary == "invocation_started":
                    driver.record_invocation_started("open-primary")
                with self.assertRaisesRegex(SourceError, "ACQ_DRIVER_RECONCILE_REQUIRED"):
                    driver.claim_dispatch("open-primary")
                if boundary == "dispatch_claimed":
                    identities = read(driver._head())["identities"]
                    runner = HostedAcquisitionRunner(
                        driver.directory.parent / "runner",
                        provider=lambda *_: self.fail("reconciliation invoked provider"),
                        configured_backend="synthetic_backend", run_deadline=100,
                        raw_byte_limit=1024, monotonic=lambda: 1,
                    )
                    identity = AcquisitionIdentity(
                        RunIdentity(**identities),
                        DispatchIdentity("open-primary", "open-primary:1", "dispatch-primary"),
                    )
                    runner.prepare(identity, ExactArguments.from_mapping(expected))
                    runner.claim("dispatch-primary")
                    with self.assertRaisesRegex(RunnerError, "NEGATIVE_EVIDENCE_UNTRUSTED"):
                        runner.record_definitely_not_dispatched(
                            "dispatch-primary", evidence_sha256="a" * 64)
                    runner.run_deadline = 0
                    with self.assertRaisesRegex(RunnerError, "DEADLINE_BEFORE_DISPATCH"):
                        runner.invoke("dispatch-primary", call_deadline=50)
                    evidence = driver.import_definitely_not_dispatched(
                        "open-primary", runner=runner, dispatch_id="dispatch-primary")
                    self.assertEqual(read(evidence)["operation_id"], "open-primary")
                    self.assertEqual(driver.claim_dispatch("open-primary"), expected)

    def test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free(self):
        driver, controller, portal = self.stack("repair")
        proposal = self.proposal()
        dispatch = controller.prepare(proposal)
        for attempt in range(2):
            with self.subTest(edge="controller_reservation", attempt=attempt):
                self.assertEqual(driver.import_controller_reservation(proposal), dispatch)

        prepared = portal.prepare(
            "open-primary", dispatch["arguments"],
            requirement_ids=dispatch["requirement_ids"],
        )
        for attempt in range(2):
            with self.subTest(edge="host_intent", attempt=attempt):
                self.assertEqual(driver.import_host_intent(
                    "open-primary", prepared["intent_ref"]), prepared["intent_ref"])

        arguments = driver.claim_dispatch("open-primary")
        raw = f"Synthetic source ({PRIMARY})\nL0: {BODY}"
        repair_runner, repair_dispatch_id, repair_receipt = self.run_dispatch(
            driver, "open-primary", arguments, raw, "repair")
        host_result = portal.capture("open-primary", {
            "actual_arguments": arguments,
            "raw_result": raw,
            "status": "returned",
        })
        for attempt in range(2):
            with self.subTest(edge="host_capture", attempt=attempt):
                imported_host = driver.import_host_capture(
                    "open-primary", host_result["operation_ref"],
                    runner=repair_runner, dispatch_id=repair_dispatch_id,
                    dispatch_ref=repair_receipt["dispatch_ref"])
                self.assertEqual(imported_host["operation_ref"], host_result["operation_ref"])

        assessment_rows = [{
            "question_id": "adoption.v1:issuer",
            "quote": "customer adoption mechanism",
            "disposition": "candidate_support",
        }]
        controller_result = controller.capture("open-primary", {
            "status": imported_host["status"],
            "code": imported_host["code"],
            "packet": imported_host["packet"],
            "assessments": assessment_rows,
        })
        for attempt in range(2):
            with self.subTest(edge="controller_capture", attempt=attempt):
                imported_controller = driver.import_controller_capture(
                    "open-primary", controller_result["decision_ref"], assessment_rows)
                self.assertEqual(imported_controller["decision_ref"],
                                 controller_result["decision_ref"])

        def interrupted_write(call, kind):
            before = set(driver.directory.glob("*.json"))
            original = driver._write
            driver._write = lambda state: (_ for _ in ()).throw(OSError("synthetic write gap"))
            try:
                with self.assertRaisesRegex(OSError, "synthetic write gap"):
                    call()
            finally:
                driver._write = original
            refs = []
            for path in set(driver.directory.glob("*.json")) - before:
                ref = {"path": str(path), "sha256": path.stem}
                try:
                    if read(ref).get("kind") == kind:
                        refs.append(ref)
                except (SourceError, AttributeError):
                    pass
            self.assertTrue(refs, kind)
            return sorted(refs, key=lambda ref: ref["sha256"])

        assessment_refs = interrupted_write(
            lambda: driver.save_assessments("open-primary", assessor_version="assessment_author_1"),
            "acquisition_quote_assessment",
        )
        unit_refs = None
        review_refs = None
        for edge, refs, importer in [
            ("assessment_write", assessment_refs,
             lambda values: driver.import_assessments("open-primary", values)),
        ]:
            for attempt in range(2):
                with self.subTest(edge=edge, attempt=attempt):
                    self.assertEqual(importer(refs), refs)

        unit_refs = interrupted_write(
            lambda: driver.attach_units("open-primary"), "acquisition_candidate_unit")
        for attempt in range(2):
            with self.subTest(edge="unit_write", attempt=attempt):
                self.assertEqual(driver.import_units("open-primary", unit_refs), unit_refs)

        review_refs = interrupted_write(
            lambda: driver.save_review(
                "open-primary", reviewer_id="reviewer_1",
                assessment_author_id="assessment_author_1", live_operator_id="operator_1",
                disposition="approve",
                checks={"question_relevance": True, "literal_support": True,
                        "canonical_lineage": True},
                reason="The question, literal quote, and canonical lineage agree.",
            ),
            "acquisition_reviewer_decision",
        )
        for attempt in range(2):
            with self.subTest(edge="review_write", attempt=attempt):
                self.assertEqual(driver.import_reviews("open-primary", review_refs), review_refs)

        final_refs = interrupted_write(driver.finish, "acquisition_driver_run")
        first = driver.reconcile_finalization()
        second = driver.reconcile_finalization()
        self.assertIn(first["final_ref"], final_refs)
        self.assertEqual(first, second)
        self.assertEqual(len(first["final"]["assessment_refs"]), 1)
        self.assertEqual(len(first["final"]["unit_refs"]), 1)
        self.assertEqual(len(first["final"]["review_refs"]), 1)


if __name__ == "__main__":
    unittest.main()
