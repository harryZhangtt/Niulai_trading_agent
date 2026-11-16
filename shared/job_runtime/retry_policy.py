"""Deterministic provider-neutral retry policy with no clocks or sleeping."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
from typing import Any, Mapping

from .provider_contract import FailureKind, ProviderResultV1, ResultStatus


class RetryPolicyError(ValueError):
    """A stable policy/input error."""


def _fail(code: str) -> None:
    raise RetryPolicyError(code)


def _number(value: Any, *, positive: bool = False, allow_zero: bool = True) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        _fail("RETRY_POLICY_NUMBER_INVALID")
    result = float(value)
    if result < 0 or (positive and (result == 0 and not allow_zero)):
        _fail("RETRY_POLICY_NUMBER_INVALID")
    return result


@dataclass(frozen=True)
class RetryPolicyV2:
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float
    deadline_seconds: float | None = None
    version: int = 2
    jitter: str = "sha256-full-jitter-v1"

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != 2 or type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            _fail("RETRY_POLICY_INVALID")
        base = _number(self.base_delay_seconds, positive=True, allow_zero=False)
        maximum = _number(self.max_delay_seconds, positive=True, allow_zero=False)
        if base > maximum or maximum > 86400 * 30:
            _fail("RETRY_POLICY_INVALID")
        deadline = None if self.deadline_seconds is None else _number(self.deadline_seconds, positive=True, allow_zero=False)
        if deadline is not None and deadline > 86400 * 365:
            _fail("RETRY_POLICY_INVALID")
        if self.jitter != "sha256-full-jitter-v1":
            _fail("RETRY_POLICY_JITTER_INVALID")
        object.__setattr__(self, "base_delay_seconds", base)
        object.__setattr__(self, "max_delay_seconds", maximum)
        object.__setattr__(self, "deadline_seconds", deadline)

    @property
    def fingerprint(self) -> str:
        payload = {"base_delay_seconds": self.base_delay_seconds,
                   "deadline_seconds": self.deadline_seconds,
                   "jitter": self.jitter, "max_attempts": self.max_attempts,
                   "max_delay_seconds": self.max_delay_seconds, "version": 2}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class RetryDecision:
    disposition: str
    reason: str
    attempt: int
    policy_fingerprint: str
    delay_seconds: float | None = None
    selected_next_at: datetime | None = None
    persistable_next_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.disposition not in ("succeeded", "terminal_failed", "unknown", "retry"):
            _fail("RETRY_DECISION_INVALID")
        if type(self.reason) is not str or not self.reason or type(self.attempt) is not int or self.attempt < 1:
            _fail("RETRY_DECISION_INVALID")
        if self.disposition == "retry":
            if self.delay_seconds is None or self.selected_next_at is None or self.persistable_next_at is None:
                _fail("RETRY_DECISION_INVALID")
            if self.selected_next_at != self.persistable_next_at:
                _fail("RETRY_DECISION_NOT_PERSISTABLE")
        elif any(value is not None for value in (self.delay_seconds, self.selected_next_at, self.persistable_next_at)):
            _fail("RETRY_DECISION_INVALID")


_MAX_RETRY_AFTER_SECONDS = 30 * 86400
_V2_KEYS = {"version", "max_attempts", "base_delay_seconds", "max_delay_seconds", "deadline_seconds", "jitter"}
_LEGACY_KEYS = {"max_attempts", "max_retries", "base_delay_seconds", "initial_delay_seconds",
                "max_delay_seconds", "deadline_seconds"}


def validate_retry_policy(value: RetryPolicyV2 | Mapping[str, Any]) -> RetryPolicyV2:
    """Validate v2 or normalize the bounded legacy policy shape to v2."""
    if isinstance(value, RetryPolicyV2):
        return value
    if type(value) is not dict:
        _fail("RETRY_POLICY_INVALID")
    if value.get("version") == 2:
        if type(value.get("version")) is not int:
            _fail("RETRY_POLICY_INVALID")
        if set(value) - _V2_KEYS or not {"version", "max_attempts", "base_delay_seconds", "max_delay_seconds"} <= set(value):
            _fail("RETRY_POLICY_INVALID")
        return RetryPolicyV2(max_attempts=value["max_attempts"],
                             base_delay_seconds=value["base_delay_seconds"],
                             max_delay_seconds=value["max_delay_seconds"],
                             deadline_seconds=value.get("deadline_seconds"),
                             jitter=value.get("jitter", "sha256-full-jitter-v1"))
    if "version" in value or set(value) - _LEGACY_KEYS:
        _fail("RETRY_POLICY_INVALID")
    if ("max_attempts" in value) == ("max_retries" in value):
        _fail("RETRY_POLICY_INVALID")
    if ("base_delay_seconds" in value) == ("initial_delay_seconds" in value):
        _fail("RETRY_POLICY_INVALID")
    attempts = value.get("max_attempts", value.get("max_retries") + 1 if type(value.get("max_retries")) is int else None)
    base = value.get("base_delay_seconds", value.get("initial_delay_seconds"))
    if attempts is None or base is None or "max_delay_seconds" not in value:
        _fail("RETRY_POLICY_INVALID")
    return RetryPolicyV2(attempts, base, value["max_delay_seconds"], value.get("deadline_seconds"))


def _aware(value: datetime, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        _fail(code)
    return value


def parse_retry_after(value: Any, source: str, *, now: datetime, past_skew_seconds: float = 1.0) -> datetime:
    """Parse a typed provider wait into an aware timestamp.

    Sources are ``retry-after-ms``, ``retry-after-seconds``, ``http-date`` and
    ``typed-timestamp``.  Untyped guessing is intentionally unsupported.
    """
    now = _aware(now, "RETRY_NOW_INVALID")
    skew = _number(past_skew_seconds)
    try:
        if source in ("retry-after-ms", "retry-after-seconds"):
            if type(value) is str and len(value) <= 32:
                try:
                    value = float(value)
                except ValueError:
                    _fail("RETRY_AFTER_INVALID")
            try:
                amount = _number(value)
            except RetryPolicyError:
                _fail("RETRY_AFTER_INVALID")
            seconds = amount / 1000.0 if source == "retry-after-ms" else amount
            if seconds > _MAX_RETRY_AFTER_SECONDS:
                _fail("RETRY_AFTER_INVALID")
            result = now + timedelta(seconds=seconds)
        elif source == "http-date":
            if type(value) is not str or len(value) > 128:
                _fail("RETRY_AFTER_INVALID")
            try:
                result = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError, OSError):
                _fail("RETRY_AFTER_INVALID")
            if result.tzinfo is None or result.utcoffset() is None:
                _fail("RETRY_AFTER_INVALID")
        elif source == "typed-timestamp":
            if isinstance(value, datetime):
                result = _aware(value, "RETRY_AFTER_INVALID")
            elif type(value) is str and len(value) <= 64:
                try:
                    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (ValueError, OverflowError, OSError):
                    _fail("RETRY_AFTER_INVALID")
                _aware(result, "RETRY_AFTER_INVALID")
            else:
                _fail("RETRY_AFTER_INVALID")
        else:
            _fail("RETRY_AFTER_SOURCE_INVALID")
        now_utc = now.astimezone(timezone.utc)
        result = result.astimezone(timezone.utc)
        delta = (result - now_utc).total_seconds()
        if delta < -skew:
            _fail("RETRY_AFTER_PAST")
        if delta > _MAX_RETRY_AFTER_SECONDS:
            _fail("RETRY_AFTER_INVALID")
        return max(result, now_utc)
    except (OverflowError, OSError):
        _fail("RETRY_AFTER_INVALID")


def deterministic_full_jitter(*, slot_id: str, attempt: int, policy: RetryPolicyV2) -> float:
    """Stable SHA-256 full-jitter in [0, exponential cap)."""
    if type(slot_id) is not str or not slot_id or len(slot_id) > 256 or type(attempt) is not int or attempt < 1:
        _fail("RETRY_JITTER_INPUT_INVALID")
    cap = min(policy.max_delay_seconds, math.ldexp(policy.base_delay_seconds, min(attempt - 1, 62)))
    seed = f"sha256-full-jitter-v1\0{slot_id}\0{attempt}\0{policy.fingerprint}".encode()
    fraction = int.from_bytes(hashlib.sha256(seed).digest(), "big") / (1 << 256)
    return cap * fraction


_PERMANENT_LOCAL_CODES = frozenset({
    "MODEL_AUTH_REQUIRED", "MODEL_UNAVAILABLE", "MODEL_CONFIGURATION_REJECTED",
    "MODEL_POLICY_VIOLATION", "MODEL_PATH_INVALID", "MODEL_PATH_OUTSIDE_STATE",
    "MODEL_PATH_SYMLINK", "MODEL_SOCKET_INVALID", "UNIX_SOCKET_INVALID",
    "LOCAL_PATH_INVALID", "LOCAL_CONFIGURATION_INVALID", "PROVIDER_CONFIG_INVALID",
})


def decide_retry(result: ProviderResultV1, policy: RetryPolicyV2 | Mapping[str, Any], *,
                 slot_id: str, attempt: int, now: datetime,
                 deadline: datetime | None = None) -> RetryDecision:
    """Classify one result and, if safe, select a deterministic next timestamp."""
    if not isinstance(result, ProviderResultV1):
        _fail("RETRY_RESULT_INVALID")
    policy = validate_retry_policy(policy)
    now = _aware(now, "RETRY_NOW_INVALID").astimezone(timezone.utc)
    if type(attempt) is not int or attempt < 1:
        _fail("RETRY_ATTEMPT_INVALID")
    if deadline is not None:
        deadline = _aware(deadline, "RETRY_DEADLINE_INVALID").astimezone(timezone.utc)
    fingerprint = policy.fingerprint

    def terminal(disposition: str, reason: str) -> RetryDecision:
        return RetryDecision(disposition, reason, attempt, fingerprint)

    if result.status is ResultStatus.SUCCEEDED:
        return terminal("succeeded", "PROVIDER_SUCCEEDED")
    if result.status is ResultStatus.UNKNOWN:
        return terminal("unknown", "PROVIDER_OUTCOME_UNKNOWN")
    if result.failure_kind is FailureKind.QUOTA_EXHAUSTED:
        return terminal("terminal_failed", "PROVIDER_QUOTA_EXHAUSTED")
    if result.status is ResultStatus.FAILED:
        return terminal("terminal_failed", "PROVIDER_TERMINAL_FAILURE")
    if result.code in _PERMANENT_LOCAL_CODES or result.failure_kind in {
            FailureKind.QUOTA_EXHAUSTED, FailureKind.AUTH, FailureKind.CONFIG,
            FailureKind.MODEL, FailureKind.POLICY, FailureKind.LOCAL_CONFIG}:
        return terminal("terminal_failed", "PERMANENT_LOCAL_FAILURE")
    if result.provider_should_retry is False:
        return terminal("terminal_failed", "PROVIDER_RETRY_DENIED")
    if not result.safe_retry_candidate:
        return terminal("unknown", "REPLAY_AUTHORITY_ABSENT")
    if result.failure_kind is FailureKind.HTTP and not result.typed_http_retry_candidate and result.provider_should_retry is not True:
        return terminal("terminal_failed", "HTTP_STATUS_NOT_RETRYABLE")
    if attempt >= policy.max_attempts:
        return terminal("terminal_failed", "ATTEMPTS_EXHAUSTED")

    selected = now + timedelta(seconds=deterministic_full_jitter(slot_id=slot_id, attempt=attempt, policy=policy))
    if result.retry_after_at is not None:
        provider_at = result.retry_after_at.astimezone(timezone.utc)
        if provider_at < now:
            return terminal("terminal_failed", "PROVIDER_WAIT_INVALID")
        if (provider_at - now).total_seconds() > policy.max_delay_seconds:
            # Capping would violate the provider's minimum wait.
            return terminal("terminal_failed", "PROVIDER_WAIT_EXCEEDS_MAX")
        selected = max(selected, provider_at)
    effective_deadline = deadline
    if policy.deadline_seconds is not None:
        policy_deadline = now + timedelta(seconds=policy.deadline_seconds)
        effective_deadline = policy_deadline if effective_deadline is None else min(effective_deadline, policy_deadline)
    if effective_deadline is not None and selected > effective_deadline:
        return terminal("terminal_failed", "RETRY_DEADLINE_EXCEEDED")
    delay = (selected - now).total_seconds()
    return RetryDecision("retry", "RETRY_SCHEDULED", attempt, fingerprint, delay, selected, selected)
