#!/usr/bin/env python3
"""Deterministically verify the provider-free Claude readiness audit package."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
ALLOWED_STATUSES = {
    "CURRENT_SUFFICIENT",
    "REFRESH_REQUIRED",
    "BLOCKED_PENDING_CLAUDE_V8_REVIEW",
}


class VerificationError(RuntimeError):
    pass


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise VerificationError("TIMESTAMP_MALFORMED") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerificationError("TIMESTAMP_NOT_AWARE")
    return parsed.astimezone(timezone.utc)


def is_fresh(now: str, start: str, end: str) -> bool:
    current = parse_time(now)
    lower = parse_time(start)
    upper = parse_time(end)
    if not lower < upper:
        raise VerificationError("TIMESTAMP_WINDOW_INVALID")
    return lower <= current < upper


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def verify_identity(identity: Mapping[str, Any]) -> None:
    if set(identity) != {"path", "bytes", "sha256"}:
        raise VerificationError("IDENTITY_SHAPE")
    path = resolve_path(identity["path"])
    if not path.is_file() or path.is_symlink():
        raise VerificationError("IDENTITY_NOT_REGULAR")
    if path.stat().st_size != identity["bytes"]:
        raise VerificationError("IDENTITY_BYTES_DRIFT")
    if sha256_file(path) != identity["sha256"]:
        raise VerificationError("IDENTITY_SHA256_DRIFT")


def load_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise VerificationError("JSON_INVALID") from exc
    if type(value) is not dict:
        raise VerificationError("JSON_OBJECT_REQUIRED")
    return value


def derive_status(v8_pending: bool, refresh_required: bool) -> str:
    if v8_pending:
        return "BLOCKED_PENDING_CLAUDE_V8_REVIEW"
    if refresh_required:
        return "REFRESH_REQUIRED"
    return "CURRENT_SUFFICIENT"


def _all_identities(decision: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield decision["protocol_identity"]
    for group in decision["evidence_identities"].values():
        if type(group) is list:
            yield from group
        else:
            yield group


def verify_decision(decision_path: Path, now: Optional[str] = None) -> Dict[str, Any]:
    candidates = sorted(HERE.glob("readiness-decision-*.json"))
    if len(candidates) != 1 or candidates[0].resolve() != decision_path.resolve():
        raise VerificationError("UNIQUE_OWNER_PRIVATE_DECISION_REQUIRED")
    if (decision_path.stat().st_mode & 0o777) != 0o600:
        raise VerificationError("DECISION_MODE_NOT_0600")
    decision = load_json(decision_path)
    if decision.get("terminal_status") not in ALLOWED_STATUSES:
        raise VerificationError("TERMINAL_STATUS_INVALID")
    if decision.get("activation") is not False or decision.get("countable") is not False:
        raise VerificationError("NONAUTHORIZING_FLAGS_INVALID")
    effects = decision.get("effects")
    if type(effects) is not dict or any(value != 0 for value in effects.values()):
        raise VerificationError("EFFECTS_NONZERO")
    for identity in _all_identities(decision):
        verify_identity(identity)

    clock = now or decision["evaluated_at"]
    account = decision["freshness_bounded_evidence"]["account_readiness"]
    account_fresh = is_fresh(clock, account["checked_at"], account["fresh_until"])
    catalog = decision["consumed_request_accounting"]
    catalog_fresh = is_fresh(
        clock, catalog["authorized_at"], catalog["deadline_at"]
    )
    if catalog["authorized_requests"] != 1 or catalog["observed_requests"] != 1:
        raise VerificationError("CATALOG_REQUEST_ACCOUNTING_INVALID")
    if catalog["remaining_requests"] != 0 or catalog["consumed"] is not True:
        raise VerificationError("CATALOG_REQUEST_NOT_CONSUMED")
    if catalog["retry"] != 0 or catalog["replay"] != 0:
        raise VerificationError("NO_RETRY_RULE_VIOLATED")

    blockers = decision["claude_v8"]
    v8_pending = (
        blockers["fresh_independent_review"] is False
        or blockers["p0_v10_reclosure"] != "CLEAN"
        or blockers["registration"] is not False
    )
    refresh_required = not account_fresh or not catalog_fresh or catalog["remaining_requests"] == 0
    derived = derive_status(v8_pending, refresh_required)
    if derived != decision["terminal_status"]:
        raise VerificationError("TERMINAL_STATUS_DRIFT")
    if decision["inference_readback"]["account_readback_in_inference"] is not False:
        raise VerificationError("ACCOUNT_READBACK_CLAIM_INVALID")
    if decision["inference_readback"]["separate_catalog_required"] is not True:
        raise VerificationError("CATALOG_SUBSTITUTION_INVALID")
    if decision["minimal_new_preflight"]["bytedcli"] != "FORBIDDEN":
        raise VerificationError("BYTEDCLI_RULE_INVALID")
    if decision["minimal_new_preflight"]["request_retries"] != 0:
        raise VerificationError("PREFLIGHT_RETRY_RULE_INVALID")
    return {
        "verified": True,
        "terminal_status": derived,
        "account_fresh": account_fresh,
        "catalog_window_fresh": catalog_fresh,
        "catalog_requests_remaining": catalog["remaining_requests"],
        "identity_count": sum(1 for _ in _all_identities(decision)),
        "effects": effects,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--decision",
        default=str(HERE / "readiness-decision-v1.json"),
    )
    parser.add_argument("--now", default=None)
    args = parser.parse_args()
    result = verify_decision(Path(args.decision), args.now)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
