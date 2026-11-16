"""Provider-free probability authority experiment.

The authority owns chronology, protected outcome bytes, and a MAC key in one
process. Producers receive only public receipts. This is an inert experiment,
not a production key-management or hostile-user security boundary.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Sequence, TypedDict

SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
GENESIS = "0" * 64
PROTOCOL_VERSION = "probability-authority-experiment-1"
REVIEW_ROLES = frozenset({"data", "statistics", "methodology"})


class GuardError(ValueError):
    """Stable, sanitized authority rejection."""


class EventType(str, Enum):
    ISSUE = "issue"
    MATURITY = "maturity"
    ACCESS_GRANT = "protected_access_grant"
    PROTECTED_ACCESS = "protected_outcome_access"
    SCORE = "score"
    REVIEW_DATA = "review_data"
    REVIEW_STATISTICS = "review_statistics"
    REVIEW_METHODOLOGY = "review_methodology"
    TRANSPORT_AUTHORIZATION = "transport_authorization"
    FACTOR_AUTHORIZATION = "factor_authorization"


class IdentityDict(TypedDict):
    target_id: str
    event_id: str
    horizon_reset_days: int
    calendar_id: str
    as_of: str
    vintage_sha256: str
    attempt_id: str
    variant_id: str
    holdout_id: str
    forecast_sha256: str


class Receipt(TypedDict):
    version: str
    event_type: str
    sequence: int
    occurred_at: str
    identity: IdentityDict
    identity_sha256: str
    payload: dict[str, Any]
    previous_event_sha256: str
    event_sha256: str
    previous_state_head: str
    state_head: str
    state_head_mac: str
    receipt_mac: str


class MutableClock:
    """Test/experiment clock that advances only by explicit injection."""

    def __init__(self, initial: str):
        self._current = normalize_time(initial, "CLOCK_INVALID")

    def now(self) -> str:
        return self._current

    def set(self, value: str) -> None:
        value = normalize_time(value, "CLOCK_INVALID")
        require(parse_time(value) >= parse_time(self._current), "CLOCK_REWIND")
        self._current = value


def require(condition: bool, code: str) -> None:
    if not condition:
        raise GuardError(code)


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise GuardError("JSON_INVALID") from None


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_time(value: str) -> datetime:
    require(isinstance(value, str) and UTC_RE.fullmatch(value) is not None, "TIME_INVALID")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise GuardError("TIME_INVALID") from None


def normalize_time(value: str, code: str) -> str:
    try:
        parsed = parse_time(value)
    except GuardError:
        raise GuardError(code) from None
    normalized = parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
    require(value == normalized, code)
    return normalized


def _id(value: Any, code: str) -> str:
    require(isinstance(value, str) and ID_RE.fullmatch(value) is not None, code)
    return value


def _hash(value: Any, code: str) -> str:
    require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, code)
    return value


def validate_identity(identity: Mapping[str, Any]) -> IdentityDict:
    keys = {"target_id", "event_id", "horizon_reset_days", "calendar_id", "as_of",
            "vintage_sha256", "attempt_id", "variant_id", "holdout_id", "forecast_sha256"}
    require(isinstance(identity, Mapping) and set(identity) == keys, "IDENTITY_SCHEMA")
    result: IdentityDict = {
        "target_id": _id(identity["target_id"], "IDENTITY_TARGET"),
        "event_id": _id(identity["event_id"], "IDENTITY_EVENT"),
        "horizon_reset_days": identity["horizon_reset_days"],
        "calendar_id": _id(identity["calendar_id"], "IDENTITY_CALENDAR"),
        "as_of": normalize_time(identity["as_of"], "IDENTITY_AS_OF"),
        "vintage_sha256": _hash(identity["vintage_sha256"], "IDENTITY_VINTAGE"),
        "attempt_id": _id(identity["attempt_id"], "IDENTITY_ATTEMPT"),
        "variant_id": _id(identity["variant_id"], "IDENTITY_VARIANT"),
        "holdout_id": _id(identity["holdout_id"], "IDENTITY_HOLDOUT"),
        "forecast_sha256": _hash(identity["forecast_sha256"], "IDENTITY_FORECAST"),
    }
    require(type(result["horizon_reset_days"]) is int and result["horizon_reset_days"] > 0,
            "IDENTITY_HORIZON")
    return result


def _strict_mapping(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    require(isinstance(value, Mapping) and set(value) == keys, code)
    return dict(value)


def _scope_transport(value: Mapping[str, Any], identity: IdentityDict) -> dict[str, Any]:
    scope = _strict_mapping(value, {"source_target_id", "destination_target_id",
                                    "transport_policy_sha256"}, "TRANSPORT_SCOPE_SCHEMA")
    require(_id(scope["source_target_id"], "TRANSPORT_SOURCE") == identity["target_id"],
            "TRANSPORT_SOURCE_MISMATCH")
    _id(scope["destination_target_id"], "TRANSPORT_DESTINATION")
    _hash(scope["transport_policy_sha256"], "TRANSPORT_POLICY")
    return scope


def _scope_factor(value: Mapping[str, Any]) -> dict[str, Any]:
    scope = _strict_mapping(value, {"factor_id", "authorization_purpose", "use_scope_sha256"},
                            "FACTOR_SCOPE_SCHEMA")
    _id(scope["factor_id"], "FACTOR_ID")
    require(scope["authorization_purpose"] in {"combination_selection", "ev_publication",
                                                "kelly_publication"}, "FACTOR_PURPOSE")
    _hash(scope["use_scope_sha256"], "FACTOR_USE_SCOPE")
    return scope


class ProbabilityAuthority:
    """Single-process authority for one exact forecast identity."""

    def __init__(self, *, clock: Callable[[], str], operator_id: str,
                 evidence_collector_id: str, protected_outcomes: Mapping[str, bytes],
                 secret: bytes | None = None):
        self._owner_pid = os.getpid()
        self._clock = clock
        self._operator_id = _id(operator_id, "OPERATOR_ID")
        self._evidence_collector_id = _id(evidence_collector_id, "COLLECTOR_ID")
        require(self._operator_id != self._evidence_collector_id, "AUTHORITY_PRINCIPALS_DISTINCT")
        self._secret = bytes(secret) if secret is not None else os.urandom(32)
        require(len(self._secret) >= 32, "SECRET_TOO_SHORT")
        self._protected_outcomes: dict[str, bytes] = {}
        for identity_sha, outcome in protected_outcomes.items():
            _hash(identity_sha, "PROTECTED_IDENTITY_HASH")
            require(isinstance(outcome, bytes) and outcome, "PROTECTED_OUTCOME_INVALID")
            self._protected_outcomes[identity_sha] = bytes(outcome)
        self._receipts: list[Receipt] = []
        self._state_head = GENESIS
        self._identity: IdentityDict | None = None
        self._identity_sha: str | None = None
        self._forecast_payload: dict[str, Any] | None = None
        self._producer_id: str | None = None
        self._maturity_at: str | None = None
        self._grant_principal: str | None = None
        self._reviewers: dict[str, str] = {}
        self._event_by_type: dict[str, Receipt] = {}

    def _owned(self) -> None:
        require(os.getpid() == self._owner_pid, "AUTHORITY_PROCESS_MISMATCH")

    def _now(self) -> str:
        self._owned()
        return normalize_time(self._clock(), "CLOCK_INVALID")

    def _mac(self, domain: bytes, value: Any) -> str:
        return hmac.new(self._secret, domain + canonical(value), hashlib.sha256).hexdigest()

    def _append(self, event_type: EventType, identity: IdentityDict,
                payload: dict[str, Any]) -> Receipt:
        self._owned()
        occurred_at = self._now()
        identity_sha = sha256(identity)
        sequence = len(self._receipts) + 1
        previous_event = self._receipts[-1]["event_sha256"] if self._receipts else GENESIS
        event_core = {"version": PROTOCOL_VERSION, "event_type": event_type.value,
                      "sequence": sequence, "occurred_at": occurred_at, "identity": identity,
                      "identity_sha256": identity_sha, "payload": payload,
                      "previous_event_sha256": previous_event}
        event_sha = sha256(event_core)
        previous_head = self._state_head
        head_core = {"version": PROTOCOL_VERSION, "sequence": sequence,
                     "previous_state_head": previous_head, "event_sha256": event_sha}
        state_head = sha256(head_core)
        receipt_without_mac = {**event_core, "event_sha256": event_sha,
                               "previous_state_head": previous_head, "state_head": state_head,
                               "state_head_mac": self._mac(b"state-head\0", head_core)}
        receipt = {**receipt_without_mac,
                   "receipt_mac": self._mac(b"receipt\0", receipt_without_mac)}
        self._receipts.append(copy.deepcopy(receipt))
        self._state_head = state_head
        self._event_by_type[event_type.value] = copy.deepcopy(receipt)
        return copy.deepcopy(receipt)  # type: ignore[return-value]

    def _verify_structure(self, receipt: Mapping[str, Any]) -> Receipt:
        expected = {"version", "event_type", "sequence", "occurred_at", "identity",
                    "identity_sha256", "payload", "previous_event_sha256", "event_sha256",
                    "previous_state_head", "state_head", "state_head_mac", "receipt_mac"}
        require(isinstance(receipt, Mapping) and set(receipt) == expected, "RECEIPT_SCHEMA")
        data = copy.deepcopy(dict(receipt))
        require(data["version"] == PROTOCOL_VERSION, "RECEIPT_VERSION")
        require(data["event_type"] in {member.value for member in EventType}, "RECEIPT_TYPE")
        require(type(data["sequence"]) is int and data["sequence"] > 0, "RECEIPT_SEQUENCE")
        normalize_time(data["occurred_at"], "RECEIPT_TIME")
        identity = validate_identity(data["identity"])
        require(data["identity_sha256"] == sha256(identity), "RECEIPT_IDENTITY_HASH")
        require(isinstance(data["payload"], dict), "RECEIPT_PAYLOAD")
        for field in ("previous_event_sha256", "event_sha256", "previous_state_head", "state_head",
                      "state_head_mac", "receipt_mac"):
            _hash(data[field], "RECEIPT_HASH")
        event_core = {key: data[key] for key in ("version", "event_type", "sequence", "occurred_at",
                                                  "identity", "identity_sha256", "payload",
                                                  "previous_event_sha256")}
        require(data["event_sha256"] == sha256(event_core), "RECEIPT_EVENT_HASH")
        head_core = {"version": data["version"], "sequence": data["sequence"],
                     "previous_state_head": data["previous_state_head"],
                     "event_sha256": data["event_sha256"]}
        require(data["state_head"] == sha256(head_core), "RECEIPT_STATE_HEAD")
        require(hmac.compare_digest(data["state_head_mac"], self._mac(b"state-head\0", head_core)),
                "RECEIPT_STATE_MAC")
        without_mac = {key: data[key] for key in expected - {"receipt_mac"}}
        require(hmac.compare_digest(data["receipt_mac"], self._mac(b"receipt\0", without_mac)),
                "RECEIPT_MAC")
        return data  # type: ignore[return-value]

    def verify_receipt(self, receipt: Mapping[str, Any], *, expected_type: EventType | None = None,
                       expected_identity: Mapping[str, Any] | None = None,
                       expected_scope: Mapping[str, Any] | None = None) -> Receipt:
        self._owned()
        valid = self._verify_structure(receipt)
        if expected_type is not None:
            require(valid["event_type"] == expected_type.value, "RECEIPT_WRONG_TYPE")
        if expected_identity is not None:
            require(valid["identity"] == validate_identity(expected_identity),
                    "RECEIPT_SCOPE_MISMATCH")
        if expected_scope is not None:
            require(valid["payload"].get("authorization_scope") == dict(expected_scope),
                    "RECEIPT_SCOPE_MISMATCH")
        return copy.deepcopy(valid)

    def _accepted(self, receipt: Mapping[str, Any], event_type: EventType) -> Receipt:
        valid = self.verify_receipt(receipt, expected_type=event_type)
        sequence = valid["sequence"]
        require(sequence <= len(self._receipts), "RECEIPT_UNKNOWN")
        require(valid == self._receipts[sequence - 1], "RECEIPT_UNKNOWN")
        require(self._identity is not None and valid["identity"] == self._identity,
                "RECEIPT_SCOPE_MISMATCH")
        return valid

    def issue(self, *, identity: Mapping[str, Any], forecast_payload: Mapping[str, Any],
              maturity_at: str, producer_id: str) -> Receipt:
        self._owned()
        require(self._identity is None, "ISSUE_REPLAY")
        valid_identity = validate_identity(identity)
        forecast = _strict_mapping(forecast_payload, {"probability"}, "FORECAST_SCHEMA")
        probability = forecast["probability"]
        require(type(probability) in (int, float) and math.isfinite(probability) and 0 <= probability <= 1,
                "FORECAST_PROBABILITY")
        require(valid_identity["forecast_sha256"] == sha256(forecast), "FORECAST_HASH_MISMATCH")
        now = self._now()
        maturity_at = normalize_time(maturity_at, "MATURITY_TIME")
        require(parse_time(valid_identity["as_of"]) <= parse_time(now), "ISSUE_AS_OF_FUTURE")
        require(parse_time(now) < parse_time(maturity_at), "ISSUE_NOT_PROSPECTIVE")
        producer = _id(producer_id, "PRODUCER_ID")
        require(producer not in {self._operator_id, self._evidence_collector_id},
                "PRODUCER_AUTHORITY_CONFLICT")
        identity_sha = sha256(valid_identity)
        require(identity_sha in self._protected_outcomes, "PROTECTED_OUTCOME_MISSING")
        self._identity, self._identity_sha = valid_identity, identity_sha
        self._forecast_payload, self._producer_id, self._maturity_at = forecast, producer, maturity_at
        return self._append(EventType.ISSUE, valid_identity,
                            {"forecast_sha256": valid_identity["forecast_sha256"],
                             "maturity_at": maturity_at, "producer_id": producer})

    def record_maturity(self, issue_receipt: Mapping[str, Any]) -> Receipt:
        issue = self._accepted(issue_receipt, EventType.ISSUE)
        require(EventType.MATURITY.value not in self._event_by_type, "MATURITY_REPLAY")
        require(self._maturity_at is not None and
                parse_time(self._now()) >= parse_time(self._maturity_at), "OUTCOME_BEFORE_MATURITY")
        return self._append(EventType.MATURITY, issue["identity"],
                            {"issue_event_sha256": issue["event_sha256"],
                             "maturity_at": self._maturity_at})

    def grant_protected_access(self, maturity_receipt: Mapping[str, Any], *, grantee_id: str) -> Receipt:
        maturity = self._accepted(maturity_receipt, EventType.MATURITY)
        require(EventType.ACCESS_GRANT.value not in self._event_by_type, "ACCESS_GRANT_REPLAY")
        grantee = _id(grantee_id, "ACCESS_GRANTEE")
        require(grantee == self._evidence_collector_id and grantee != self._producer_id,
                "PROTECTED_ACCESS_DENIED")
        self._grant_principal = grantee
        return self._append(EventType.ACCESS_GRANT, maturity["identity"],
                            {"grantee_id": grantee,
                             "maturity_event_sha256": maturity["event_sha256"]})

    def access_protected_outcome(self, grant_receipt: Mapping[str, Any], *,
                                 principal_id: str) -> tuple[bytes, Receipt]:
        grant = self._accepted(grant_receipt, EventType.ACCESS_GRANT)
        require(EventType.PROTECTED_ACCESS.value not in self._event_by_type,
                "PROTECTED_ACCESS_DUPLICATE")
        principal = _id(principal_id, "ACCESS_PRINCIPAL")
        require(principal == self._grant_principal and principal != self._producer_id,
                "PROTECTED_ACCESS_DENIED")
        require(self._identity_sha is not None, "AUTHORITY_STATE")
        outcome = self._protected_outcomes[self._identity_sha]
        receipt = self._append(EventType.PROTECTED_ACCESS, grant["identity"],
                               {"access_grant_event_sha256": grant["event_sha256"],
                                "outcome_sha256": bytes_sha256(outcome),
                                "principal_id": principal})
        return bytes(outcome), receipt

    def score(self, access_receipt: Mapping[str, Any], *, scorer_id: str) -> Receipt:
        access = self._accepted(access_receipt, EventType.PROTECTED_ACCESS)
        require(EventType.SCORE.value not in self._event_by_type, "SCORE_REPLAY")
        scorer = _id(scorer_id, "SCORER_ID")
        require(scorer != self._producer_id, "PRODUCER_SCORE_DENIED")
        require(self._identity_sha is not None and self._forecast_payload is not None,
                "AUTHORITY_STATE")
        outcome_bytes = self._protected_outcomes[self._identity_sha]
        try:
            outcome = json.loads(outcome_bytes.decode("utf-8"))
        except (UnicodeError, ValueError):
            raise GuardError("PROTECTED_OUTCOME_FORMAT") from None
        require(isinstance(outcome, dict) and set(outcome) == {"observed"} and
                type(outcome["observed"]) is bool, "PROTECTED_OUTCOME_FORMAT")
        probability = float(self._forecast_payload["probability"])
        observed = 1.0 if outcome["observed"] else 0.0
        return self._append(EventType.SCORE, access["identity"],
                            {"access_event_sha256": access["event_sha256"],
                             "forecast_sha256": access["identity"]["forecast_sha256"],
                             "metric": "brier", "outcome_sha256": bytes_sha256(outcome_bytes),
                             "score_value": (probability - observed) ** 2,
                             "scorer_id": scorer})

    def review(self, score_receipt: Mapping[str, Any], *, role: str, reviewer_id: str,
               verdict: str = "approved") -> Receipt:
        score = self._accepted(score_receipt, EventType.SCORE)
        require(role in REVIEW_ROLES, "REVIEW_ROLE")
        require(role not in self._reviewers, "REVIEW_ROLE_REPLAY")
        reviewer = _id(reviewer_id, "REVIEWER_ID")
        require(reviewer not in {self._producer_id, self._operator_id, self._evidence_collector_id},
                "REVIEWER_NOT_INDEPENDENT")
        require(reviewer not in self._reviewers.values(), "REVIEWER_NOT_DISTINCT")
        require(verdict == "approved", "REVIEW_NOT_APPROVED")
        event_type = {"data": EventType.REVIEW_DATA, "statistics": EventType.REVIEW_STATISTICS,
                      "methodology": EventType.REVIEW_METHODOLOGY}[role]
        self._reviewers[role] = reviewer
        return self._append(event_type, score["identity"],
                            {"evidence_event_sha256": score["event_sha256"],
                             "reviewer_id": reviewer, "role": role, "verdict": verdict})

    def _complete_reviews(self, review_receipts: Sequence[Mapping[str, Any]]) -> list[Receipt]:
        require(len(review_receipts) == 3, "AUTHORIZATION_EVIDENCE_INCOMPLETE")
        by_role: dict[str, Receipt] = {}
        type_by_role = {"data": EventType.REVIEW_DATA, "statistics": EventType.REVIEW_STATISTICS,
                        "methodology": EventType.REVIEW_METHODOLOGY}
        for receipt in review_receipts:
            role = receipt.get("payload", {}).get("role") if isinstance(receipt, Mapping) else None
            require(role in type_by_role, "AUTHORIZATION_EVIDENCE_INCOMPLETE")
            valid = self._accepted(receipt, type_by_role[role])
            require(role not in by_role, "AUTHORIZATION_EVIDENCE_INCOMPLETE")
            by_role[role] = valid
        require(set(by_role) == REVIEW_ROLES and set(self._reviewers) == REVIEW_ROLES,
                "AUTHORIZATION_EVIDENCE_INCOMPLETE")
        require({item["payload"]["reviewer_id"] for item in by_role.values()} ==
                set(self._reviewers.values()), "AUTHORIZATION_EVIDENCE_INCOMPLETE")
        return [by_role[role] for role in sorted(by_role)]

    def authorize_transport(self, review_receipts: Sequence[Mapping[str, Any]], *,
                            scope: Mapping[str, Any]) -> Receipt:
        reviews = self._complete_reviews(review_receipts)
        require(EventType.TRANSPORT_AUTHORIZATION.value not in self._event_by_type,
                "TRANSPORT_AUTHORIZATION_REPLAY")
        require(self._identity is not None, "AUTHORITY_STATE")
        return self._append(EventType.TRANSPORT_AUTHORIZATION, self._identity,
                            {"authorization_scope": _scope_transport(scope, self._identity),
                             "review_event_sha256s": [item["event_sha256"] for item in reviews]})

    def authorize_factor(self, review_receipts: Sequence[Mapping[str, Any]], *,
                         scope: Mapping[str, Any]) -> Receipt:
        reviews = self._complete_reviews(review_receipts)
        require(EventType.FACTOR_AUTHORIZATION.value not in self._event_by_type,
                "FACTOR_AUTHORIZATION_REPLAY")
        require(self._identity is not None, "AUTHORITY_STATE")
        return self._append(EventType.FACTOR_AUTHORIZATION, self._identity,
                            {"authorization_scope": _scope_factor(scope),
                             "review_event_sha256s": [item["event_sha256"] for item in reviews]})

    def public_snapshot(self) -> dict[str, Any]:
        self._owned()
        return {"version": PROTOCOL_VERSION, "event_count": len(self._receipts),
                "state_head": self._state_head, "receipts": copy.deepcopy(self._receipts)}

    def validate_snapshot(self, snapshot: Mapping[str, Any]) -> bool:
        self._owned()
        data = _strict_mapping(snapshot, {"version", "event_count", "state_head", "receipts"},
                               "SNAPSHOT_SCHEMA")
        require(data["version"] == PROTOCOL_VERSION, "SNAPSHOT_VERSION")
        require(isinstance(data["receipts"], list), "SNAPSHOT_RECEIPTS")
        require(data["event_count"] == len(data["receipts"]), "SNAPSHOT_COUNT")
        previous_event, previous_head = GENESIS, GENESIS
        for index, raw in enumerate(data["receipts"], start=1):
            receipt = self._verify_structure(raw)
            require(receipt["sequence"] == index, "SNAPSHOT_SEQUENCE")
            require(receipt["previous_event_sha256"] == previous_event, "SNAPSHOT_EVENT_CHAIN")
            require(receipt["previous_state_head"] == previous_head, "SNAPSHOT_HEAD_CHAIN")
            previous_event, previous_head = receipt["event_sha256"], receipt["state_head"]
        require(data["state_head"] == previous_head, "SNAPSHOT_STATE_HEAD")
        return True
