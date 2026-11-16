"""Bounded read-only dashboard projection for the fixed mentor scheduler adapter."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import math
import os
import re
import sqlite3
import stat
from typing import Any

from shared.job_runtime.dashboard import database, inside, read_file, require

from .contracts import WorkOrder, strict_json_loads
from . import resilience_preflight as resilience
from .state import DurableSessionStore

UTC = timezone.utc
_ADAPTER_KEYS = {
    "candidate_manifest_path", "candidate_manifest_sha256", "expected_model_profile",
    "model_profile_sha256", "owner_id", "required_source_paths", "state_directory",
    "verifier_kind", "work_order_path",
}
_ENGINE_STATES = {"ready", "running", "retry_wait", "succeeded", "failed", "unknown", "missed", "coalesced"}
_SESSION_STATES = {"active", "blocked_pending_effect", "completed", "failed", "cancelled"}
_ACCEPTANCE_STATES = {"pending", "passed", "partial", "failed", "unverified"}
_EXECUTION_STATES = {"pending", "running", "passed", "partial", "failed", "unverified"}
_EMAIL_STATES = {"pending", "verified", "failed", "unknown"}
_RECONCILIATION_DISPATCH = {
    "definitely_not_dispatched": "definitely_not_dispatched",
    "unknown_outcome": "possibly_dispatched",
    "dispatched": "confirmed_dispatched",
}
_GATE_IDS = (
    "future_wake", "profile_binding", "stop_propagation", "model_turn",
    "journal_cycle_postcondition", "no_duplicate_dispatch",
)
_GATE_STATES = {"verified", "failed", "not_verified"}
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,99}$")
_ENGINE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,255}$")
_EVENT_KEYS = {
    "sequence", "previous_event_hash", "owner_id", "work_order_id",
    "logical_session_id", "kind", "data", "recorded_at",
}
_CYCLE_KEYS = {
    "cycle_id", "variant_id", "action_sha256", "outcome",
    "verified_evidence_artifact_path", "verified_evidence_artifact_sha256",
    "verified_evidence_ids", "effect_id", "effect_status",
}
_PREFLIGHT_KEYS = {
    "schema_version", "state", "reason", "observed_at", "snapshot",
    "scheduler", "provider", "recovery", "host", "catch_up", "loop",
}
_PREFLIGHT_HOST_KEYS = {
    "state", "reason", "stable", "sample_count", "heartbeat_age_seconds",
    "last_tick_age_seconds", "watchdog_age_seconds",
}
_PREFLIGHT_CATCH_UP_KEYS = {"state", "reason", "total", "within_grace", "missed", "coalesced"}
_PREFLIGHT_LOOP_KEYS = {"state", "reason", "should_dispatch"}
_PREFLIGHT_STATES = {"current", "partial", "stale", "unavailable"}
_PREFLIGHT_REASONS = {
    "SUMMARY_RECOVERY_UNKNOWN_FENCE", "SUMMARY_COMPONENT_UNAVAILABLE",
    "SUMMARY_STALE", "SUMMARY_PARTIAL", "SUMMARY_CURRENT",
}
_RESILIENCE_KEYS = {
    "generated_at", "status", "projection_state", "scheduler",
    "provider_safety", "mentor", "health",
}
_RESILIENCE_SCHEDULER_KEYS = {"status", "attempts"}
_RESILIENCE_PROVIDER_KEYS = {
    "latest_attempt", "delayed_until", "delay_source", "unknown_fence",
    "replay_authorization",
}
_RESILIENCE_MENTOR_KEYS = {"cycles", "no_progress", "repeated", "evidence_reset"}
_RESILIENCE_BUDGET_KEYS = {"used", "limit"}
_RESILIENCE_HEALTH_KEYS = {"heartbeat_age_seconds", "watchdog_healthy"}


def _exact(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    require(isinstance(value, dict) and set(value) == keys, f"MENTOR_{label}_INVALID")
    return value


def _bounded_count(value: Any, label: str) -> int:
    require(type(value) is int and 0 <= value <= 1_000_000, f"MENTOR_{label}_INVALID")
    return value


def _aware(value: Any, label: str) -> str:
    require(isinstance(value, str), f"MENTOR_{label}_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        require(False, f"MENTOR_{label}_INVALID")
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"MENTOR_{label}_INVALID")
    return parsed.astimezone(UTC).isoformat()


def _private_file(root: Path, path: Path) -> Path:
    path = inside(path, root)
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and not path.is_symlink()
        and info.st_uid == os.getuid() and not stat.S_IMODE(info.st_mode) & 0o077,
        "MENTOR_EVIDENCE_PERMISSIONS_INVALID",
    )
    return path


def _strict_json(root: Path, path: Path) -> dict[str, Any]:
    value = strict_json_loads(read_file(root, _private_file(root, path)).decode("utf-8"))
    require(isinstance(value, dict), "MENTOR_EVIDENCE_INVALID")
    return value


def _last_cycle_evidence_changed(
    root: Path, store: DurableSessionStore, head: dict[str, Any],
) -> bool:
    kinds = head["event_kinds"]
    require(isinstance(kinds, list) and len(kinds) == head["revision"], "MENTOR_SESSION_STATE_INVALID")
    if "cycle" not in kinds:
        return False
    index = len(kinds) - 1 - kinds[::-1].index("cycle")
    paths = store._event_paths()
    require(len(paths) == head["revision"], "MENTOR_SESSION_STATE_INVALID")
    event = _exact(_strict_json(root, paths[index]), _EVENT_KEYS, "CYCLE_EVENT")
    require(
        event["sequence"] == index + 1
        and event["owner_id"] == head["owner_id"]
        and event["work_order_id"] == head["work_order_id"]
        and event["logical_session_id"] == head["logical_session_id"]
        and event["kind"] == "cycle",
        "MENTOR_CYCLE_EVENT_INVALID",
    )
    data = _exact(event["data"], _CYCLE_KEYS, "CYCLE_EVENT_DATA")
    evidence = data["verified_evidence_ids"]
    require(isinstance(evidence, list) and all(isinstance(item, str) for item in evidence), "MENTOR_CYCLE_EVENT_INVALID")
    return bool(evidence)


def _work_order(root: Path, options: dict[str, Any]) -> tuple[WorkOrder, DurableSessionStore, dict[str, Any], bool]:
    _exact(options, _ADAPTER_KEYS, "CONFIG")
    require(options["verifier_kind"] == "synthetic_bindings_v1", "MENTOR_CONFIG_INVALID")
    order_path = _private_file(root, root / options["work_order_path"])
    order = WorkOrder.from_json(read_file(root, order_path).decode("utf-8"), root)
    _private_file(root, root / order.plan.path)
    _private_file(root, root / order.acceptance.path)
    require(
        options["owner_id"] == order.work_order_id == order.logical_session.logical_session_id,
        "MENTOR_IDENTITY_INVALID",
    )
    store = DurableSessionStore(root, options["state_directory"], options["owner_id"])
    with store._locked():
        head = store._load_unlocked(order)
        evidence_changed = _last_cycle_evidence_changed(root, store, head)
    return order, store, head, evidence_changed


def _epoch(value: Any, label: str) -> datetime:
    require(type(value) in {int, float} and math.isfinite(value), f"MENTOR_{label}_INVALID")
    try:
        return datetime.fromtimestamp(value, UTC)
    except (OverflowError, OSError, ValueError):
        require(False, f"MENTOR_{label}_INVALID")
    raise AssertionError("unreachable")


def _engine(root: Path, job_id: str, observed: datetime) -> dict[str, Any]:
    path = _private_file(root, root / ".job-runtime/engine/schedule.sqlite")
    with database(root, path) as db:
        rows = db.execute(
            "SELECT slot_id,status,code,attempts,scheduled_at,next_attempt_at,updated_at "
            "FROM slots WHERE job_id=? ORDER BY scheduled_at DESC LIMIT 2",
            (job_id,),
        ).fetchall()
    require(1 <= len(rows) <= 2, "MENTOR_ENGINE_IDENTITY_INVALID")
    slots: list[dict[str, Any]] = []
    next_attempts: list[datetime | None] = []
    for row in rows:
        status, code = row["status"], row["code"]
        attempts = _bounded_count(row["attempts"], "ATTEMPTS")
        require(status in _ENGINE_STATES and isinstance(code, str) and _CODE_RE.fullmatch(code), "MENTOR_ENGINE_STATE_INVALID")
        next_attempt = (
            None if row["next_attempt_at"] is None
            else _epoch(row["next_attempt_at"], "NEXT_ATTEMPT_AT")
        )
        require(
            (status == "retry_wait" and next_attempt is not None and next_attempt > observed)
            or (status != "retry_wait" and next_attempt is None),
            "MENTOR_NEXT_ATTEMPT_INVALID",
        )
        slots.append({
            "status": status,
            "scheduled": _epoch(row["scheduled_at"], "SCHEDULED_AT"),
            "updated": _epoch(row["updated_at"], "UPDATED_AT"),
            "attempts": attempts,
        })
        next_attempts.append(next_attempt)
    latest = rows[0]
    require(isinstance(latest["slot_id"], str) and _ENGINE_ID_RE.fullmatch(latest["slot_id"]), "MENTOR_ENGINE_IDENTITY_INVALID")
    return {
        "status": latest["status"], "code": latest["code"],
        "attempts": slots[0]["attempts"], "slots": slots,
        "next_attempt": next_attempts[0], "slot_id": latest["slot_id"],
    }


def _bind_reconciliation(
    root: Path, engine: dict[str, Any], acceptance: dict[str, Any],
) -> None:
    reconciliation = acceptance["reconciliation"]
    if reconciliation is None:
        return
    attempt_id = reconciliation.get("attempt_id")
    require(
        isinstance(attempt_id, str) and _ENGINE_ID_RE.fullmatch(attempt_id),
        "MENTOR_RECONCILIATION_INVALID",
    )
    path = _private_file(root, root / ".job-runtime/engine/schedule.sqlite")
    with database(root, path) as db:
        row = db.execute(
            "SELECT attempt_id,attempt_no FROM attempts WHERE slot_id=? "
            "ORDER BY attempt_no DESC LIMIT 1",
            (engine["slot_id"],),
        ).fetchone()
    require(
        row is not None
        and row["attempt_id"] == attempt_id
        and row["attempt_no"] == engine["attempts"],
        "MENTOR_RECONCILIATION_IDENTITY_INVALID",
    )


def _acceptance(root: Path, options: dict[str, Any], job_id: str) -> dict[str, Any]:
    manifest = Path(options["candidate_manifest_path"])
    require(manifest.name == "candidate-manifest.json", "MENTOR_ACCEPTANCE_PATH_INVALID")
    record = _strict_json(root, root / manifest.parent / "record.json")
    required = {"acceptance", "change_id", "email_sync", "execution", "owner", "record_version"}
    require(required <= set(record), "MENTOR_ACCEPTANCE_INVALID")
    require(record["record_version"] == 1 and record["owner"] == "mentor-scheduler", "MENTOR_ACCEPTANCE_INVALID")
    require(record["change_id"] == options["owner_id"], "MENTOR_IDENTITY_INVALID")
    execution = record["execution"]
    email = record["email_sync"]
    require(isinstance(execution, dict) and execution.get("job_id") == job_id, "MENTOR_IDENTITY_INVALID")
    require(isinstance(email, dict), "MENTOR_ACCEPTANCE_INVALID")
    acceptance = record["acceptance"]
    execution_status = execution.get("status")
    email_status = email.get("status")
    require(
        acceptance in _ACCEPTANCE_STATES
        and execution_status in _EXECUTION_STATES
        and email_status in _EMAIL_STATES,
        "MENTOR_ACCEPTANCE_STATE_INVALID",
    )
    if acceptance == "unverified":
        require(execution_status in {"pending", "running", "unverified", "passed"}, "MENTOR_ACCEPTANCE_STATE_INVALID")
        require(not (execution_status == "passed" and email_status == "verified"), "MENTOR_ACCEPTANCE_STATE_INVALID")
    elif acceptance == "pending":
        require(execution_status in {"pending", "running"}, "MENTOR_ACCEPTANCE_STATE_INVALID")
    else:
        require(acceptance == execution_status, "MENTOR_ACCEPTANCE_STATE_INVALID")
    require(acceptance != "passed" or email_status == "verified", "MENTOR_ACCEPTANCE_STATE_INVALID")

    reconciliations = execution.get("reconciliations")
    require(isinstance(reconciliations, list) and len(reconciliations) <= 1, "MENTOR_DISPATCH_INVALID")
    dispatch = "not_attempted"
    reconciliation = None
    if reconciliations:
        reconciliation = reconciliations[0]
        require(isinstance(reconciliation, dict), "MENTOR_DISPATCH_INVALID")
        classification = reconciliation.get("classification")
        require(classification in _RECONCILIATION_DISPATCH, "MENTOR_DISPATCH_INVALID")
        dispatch = _RECONCILIATION_DISPATCH[classification]

    postconditions = execution.get("postconditions", [])
    partial = execution.get("partial_coverage", [])
    require(
        isinstance(postconditions, list) and len(postconditions) <= len(_GATE_IDS)
        and len(postconditions) == len(set(postconditions)) and set(postconditions) <= set(_GATE_IDS),
        "MENTOR_GATES_INVALID",
    )
    require(isinstance(partial, list) and len(partial) <= 64, "MENTOR_GATES_INVALID")
    turn_completed = execution.get("turn_completed")
    require(turn_completed is None or type(turn_completed) is bool, "MENTOR_MODEL_TURN_INVALID")
    return {
        "acceptance": acceptance,
        "execution": execution_status,
        "email": email_status,
        "dispatch": dispatch,
        "postconditions": set(postconditions),
        "turn_completed": turn_completed,
        "scheduled_at": execution.get("scheduled_at"),
        "started_at": execution.get("started_at"),
        "completed_at": execution.get("completed_at"),
        "reconciliation": reconciliation,
        "thread_started": bool(execution.get("codex_thread_id")),
    }


def _timeline(acceptance: dict[str, Any]) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    if acceptance["scheduled_at"] is not None:
        events.append({"event": "scheduled", "status": "recorded", "at": _aware(acceptance["scheduled_at"], "SCHEDULED_AT")})
    if acceptance["started_at"] is not None:
        events.append({"event": "attempt_started", "status": "recorded", "at": _aware(acceptance["started_at"], "STARTED_AT")})
    if acceptance["execution"] == "failed" and acceptance["completed_at"] is not None:
        events.append({"event": "dispatch_failed", "status": "failed", "at": _aware(acceptance["completed_at"], "COMPLETED_AT")})
    reconciliation = acceptance["reconciliation"]
    if reconciliation is not None:
        require(reconciliation.get("outcome") in {"succeeded", "failed"}, "MENTOR_RECONCILIATION_INVALID")
        events.append({
            "event": "operator_reconciled", "status": "resolved",
            "at": _aware(reconciliation.get("verified_at"), "RECONCILED_AT"),
        })
    require(len(events) <= 4, "MENTOR_TIMELINE_INVALID")
    timestamps = [datetime.fromisoformat(item["at"]) for item in events]
    require(
        all(earlier <= later for earlier, later in zip(timestamps, timestamps[1:])),
        "MENTOR_TIMELINE_ORDER_INVALID",
    )
    return events


def _gates(
    engine: dict[str, Any], acceptance: dict[str, Any], head: dict[str, Any],
    required_event_kinds: tuple[str, ...],
) -> dict[str, str]:
    # Profile/STOP have no local engine or ledger predicate; their structured
    # acceptance postconditions are the only admissible positive evidence.
    result = {gate: "not_verified" for gate in _GATE_IDS}
    for gate in acceptance["postconditions"] & {"profile_binding", "stop_propagation"}:
        result[gate] = "verified"

    if engine["attempts"] > 0 and acceptance["scheduled_at"] is not None and acceptance["started_at"] is not None:
        result["future_wake"] = "verified"
    elif acceptance["execution"] == "failed" and engine["attempts"] == 0:
        result["future_wake"] = "failed"
    result["no_duplicate_dispatch"] = (
        "not_verified" if engine["attempts"] == 0 else "verified" if engine["attempts"] == 1 else "failed"
    )

    model_evidence = (
        acceptance["turn_completed"] is True
        and acceptance["dispatch"] == "confirmed_dispatched"
        and bool(head["provider_threads"]) and bool(head["cycle_ids"])
    )
    if model_evidence:
        result["model_turn"] = "verified"
    elif acceptance["execution"] == "failed" and acceptance["dispatch"] == "definitely_not_dispatched":
        result["model_turn"] = "failed"

    journal_evidence = (
        head["status"] == "completed" and not head["pending_effects"]
        and set(required_event_kinds) <= set(head["event_kinds"])
        and "cycle" in head["event_kinds"]
    )
    if journal_evidence:
        result["journal_cycle_postcondition"] = "verified"

    authoritative = {
        "future_wake", "model_turn", "journal_cycle_postcondition", "no_duplicate_dispatch",
    }
    contradicted = acceptance["postconditions"] & authoritative
    require(all(result[gate] == "verified" for gate in contradicted), "MENTOR_GATES_CONTRADICTORY")
    require(set(result) == set(_GATE_IDS) and set(result.values()) <= _GATE_STATES, "MENTOR_GATES_INVALID")
    return result


def _resilience(
    job: dict[str, Any], order: WorkOrder, head: dict[str, Any],
    engine: dict[str, Any], acceptance: dict[str, Any], at: datetime,
    evidence_changed: bool,
) -> dict[str, Any]:
    observed = at.astimezone(UTC)
    host = resilience.HostAssessment(
        "unavailable", "HOST_INSUFFICIENT_SAMPLES", False, 0, None, None, None,
    )
    catch_up = resilience.assess_catch_up(engine["slots"], observed)
    loop = resilience.assess_loop(
        head.get("consecutive_no_progress"),
        order.supervision.max_no_progress_cycles,
        head.get("repeated_action_count"),
        order.supervision.max_repeated_actions,
        evidence_changed,
    )
    scheduler_active = (
        job.get("enabled") is True
        and engine["status"] in {"ready", "running", "retry_wait"}
    )
    provider_active = (
        scheduler_active and engine["status"] == "running"
        and acceptance["thread_started"] is True
    )
    dispatch = acceptance["dispatch"]
    unknown_fence = engine["status"] == "unknown" or dispatch == "possibly_dispatched"
    summary = resilience.build_resilience_summary(
        # The validated inner snapshot is always current.  Freshness and stale
        # overrides belong to the enclosing scheduler packet.
        snapshot_state="current",
        scheduler_active=scheduler_active,
        provider_active=provider_active,
        recovery_unknown=unknown_fence,
        recovery_retry=engine["status"] == "retry_wait",
        recovery_reconcile=engine["code"] == "OPERATOR_RECONCILED",
        host=host,
        catch_up=catch_up,
        loop=loop,
        observed_at=observed,
    )
    require(
        type(summary) is resilience.ResilienceSummary
        and summary.schema_version == 1
        and summary.state in _PREFLIGHT_STATES
        and summary.reason in _PREFLIGHT_REASONS
        and summary.observed_at == observed.isoformat()
        and summary.snapshot == "current"
        and summary.scheduler in {"active", "inactive"}
        and summary.provider in {"active", "inactive"}
        and summary.recovery in {"unknown", "retry", "reconcile", "none"}
        and summary.host == host and summary.catch_up == catch_up and summary.loop == loop,
        "MENTOR_RESILIENCE_INVALID",
    )
    expected_preflight = {
        "schema_version": summary.schema_version,
        "state": summary.state,
        "reason": summary.reason,
        "observed_at": summary.observed_at,
        "snapshot": summary.snapshot,
        "scheduler": summary.scheduler,
        "provider": summary.provider,
        "recovery": summary.recovery,
        "host": {
            "state": host.state, "reason": host.reason, "stable": host.stable,
            "sample_count": host.sample_count,
            "heartbeat_age_seconds": host.heartbeat_age_seconds,
            "last_tick_age_seconds": host.last_tick_age_seconds,
            "watchdog_age_seconds": host.watchdog_age_seconds,
        },
        "catch_up": {
            "state": catch_up.state, "reason": catch_up.reason,
            "total": catch_up.total, "within_grace": catch_up.within_grace,
            "missed": catch_up.missed, "coalesced": catch_up.coalesced,
        },
        "loop": {
            "state": loop.state, "reason": loop.reason,
            "should_dispatch": loop.should_dispatch,
        },
    }
    preflight = summary.as_dict()
    _exact(preflight, _PREFLIGHT_KEYS, "RESILIENCE_PREFLIGHT")
    _exact(preflight["host"], _PREFLIGHT_HOST_KEYS, "RESILIENCE_PREFLIGHT_HOST")
    _exact(preflight["catch_up"], _PREFLIGHT_CATCH_UP_KEYS, "RESILIENCE_PREFLIGHT_CATCH_UP")
    _exact(preflight["loop"], _PREFLIGHT_LOOP_KEYS, "RESILIENCE_PREFLIGHT_LOOP")
    require(preflight == expected_preflight, "MENTOR_RESILIENCE_INVALID")

    delayed = engine["next_attempt"]
    value = {
        "generated_at": observed.isoformat(),
        "status": "ok" if summary.state == "current" else "partial",
        "projection_state": "current",
        "scheduler": {"status": engine["status"], "attempts": engine["attempts"]},
        "provider_safety": {
            # Transport phase/status are not scheduler-engine facts.
            "latest_attempt": None,
            "delayed_until": delayed.isoformat() if delayed is not None else None,
            "delay_source": "backoff" if delayed is not None else None,
            "unknown_fence": unknown_fence,
            "replay_authorization": "not_authorized" if unknown_fence else "not_applicable",
        },
        "mentor": {
            "cycles": _bounded_count(head.get("turns_used"), "RESILIENCE_CYCLES"),
            "no_progress": {
                "used": _bounded_count(head.get("consecutive_no_progress"), "NO_PROGRESS"),
                "limit": _bounded_count(order.supervision.max_no_progress_cycles, "NO_PROGRESS_LIMIT"),
            },
            "repeated": {
                "used": _bounded_count(head.get("repeated_action_count"), "REPEATED"),
                "limit": _bounded_count(order.supervision.max_repeated_actions, "REPEATED_LIMIT"),
            },
            "evidence_reset": evidence_changed,
        },
        "health": {"heartbeat_age_seconds": None, "watchdog_healthy": None},
    }
    _exact(value, _RESILIENCE_KEYS, "RESILIENCE")
    _exact(value["scheduler"], _RESILIENCE_SCHEDULER_KEYS, "RESILIENCE_SCHEDULER")
    provider = _exact(value["provider_safety"], _RESILIENCE_PROVIDER_KEYS, "RESILIENCE_PROVIDER")
    mentor = _exact(value["mentor"], _RESILIENCE_MENTOR_KEYS, "RESILIENCE_MENTOR")
    _exact(mentor["no_progress"], _RESILIENCE_BUDGET_KEYS, "RESILIENCE_NO_PROGRESS")
    _exact(mentor["repeated"], _RESILIENCE_BUDGET_KEYS, "RESILIENCE_REPEATED")
    _exact(value["health"], _RESILIENCE_HEALTH_KEYS, "RESILIENCE_HEALTH")
    require(
        mentor["no_progress"]["used"] <= mentor["no_progress"]["limit"]
        and mentor["repeated"]["used"] <= mentor["repeated"]["limit"]
        and ((provider["delayed_until"] is None) == (provider["delay_source"] is None))
        and (
            not provider["unknown_fence"]
            or (
                (provider["latest_attempt"] is None
                 or (isinstance(provider["latest_attempt"], dict)
                     and provider["latest_attempt"].get("status") == "unknown"))
                and provider["replay_authorization"] in {"reconciliation_required", "not_authorized"}
            )
        )
        and (provider["unknown_fence"] or provider["replay_authorization"] != "reconciliation_required"),
        "MENTOR_RESILIENCE_INVALID",
    )
    return value


def _mentor(root: Path, job: dict[str, Any], at: datetime) -> dict[str, Any]:
    options = job.get("adapter_config")
    require(isinstance(options, dict), "MENTOR_CONFIG_INVALID")
    order, _store, head, evidence_changed = _work_order(root, options)
    status = head.get("status")
    require(status in _SESSION_STATES, "MENTOR_SESSION_STATE_INVALID")
    revision = _bounded_count(head.get("revision"), "REVISION")
    turns = _bounded_count(head.get("turns_used"), "TURNS")
    collections = {
        "provider_threads": head.get("provider_threads"), "variants": head.get("variants"),
        "interventions": head.get("interventions"), "reused_evaluations": head.get("reused_evaluations"),
        "pending_effects": head.get("pending_effects"), "event_kinds": head.get("event_kinds"),
        "cycle_ids": head.get("cycle_ids"),
    }
    require(all(isinstance(value, list) for value in collections.values()), "MENTOR_SESSION_STATE_INVALID")
    require(revision == len(collections["event_kinds"]), "MENTOR_SESSION_STATE_INVALID")
    limits = {
        "cycles": order.execution.max_turns,
        "provider_threads": order.logical_session.max_provider_threads,
        "variants": order.evidence_policy.max_variants,
        "interventions": order.supervision.max_interventions,
        "reused_evaluations": order.evidence_policy.max_reused_evaluations,
    }
    used = {
        "cycles": turns,
        "provider_threads": len(collections["provider_threads"]),
        "variants": len(collections["variants"]),
        "interventions": len(collections["interventions"]),
        "reused_evaluations": len(collections["reused_evaluations"]),
    }
    require(all(_bounded_count(value, key.upper()) <= limits[key] for key, value in used.items()), "MENTOR_BUDGET_INVALID")
    require(at.tzinfo is not None and at.utcoffset() is not None, "MENTOR_TIME_INVALID")
    now = at.astimezone(UTC)
    engine = _engine(root, job["id"], now)
    acceptance = _acceptance(root, options, job["id"])
    _bind_reconciliation(root, engine, acceptance)
    require(not (acceptance["dispatch"] == "definitely_not_dispatched" and acceptance["turn_completed"] is True), "MENTOR_DISPATCH_INVALID")
    if acceptance["dispatch"] == "not_attempted":
        require(engine["attempts"] == 0, "MENTOR_DISPATCH_INVALID")
    gate_states = _gates(engine, acceptance, head, order.completion.required_event_kinds)
    if acceptance["acceptance"] == "passed":
        require(
            acceptance["turn_completed"] is True and engine["attempts"] == 1
            and head["status"] == "completed" and all(value == "verified" for value in gate_states.values()),
            "MENTOR_ACCEPTANCE_STATE_INVALID",
        )
    start = order.execution.starts_at.astimezone(UTC)
    end = order.execution.ends_at.astimezone(UTC)
    window_state = "upcoming" if now < start else "open" if now < end else "expired"
    model_turn = (
        "completed" if acceptance["turn_completed"] is True
        else "started" if acceptance["thread_started"]
        else "not_started" if acceptance["turn_completed"] is False and acceptance["dispatch"] in {"not_attempted", "definitely_not_dispatched"}
        else "unknown"
    )
    return {
        "work_order": {
            "id": order.work_order_id,
            "logical_session_id": order.logical_session.logical_session_id,
            "starts_at": start.isoformat(), "ends_at": end.isoformat(), "window_state": window_state,
            "acceptance_criteria_total": len(order.acceptance_criteria),
            "required_event_kinds": list(order.completion.required_event_kinds),
        },
        "scheduler": {
            "status": engine["status"], "code": engine["code"],
            "attempts": engine["attempts"], "dispatch": acceptance["dispatch"],
        },
        "session": {"status": status, "revision": revision},
        "progress": {
            **{key: {"used": used[key], "limit": limits[key]} for key in used},
            "pending_effects": len(collections["pending_effects"]),
        },
        "safeguards": {
            "provider_thread_mode": order.logical_session.provider_thread_mode,
            "record_all_variants": order.evidence_policy.record_all_variants,
            "worker_holdout_access": order.evidence_policy.worker_holdout_access,
            "require_no_pending_effects": order.completion.require_no_pending_effects,
            "configured_replay_safe": job.get("replay_safe") is True,
            "replay_authorization": "not_authorized",
        },
        "gates": gate_states,
        "evaluation": {
            "attempt_ledger_preserved": True,
            "baseline": "pending", "ablation": "not_required", "holdout": "unverified", "promotion": "inconclusive",
        },
        "runtime_acceptance": {
            "execution": acceptance["execution"], "acceptance": acceptance["acceptance"],
            "model_turn": model_turn, "email": acceptance["email"],
        },
        "recovery_timeline": _timeline(acceptance),
        "resilience": _resilience(
            job, order, head, engine, acceptance, at, evidence_changed,
        ),
    }


def describe(root, job, at, *, next_tick, detail=False, output_id=None):
    """Describe only the fixed mentor adapter without exposing evidence payloads."""
    del next_tick, detail
    require(output_id is None, "DASHBOARD_OUTPUT_NOT_FOUND")
    result = {
        "job_type": "mentor",
        "title": "Mentor scheduler acceptance",
        "description": "Read-only mentor scheduler status.",
        "delivery": {"mode": "acceptance", "next_send_at": None, "note": "Runtime acceptance email status is shown separately."},
        "outputs": [],
    }
    try:
        result["mentor"] = _mentor(Path(root), job, at)
    except (OSError, UnicodeError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error):
        result["mentor"] = {"status": "unavailable"}
    return result
