#!/usr/bin/env python3
"""Run and freeze the deterministic provider-free O2 vertical experiment."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable

BASE = Path(__file__).resolve().parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from probability_guard import (  # noqa: E402
    EventType,
    GENESIS,
    GuardError,
    MutableClock,
    PROTOCOL_VERSION,
    ProbabilityAuthority,
    canonical,
    sha256,
)

SYNTHETIC_SECRET = b"o2-experiment-synthetic-secret-32b"
PROTECTED_OUTCOME = b'{"observed":true}'
FORECAST = {"probability": 0.625}
ISSUED_AT = "2026-01-02T12:00:00Z"
MATURITY_AT = "2026-07-02T12:00:00Z"
ARCHITECTURE_CANDIDATE_SHA256 = "a178b1975f4903a56e379c153d04a73fe2e967a35dc1373af401ed384f3ee918"
PROTOCOL = {
    "version": PROTOCOL_VERSION,
    "hypothesis": "one process-owned guard can enforce the complete authority chronology",
    "falsifier": (
        "producer protected-state access, accepted forge/backdate/head rewrite/cross-scope reuse, "
        "or authorization without matured evidence and distinct review"
    ),
    "identity_fields": ["target_id", "event_id", "horizon_reset_days", "calendar_id", "as_of",
                        "vintage_sha256", "attempt_id", "variant_id", "holdout_id",
                        "forecast_sha256"],
    "review_roles": ["data", "statistics", "methodology"],
    "no_external_effects": True,
}


def case_identity() -> dict[str, Any]:
    return {
        "target_id": "soxl.reset_loss",
        "event_id": "drawdown_30pct",
        "horizon_reset_days": 126,
        "calendar_id": "xnys_sessions_v1",
        "as_of": "2026-01-02T11:59:00Z",
        "vintage_sha256": hashlib.sha256(b"synthetic-vintage-2026-01-02").hexdigest(),
        "attempt_id": "attempt-001",
        "variant_id": "variant-base",
        "holdout_id": "holdout-protected-001",
        "forecast_sha256": sha256(FORECAST),
    }


def make_authority(clock: MutableClock | None = None) -> tuple[ProbabilityAuthority, MutableClock]:
    clock = clock or MutableClock(ISSUED_AT)
    identity = case_identity()
    authority = ProbabilityAuthority(
        clock=clock.now,
        operator_id="guard-operator",
        evidence_collector_id="evidence-collector",
        protected_outcomes={sha256(identity): PROTECTED_OUTCOME},
        secret=SYNTHETIC_SECRET,
    )
    return authority, clock


def rejection(action: Callable[[], Any], expected: str | tuple[str, ...] | None = None) -> str:
    try:
        action()
    except GuardError as error:
        code = str(error)
        if expected is not None:
            allowed = (expected,) if isinstance(expected, str) else expected
            if code not in allowed:
                raise AssertionError(f"expected {allowed}, got {code}") from error
        return code
    raise AssertionError("operation unexpectedly succeeded")


def public_rehash(receipt: dict[str, Any], *, occurred_at: str | None = None,
                  payload_patch: dict[str, Any] | None = None) -> dict[str, Any]:
    """Model a producer who can recompute public SHA fields but has no MAC key."""
    forged = copy.deepcopy(receipt)
    if occurred_at is not None:
        forged["occurred_at"] = occurred_at
    if payload_patch:
        forged["payload"].update(payload_patch)
    event_core = {key: forged[key] for key in ("version", "event_type", "sequence", "occurred_at",
                                                "identity", "identity_sha256", "payload",
                                                "previous_event_sha256")}
    forged["event_sha256"] = sha256(event_core)
    head_core = {"version": forged["version"], "sequence": forged["sequence"],
                 "previous_state_head": forged["previous_state_head"],
                 "event_sha256": forged["event_sha256"]}
    forged["state_head"] = sha256(head_core)
    return forged


def producer_subprocess_probe(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Exec a producer with only the public snapshot in an empty local directory."""
    program = r'''
import json, os, pathlib, sys
snapshot = json.loads(sys.stdin.read())
files = []
for path in pathlib.Path(".").rglob("*"):
    if path.is_file():
        files.append({"path": str(path), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()})
sensitive_env = sorted(k for k in os.environ if "PROBABILITY_GUARD" in k or "PROTECTED_OUTCOME" in k)
print(json.dumps({"event_count": snapshot["event_count"], "files": files,
                  "sensitive_environment_names": sensitive_env}, sort_keys=True))
'''
    with tempfile.TemporaryDirectory(prefix=".producer-probe-", dir=BASE) as work:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", program],
            input=json.dumps(snapshot, sort_keys=True),
            text=True,
            capture_output=True,
            cwd=work,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
            timeout=10,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(f"producer probe failed: {completed.stderr.strip()}")
        result = json.loads(completed.stdout)
        if result["files"] or result["sensitive_environment_names"]:
            raise AssertionError("producer observed non-public state channel")
        if SYNTHETIC_SECRET.hex() in completed.stdout or PROTECTED_OUTCOME.decode() in completed.stdout:
            raise AssertionError("producer output exposed protected material")
        result["secret_or_outcome_observed"] = False
        return result


def execute() -> tuple[dict[str, Any], dict[str, Any]]:
    authority, clock = make_authority()
    identity = case_identity()
    issue = authority.issue(identity=identity, forecast_payload=FORECAST,
                            maturity_at=MATURITY_AT, producer_id="producer-forecast")
    failures: dict[str, dict[str, Any]] = {}

    failures["outcome_before_maturity"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.record_maturity(issue), "OUTCOME_BEFORE_MATURITY"),
    }
    failures["access_without_maturity_or_grant"] = {
        "status": "rejected",
        "code": rejection(
            lambda: authority.access_protected_outcome(issue, principal_id="producer-forecast"),
            "RECEIPT_WRONG_TYPE",
        ),
    }
    forged_public = public_rehash(issue, payload_patch={"producer_id": "producer-forged"})
    failures["producer_authored_public_sha_chain"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.verify_receipt(forged_public),
                          ("RECEIPT_STATE_MAC", "RECEIPT_MAC")),
    }
    forged_backdated = public_rehash(issue, occurred_at="2025-12-01T00:00:00Z")
    failures["backdated_issue"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.verify_receipt(forged_backdated),
                          ("RECEIPT_STATE_MAC", "RECEIPT_MAC")),
    }
    probe = producer_subprocess_probe(authority.public_snapshot())
    failures["producer_subprocess_parent_memory"] = {
        "status": "unavailable",
        "secret_or_outcome_observed": probe["secret_or_outcome_observed"],
        "workspace_files_observed": len(probe["files"]),
        "sensitive_environment_names": probe["sensitive_environment_names"],
    }

    clock.set(MATURITY_AT)
    maturity = authority.record_maturity(issue)
    failures["replay_maturity"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.record_maturity(issue), "MATURITY_REPLAY"),
    }
    failures["producer_access_grant"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.grant_protected_access(
            maturity, grantee_id="producer-forecast"), "PROTECTED_ACCESS_DENIED"),
    }
    grant = authority.grant_protected_access(maturity, grantee_id="evidence-collector")
    outcome, access = authority.access_protected_outcome(grant, principal_id="evidence-collector")
    if outcome != PROTECTED_OUTCOME:
        raise AssertionError("authority returned wrong protected outcome")
    failures["duplicate_protected_access"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.access_protected_outcome(
            grant, principal_id="evidence-collector"), "PROTECTED_ACCESS_DUPLICATE"),
    }
    score = authority.score(access, scorer_id="score-authority")

    failures["authorization_before_evidence"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.authorize_transport([], scope={
            "source_target_id": identity["target_id"],
            "destination_target_id": "tqqq.reset_loss",
            "transport_policy_sha256": hashlib.sha256(b"transport-policy").hexdigest(),
        }), "AUTHORIZATION_EVIDENCE_INCOMPLETE"),
    }
    data_review = authority.review(score, role="data", reviewer_id="reviewer-data")
    failures["same_reviewer"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.review(
            score, role="statistics", reviewer_id="reviewer-data"), "REVIEWER_NOT_DISTINCT"),
    }
    failures["producer_reviewer"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.review(
            score, role="statistics", reviewer_id="producer-forecast"),
            "REVIEWER_NOT_INDEPENDENT"),
    }
    statistics_review = authority.review(score, role="statistics", reviewer_id="reviewer-statistics")
    methodology_review = authority.review(score, role="methodology", reviewer_id="reviewer-methodology")
    reviews = [data_review, statistics_review, methodology_review]

    transport_scope = {
        "source_target_id": identity["target_id"],
        "destination_target_id": "tqqq.reset_loss",
        "transport_policy_sha256": hashlib.sha256(b"transport-policy").hexdigest(),
    }
    factor_scope = {
        "factor_id": "probability-feature-01",
        "authorization_purpose": "combination_selection",
        "use_scope_sha256": hashlib.sha256(b"factor-use-scope").hexdigest(),
    }
    transport = authority.authorize_transport(reviews, scope=transport_scope)
    factor = authority.authorize_factor(reviews, scope=factor_scope)

    wrong_identity = dict(identity)
    wrong_identity.update({"target_id": "tqqq.reset_loss", "horizon_reset_days": 63,
                           "attempt_id": "attempt-002"})
    cross_scope_codes = [
        rejection(lambda: authority.verify_receipt(
            transport, expected_type=EventType.TRANSPORT_AUTHORIZATION,
            expected_identity=wrong_identity), "RECEIPT_SCOPE_MISMATCH"),
        rejection(lambda: authority.verify_receipt(
            transport, expected_type=EventType.TRANSPORT_AUTHORIZATION,
            expected_identity=identity,
            expected_scope={**transport_scope, "destination_target_id": "spxl.reset_loss"}),
                  "RECEIPT_SCOPE_MISMATCH"),
    ]
    failures["cross_scope_receipt_reuse"] = {"status": "rejected", "codes": cross_scope_codes}

    rewritten = authority.public_snapshot()
    rewritten["state_head"] = hashlib.sha256(b"producer-rewritten-head").hexdigest()
    failures["state_head_rewrite"] = {
        "status": "rejected",
        "code": rejection(lambda: authority.validate_snapshot(rewritten), "SNAPSHOT_STATE_HEAD"),
    }
    snapshot = authority.public_snapshot()
    if not authority.validate_snapshot(snapshot):
        raise AssertionError("canonical snapshot failed validation")

    nominal = {
        "event_count": snapshot["event_count"],
        "event_types": [item["event_type"] for item in snapshot["receipts"]],
        "event_sha256s": [item["event_sha256"] for item in snapshot["receipts"]],
        "receipt_macs": [item["receipt_mac"] for item in snapshot["receipts"]],
        "state_head": snapshot["state_head"],
        "issued_at": issue["occurred_at"],
        "maturity_at": maturity["occurred_at"],
        "outcome_sha256": access["payload"]["outcome_sha256"],
        "score": {"metric": score["payload"]["metric"],
                  "value": score["payload"]["score_value"]},
        "reviewers": {item["payload"]["role"]: item["payload"]["reviewer_id"] for item in reviews},
        "transport_scope": transport["payload"]["authorization_scope"],
        "factor_scope": factor["payload"]["authorization_scope"],
    }
    return nominal, failures


def source_hashes() -> dict[str, str]:
    names = ["__init__.py", "README.md", "PROTOCOL.md", "probability_guard.py", "experiment.py",
             "tests/test_probability_guard.py"]
    return {name: hashlib.sha256((BASE / name).read_bytes()).hexdigest() for name in names}


def build_receipt() -> dict[str, Any]:
    nominal, failures = execute()
    expected_failures = {
        "outcome_before_maturity", "access_without_maturity_or_grant",
        "producer_authored_public_sha_chain", "backdated_issue",
        "producer_subprocess_parent_memory", "replay_maturity", "producer_access_grant",
        "duplicate_protected_access", "authorization_before_evidence", "same_reviewer",
        "producer_reviewer", "cross_scope_receipt_reuse", "state_head_rewrite",
    }
    if set(failures) != expected_failures:
        raise AssertionError("failure matrix incomplete")
    core = {
        "version": "probability-guard-experiment-receipt-1",
        "architecture_candidate_sha256": ARCHITECTURE_CANDIDATE_SHA256,
        "protocol_sha256": sha256(PROTOCOL),
        "identity": case_identity(),
        "nominal": nominal,
        "failure_results": failures,
        "falsifier_triggered": False,
        "decision": "O2_NOT_FALSIFIED_IN_BOUNDED_EXPERIMENT",
        "source_sha256": source_hashes(),
        "external_effects": {"network": False, "email": False, "holdings": False,
                             "orders": False, "alerts": False, "hooks": False,
                             "configuration": False, "scheduler_or_runtime_activation": False},
        "limitations": [
            "experiment process boundary only; not same-user hostile security",
            "synthetic in-memory key; no durable production key management",
            "no crash-safe durable ledger or intended-runtime acceptance",
            "no probability quality, L3/L4, transport, factor, trade, sizing, or alert claim",
        ],
    }
    return {**core, "receipt_sha256": sha256(core)}


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", metavar="PATH")
    group.add_argument("--check", metavar="PATH")
    args = parser.parse_args()
    receipt = build_receipt()
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    path = (BASE / (args.write or args.check)).resolve()
    if BASE not in path.parents:
        raise SystemExit("receipt path must remain inside experiment directory")
    if args.write:
        path.write_text(encoded, encoding="utf-8")
        print(f"wrote deterministic receipt {receipt['receipt_sha256']}")
        return 0
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print("frozen receipt missing", file=sys.stderr)
        return 1
    if existing != encoded:
        print("frozen receipt mismatch", file=sys.stderr)
        return 1
    print(f"verified deterministic receipt {receipt['receipt_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
