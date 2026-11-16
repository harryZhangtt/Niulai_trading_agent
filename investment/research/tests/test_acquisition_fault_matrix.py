"""Executable Stage 0B coverage roster and focused missing fault injections.

The matrix is machine-readable by importing ``FAULT_MATRIX``.  ``verified`` rows
name executable evidence; ``blocked`` rows remain explicit and cannot be counted as
passes.  No provider or network route is used.
"""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from investment.research.acquisition_runner import (
    HostedAcquisitionRunner,
    HostedProviderResponse,
    RunnerError,
)
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    ExactArguments,
    RunIdentity,
)
from shared.research_sources.artifacts import SOURCE_STATE, read, save
from shared.research_sources.host_web import HostWeb


ROOT = Path(__file__).resolve().parents[3]
OUTCOMES = {"resumable", "terminal_blocked", "reconcile_required"}


def row(boundary, outcome, evidence, *, status="verified", limitation=None):
    return {
        "injection_boundary": boundary,
        "expected_outcome": outcome,
        "evidence": evidence,
        "status": status,
        "limitation": limitation,
    }


FAULT_MATRIX = (
    row("Before controller reservation", "terminal_blocked", [
        "investment.research.tests.test_acquisition_orchestration:AcquisitionOrchestrationTests.test_shared_preflight_rejects_incompatible_capability_and_host_url"]),
    row("Controller committed before driver write", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_controller_reservation_can_be_recovered_after_driver_write_gap",
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Host intent committed before driver write", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Claim persisted before invocation", "reconcile_required", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_claimed_restart_is_fenced_until_authoritative_not_dispatched_evidence",
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_dispatch_ambiguity_is_fenced_until_authoritative_negative_evidence"]),
    row("Invocation started, callback lost", "reconcile_required", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_restart_recovers_invocation_started_to_unknown_and_cleans_orphans",
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_unknown_outcome_is_committed_once_and_never_replayed"]),
    row("Provider returned before raw journal persistence", "reconcile_required", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_restart_recovers_invocation_started_to_unknown_and_cleans_orphans",
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_captured_journal_receipt_gap_is_recoverable_without_redispatch"]),
    row("HostWeb capture committed before driver update", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Controller capture committed before driver update", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Assessment save interrupted", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Unit attachment interrupted", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Reviewer save interrupted", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Finalization interrupted", "resumable", [
        "investment.research.tests.test_acquisition_driver:AcquisitionDriverTests.test_table_driven_committed_side_effect_repair_is_idempotent_and_provider_free"]),
    row("Disk full / permission / rename / fsync failure", "reconcile_required", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_atomic_journal_replace_failure_preserves_prior_state"]),
    row("Deadline before invocation", "resumable", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_deadline_before_invocation_proves_zero_dispatches",
        "shared.research_sources.tests.test_host_web:HostWebTests.test_deadline_before_dispatch_has_distinct_closed_code_and_zero_accounting"]),
    row("Deadline after invocation may have begun", "reconcile_required", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_noncooperative_provider_is_bounded_and_fenced_without_worker"]),
    row("401/403/404 policy result", "terminal_blocked", [
        "investment.research.tests.test_acquisition_orchestration:AcquisitionOrchestrationTests.test_non_representation_failures_never_fallback",
        "shared.research_sources.tests.test_host_web:HostWebTests.test_policy_failure_forbids_fallback_and_representation_failure_allows_sealed_alternate"]),
    row("429/503", "terminal_blocked", [
        "investment.research.tests.test_acquisition_orchestration:AcquisitionOrchestrationTests.test_non_representation_failures_never_fallback"]),
    row("Explicit oversized PDF", "resumable", [
        "investment.research.tests.test_acquisition_synthetic_e2e:AcquisitionSyntheticE2ETests.test_search_pdf_html_review_checker_and_projection"]),
    row("Malformed/truncated/invalid-UTF provider result", "terminal_blocked", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_invalid_utf8_is_typed_failure_without_exposure"]),
    row("Provider schema drift", "reconcile_required", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_provider_schema_drift_fences_unknown"]),
    row("Raw result above bound", "terminal_blocked", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_raw_bound_is_hard_and_temporary_file_and_iterator_are_cleaned"]),
    row("Redirect/canonical mismatch", "terminal_blocked", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_document_url_mismatch_gets_no_credit"]),
    row("URL/body mismatch", "terminal_blocked", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_document_url_mismatch_gets_no_credit"]),
    row("Future or unknown eligibility timestamp", "terminal_blocked", [
        "shared.research_sources.tests.test_host_web:HostWebTests.test_future_publication_and_late_response_never_exposed"]),
    row("Source/code pin drift", "terminal_blocked", [
        "shared.research_sources.tests.test_host_web:HostWebTests.test_frozen_code_file_change_during_pending_archives_raw_without_exposure_and_blocks_cache"]),
    row("Quote absent from screened text", "terminal_blocked", [
        "investment.research.tests.test_acquisition_orchestration:AcquisitionOrchestrationTests.test_successful_fallback_requires_literal_quote_and_remains_provisional"]),
    row("Same arguments under different operation ID", "terminal_blocked", [
        "investment.research.tests.test_acquisition_orchestration:AcquisitionOrchestrationTests.test_pdf_requires_declared_alternate_and_duplicate_is_rejected"]),
    row("Concurrent runner / stale lock", "reconcile_required", [
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_concurrent_runner_lock_returns_bounded_busy"]),
    row("Cancellation / timeout", "reconcile_required", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_deadline_during_stream_closes_iterator_and_never_exposes_raw",
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_noncooperative_provider_is_bounded_and_fenced_without_worker"]),
    row("Observer/cache publication failure", "resumable", [
        "shared.research_sources.tests.test_host_web:HostWebTests.test_ephemeral_refs_secrets_budget_and_observer_failure_are_contained",
        "investment.research.tests.test_acquisition_fault_matrix:AcquisitionFaultMatrixTests.test_cache_publication_failure_preserves_capture"]),
    row("Prompt-injection/HTML/script canary", "terminal_blocked", [
        "js:ui/datasource/tests/scheduler.spec.mjs::stored message preview cannot execute scripts, navigate parent or load remote content",
        "js:ui/datasource/tests/acquisition-trace.spec.mjs::checker-approved trace is keyboard-readable, inert, and overflow-safe"]),
    row("Secret/private-path canary", "terminal_blocked", [
        "investment.research.tests.test_acquisition_runner:AcquisitionRunnerTests.test_provider_exception_is_sanitized_and_fenced_as_possible_dispatch",
        "js:ui/datasource/tests/acquisition-trace.spec.mjs::client boundary rejects a trace that is not checker-approved"]),
    row("Finalized replay", "terminal_blocked", [
        "investment.research.tests.test_acquisition_synthetic_e2e:AcquisitionSyntheticE2ETests.test_search_pdf_html_review_checker_and_projection"]),
)


class SyntheticProvider:
    def __init__(self, response=None):
        self.calls = []
        self.response = response if response is not None else HostedProviderResponse([b"synthetic"])

    def __call__(self, arguments, deadline):
        self.calls.append((arguments, deadline))
        return self.response


class AcquisitionFaultMatrixTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)

    @staticmethod
    def identity(dispatch_id="dispatch-fault"):
        return AcquisitionIdentity(
            RunIdentity("experiment-fault", "execution-fault", "trace-fault"),
            DispatchIdentity("operation-fault", "attempt-fault", dispatch_id),
        )

    @staticmethod
    def arguments(url="https://example.com/report.html"):
        return ExactArguments.from_mapping({
            "open": [{"ref_id": url}], "response_length": "long",
        })

    def runner(self, provider, name="runner"):
        return HostedAcquisitionRunner(
            self.root / name, provider=provider,
            configured_backend="synthetic.backend", run_deadline=200,
            raw_byte_limit=65536, monotonic=lambda: 100,
        )

    def portal(self, name="host", *, cache_enabled=False):
        baseline = save(self.root, {"kind": "synthetic-baseline"})
        config = {
            "schema_version": 1, "execution_id": str(uuid.uuid4()), "arm": "A",
            "question": "What is supported?", "baseline_ref": baseline,
            "cutoff": "2026-11-05T12:10:00+00:00", "model_sha256": "a" * 64,
            "backend": "native_tools.web__run", "cohort": "fault",
            "cache_enabled": cache_enabled, "cache_max_age_seconds": 3600,
            "max_fallbacks": 1, "requirement_ids": ["question-1"],
            "budget": {"search_items": 1, "open_items": 2,
                       "provider_items": 2, "wall_seconds": 600},
        }
        return HostWeb(self.root / name, config=config,
                       cache_directory=self.root / (name + "-cache"),
                       now=lambda: self.now.isoformat())

    def test_matrix_rows_are_unique_machine_readable_and_evidence_resolves(self):
        plan_rows = {
            "Before controller reservation", "Controller committed before driver write",
            "Host intent committed before driver write", "Claim persisted before invocation",
            "Invocation started, callback lost", "Provider returned before raw journal persistence",
            "HostWeb capture committed before driver update", "Controller capture committed before driver update",
            "Assessment save interrupted", "Unit attachment interrupted", "Reviewer save interrupted",
            "Finalization interrupted", "Disk full / permission / rename / fsync failure",
            "Deadline before invocation", "Deadline after invocation may have begun",
            "401/403/404 policy result", "429/503", "Explicit oversized PDF",
            "Malformed/truncated/invalid-UTF provider result", "Provider schema drift",
            "Raw result above bound", "Redirect/canonical mismatch", "URL/body mismatch",
            "Future or unknown eligibility timestamp", "Source/code pin drift",
            "Quote absent from screened text", "Same arguments under different operation ID",
            "Concurrent runner / stale lock", "Cancellation / timeout",
            "Observer/cache publication failure", "Prompt-injection/HTML/script canary",
            "Secret/private-path canary", "Finalized replay",
        }
        self.assertEqual({item["injection_boundary"] for item in FAULT_MATRIX}, plan_rows)
        self.assertEqual(len(FAULT_MATRIX), len(plan_rows))
        self.assertFalse([item for item in FAULT_MATRIX if item["status"] != "verified"])
        for item in FAULT_MATRIX:
            with self.subTest(boundary=item["injection_boundary"]):
                self.assertIn(item["expected_outcome"], OUTCOMES)
                self.assertIn(item["status"], {"verified", "blocked"})
                if item["status"] == "blocked":
                    self.assertFalse(item["evidence"])
                    self.assertTrue(item["limitation"])
                    continue
                self.assertTrue(item["evidence"])
                for reference in item["evidence"]:
                    if reference.startswith("js:"):
                        path, title = reference[3:].split("::", 1)
                        self.assertIn(title, (ROOT / path).read_text())
                        continue
                    module_name, symbol = reference.split(":", 1)
                    owner_name, method_name = symbol.split(".", 1)
                    owner = getattr(importlib.import_module(module_name), owner_name)
                    self.assertTrue(callable(getattr(owner, method_name)))

    def test_atomic_journal_replace_failure_preserves_prior_state(self):
        provider = SyntheticProvider()
        runner = self.runner(provider, "atomic")
        dispatch_id = "dispatch-atomic"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        journal = runner._journal_path(dispatch_id)
        before = journal.read_bytes()
        with patch("investment.research.acquisition_runner.os.replace", side_effect=OSError("synthetic rename failure")):
            with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_JOURNAL_WRITE_FAILED"):
                runner.claim(dispatch_id)
        self.assertEqual(journal.read_bytes(), before)
        self.assertEqual(runner.journal(dispatch_id)[-1]["state"], "prepared")
        self.assertFalse(any(path.name.startswith(".dispatch-") for path in runner.directory.iterdir()))
        self.assertEqual(provider.calls, [])

    def test_concurrent_runner_lock_returns_bounded_busy(self):
        provider = SyntheticProvider()
        runner = self.runner(provider, "busy")
        dispatch_id = "dispatch-busy"
        with runner._lock(dispatch_id):
            with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_BUSY"):
                runner.prepare(self.identity(dispatch_id), self.arguments())
        self.assertEqual(provider.calls, [])

    def test_provider_schema_drift_fences_unknown(self):
        provider = SyntheticProvider(response={"unexpected": "shape"})
        runner = self.runner(provider, "schema")
        dispatch_id = "dispatch-schema"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_PROVIDER_OUTCOME_UNKNOWN"):
            runner.invoke(dispatch_id, call_deadline=150)
        self.assertEqual(runner.journal(dispatch_id)[-1]["state"], "possibly_dispatched")
        self.assertEqual(len(provider.calls), 1)

    def test_invalid_utf8_is_typed_failure_without_exposure(self):
        provider = SyntheticProvider(HostedProviderResponse([b"valid prefix ", b"\xfftruncated"]))
        runner = self.runner(provider, "invalid-utf8")
        dispatch_id = "dispatch-invalid-utf8"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        receipt = runner.invoke(dispatch_id, call_deadline=150)
        self.assertEqual((receipt["status"], receipt["code"]),
                         ("failed", "HOST_WEB_BODY_UNPARSEABLE"))
        self.assertNotIn("raw_ref", receipt)
        self.assertEqual(list(runner.raw_directory.iterdir()), [])
        self.assertEqual(len(provider.calls), 1)

    def test_document_url_mismatch_gets_no_credit(self):
        portal = self.portal()
        expected = "https://example.com/report.html"
        actual = "https://example.com/redirected.html"
        arguments = {"open": [{"ref_id": expected}], "response_length": "long"}
        portal.prepare("open-mismatch", arguments, requirement_ids=["question-1"])
        raw = f"Synthetic source ({expected}) ({actual})\nL0: " + "x" * 100
        result = portal.capture("open-mismatch", {
            "actual_arguments": arguments, "raw_result": raw, "status": "returned",
            "documents": [{"url": actual, "text": "x" * 100}],
        })
        self.assertEqual((result["status"], result["code"]),
                         ("failed", "HOST_WEB_BODY_UNPARSEABLE"))
        self.assertEqual(result["source_refs"], [])
        self.assertEqual(result["packet"], {})

    def test_cache_publication_failure_preserves_capture(self):
        portal = self.portal("cache-failure", cache_enabled=True)
        url = "https://example.com/report.html"
        arguments = {"open": [{"ref_id": url}], "response_length": "long"}
        portal.prepare("open-cache", arguments, requirement_ids=["question-1"])
        body = "x" * 100
        raw = f"Synthetic source ({url})\nL0: {body}"
        with patch("shared.research_sources.host_web.Store.cache_publish", side_effect=OSError("synthetic cache failure")):
            result = portal.capture("open-cache", {
                "actual_arguments": arguments, "raw_result": raw, "status": "returned",
                "documents": [{"url": url, "text": body}],
            })
        self.assertEqual(result["status"], "returned")
        receipt = read(result["operation_ref"])
        self.assertEqual(receipt["status"], "success")
        attempts = [read(ref) for ref in read(portal._head())["cache_attempt_refs"]]
        self.assertTrue(any(row["reasons"] == ["HOST_WEB_CACHE_PUBLICATION_UNAVAILABLE"]
                            and row["fetch_executed"] for row in attempts))


if __name__ == "__main__":
    unittest.main()
