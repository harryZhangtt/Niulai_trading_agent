"""Closed, provider-free contracts for the disabled R6 Codex live-driver candidate."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from shared.job_runtime.candidates.r6_one_off_evidence_v1.contracts import admission_key, request_fingerprint
from shared.job_runtime.candidates.r6_one_off_codex_adapter_v1.contracts import (
    MODEL as ADAPTER_MODEL,
    RELEASE as ADAPTER_RELEASE,
    stage_a_template,
    validate_stage_a_template,
)

DESIGN = ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-driver-design.json", 35203, "ac495d170cc6a681c6b5cd52a0bc5b5a4bb59bd984879da67f719d6e62429641")
DESIGN_REVIEW = ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-driver-design-independent-review.json", 18561, "dc805ac1e73b980fd0a45661f7009235f3a4dcaf2d0e48df0af10192d80e8bd5")
ADAPTER_VERIFICATION = ("tuning/architecture/r6_one_off_codex_adapter_v1/producer-verification-v4-final.json", 10809, "cc608750c4b06a502195a28f1e13308ba7702803482a78fe1c7ba25894b50644")
ADAPTER_REVIEW = ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-adapter-provider-free-v4-independent-review.json", 11239, "e02ab04cfa2ea891b4830f03d20563c6493f694d3f88e2524a3cee86d7efd214")
PROVIDER = "codex_cli"
RELEASE = "0.167.0"
MODEL = "gpt-6.1-sol"
EFFORT = "low"
PROVIDER_ID = "r6_local_observer"
PATH = "/backend-api/codex/responses"
UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
PROMPT_BYTES = 526
PROMPT_SHA256 = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
ENV_ALLOWLIST = frozenset(("HOME", "USER", "LOGNAME", "PATH", "TMPDIR", "LANG", "LC_ALL", "TERM", "NO_COLOR", "CODEX_HOME"))
FORBIDDEN_ENV = re.compile(r"(^|_)(TOKEN|KEY|SECRET|COOKIE)(_|$)|AUTH|^(HTTP|HTTPS|ALL)_PROXY$", re.I)
OUTCOMES = frozenset(("PASS", "STOP", "UNKNOWN"))
CONFIG_KEYS = frozenset(("version", "mode", "enabled", "provider", "release", "model", "effort", "binary", "argv", "model_provider", "environment", "timeouts_seconds", "limits", "prompt", "source", "custody", "held"))
HELD_KEYS = frozenset(("binary", "argv", "config", "parser", "gateway", "prompt", "source_closure", "grant"))
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z][a-z0-9._:-]{7,191}\Z")

class ContractError(ValueError):
    """A closed contract failed validation."""


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ContractError(code)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json_loads(value: str) -> Any:
    def pairs(items: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, item in items:
            if key in out:
                raise ContractError("DUPLICATE_JSON_KEY")
            out[key] = item
        return out
    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ContractError("NONFINITE_JSON")))
    except ContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError("INVALID_JSON") from exc


def _exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _digest(value: Any, code: str) -> str:
    require(type(value) is str and _SHA.fullmatch(value) is not None, code)
    return value


def _artifact(value: Any, code: str) -> Mapping[str, Any]:
    item = _exact(value, ("path", "bytes", "sha256"), code)
    require(type(item["path"]) is str and item["path"] and not Path(item["path"]).is_absolute(), code + "_PATH")
    require(type(item["bytes"]) is int and item["bytes"] >= 0, code + "_BYTES")
    _digest(item["sha256"], code + "_SHA")
    return item


def compose_reviewed_public_contracts(profile_fingerprint: str, credential_reference: str) -> Mapping[str, Any]:
    """Exercise only the reviewed public Stage-A contract; it cannot mint Stage-B authority."""
    require(ADAPTER_MODEL == MODEL and ADAPTER_RELEASE == RELEASE, "ADAPTER_CONSTANT_DRIFT")
    return validate_stage_a_template(stage_a_template(profile_fingerprint, credential_reference))


def verify_frozen_predecessors(root: Path) -> None:
    for path, size, digest in (DESIGN, DESIGN_REVIEW, ADAPTER_VERIFICATION, ADAPTER_REVIEW):
        target = root / path
        require(target.is_file() and not target.is_symlink(), "PREDECESSOR_MISSING")
        raw = target.read_bytes()
        require(len(raw) == size and sha256_bytes(raw) == digest, "PREDECESSOR_DRIFT")


def validate_config(value: Any) -> Mapping[str, Any]:
    item = _exact(value, CONFIG_KEYS, "CONFIG_SHAPE")
    require(item["version"] == "r6-one-off-codex-live-driver-config-v1", "CONFIG_VERSION")
    require(item["mode"] == "provider_free_fixture" and item["enabled"] is False, "CONFIG_NOT_INERT")
    require((item["provider"], item["release"], item["model"], item["effort"]) == (PROVIDER, RELEASE, MODEL, EFFORT), "TREATMENT_DRIFT")
    binary = _exact(item["binary"], ("path", "bytes", "sha256", "mode", "regular", "symlink", "owner_private"), "BINARY_SHAPE")
    require(type(binary["path"]) is str and binary["path"], "BINARY_PATH")
    require(type(binary["bytes"]) is int and binary["bytes"] > 0 and _SHA.fullmatch(binary["sha256"] or "") is not None, "BINARY_IDENTITY")
    require(binary["mode"] == "0755" and binary["regular"] is True and binary["symlink"] is False and binary["owner_private"] is True, "BINARY_POLICY")
    argv = item["argv"]
    require(type(argv) is list and len(argv) >= 7 and all(type(v) is str and v for v in argv), "ARGV_INVALID")
    require(argv[0] == binary["path"] and argv[1] == "exec" and "--json" in argv and MODEL in argv and argv[-1] == "-", "ARGV_SEMANTICS")
    provider = _exact(item["model_provider"], ("id", "base_url", "wire_api", "requires_openai_auth", "supports_websockets", "request_max_retries", "stream_max_retries", "stream_idle_timeout_ms"), "PROVIDER_CONFIG_SHAPE")
    require(provider == {"id": PROVIDER_ID, "base_url": "http://127.0.0.1:<injected-fixture-port>/backend-api/codex", "wire_api": "responses", "requires_openai_auth": True, "supports_websockets": False, "request_max_retries": 0, "stream_max_retries": 0, "stream_idle_timeout_ms": 60000}, "PROVIDER_CONFIG_DRIFT")
    env = _exact(item["environment"], ("inherit_all", "allowlist", "values"), "ENV_SHAPE")
    require(env["inherit_all"] is False and env["allowlist"] == sorted(ENV_ALLOWLIST), "ENV_POLICY")
    require(type(env["values"]) is dict and set(env["values"]).issubset(ENV_ALLOWLIST), "ENV_UNALLOWLISTED")
    for key, val in env["values"].items():
        require(FORBIDDEN_ENV.search(key) is None and type(val) is str and "secret" not in val.lower() and "token" not in val.lower(), "ENV_SECRET")
    require(item["timeouts_seconds"] == {"fresh_readiness": 10, "catalog": 30, "gateway_startup": 5, "process_total": 300, "stream_idle": 60, "graceful_shutdown": 5, "forced_reap": 5, "publication": 10, "overall": 420}, "TIMEOUT_DRIFT")
    require(item["limits"] == {"currency": "USD", "provider_subcap": "0.01", "combined_cap": "0.02", "window_minutes": 30, "max_attempts": 1, "concurrency": 1, "catalog_requests_max": 1, "inference_requests_max": 1, "admissions_max": 1, "request_retries": 0, "stream_retries": 0, "gateway_retries": 0, "countable_observation": False}, "LIMIT_DRIFT")
    prompt = _exact(item["prompt"], ("bytes", "sha256", "stdin_once"), "PROMPT_SHAPE")
    require(prompt == {"bytes": PROMPT_BYTES, "sha256": PROMPT_SHA256, "stdin_once": True}, "PROMPT_DRIFT")
    source = _exact(item["source"], ("cutoff_at", "allowed"), "SOURCE_SHAPE")
    require(source["cutoff_at"] == "2026-11-09T00:00:00Z" and type(source["allowed"]) is list and len(source["allowed"]) == 2, "SOURCE_DRIFT")
    custody = _exact(item["custody"], ("fixture_root", "root_mode", "file_mode", "nofollow", "raw_public"), "CUSTODY_SHAPE")
    require(custody["fixture_root"] is True and custody["root_mode"] == "0700" and custody["file_mode"] == "0600" and custody["nofollow"] is True and custody["raw_public"] is False, "CUSTODY_POLICY")
    held = _exact(item["held"], HELD_KEYS, "HELD_SHAPE")
    for name in HELD_KEYS:
        _artifact(held[name], "HELD_" + name.upper())
    return item


def validate_preflight(value: Any, now: Optional[datetime] = None) -> Mapping[str, Any]:
    item = _exact(value, ("authority", "binding", "readiness", "catalog", "budget", "window", "custody"), "PREFLIGHT_SHAPE")
    require(item["authority"] == "INJECTED_PROVIDER_FREE_TEST_AUTHORITY" and item["binding"] == "EXACT", "AUTHORITY_DENIED")
    readiness = _exact(item["readiness"], ("fresh", "profile", "account_equal", "credential_reference_only", "credential_usable", "model_entitled"), "READINESS_SHAPE")
    require(readiness == {"fresh": True, "profile": "current CLI profile held reference only", "account_equal": True, "credential_reference_only": True, "credential_usable": True, "model_entitled": True}, "READINESS_DENIED")
    catalog = _exact(item["catalog"], ("requests", "selected_occurrences", "model"), "CATALOG_SHAPE")
    require(catalog == {"requests": 1, "selected_occurrences": 1, "model": MODEL}, "CATALOG_DENIED")
    budget = _exact(item["budget"], ("currency", "provider_remaining", "combined_remaining"), "BUDGET_SHAPE")
    
    try:
        provider_amount = Decimal(str(budget["provider_remaining"])); combined_amount = Decimal(str(budget["combined_remaining"]))
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("BUDGET_DECIMAL_INVALID") from exc
    require(provider_amount.is_finite() and combined_amount.is_finite(), "BUDGET_NONFINITE")
    require(budget["currency"] == "USD" and provider_amount == Decimal("0.01") and Decimal("0.00") <= combined_amount <= Decimal("0.02") and provider_amount <= combined_amount, "BUDGET_DENIED")
    window = _exact(item["window"], ("not_before", "deadline", "minutes"), "WINDOW_SHAPE")
    try:
        start = datetime.fromisoformat(window["not_before"].replace("Z", "+00:00")); end = datetime.fromisoformat(window["deadline"].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ContractError("WINDOW_INVALID") from exc
    current = now or start
    require(start.tzinfo is not None and end.tzinfo is not None and window["minutes"] == 30 and (end-start).total_seconds() == 1800 and start <= current <= end, "WINDOW_DENIED")
    require(item["custody"] == {"fresh": True, "fixture_only": True, "nofollow": True}, "CUSTODY_DENIED")
    return item


def validate_held_bytes(config: Mapping[str, Any], observed: Mapping[str, bytes]) -> None:
    require(set(observed) == HELD_KEYS, "HELD_OBSERVED_SHAPE")
    for name in HELD_KEYS:
        ref = config["held"][name]
        raw = observed[name]
        require(type(raw) is bytes and len(raw) == ref["bytes"] and sha256_bytes(raw) == ref["sha256"], "HELD_DRIFT_" + name.upper())


def make_request_fingerprint(operation_id: str, prompt_sha256: str, body_sha256: str) -> Tuple[str, str]:
    request = {"method": "POST", "path": PATH, "query": "", "prompt_sha256": prompt_sha256, "body_sha256": body_sha256, "provider_id": PROVIDER_ID}
    fingerprint = request_fingerprint(request)
    return fingerprint, admission_key(operation_id, fingerprint)


@dataclass(frozen=True)
class DriverResult:
    outcome: str
    code: str
    countable_observation: bool
    engine: Mapping[str, Any]
    counters: Mapping[str, int]
    receipts: Mapping[str, Any]
    publication: Optional[Mapping[str, Any]]

    def __post_init__(self) -> None:
        require(self.outcome in OUTCOMES and self.countable_observation is False, "RESULT_INVALID")

# Successor fixed-point/effect contracts. Kept additive to preserve the reviewed public surface.
from decimal import Decimal, InvalidOperation
from dataclasses import dataclass as _dataclass
import time as _time

@_dataclass(frozen=True)
class ExecutionBinding:
    job_id: str
    slot_id: str
    attempt_id: str
    operation_id: str
    process_id: str
    request_fingerprint: str
    model: str
    prompt_sha256: str
    grant_sha256: str

    def public(self) -> Dict[str, str]:
        value = dict(self.__dict__)
        require(len(set((self.job_id, self.slot_id, self.attempt_id, self.operation_id, self.process_id))) == 5, "BINDING_ID_COLLISION")
        require(self.model == MODEL and _SHA.fullmatch(self.prompt_sha256) and _SHA.fullmatch(self.grant_sha256), "BINDING_TREATMENT")
        require(_SHA.fullmatch(self.request_fingerprint) is not None, "BINDING_REQUEST")
        return value

class EffectGuard:
    """Fixed-point cap and monotonic deadline checked at every named effect."""
    def __init__(self, provider_remaining: str, combined_remaining: str, deadline_monotonic: float, monotonic=None) -> None:
        try:
            self.provider_remaining = Decimal(provider_remaining)
            self.combined_remaining = Decimal(combined_remaining)
        except (InvalidOperation, TypeError) as exc:
            raise ContractError("BUDGET_DECIMAL_INVALID") from exc
        require(self.provider_remaining.is_finite() and self.combined_remaining.is_finite(), "BUDGET_NONFINITE")
        require(self.provider_remaining == Decimal("0.01") and Decimal("0.00") <= self.combined_remaining <= Decimal("0.02") and self.provider_remaining <= self.combined_remaining, "BUDGET_DENIED")
        self.deadline = float(deadline_monotonic)
        self.monotonic = monotonic or _time.monotonic
        self.effects = []  # type: list
        self.late_effects = []  # type: list
        self.reserved = Decimal("0.00")

    def observe(self, effect: str) -> bool:
        require(type(effect) is str and effect, "EFFECT_NAME")
        on_time = self.monotonic() <= self.deadline
        self.effects.append(effect if on_time else effect + ":late")
        if not on_time:
            self.late_effects.append(effect)
        return on_time

    def check(self, effect: str, reserve_usd: str = "0.00") -> None:
        require(self.observe(effect), "MONOTONIC_DEADLINE_EXPIRED")
        try: reserve = Decimal(reserve_usd)
        except InvalidOperation as exc: raise ContractError("BUDGET_DECIMAL_INVALID") from exc
        require(reserve >= 0 and self.reserved + reserve <= self.provider_remaining and self.reserved + reserve <= self.combined_remaining, "BUDGET_CAP_EXCEEDED")
        self.reserved += reserve

def validate_receipt_binding(receipt: Mapping[str, Any], binding: ExecutionBinding, kind: str) -> None:
    require(type(receipt) is dict and receipt.get("kind") == kind, kind.upper() + "_RECEIPT_KIND")
    expected = binding.public()
    require(receipt.get("binding") == expected, kind.upper() + "_BINDING_MISMATCH")
