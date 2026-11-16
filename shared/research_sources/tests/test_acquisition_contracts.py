import dataclasses
import unittest

from shared.research_sources.acquisition_contracts import (
    CONTRACT_VERSION,
    TAXONOMY_VERSION,
    AcquisitionIdentity,
    AlternateDescriptor,
    AlternateRelationship,
    ContractError,
    CrossLedgerVerdict,
    DispatchEvent,
    DispatchIdentity,
    DispatchState,
    EffectiveConfigInputs,
    ExactArguments,
    FailureClass,
    FailureCode,
    FallbackEligibility,
    GateDisposition,
    LedgerGate,
    RepresentationKind,
    ReviewerDecision,
    ReviewerDisposition,
    RunIdentity,
    append_dispatch_event,
    classify_failure,
    fallback_allowed,
    validate_dispatch_history,
)


_SHA = "a" * 64


class AcquisitionContractTests(unittest.TestCase):
    def run_identity(self):
        return RunIdentity("experiment-1", "execution-1", "trace-1")

    def test_all_failure_classes_are_closed_and_fallback_is_narrow(self):
        classifications = {classify_failure(code).failure_class for code in FailureCode}
        self.assertEqual(classifications, set(FailureClass))
        oversized = classify_failure("HOST_WEB_BODY_TOO_LARGE")
        self.assertEqual(oversized.taxonomy_version, TAXONOMY_VERSION)
        self.assertEqual(oversized.fallback, FallbackEligibility.SEALED_ALTERNATE)
        self.assertTrue(fallback_allowed(FailureCode.HOST_WEB_SOURCE_INACCESSIBLE))
        self.assertFalse(fallback_allowed(FailureCode.HOST_WEB_BODY_UNPARSEABLE))
        self.assertTrue(fallback_allowed(
            FailureCode.HOST_WEB_BODY_UNPARSEABLE, unparseable_predeclared=True))
        for code in (FailureCode.SOURCE_HTTP_403, FailureCode.SOURCE_HTTP_429,
                     FailureCode.NATIVE_TRANSPORT_FAILED, FailureCode.HOST_WEB_DEADLINE,
                     FailureCode.HOST_WEB_RESULT_UNKNOWN):
            with self.subTest(code=code):
                self.assertFalse(fallback_allowed(code))
        with self.assertRaisesRegex(ContractError, "ACQ_FAILURE_CODE_UNKNOWN"):
            classify_failure("invented_by_body_text")

    def test_exact_arguments_and_alternate_are_deeply_frozen(self):
        original = {"open": [{"ref_id": "https://example.com/disclosure.html"}],
                    "response_length": "long"}
        exact = ExactArguments.from_mapping(original)
        original["open"][0]["ref_id"] = "https://example.com/mutated"
        self.assertEqual(exact.to_dict()["open"][0]["ref_id"],
                         "https://example.com/disclosure.html")
        descriptor = AlternateDescriptor(
            RepresentationKind.HTML,
            exact,
            "issuer_document",
            "official_document",
            "public",
            "disclosure-1",
            AlternateRelationship.SEMANTICALLY_EQUIVALENT_REPRESENTATION,
            "Publisher-controlled HTML rendering of the same dated release.",
            frozenset({FailureCode.HOST_WEB_BODY_TOO_LARGE,
                       FailureCode.HOST_WEB_SOURCE_INACCESSIBLE}),
            1,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            descriptor.budget_cost = 2
        with self.assertRaisesRegex(ContractError, "ACQ_ALTERNATE_TRIGGER_CODES"):
            dataclasses.replace(
                descriptor,
                permitted_trigger_codes=frozenset({FailureCode.SOURCE_HTTP_404}),
            )
        with self.assertRaisesRegex(ContractError, "ACQ_EXACT_ARGUMENTS"):
            ExactArguments(b'{"response_length": "long"}')

    def test_identities_are_typed_frozen_and_closed(self):
        identity = AcquisitionIdentity(
            self.run_identity(), DispatchIdentity("operation-1", "attempt-1", "dispatch-1"))
        self.assertEqual(identity.dispatch.dispatch_id, "dispatch-1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            identity.run = self.run_identity()
        with self.assertRaisesRegex(ContractError, "ACQ_CONTRACT_DISPATCH_ID"):
            DispatchIdentity("bad id", "attempt-1", "dispatch-1")

    def test_dispatch_history_requires_legal_append_only_transitions_and_evidence(self):
        history = (DispatchEvent("dispatch-1", 0, DispatchState.PREPARED),)
        history = append_dispatch_event(history, DispatchState.CLAIMED)
        with self.assertRaisesRegex(ContractError, "ACQ_DISPATCH_EVIDENCE_REQUIRED"):
            append_dispatch_event(history, DispatchState.DEFINITELY_NOT_DISPATCHED)
        history = append_dispatch_event(
            history, DispatchState.DEFINITELY_NOT_DISPATCHED, evidence_sha256=_SHA)
        history = append_dispatch_event(history, DispatchState.CLAIMED)
        history = append_dispatch_event(history, DispatchState.INVOCATION_STARTED)
        history = append_dispatch_event(history, DispatchState.POSSIBLY_DISPATCHED)
        with self.assertRaisesRegex(ContractError, "ACQ_DISPATCH_EVIDENCE_REQUIRED"):
            append_dispatch_event(history, DispatchState.CAPTURED)
        history = append_dispatch_event(history, DispatchState.CAPTURED, evidence_sha256=_SHA)
        self.assertEqual(validate_dispatch_history(history), history)
        with self.assertRaisesRegex(ContractError, "ACQ_DISPATCH_TRANSITION"):
            append_dispatch_event(history, DispatchState.CLAIMED)
        with self.assertRaisesRegex(ContractError, "ACQ_DISPATCH_HISTORY_APPEND_ONLY"):
            validate_dispatch_history((history[0], DispatchEvent(
                "dispatch-2", 1, DispatchState.CLAIMED)))

    def test_reviewer_must_be_independent_and_hash_bound(self):
        decision = ReviewerDecision(
            self.run_identity(), "assessment-1", "unit-1", "reviewer-1",
            "assessor-1", "operator-1", _SHA, _SHA, _SHA,
            ReviewerDisposition.APPROVE, ("literal_support", "canonical_lineage"),
        )
        self.assertEqual(decision.disposition, ReviewerDisposition.APPROVE)
        with self.assertRaisesRegex(ContractError, "ACQ_REVIEWER_NOT_INDEPENDENT"):
            dataclasses.replace(decision, reviewer_id="operator-1")
        with self.assertRaisesRegex(ContractError, "ACQ_REVIEW_HASH"):
            dataclasses.replace(decision, unit_sha256="not-a-hash")

    def test_cross_ledger_verdict_cannot_claim_a_conflicting_pass(self):
        gate = LedgerGate("dispatch_cardinality", GateDisposition.PASS, "exact_count")
        verdict = CrossLedgerVerdict(
            self.run_identity(), GateDisposition.PASS, (gate,), 3, 3, 3, 1, 1)
        self.assertEqual(verdict.actual_dispatches, 3)
        with self.assertRaisesRegex(ContractError, "ACQ_LEDGER_PASS_CONFLICT"):
            CrossLedgerVerdict(
                self.run_identity(), GateDisposition.PASS,
                (LedgerGate("dispatch_cardinality", GateDisposition.FAIL, "duplicate"),),
                3, 3, 4, 0, 0,
            )
        with self.assertRaisesRegex(ContractError, "ACQ_LEDGER_CREDIT_CONFLICT"):
            dataclasses.replace(verdict, complete_chains=0)
        inconclusive = CrossLedgerVerdict(
            self.run_identity(), GateDisposition.INCONCLUSIVE,
            (LedgerGate("recovery_opportunity", GateDisposition.INCONCLUSIVE,
                        "pdf_succeeded"),),
            2, 2, 2, 0, 0,
        )
        self.assertEqual(inconclusive.disposition, GateDisposition.INCONCLUSIVE)

    def test_effective_config_requires_every_explicit_hash_input(self):
        values = {field.name: _SHA for field in dataclasses.fields(EffectiveConfigInputs)
                  if field.name != "contract_version"}
        envelope = EffectiveConfigInputs(**values)
        self.assertEqual(envelope.contract_version, CONTRACT_VERSION)
        with self.assertRaisesRegex(ContractError, "ACQ_EFFECTIVE_CONFIG_INPUT"):
            EffectiveConfigInputs(**{**values, "checker_sha256": "missing"})
        with self.assertRaisesRegex(ContractError, "ACQ_EFFECTIVE_CONFIG_VERSION"):
            dataclasses.replace(envelope, contract_version="acquisition-contracts-2")


if __name__ == "__main__":
    unittest.main()
