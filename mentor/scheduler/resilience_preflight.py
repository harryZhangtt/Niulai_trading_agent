"""Pure, read-only resilience preflight assessments for sanitized facts.

This module deliberately performs no discovery or I/O.  Callers remain responsible
for collecting and sanitizing host, slot, snapshot, and recovery observations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

UTC = timezone.utc
MAX_SLOTS = 256
MAX_COUNT = 1_000_000
MAX_STALE_SECONDS = 31_536_000

_HOST_STATES = frozenset({"ready", "stale", "unavailable"})
_CATCH_UP_STATES = frozenset({"within_grace", "missed", "coalesced", "not_computable"})
_LOOP_STATES = frozenset({"neutral", "info", "warning", "critical", "unavailable"})
_SNAPSHOT_STATES = frozenset({"current", "partial", "stale"})
_SLOT_STATUSES = frozenset({
    "ready", "running", "retry_wait", "succeeded", "failed", "unknown",
    "missed", "coalesced",
})
_SLOT_KEYS = frozenset({"status", "scheduled", "updated", "attempts"})


@dataclass(frozen=True)
class HostAssessment:
    state: str
    reason: str
    stable: bool
    sample_count: int
    heartbeat_age_seconds: Optional[int]
    last_tick_age_seconds: Optional[int]
    watchdog_age_seconds: Optional[int]


@dataclass(frozen=True)
class CatchUpAssessment:
    state: str
    reason: str
    total: int
    within_grace: int
    missed: int
    coalesced: int


@dataclass(frozen=True)
class LoopAssessment:
    state: str
    reason: str
    should_dispatch: bool


@dataclass(frozen=True)
class ResilienceSummary:
    """Bounded projection contract for a future scheduler-view adapter."""

    schema_version: int
    state: str
    reason: str
    observed_at: str
    snapshot: str
    scheduler: str
    provider: str
    recovery: str
    host: HostAssessment
    catch_up: CatchUpAssessment
    loop: LoopAssessment

    def as_dict(self) -> dict[str, Any]:
        """Return the exact public projection; it contains no identity material."""

        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "reason": self.reason,
            "observed_at": self.observed_at,
            "snapshot": self.snapshot,
            "scheduler": self.scheduler,
            "provider": self.provider,
            "recovery": self.recovery,
            "host": {
                "state": self.host.state,
                "reason": self.host.reason,
                "stable": self.host.stable,
                "sample_count": self.host.sample_count,
                "heartbeat_age_seconds": self.host.heartbeat_age_seconds,
                "last_tick_age_seconds": self.host.last_tick_age_seconds,
                "watchdog_age_seconds": self.host.watchdog_age_seconds,
            },
            "catch_up": {
                "state": self.catch_up.state,
                "reason": self.catch_up.reason,
                "total": self.catch_up.total,
                "within_grace": self.catch_up.within_grace,
                "missed": self.catch_up.missed,
                "coalesced": self.catch_up.coalesced,
            },
            "loop": {
                "state": self.loop.state,
                "reason": self.loop.reason,
                "should_dispatch": self.loop.should_dispatch,
            },
        }


def _utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        offset = value.utcoffset()
    except (TypeError, ValueError, OverflowError):
        return None
    if offset != timedelta(0):
        return None
    try:
        return value.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def _strict_bool(value: Any) -> bool:
    return type(value) is bool


def _bounded_int(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _host_unavailable(reason: str) -> HostAssessment:
    return HostAssessment("unavailable", reason, False, 0, None, None, None)


def assess_host(
    daemon_registered: Any,
    service_generation_current: Any,
    heartbeat_at: Any,
    last_tick_at: Any,
    watchdog_checked_at: Any,
    watchdog_healthy: Any,
    now: Any,
    stale_seconds: Any,
) -> HostAssessment:
    """Assess supplied host facts without probing the host.

    Timestamp observations are optional individually, but at least two distinct
    supplied observations are required before ``stable`` can be true.  Freshness
    is inclusive at ``stale_seconds``; a greater age is stale.  A timestamp later
    than ``now`` is treated as a clock rollback/future-observation failure.
    """

    instant = _utc(now)
    if (
        not _strict_bool(daemon_registered)
        or not _strict_bool(service_generation_current)
        or instant is None
        or not _bounded_int(stale_seconds, 1, MAX_STALE_SECONDS)
        or watchdog_healthy is not None and not _strict_bool(watchdog_healthy)
    ):
        return _host_unavailable("HOST_INPUT_INVALID")

    raw_samples = (heartbeat_at, last_tick_at, watchdog_checked_at)
    parsed: list[Optional[datetime]] = []
    for value in raw_samples:
        if value is None:
            parsed.append(None)
            continue
        sample = _utc(value)
        if sample is None:
            return _host_unavailable("HOST_INPUT_INVALID")
        parsed.append(sample)

    if (watchdog_checked_at is None) != (watchdog_healthy is None):
        return _host_unavailable("HOST_INPUT_INVALID")
    if not daemon_registered:
        return _host_unavailable("HOST_DAEMON_UNREGISTERED")
    if not service_generation_current:
        return _host_unavailable("HOST_SERVICE_GENERATION_STALE")
    if watchdog_healthy is False:
        return _host_unavailable("HOST_WATCHDOG_UNHEALTHY")

    samples = [sample for sample in parsed if sample is not None]
    if any(sample > instant for sample in samples):
        return _host_unavailable("HOST_CLOCK_ROLLBACK")
    if len(samples) < 2:
        return HostAssessment(
            "unavailable", "HOST_INSUFFICIENT_SAMPLES", False, len(samples),
            None, None, None,
        )

    ages = [
        None if sample is None
        else min(int((instant - sample).total_seconds()), MAX_STALE_SECONDS + 1)
        for sample in parsed
    ]
    stale = any(instant - sample > timedelta(seconds=stale_seconds) for sample in samples)
    return HostAssessment(
        "stale" if stale else "ready",
        "HOST_OBSERVATION_STALE" if stale else "HOST_READY_STABLE",
        not stale,
        len(samples),
        ages[0],
        ages[1],
        ages[2],
    )


def _catch_up_unavailable(reason: str = "CATCH_UP_INPUT_INVALID") -> CatchUpAssessment:
    return CatchUpAssessment("not_computable", reason, 0, 0, 0, 0)


def assess_catch_up(slots: Any, observed_at: Any) -> CatchUpAssessment:
    """Classify bounded sanitized slot rows and return exact category counts.

    This assessment intentionally does not infer or expose a ``sleep_detected``
    claim.  Without a caller-supplied grace duration, a valid non-missed and
    non-coalesced row means only that it remained within the supplied slot facts.
    """

    observed = _utc(observed_at)
    if observed is None or not isinstance(slots, (list, tuple)):
        return _catch_up_unavailable()
    if not 1 <= len(slots) <= MAX_SLOTS:
        return _catch_up_unavailable("CATCH_UP_NO_BOUNDED_OBSERVATIONS")

    counts = {"within_grace": 0, "missed": 0, "coalesced": 0}
    for row in slots:
        if not isinstance(row, Mapping) or frozenset(row.keys()) != _SLOT_KEYS:
            return _catch_up_unavailable()
        status = row["status"]
        scheduled = _utc(row["scheduled"])
        updated = _utc(row["updated"])
        attempts = row["attempts"]
        if (
            type(status) is not str
            or status not in _SLOT_STATUSES
            or scheduled is None
            or updated is None
            or not _bounded_int(attempts, 0, MAX_COUNT)
            or scheduled > updated
            or updated > observed
        ):
            return _catch_up_unavailable()
        if status == "ready" and attempts != 0:
            return _catch_up_unavailable()
        if status not in {"ready", "missed", "coalesced"} and attempts == 0:
            return _catch_up_unavailable()
        counts[status if status in {"missed", "coalesced"} else "within_grace"] += 1

    total = len(slots)
    if counts["coalesced"]:
        state, reason = "coalesced", "CATCH_UP_COALESCED"
    elif counts["missed"]:
        state, reason = "missed", "CATCH_UP_MISSED"
    else:
        state, reason = "within_grace", "CATCH_UP_WITHIN_GRACE"
    return CatchUpAssessment(
        state, reason, total,
        counts["within_grace"], counts["missed"], counts["coalesced"],
    )


def assess_loop(
    consecutive_no_progress: Any,
    max_no_progress: Any,
    repeated_action: Any,
    max_repeated: Any,
    verified_evidence_changed: Any,
) -> LoopAssessment:
    """Apply exact inclusive supervision thresholds to sanitized counters."""

    if (
        not _bounded_int(consecutive_no_progress, 0, MAX_COUNT)
        or not _bounded_int(max_no_progress, 1, MAX_COUNT)
        or not _bounded_int(repeated_action, 0, MAX_COUNT)
        or not _bounded_int(max_repeated, 1, MAX_COUNT)
        or not _strict_bool(verified_evidence_changed)
    ):
        return LoopAssessment("unavailable", "LOOP_INPUT_INVALID", False)
    if verified_evidence_changed:
        return LoopAssessment("neutral", "LOOP_VERIFIED_EVIDENCE_RESET", False)

    no_progress_limit = consecutive_no_progress >= max_no_progress
    repeated_limit = repeated_action >= max_repeated
    if no_progress_limit and repeated_limit:
        return LoopAssessment("critical", "LOOP_BOTH_THRESHOLDS_REACHED", True)
    if no_progress_limit:
        return LoopAssessment("warning", "LOOP_NO_PROGRESS_THRESHOLD_REACHED", True)
    if repeated_limit:
        return LoopAssessment("warning", "LOOP_REPEATED_THRESHOLD_REACHED", True)
    if consecutive_no_progress or repeated_action:
        return LoopAssessment("info", "LOOP_BELOW_THRESHOLDS", False)
    return LoopAssessment("neutral", "LOOP_CLEAR", False)


def _valid_host(value: Any) -> bool:
    if type(value) is not HostAssessment:
        return False
    if (
        type(value.state) is not str
        or type(value.reason) is not str
        or not _strict_bool(value.stable)
        or not _bounded_int(value.sample_count, 0, 3)
    ):
        return False
    ages = (
        value.heartbeat_age_seconds,
        value.last_tick_age_seconds,
        value.watchdog_age_seconds,
    )
    if any(age is not None and not _bounded_int(age, 0, MAX_STALE_SECONDS + 1) for age in ages):
        return False
    supplied_ages = sum(age is not None for age in ages)
    unavailable_reasons = {
        "HOST_INPUT_INVALID",
        "HOST_DAEMON_UNREGISTERED",
        "HOST_SERVICE_GENERATION_STALE",
        "HOST_WATCHDOG_UNHEALTHY",
        "HOST_CLOCK_ROLLBACK",
    }
    if value.state == "unavailable":
        if value.stable or any(age is not None for age in ages):
            return False
        if value.reason == "HOST_INSUFFICIENT_SAMPLES":
            return value.sample_count in {0, 1}
        return value.reason in unavailable_reasons and value.sample_count == 0
    if value.state == "ready":
        return (
            value.reason == "HOST_READY_STABLE"
            and value.stable
            and value.sample_count in {2, 3}
            and supplied_ages == value.sample_count
        )
    if value.state == "stale":
        return (
            value.reason == "HOST_OBSERVATION_STALE"
            and not value.stable
            and value.sample_count in {2, 3}
            and supplied_ages == value.sample_count
        )
    return False


def _valid_catch_up(value: Any) -> bool:
    if type(value) is not CatchUpAssessment:
        return False
    if type(value.state) is not str or type(value.reason) is not str:
        return False
    counts = (value.total, value.within_grace, value.missed, value.coalesced)
    if not all(_bounded_int(count, 0, MAX_SLOTS) for count in counts):
        return False
    if value.state == "not_computable":
        return (
            value.reason in {"CATCH_UP_INPUT_INVALID", "CATCH_UP_NO_BOUNDED_OBSERVATIONS"}
            and counts == (0, 0, 0, 0)
        )
    if not 1 <= value.total <= MAX_SLOTS:
        return False
    if value.within_grace + value.missed + value.coalesced != value.total:
        return False
    if value.state == "within_grace":
        return value.reason == "CATCH_UP_WITHIN_GRACE" and value.missed == value.coalesced == 0
    if value.state == "missed":
        return value.reason == "CATCH_UP_MISSED" and value.missed > 0 and value.coalesced == 0
    if value.state == "coalesced":
        return value.reason == "CATCH_UP_COALESCED" and value.coalesced > 0
    return False


def _valid_loop(value: Any) -> bool:
    if (
        type(value) is not LoopAssessment
        or type(value.state) is not str
        or type(value.reason) is not str
        or not _strict_bool(value.should_dispatch)
    ):
        return False
    allowed = {
        "unavailable": ({"LOOP_INPUT_INVALID"}, False),
        "neutral": ({"LOOP_VERIFIED_EVIDENCE_RESET", "LOOP_CLEAR"}, False),
        "info": ({"LOOP_BELOW_THRESHOLDS"}, False),
        "warning": ({"LOOP_NO_PROGRESS_THRESHOLD_REACHED", "LOOP_REPEATED_THRESHOLD_REACHED"}, True),
        "critical": ({"LOOP_BOTH_THRESHOLDS_REACHED"}, True),
    }
    if value.state not in allowed:
        return False
    reasons, dispatch = allowed[value.state]
    return value.reason in reasons and value.should_dispatch is dispatch


def _summary_fallback(observed_at: Any) -> ResilienceSummary:
    observed = _utc(observed_at)
    rendered = observed.isoformat() if observed is not None else "unavailable"
    return ResilienceSummary(
        1, "unavailable", "SUMMARY_INPUT_INVALID", rendered,
        "unavailable", "unavailable", "unavailable", "unknown",
        _host_unavailable("HOST_INPUT_INVALID"),
        _catch_up_unavailable(),
        LoopAssessment("unavailable", "LOOP_INPUT_INVALID", False),
    )


def build_resilience_summary(
    *,
    snapshot_state: Any,
    scheduler_active: Any,
    provider_active: Any,
    recovery_unknown: Any,
    recovery_retry: Any,
    recovery_reconcile: Any,
    host: Any,
    catch_up: Any,
    loop: Any,
    observed_at: Any,
) -> ResilienceSummary:
    """Combine sanitized assessments into an exact, privacy-bounded snapshot.

    An unknown recovery outcome is a fence and has precedence over every optimistic
    state.  Reconciliation has precedence over retry when both are reported.
    Invalid component DTOs or values fail closed to an unavailable summary.
    """

    observed = _utc(observed_at)
    booleans = (scheduler_active, provider_active, recovery_unknown, recovery_retry, recovery_reconcile)
    if (
        type(snapshot_state) is not str
        or snapshot_state not in _SNAPSHOT_STATES
        or any(not _strict_bool(value) for value in booleans)
        or provider_active and not scheduler_active
        or observed is None
        or not _valid_host(host)
        or not _valid_catch_up(catch_up)
        or not _valid_loop(loop)
    ):
        return _summary_fallback(observed_at)

    recovery = (
        "unknown" if recovery_unknown
        else "reconcile" if recovery_reconcile
        else "retry" if recovery_retry
        else "none"
    )
    scheduler = "active" if scheduler_active else "inactive"
    provider = "active" if provider_active else "inactive"

    if recovery == "unknown":
        state, reason = "unavailable", "SUMMARY_RECOVERY_UNKNOWN_FENCE"
    elif host.state == "unavailable" or catch_up.state == "not_computable" or loop.state == "unavailable":
        state, reason = "unavailable", "SUMMARY_COMPONENT_UNAVAILABLE"
    elif snapshot_state == "stale" or host.state == "stale":
        state, reason = "stale", "SUMMARY_STALE"
    elif (
        snapshot_state == "partial"
        or not scheduler_active
        or not provider_active
        or recovery != "none"
        or catch_up.state in {"missed", "coalesced"}
        or loop.state in {"warning", "critical"}
    ):
        state, reason = "partial", "SUMMARY_PARTIAL"
    else:
        state, reason = "current", "SUMMARY_CURRENT"

    return ResilienceSummary(
        1, state, reason, observed.isoformat(), snapshot_state,
        scheduler, provider, recovery, host, catch_up, loop,
    )
