"""Strict sanitized hash-chained monitor events for the inert candidate."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence

from .canonical import canonical_sha256


class MonitorError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _at(value: object) -> datetime:
    if type(value) is not str or not value.endswith("Z"):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, AttributeError):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID") from None
    if result.tzinfo is None or result.astimezone(timezone.utc).utcoffset().total_seconds() != 0:
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    return result


def _validate_semantics(event: Mapping[str, Any]) -> None:
    kind, status = event["event_type"], event["slot_status"]
    slot, attempt, job = event["slot_ordinal"], event["attempt_ordinal"], event["job_identity_sha256"]
    counts = event["counts"]
    terminal_status = {"succeeded", "failed", "unknown", "missed"}
    if kind in {"workspace_prepared", "bundle_verified", "database_created", "cleanup_started", "cleanup_terminal"}:
        if slot is not None or attempt is not None or job is not None:
            raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if kind in {"slot_claimed", "process_started", "process_terminated", "slot_terminal", "recovery_observed"}:
        if slot not in {1, 2} or attempt != 1 or not _sha(job):
            raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if kind == "workspace_prepared" and (event["sequence"] != 1 or status != "ready" or counts != {"claims": 0, "attempts": 0, "running": 0, "terminal": 0}):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if kind in {"slot_claimed", "process_started"} and (status != "running" or counts["running"] != 1):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if kind == "slot_terminal" and (status not in terminal_status or counts["running"] != 0 or counts["terminal"] not in {1, 2}):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if status == "coalesced":
        raise MonitorError("CANARY_ONCE_COALESCED_INVALID")


def _validate_shape(event: Mapping[str, Any], *, with_hash: bool) -> None:
    keys = {"schema_version", "event_id", "sequence", "observed_at", "candidate_id", "bundle_sha256", "workspace_identity_sha256", "job_identity_sha256", "slot_ordinal", "attempt_ordinal", "event_type", "slot_status", "code", "process_present", "label_present", "db_schema_version", "counts", "previous_event_sha256"}
    if with_hash:
        keys.add("event_sha256")
    if type(event) is not dict or set(event) != keys or event.get("schema_version") != 1:
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if type(event["sequence"]) is not int or not 1 <= event["sequence"] <= 10_000 or not re.fullmatch(r"icq1-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{24}", event["candidate_id"]):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    _at(event["observed_at"])
    if not _sha(event["bundle_sha256"]) or not _sha(event["workspace_identity_sha256"]):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if event["job_identity_sha256"] is not None and not _sha(event["job_identity_sha256"]):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if event["slot_ordinal"] not in (None, 1, 2) or event["attempt_ordinal"] not in (None, 1):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if event["event_type"] not in {"workspace_prepared", "bundle_verified", "database_created", "slot_claimed", "process_started", "process_terminated", "slot_terminal", "recovery_observed", "cleanup_started", "cleanup_terminal"} or event["slot_status"] not in {None, "ready", "running", "succeeded", "failed", "unknown", "missed", "coalesced"} or re.fullmatch(r"CANARY_[A-Z0-9_]+", event["code"]) is None:
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if type(event["process_present"]) is not bool or type(event["label_present"]) is not bool or event["db_schema_version"] != 9:
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    counts = event["counts"]
    if type(counts) is not dict or set(counts) != {"claims", "attempts", "running", "terminal"} or any(type(x) is not int or not 0 <= x <= 2 for x in counts.values()):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if event["previous_event_sha256"] is not None and not _sha(event["previous_event_sha256"]):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    if with_hash and not _sha(event.get("event_sha256")):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    expected_id = canonical_sha256({"candidate_id": event["candidate_id"], "sequence": event["sequence"]})[:24]
    if event["event_id"] != expected_id:
        raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
    _validate_semantics(event)


def make_monitor_event(observation: Mapping[str, Any], previous_sha256: str | None) -> dict[str, Any]:
    if not isinstance(observation, Mapping):
        raise MonitorError("CANARY_MONITOR_EVENT_INVALID")
    forbidden = {"path", "pid", "pgid", "label", "prompt", "credential", "recipient", "subject", "message_id", "stdout", "stderr", "exception"}
    if forbidden & set(observation):
        raise MonitorError("CANARY_MONITOR_SECRET_REJECTED")
    event = {"schema_version": 1, "event_id": canonical_sha256({"candidate_id": observation.get("candidate_id"), "sequence": observation.get("sequence")})[:24], **dict(observation), "db_schema_version": 9, "previous_event_sha256": previous_sha256}
    _validate_shape(event, with_hash=False)
    event["event_sha256"] = canonical_sha256(event)
    return event


def validate_monitor_event(event: Mapping[str, Any], previous: Mapping[str, Any] | None) -> None:
    _validate_shape(event, with_hash=True)
    expected = canonical_sha256({key: value for key, value in event.items() if key != "event_sha256"})
    if event["event_sha256"] != expected:
        raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
    if previous is None:
        if event["sequence"] != 1 or event["previous_event_sha256"] is not None:
            raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
        return
    _validate_shape(previous, with_hash=True)
    if event["previous_event_sha256"] != previous["event_sha256"] or event["sequence"] != previous["sequence"] + 1 or any(event[key] != previous[key] for key in ("candidate_id", "bundle_sha256", "workspace_identity_sha256")) or _at(event["observed_at"]) < _at(previous["observed_at"]):
        raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
    if previous["event_type"] == "cleanup_terminal":
        raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
    if any(event["counts"][key] < previous["counts"][key] for key in ("claims", "attempts", "terminal")):
        raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")


def project_monitor(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    expected_slots = (1, 2)
    previous = None
    terminals: dict[int, str] = {}
    for event in events:
        validate_monitor_event(event, previous)
        if event["event_type"] == "slot_terminal":
            slot = event["slot_ordinal"]
            if slot in terminals:
                raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
            terminals[slot] = event["slot_status"]
            if event["counts"]["terminal"] != len(terminals):
                raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
        previous = event
    if set(terminals) != set(expected_slots):
        raise MonitorError("CANARY_MONITOR_TERMINAL_INCOMPLETE")
    values = set(terminals.values())
    if "unknown" in values: aggregate = "unknown"
    elif "failed" in values: aggregate = "failed"
    elif "missed" in values: aggregate = "missed"
    elif values == {"succeeded"}: aggregate = "succeeded"
    else: raise MonitorError("CANARY_MONITOR_CHAIN_INVALID")
    return {"schema_version": 1, "candidate_id": events[-1]["candidate_id"], "last_sequence": events[-1]["sequence"], "last_event_sha256": events[-1]["event_sha256"], "event_count": len(events), "slot_terminal_count": len(terminals), "slot_statuses": {str(slot): terminals[slot] for slot in expected_slots}, "status": aggregate, "cleanup_status": events[-1]["event_type"] if events[-1]["event_type"].startswith("cleanup_") else None}
