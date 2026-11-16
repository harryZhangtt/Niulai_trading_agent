"""Immutable, independent review decisions for acquisition candidate units.

Review decisions are content-addressed artifacts.  This module reopens the bound
assessment, unit, source and text; it never accepts an operator summary as proof.
"""
from shared.research_sources.artifacts import ROOT, digest, read, require, save
from shared.research_sources.host_adapter_contracts import (
    HostContractError,
    OperationalTrustPolicy,
    ReviewerSessionReceipt,
    WorkspaceFileRef,
)


VERSION = "acquisition-review-0.1.0"
_DECISIONS = {"approve", "reject"}
_CHECKS = ("question_relevance", "literal_support", "canonical_lineage")


def _identity(value, code):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 256, code)
    return value.strip()


def review_payload_sha256(*, assessment_ref, unit_ref, reviewer_id,
                          assessment_author_id, operator_id, disposition, checks, reason):
    """Hash the exact review request before binding a reviewer-session receipt."""
    return digest({
        "assessment_ref": assessment_ref,
        "unit_ref": unit_ref,
        "reviewer_id": reviewer_id,
        "assessment_author_id": assessment_author_id,
        "operator_id": operator_id,
        "disposition": disposition,
        "checks": checks,
        "reason": reason.strip() if isinstance(reason, str) else reason,
    })


def record_reviewer_decision(
        directory, *, assessment_ref, unit_ref, reviewer_id,
        assessment_author_id, operator_id, disposition, checks, reason,
        reviewer_session_receipt=None, reviewer_session_receipt_ref=None,
        trust_policy=None):
    """Validate and persist one hash-bound reviewer decision.

    The reviewer must differ from both the assessment author and live operator.
    Approval additionally requires every bounded review check to pass.  The
    function verifies literal support itself, while leaving semantic judgement
    represented as the reviewer's recorded decision.
    """
    reviewer_id = _identity(reviewer_id, "ACQ_REVIEW_REVIEWER_ID")
    assessment_author_id = _identity(
        assessment_author_id, "ACQ_REVIEW_ASSESSMENT_AUTHOR_ID")
    operator_id = _identity(operator_id, "ACQ_REVIEW_OPERATOR_ID")
    require(len({reviewer_id, assessment_author_id, operator_id}) == 3,
            "ACQ_REVIEW_INDEPENDENCE_REQUIRED")
    require(disposition in _DECISIONS, "ACQ_REVIEW_DISPOSITION_INVALID")
    require(isinstance(reason, str) and 0 < len(reason.strip()) <= 2000,
            "ACQ_REVIEW_REASON_INVALID")
    require(isinstance(checks, dict) and set(checks) == set(_CHECKS)
            and all(type(checks[name]) is bool for name in _CHECKS),
            "ACQ_REVIEW_CHECKS_INVALID")
    if disposition == "approve":
        require(all(checks.values()), "ACQ_REVIEW_APPROVAL_CHECKS")

    operational_receipt = None
    if reviewer_session_receipt is not None or trust_policy is not None:
        require(trust_policy == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
                and isinstance(reviewer_session_receipt, dict),
                "ACQ_REVIEW_OPERATIONAL_RECEIPT_REQUIRED")
        try:
            operational_receipt = ReviewerSessionReceipt.from_public_dict(
                reviewer_session_receipt)
        except HostContractError:
            require(False, "ACQ_REVIEW_OPERATIONAL_RECEIPT_INVALID")
        expected_review_hash = review_payload_sha256(
            assessment_ref=assessment_ref, unit_ref=unit_ref,
            reviewer_id=reviewer_id, assessment_author_id=assessment_author_id,
            operator_id=operator_id, disposition=disposition, checks=checks,
            reason=reason)
        require(operational_receipt.review_artifact_sha256 == expected_review_hash,
                "ACQ_REVIEW_OPERATIONAL_RECEIPT_MISMATCH")
        require(operational_receipt.principal_ref == reviewer_id,
                "ACQ_REVIEW_OPERATIONAL_PRINCIPAL_MISMATCH")
        if reviewer_session_receipt_ref is not None:
            try:
                workspace_ref = WorkspaceFileRef(**reviewer_session_receipt_ref)
                source_value = __import__("json").loads(
                    workspace_ref.verify(ROOT, "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_INVALID").read_bytes())
            except Exception:
                require(False, "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_INVALID")
            require(source_value == reviewer_session_receipt,
                    "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_MISMATCH")

    assessment = read(assessment_ref)
    unit = read(unit_ref)
    require(assessment.get("kind") == "acquisition_quote_assessment",
            "ACQ_REVIEW_ASSESSMENT_INVALID")
    require(unit.get("kind") == "acquisition_candidate_unit",
            "ACQ_REVIEW_UNIT_INVALID")
    require(unit.get("assessment_ref") == assessment_ref,
            "ACQ_REVIEW_UNIT_ASSESSMENT_MISMATCH")
    require(unit.get("source_ref") == assessment.get("source_ref")
            and unit.get("question_id") == assessment.get("question_id")
            and unit.get("quote") == assessment.get("quote"),
            "ACQ_REVIEW_BINDING_MISMATCH")

    declared_author = assessment.get("assessment_author_id")
    if declared_author is not None:
        require(declared_author == assessment_author_id,
                "ACQ_REVIEW_ASSESSMENT_AUTHOR_MISMATCH")
    declared_operator = assessment.get("operator_id")
    if declared_operator is not None:
        require(declared_operator == operator_id,
                "ACQ_REVIEW_OPERATOR_MISMATCH")

    source = read(assessment["source_ref"])
    text = read(source["text"], json_value=False).decode("utf-8")
    require(assessment["quote"] in text, "ACQ_REVIEW_LITERAL_SUPPORT_MISMATCH")
    require(assessment.get("source_version") == source.get("source_version")
            and assessment.get("raw_sha256") == source.get("raw", {}).get("sha256")
            and assessment.get("text_sha256") == source["text"]["sha256"],
            "ACQ_REVIEW_SOURCE_VERSION_MISMATCH")

    identities = {
        key: assessment.get(key)
        for key in ("experiment_id", "execution_id", "trace_id")
    }
    require(all(isinstance(value, str) and value for value in identities.values())
            and all(unit.get(key) == value for key, value in identities.items()),
            "ACQ_REVIEW_IDENTITY_MISMATCH")
    binding = {
        "assessment_ref": assessment_ref,
        "unit_ref": unit_ref,
        "source_ref": assessment["source_ref"],
        "question_id": assessment["question_id"],
        "quote_sha256": digest(assessment["quote"]),
        "source_version": assessment["source_version"],
        "raw_sha256": assessment["raw_sha256"],
        "text_sha256": assessment["text_sha256"],
    }
    decision = {
        "kind": "acquisition_reviewer_decision",
        "version": VERSION,
        **identities,
        "review_id": digest([identities, binding, reviewer_id, disposition, checks]),
        "reviewer_id": reviewer_id,
        "assessment_author_id": assessment_author_id,
        "operator_id": operator_id,
        "disposition": disposition,
        "checks": dict(checks),
        "reason": reason.strip(),
        "binding": binding,
        "trust_policy": trust_policy,
        "reviewer_session_receipt": (
            operational_receipt.to_public_dict() if operational_receipt else None),
        "reviewer_session_receipt_ref": reviewer_session_receipt_ref,
        "live_acceptance_eligible": bool(
            operational_receipt and operational_receipt.live_acceptance_eligible
            and reviewer_session_receipt_ref is not None),
        "scope": "literal_support_relevance_and_lineage_not_investment_importance",
    }
    return save(directory, decision)


def verify_reviewer_decision(review_ref):
    """Reopen a decision and every bound artifact, returning verified content."""
    decision = read(review_ref)
    require(decision.get("kind") == "acquisition_reviewer_decision"
            and decision.get("version") == VERSION, "ACQ_REVIEW_INVALID")
    binding = decision.get("binding")
    require(isinstance(binding, dict), "ACQ_REVIEW_BINDING_INVALID")
    assessment = read(binding["assessment_ref"])
    unit = read(binding["unit_ref"])
    source = read(binding["source_ref"])
    text = read(source["text"], json_value=False).decode("utf-8")
    require(unit.get("assessment_ref") == binding["assessment_ref"]
            and assessment.get("source_ref") == binding["source_ref"]
            and assessment.get("question_id") == binding.get("question_id")
            and digest(assessment.get("quote")) == binding.get("quote_sha256")
            and assessment.get("quote") in text,
            "ACQ_REVIEW_BINDING_STALE")
    require(assessment.get("source_version") == binding.get("source_version")
            and source.get("source_version") == binding.get("source_version")
            and source.get("raw", {}).get("sha256") == binding.get("raw_sha256")
            and source["text"]["sha256"] == binding.get("text_sha256"),
            "ACQ_REVIEW_BINDING_STALE")
    require(len({decision.get("reviewer_id"),
                 decision.get("assessment_author_id"),
                 decision.get("operator_id")}) == 3,
            "ACQ_REVIEW_INDEPENDENCE_REQUIRED")
    checks = decision.get("checks")
    require(isinstance(checks, dict) and set(checks) == set(_CHECKS)
            and all(type(checks[name]) is bool for name in _CHECKS),
            "ACQ_REVIEW_CHECKS_INVALID")
    require(decision.get("disposition") in _DECISIONS
            and (decision["disposition"] != "approve" or all(checks.values())),
            "ACQ_REVIEW_DISPOSITION_INVALID")
    receipt_value = decision.get("reviewer_session_receipt")
    if decision.get("trust_policy") is not None or receipt_value is not None:
        require(decision.get("trust_policy")
                == OperationalTrustPolicy.OPERATIONAL_HOST_EVIDENCE.value
                and isinstance(receipt_value, dict),
                "ACQ_REVIEW_OPERATIONAL_RECEIPT_REQUIRED")
        try:
            receipt = ReviewerSessionReceipt.from_public_dict(receipt_value)
        except HostContractError:
            require(False, "ACQ_REVIEW_OPERATIONAL_RECEIPT_INVALID")
        expected = review_payload_sha256(
            assessment_ref=binding["assessment_ref"], unit_ref=binding["unit_ref"],
            reviewer_id=decision["reviewer_id"],
            assessment_author_id=decision["assessment_author_id"],
            operator_id=decision["operator_id"],
            disposition=decision["disposition"], checks=checks,
            reason=decision["reason"])
        require(receipt.review_artifact_sha256 == expected
                and receipt.principal_ref == decision["reviewer_id"],
                "ACQ_REVIEW_OPERATIONAL_RECEIPT_MISMATCH")
        receipt_ref = decision.get("reviewer_session_receipt_ref")
        if receipt_ref is not None:
            try:
                workspace_ref = WorkspaceFileRef(**receipt_ref)
                source_value = __import__("json").loads(
                    workspace_ref.verify(ROOT, "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_INVALID").read_bytes())
            except Exception:
                require(False, "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_INVALID")
            require(source_value == receipt_value,
                    "ACQ_REVIEW_OPERATIONAL_RECEIPT_REF_MISMATCH")
        require(decision.get("live_acceptance_eligible")
                is bool(receipt.live_acceptance_eligible and receipt_ref is not None),
                "ACQ_REVIEW_OPERATIONAL_ELIGIBILITY_MISMATCH")
    else:
        require(decision.get("live_acceptance_eligible") in {None, False},
                "ACQ_REVIEW_OPERATIONAL_ELIGIBILITY_MISMATCH")
    return decision
