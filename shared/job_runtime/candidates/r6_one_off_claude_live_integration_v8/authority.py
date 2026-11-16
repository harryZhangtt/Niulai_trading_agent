"""Exact source-pinned provider-free authority; callers select no trust or clock source."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Tuple

from .contracts import (
    ContractError, require, sha256_bytes, validate_grant, validate_registry,
    validate_review, validate_window,
)

ROOT = Path(__file__).resolve().parents[4]
REGISTRY_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/"
    "r6-o1-claude-live-integration-v4-provider-free-registry.json",
    381, "c1b1a816a2ee42f08d6e135b495a60e65a3a081f4b94b39bf60aed3cf4c8ba82",
)
REGISTRY_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/"
    "r6-o1-claude-live-integration-v4-provider-free-registry-independent-review.json",
    2971, "55cbcc07837e27607ee88e3a3d82aa59f63575444c24a257cc4ecefdb560e7cb",
)
GRANT_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/"
    "r6-o1-claude-live-integration-v4-provider-free-grant.json",
    1108, "e39fbc491d447cc239e26b837c2d8185c21de9944c39ff79c1538333edbdc06b",
)
GRANT_REVIEW_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/"
    "r6-o1-claude-live-integration-v4-provider-free-grant-independent-review.json",
    304, "d4a02c8ae663128c1bb883c71ab44f298119b22c1e38658308844826c71e4059",
)
SCOPE_REF = (
    "mentor/runtime/scheduler-midresponse-recovery-20261107/"
    "r6-o1-claude-live-integration-v4-provider-free-registry-scope.json",
    918, "d2f4d61436a8884d5a46ec3d1ae163aa0d1c17344a85010395f832c49ea3f267",
)
CLOCK_ID = "system_utc_time_ns"


@dataclass(frozen=True)
class ValidatedAuthority:
    grant: dict
    grant_sha256: str
    grant_review_sha256: str
    registry_sha256: str
    registry_review_sha256: str
    scope_sha256: str
    binary_path: Path
    clock_id: str


def _held(ref: Tuple[str, int, str]) -> Any:
    rel, size, expected = ref
    path = ROOT / rel
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ContractError("PINNED_AUTHORITY_NOFOLLOW") from exc
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode), "PINNED_AUTHORITY_NOT_REGULAR")
        chunks = []
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            chunks.append(part)
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    require(len(raw) == size and sha256_bytes(raw) == expected,
            "PINNED_AUTHORITY_IDENTITY_DRIFT")
    try:
        return json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, ValueError, TypeError):
        raise ContractError("PINNED_AUTHORITY_JSON") from None


def _descriptor(value: Any, ref: Tuple[str, int, str], code: str) -> None:
    require(type(value) is dict and
            set(value) == {"bytes", "mode", "owner", "path", "sha256"}, code)
    require(value == {"bytes": ref[1], "mode": "0600", "owner": "bytedance",
                      "path": ref[0], "sha256": ref[2]}, code)


def _validate_registry_review(value: Any) -> None:
    require(type(value) is dict and set(value) == {
        "bindings", "checks", "claim_limits", "identities", "no_action",
        "status", "verdict", "version",
    }, "REGISTRY_REVIEW_SHAPE")
    require(value["version"] == 1 and
            value["status"] == value["verdict"] ==
            "CLEAN_PROVIDER_FREE_AUTHORITY_REGISTRY", "REGISTRY_REVIEW_VERDICT")
    require(type(value["bindings"]) is dict and set(value["bindings"]) == {
        "grant", "grant_review", "registry", "scope"}, "REGISTRY_REVIEW_BINDINGS")
    _descriptor(value["bindings"]["grant"], GRANT_REF, "REGISTRY_REVIEW_GRANT")
    _descriptor(value["bindings"]["grant_review"], GRANT_REVIEW_REF,
                "REGISTRY_REVIEW_GRANT_REVIEW")
    _descriptor(value["bindings"]["registry"], REGISTRY_REF, "REGISTRY_REVIEW_REGISTRY")
    _descriptor(value["bindings"]["scope"], SCOPE_REF, "REGISTRY_REVIEW_SCOPE")
    expected_checks = {
        "authority_is_external_main_session_integration_owner",
        "canonical_registry_v2_shape", "entry_cell_grant_review_hashes_exact",
        "grant_and_review_owner_mode_0600", "grant_reviewer_distinct_from_issuer",
        "one_active_entry", "provider_free_only",
        "registry_reviewer_distinct_from_grant_reviewer",
        "scope_activation_false", "scope_countable_false", "scope_live_authority_false",
    }
    require(type(value["checks"]) is dict and set(value["checks"]) == expected_checks and
            all(item is True for item in value["checks"].values()),
            "REGISTRY_REVIEW_CHECKS")
    require(value["identities"] == {
        "grant_issuer": "main-session/integration-owner-v4",
        "grant_reviewer": "independent/claude-v4-provider-free-review",
        "registry_reviewer": "independent/claude-v4-provider-free-registry-review",
    }, "REGISTRY_REVIEW_IDENTITIES")
    require(type(value["claim_limits"]) is list and len(value["claim_limits"]) == 4 and
            all(type(item) is str and item for item in value["claim_limits"]),
            "REGISTRY_REVIEW_LIMITS")
    require(type(value["no_action"]) is dict and set(value["no_action"]) == {
        "agents", "live", "network", "private_state", "provider", "source_edits",
        "tests", "writes_other_than_this_review",
    } and all(item is False for item in value["no_action"].values()),
            "REGISTRY_REVIEW_NO_ACTION")


def _validate_scope(value: Any) -> None:
    require(type(value) is dict and set(value) == {
        "activation", "countable", "grant", "live_authority", "registry", "review",
        "status", "version",
    }, "SCOPE_SHAPE")
    require(value["version"] == 1 and value["activation"] is False and
            value["countable"] is False and value["live_authority"] is False,
            "SCOPE_NOT_PROVIDER_FREE")
    for key, ref in (("grant", GRANT_REF), ("registry", REGISTRY_REF),
                     ("review", GRANT_REVIEW_REF)):
        require(value[key] == {"bytes": ref[1], "path": ref[0], "sha256": ref[2]},
                "SCOPE_BINDING")


def _trusted_utc_now() -> datetime:
    """Read host wall time internally; no caller can choose freshness time."""
    return datetime.fromtimestamp(time.time_ns() / 1_000_000_000, timezone.utc)


def load_pinned() -> ValidatedAuthority:
    registry = _held(REGISTRY_REF)
    registry_review = _held(REGISTRY_REVIEW_REF)
    grant = _held(GRANT_REF)
    grant_review = _held(GRANT_REVIEW_REF)
    scope = _held(SCOPE_REF)
    validate_grant(grant)
    validate_window(grant, _trusted_utc_now())
    validate_review(grant_review, GRANT_REF[2], grant["issuer"])
    validate_registry(registry, grant["cell_id"], GRANT_REF[2], GRANT_REVIEW_REF[2])
    _validate_registry_review(registry_review)
    _validate_scope(scope)
    binary = ROOT / grant["binary_ref"]
    require(binary.resolve(strict=True).is_relative_to(ROOT.resolve()), "BINARY_OUTSIDE_ROOT")
    return ValidatedAuthority(
        dict(grant), GRANT_REF[2], GRANT_REVIEW_REF[2], REGISTRY_REF[2],
        REGISTRY_REVIEW_REF[2], SCOPE_REF[2], binary, CLOCK_ID,
    )
