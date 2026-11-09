"""Fail-closed validation for the inert local Docker/Colima candidate.

This module reads JSON documents only. It never invokes Docker, Colima, Compose,
a daemon, a container, a network, or a credential provider.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

PACKAGE = Path(__file__).resolve().parent
MAX_BYTES = 512 * 1024
PROFILE_PATH = PACKAGE / "runtime-profile.json"
SERVICES_PATH = PACKAGE / "service-declarations.json"
SOURCES_PATH = PACKAGE / "source-inventory.json"

BLOCKERS = [
    "colima-version-unverified",
    "docker-version-unverified",
    "colima-path-unverified",
    "docker-path-unverified",
    "docker-context-unverified",
    "vm-identity-unverified",
    "controller-image-digest-unresolved",
    "proxy-image-digest-unresolved",
    "executor-image-digest-unresolved",
    "evaluator-image-digest-unresolved",
    "checker-image-digest-unresolved",
    "release-digest-unresolved",
    "host-headroom-unmeasured",
    "disposable-lifecycle-unrun",
    "pressure-behavior-unverified",
    "future-io-sources-unresolved",
    "output-promotion-root-unresolved",
    "future-io-conformance-unverified",
    "internal-network-identity-unresolved",
    "egress-network-identity-unresolved",
    "dual-network-conformance-unverified",
    "stable-lifecycle-conformance-unverified",
    "linux-userspace-base-release-unresolved",
    "oci-architecture-unresolved",
    "in-image-verifier-digests-unresolved",
    "image-contract-conformance-unverified",
    "official-source-live-verification-receipts-unavailable",
    "runtime-acceptance-unrun",
]
ROLES = ("controller", "proxy", "executor", "evaluator", "checker")
STABLE = ("controller", "proxy")
ATTEMPT = ("executor", "evaluator", "checker")
IMAGE_BLOCKER = {role: f"{role}-image-digest-unresolved" for role in ROLES}
HOST_STATE = {
    "workspace_token": "$WORKSPACE",
    "artifacts_root": "$WORKSPACE/factor/runtime/local",
    "artifact_classes": ["config", "cache", "runtime"],
    "artifacts_must_be_git_ignored": True,
    "colima_environment": {
        "COLIMA_HOME": "$WORKSPACE/factor/runtime/local/colima",
        "COLIMA_PROFILE": "factor-mining",
    },
    "colima_config": {"autoActivate": False},
    "default_colima_home": "~/.colima",
    "default_colima_home_policy": "prohibited-fail-closed",
    "expected_docker_context": "colima-factor-mining",
    "context_discovery": "future-activation-discover-and-validate",
    "change_global_current_docker_context": False,
    "docker_wrapper_required_args": ["--context", "colima-factor-mining"],
}


class LocalContractError(ValueError):
    """Stable, sanitized contract rejection."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise LocalContractError(code)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "LOCAL_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw: bytes | str) -> Any:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "LOCAL_JSON_SIZE")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LocalContractError("LOCAL_JSON_NONFINITE")
            ),
        )
    except LocalContractError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise LocalContractError("LOCAL_JSON_INVALID") from None


def _read_regular(path: Path | str, *, allow_empty: bool = False,
                  size_code: str = "LOCAL_JSON_SIZE",
                  unavailable_code: str = "LOCAL_JSON_UNAVAILABLE") -> bytes:
    fd: int | None = None
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(Path(path), flags)
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode), size_code)
        require(info.st_size <= MAX_BYTES and (allow_empty or info.st_size > 0),
                size_code)
        chunks: list[bytes] = []
        remaining = MAX_BYTES + 1
        while remaining:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        require(len(raw) <= MAX_BYTES and len(raw) == info.st_size and
                (allow_empty or len(raw) > 0), size_code)
        return raw
    except LocalContractError:
        raise
    except OSError:
        raise LocalContractError(unavailable_code) from None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def load_json(path: Path | str) -> Any:
    return loads_strict(_read_regular(path))


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise LocalContractError("LOCAL_JSON_INVALID") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _exact(value: Any, expected: Any, code: str) -> None:
    """Compare recursively with exact types (so bool never equals int)."""
    require(type(value) is type(expected), code)
    if isinstance(expected, dict):
        require(set(value) == set(expected), code)
        for key in expected:
            _exact(value[key], expected[key], code)
    elif isinstance(expected, list):
        require(len(value) == len(expected), code)
        for actual_item, expected_item in zip(value, expected):
            _exact(actual_item, expected_item, code)
    else:
        require(value == expected, code)


def validate_profile(value: Any) -> dict[str, Any]:
    expected = load_json(PACKAGE / "fixtures" / "valid-runtime-profile.json")
    _exact(value, expected, "LOCAL_PROFILE_CONTRACT")
    require(value["status"] == "selected-disabled", "LOCAL_PROFILE_STATUS")
    require(value["runnable"] is False and value["apply_allowed"] is False,
            "LOCAL_PROFILE_APPLY_FENCE")
    require(all(item is None for item in value["live_identity"].values()),
            "LOCAL_PROFILE_LIVE_IDENTITY")
    require(all(item is None for item in value["artifacts"]["image_digests"].values()) and
            value["artifacts"]["release_digest"] is None,
            "LOCAL_PROFILE_ARTIFACT_IDENTITY")
    require(value["host_state"] == HOST_STATE, "LOCAL_PROFILE_HOST_STATE")
    require(value["host_state"]["default_colima_home_policy"] ==
            "prohibited-fail-closed" and
            value["host_state"]["colima_config"] == {"autoActivate": False} and
            value["host_state"]["change_global_current_docker_context"] is False and
            value["host_state"]["docker_wrapper_required_args"] ==
            ["--context", "colima-factor-mining"], "LOCAL_PROFILE_CONTEXT_FENCE")
    require(value["blockers"] == BLOCKERS, "LOCAL_PROFILE_BLOCKERS")
    return value


def _expected_service(role: str) -> dict[str, Any]:
    stable = role in STABLE
    network_policy = {
        "controller": "future-internal-only",
        "proxy": "future-internal-plus-egress",
        "executor": "none",
        "evaluator": "none",
        "checker": "none",
    }[role]
    common = {
        "name": role,
        "class": "stable" if stable else "attempt",
        "image_digest": None,
        "image_blocker": IMAGE_BLOCKER[role],
        "image_contract_id": f"{role}-linux-oci-v1",
        "restart": "no",
        "restart_owner": "host-authority" if stable else "engine",
        "replicas": 1,
        "scale_mode": "explicit-only",
        "future_network_policy": network_policy,
        "mounts": [],
        "docker_socket": False,
        "privileged": False,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "logging": {"driver": "local", "max_size": "10m", "max_files": 3},
    }
    if role == "executor":
        common.update({
            "network_mode": "none",
            "read_only_root": True,
            "tmpfs": [
                {"target": "/tmp", "size_bytes": 536870912, "mode": "1777"},
                {"target": "/run", "size_bytes": 67108864, "mode": "0755"},
            ],
            "secrets": [],
            "resources": {
                "cpu_hard": 2.0,
                "memory_hard_bytes": 4294967296,
                "memory_reservation_bytes": 2147483648,
                "memory_swap_bytes": 4294967296,
                "additional_swap_bytes": 0,
                "pids_limit": 512,
                "cpu_shares": 256,
            },
        })
    elif role == "controller":
        common.update({
            "network_mode": "unconfigured-blocked",
            "read_only_root": True,
            "tmpfs": [{"target": "/tmp", "size_bytes": 67108864, "mode": "1777"}],
            "secrets": [],
            "resources": {"cpu_hard": 1.0, "memory_hard_bytes": 1073741824,
                          "memory_swap_bytes": 1073741824,
                          "additional_swap_bytes": 0, "pids_limit": 512},
        })
    else:
        common.update({
            "network_mode": "unconfigured-blocked" if role == "proxy" else "none",
            "read_only_root": True,
            "tmpfs": [{"target": "/tmp", "size_bytes": 268435456, "mode": "1777"}],
            "secrets": [],
            "resources": {"cpu_hard": 1.0, "memory_hard_bytes": 1073741824,
                          "memory_swap_bytes": 1073741824,
                          "additional_swap_bytes": 0, "pids_limit": 512},
        })
    return common


def validate_services(value: Any) -> dict[str, Any]:
    require(type(value) is dict and set(value) == {
        "schema_version", "kind", "apply_allowed", "compose_file", "stable", "attempt"
    }, "LOCAL_SERVICES_SCHEMA")
    _exact(value["schema_version"], 1, "LOCAL_SERVICES_VERSION")
    _exact(value["kind"], "factor_local_service_declarations", "LOCAL_SERVICES_KIND")
    _exact(value["apply_allowed"], False, "LOCAL_SERVICES_APPLY_FENCE")
    _exact(value["compose_file"], None, "LOCAL_SERVICES_NO_COMPOSE")
    require(type(value["stable"]) is dict and set(value["stable"]) == set(STABLE),
            "LOCAL_SERVICES_STABLE_ROSTER")
    require(type(value["attempt"]) is dict and set(value["attempt"]) == set(ATTEMPT),
            "LOCAL_SERVICES_ATTEMPT_ROSTER")
    for role in ROLES:
        group = value["stable"] if role in STABLE else value["attempt"]
        _exact(group[role], _expected_service(role), f"LOCAL_SERVICE_{role.upper()}")
    return value


def validate_sources(value: Any) -> dict[str, Any]:
    expected = load_json(PACKAGE / "fixtures" / "valid-source-inventory.json")
    _exact(value, expected, "LOCAL_SOURCES_CONTRACT")
    require(value["live_fetch_performed"] is False, "LOCAL_SOURCES_FETCH_CLAIM")
    require(value["coordinating_session_verification"] == {
        "reported_date": "2026-11-05", "reported_live_verified": True,
        "exact_receipts_available_to_this_artifact": False,
        "receipt_urls_imported": False,
        "evidence_status": "reported-but-unavailable-not-adopted",
    }, "LOCAL_SOURCES_EXTERNAL_RECEIPTS")
    for source in value["sources"]:
        require(source["official"] is True and source["live_fetched_in_task"] is False,
                "LOCAL_SOURCE_PROVENANCE")
        require(source["evidence_status"] == "reference-not-live-verified",
                "LOCAL_SOURCE_EVIDENCE_STATUS")
    return value


def validate_exact_schema(instance: Any, schema: Any, path: str = "$") -> None:
    """Validate the exact-schema subset emitted for this package."""
    require(type(schema) is dict, "LOCAL_SCHEMA_DOCUMENT")
    if "const" in schema:
        _exact(instance, schema["const"], "LOCAL_SCHEMA_CONST")
        return
    if schema.get("type") == "null":
        require(instance is None, "LOCAL_SCHEMA_TYPE")
        return
    require(schema.get("type") == "object" and schema.get("additionalProperties") is False,
            "LOCAL_SCHEMA_NOT_CLOSED")
    properties = schema.get("properties")
    required = schema.get("required")
    require(type(properties) is dict and type(required) is list and
            set(required) == set(properties) and len(required) == len(properties),
            "LOCAL_SCHEMA_REQUIRED")
    require(type(instance) is dict and set(instance) == set(properties),
            "LOCAL_SCHEMA_PROPERTIES")
    for key, subschema in properties.items():
        validate_exact_schema(instance[key], subschema, f"{path}.{key}")


def _load_and_check_schema(name: str, instance: Any) -> None:
    schema = load_json(PACKAGE / name)
    require(type(schema) is dict and schema.get("$schema") ==
            "https://json-schema.org/draft/2020-12/schema" and
            type(schema.get("$id")) is str, "LOCAL_SCHEMA_HEADER")
    body = {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}
    validate_exact_schema(instance, body)


def validate_bundle(profile_path: Path | str = PROFILE_PATH,
                    services_path: Path | str = SERVICES_PATH,
                    sources_path: Path | str = SOURCES_PATH) -> dict[str, str]:
    profile = validate_profile(load_json(profile_path))
    services = validate_services(load_json(services_path))
    sources = validate_sources(load_json(sources_path))
    _load_and_check_schema("runtime-profile-v1.schema.json", profile)
    _load_and_check_schema("service-declarations-v1.schema.json", services)
    _load_and_check_schema("source-inventory-v1.schema.json", sources)
    return {
        "runtime-profile.json": digest(profile),
        "service-declarations.json": digest(services),
        "source-inventory.json": digest(sources),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate inert local factor-mining contracts")
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    parser.add_argument("--services", type=Path, default=SERVICES_PATH)
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    args = parser.parse_args(argv)
    try:
        hashes = validate_bundle(args.profile, args.services, args.sources)
    except LocalContractError as exc:
        print(f"INVALID {exc}")
        return 2
    print(json.dumps({"valid": True, "apply_allowed": False, "sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
