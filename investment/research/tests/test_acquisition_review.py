from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from investment.research.acquisition_review import (
    record_reviewer_decision, review_payload_sha256, verify_reviewer_decision,
)
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, SourceError, read, save
from shared.research_sources.host_adapter_contracts import (
    AdapterId, NON_CRYPTO_LIMITATION, OperationalEvidenceSource,
    OperationalTrustPolicy, ReviewerSessionReceipt,
)


class AcquisitionReviewTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        text = "Synthetic issuer evidence states that customer adoption expanded in the bounded period."
        raw = save(self.root, {"raw": "synthetic"})
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
            "kind": "acquisition_quote_assessment",
            "experiment_id": "experiment-1",
            "execution_id": "execution-1",
            "trace_id": "trace-1",
            "operation_id": "open-html",
            "attempt_id": "open-html:1",
            "question_id": "adoption.v1:issuer",
            "source_ref": self.source_ref,
            "source_version": raw["sha256"],
            "raw_sha256": raw["sha256"],
            "text_sha256": text_ref["sha256"],
            "quote": "customer adoption expanded",
            "assessment_author_id": "assessment-author",
            "operator_id": "live-operator",
        })
        self.unit_ref = save(self.root, {
            "kind": "acquisition_candidate_unit",
            "experiment_id": "experiment-1",
            "execution_id": "execution-1",
            "trace_id": "trace-1",
            "unit_id": "unit-1",
            "question_id": "adoption.v1:issuer",
            "assessment_ref": self.assessment_ref,
            "source_ref": self.source_ref,
            "quote": "customer adoption expanded",
        })

    def decision(self, **updates):
        values = {
            "assessment_ref": self.assessment_ref,
            "unit_ref": self.unit_ref,
            "reviewer_id": "independent-reviewer",
            "assessment_author_id": "assessment-author",
            "operator_id": "live-operator",
            "disposition": "approve",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True},
            "reason": "The literal quote answers the bounded question and retains canonical lineage.",
        }
        values.update(updates)
        return record_reviewer_decision(self.root, **values)

    def test_records_hash_bound_independent_decision(self):
        first = self.decision()
        second = self.decision()
        self.assertEqual(first, second)
        decision = verify_reviewer_decision(first)
        self.assertEqual(decision, read(first))
        self.assertEqual(decision["binding"]["assessment_ref"], self.assessment_ref)
        self.assertEqual(decision["binding"]["unit_ref"], self.unit_ref)
        self.assertIn("not_investment_importance", decision["scope"])

    def test_rejects_reviewer_who_authored_or_operated(self):
        with self.assertRaisesRegex(SourceError, "ACQ_REVIEW_INDEPENDENCE_REQUIRED"):
            self.decision(reviewer_id="assessment-author")
        with self.assertRaisesRegex(SourceError, "ACQ_REVIEW_INDEPENDENCE_REQUIRED"):
            self.decision(reviewer_id="live-operator")

    def test_approval_requires_all_checks(self):
        with self.assertRaisesRegex(SourceError, "ACQ_REVIEW_APPROVAL_CHECKS"):
            self.decision(checks={"question_relevance": True, "literal_support": False,
                                  "canonical_lineage": True})
        rejected = self.decision(
            disposition="reject",
            checks={"question_relevance": True, "literal_support": False,
                    "canonical_lineage": True},
        )
        self.assertEqual(read(rejected)["disposition"], "reject")

    def test_operational_review_requires_bound_distinct_reviewer_session(self):
        checks = {"question_relevance": True, "literal_support": True,
                  "canonical_lineage": True}
        reason = "The literal quote answers the bounded question and retains canonical lineage."
        payload_hash = review_payload_sha256(
            assessment_ref=self.assessment_ref, unit_ref=self.unit_ref,
            reviewer_id="independent-reviewer",
            assessment_author_id="assessment-author", operator_id="live-operator",
            disposition="approve", checks=checks, reason=reason)
        receipt = ReviewerSessionReceipt(
            adapter_id=AdapterId.CLAUDE_CODE_WEB,
            host_session_id="claude-review-session",
            principal_ref="independent-reviewer",
            review_artifact_sha256=payload_hash,
            checked_at="2026-11-05T01:02:00+00:00",
            source=OperationalEvidenceSource.HOST_RETURNED,
            trust_policy=OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE,
            limitations=(NON_CRYPTO_LIMITATION,),
        ).to_public_dict()
        receipt_path = self.root / "reviewer-receipt.json"
        receipt_path.write_text(json.dumps(receipt))
        receipt_ref = {"path": str(receipt_path.relative_to(ROOT)),
                       "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()}
        ref = record_reviewer_decision(
            self.root, assessment_ref=self.assessment_ref, unit_ref=self.unit_ref,
            reviewer_id="independent-reviewer",
            assessment_author_id="assessment-author", operator_id="live-operator",
            disposition="approve", checks=checks, reason=reason,
            reviewer_session_receipt=receipt,
            reviewer_session_receipt_ref=receipt_ref,
            trust_policy="operational_host_evidence")
        decision = verify_reviewer_decision(ref)
        self.assertTrue(decision["live_acceptance_eligible"])
        self.assertFalse(decision["reviewer_session_receipt"]["cryptographic_remote_attestation"])
        with self.assertRaisesRegex(SourceError, "ACQ_REVIEW_OPERATIONAL_RECEIPT_MISMATCH"):
            record_reviewer_decision(
                self.root, assessment_ref=self.assessment_ref, unit_ref=self.unit_ref,
                reviewer_id="independent-reviewer",
                assessment_author_id="assessment-author", operator_id="live-operator",
                disposition="reject", checks=checks, reason=reason,
                reviewer_session_receipt=receipt,
                trust_policy="operational_host_evidence")


if __name__ == "__main__":
    unittest.main()
