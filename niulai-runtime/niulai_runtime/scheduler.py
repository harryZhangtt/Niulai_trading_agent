"""Admission only; no timer, external scheduler, or email sender is installed."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo
from .config import RuntimeConfig


@dataclass(frozen=True)
class CutoverEvidence:
    """Caller-verified references, not flags to infer from a saved config.

    The orchestrator must actually inspect old-scheduler disablement and import
    existing delivery records before constructing this object. This module
    cannot query the cloud scheduler and does not claim to verify it.
    """
    previous_sender_disabled_receipt: str
    delivery_ledger_import_receipt: str
    runtime_owner: str


@dataclass(frozen=True)
class Admission:
    allowed: bool
    reason: str
    mode: str
    ny_date: str | None = None
    slot: str | None = None
    delivery_key: str | None = None
    send_allowed: bool = False


def admit(config: RuntimeConfig, now: datetime, calendar, actor_id: str,
          manual_request_id: str | None = None, completed_keys=(),
          cutover: CutoverEvidence | None = None) -> Admission:
    """Evaluate a wake using actual aware time; never call with backdated time.

    Tests can inject time/calendar. Production calendar must be a real XNYS
    adapter whose is_session(date) raises when coverage is unavailable. Caller
    must atomically claim the returned key in the delivery ledger; this pure
    check alone is NOT cross-process duplicate protection.
    """
    def reject(reason):
        return Admission(False, reason, config.mode)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return reject("AWARE_CLOCK_REQUIRED")
    if actor_id != config.scheduler_owner:
        return reject("SCHEDULER_OWNER_MISMATCH")
    local = now.astimezone(ZoneInfo(config.timezone))
    day = local.date().isoformat()
    if config.mode == "manual_test":
        if not isinstance(manual_request_id, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", manual_request_id):
            return reject("MANUAL_REQUEST_ID_REQUIRED")
        # No date in this key: replaying the same authorized test tomorrow
        # must not silently authorize a second send.
        key = f"manual-email:{config.automation_id}:{manual_request_id}:{config.recipient}"
        if key in completed_keys:
            return reject("DELIVERY_ALREADY_RECORDED")
        return Admission(True, "MANUAL_TEST", config.mode, day, None, key, True)
    if manual_request_id is not None:
        return reject("MANUAL_ID_FORBIDDEN")
    if config.mode == "production":
        if not config.production_enabled:
            return reject("PRODUCTION_DISABLED")
        if not isinstance(cutover, CutoverEvidence) or cutover.runtime_owner != actor_id or not all(
                isinstance(x, str) and x.strip() for x in (
                    cutover.previous_sender_disabled_receipt, cutover.delivery_ledger_import_receipt)):
            return reject("CUTOVER_EVIDENCE_REQUIRED")
    if calendar is None or getattr(calendar, "name", None) != config.calendar:
        return reject("XNYS_CALENDAR_REQUIRED")
    try:
        session = calendar.is_session(local.date())
        if type(session) is not bool:
            return reject("CALENDAR_RESULT_INVALID")
    except Exception:
        return reject("CALENDAR_UNAVAILABLE")
    if not session:
        return reject("NOT_XNYS_SESSION")
    due = []
    for slot in config.slots:
        hour, minute = map(int, slot.split(":"))
        scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= local <= scheduled + timedelta(minutes=config.grace_minutes):
            due.append(slot)
    if len(due) != 1:
        return reject("OUTSIDE_DUE_WINDOW")
    slot = due[0]
    # Preserve the source workflow's production key across code/config revisions.
    key = f"portfolio-email:{config.automation_id}:{day}:{slot}:{config.recipient}"
    if key in completed_keys:
        return reject("DELIVERY_ALREADY_RECORDED")
    return Admission(True, "DUE", config.mode, day, slot, key,
                     config.mode == "production")
