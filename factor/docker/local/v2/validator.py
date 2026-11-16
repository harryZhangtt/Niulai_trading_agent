"""Read-only validation for installation evidence and the disabled v2 profile.

The validator reads files and computes hashes only. It never invokes Colima,
Docker, Homebrew, a daemon, a VM, a context, a container, or a network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
V1_ROOT = PACKAGE.parent
MAX_BYTES = 512 * 1024
RECEIPT_PATH = PACKAGE / "installation-receipt.json"
PROFILE_PATH = PACKAGE / "runtime-profile-v2.json"
EXPECTED_V1_TREE_SHA256 = "ba79cf54ea34bdd09f063c1809060d6f9564b5d8f46aa726aff750ffea8c7908"
EXPECTED_V1_PROFILE_SHA256 = "0018efdecd22659125880e398f831ab7e93ede52e81724908d2c17c467950d1a"
EXPECTED_RECEIPT_SHA256 = "c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327"
EXPECTED_TOOLS = {
    "colima": ("0.10.3", "/opt/homebrew/bin/colima", "55278419bd4288e4ab11eb30be13f5e655f3886c0979b68e435df910dbc9bbdf"),
    "docker": ("29.9.3", "/opt/homebrew/bin/docker", "07e3a894d913ccbd07b11d984edde25b0d683bfc2fec986d3e378eef035bc219"),
    "compose": ("5.7.0", "/opt/homebrew/lib/docker/cli-plugins/docker-compose", "f826c82d69e24647e080eab992f8aa0abc14ade04762780044c4a7602b7275fc"),
    "buildx": ("0.38.2", "/opt/homebrew/lib/docker/cli-plugins/docker-buildx", "b0c443c3bafc5fd0e7d6cbb19478ce0d0b35122e5e257b53bd714ce80ab123a6"),
    "lima": ("2.2.1", "/opt/homebrew/bin/limactl", "e79b14815dc7e51629e064dba950120c4c9323e2b8ba6a52fe816b15f7f9803d"),
}
RESOLVED_BLOCKERS = [
    "colima-version-unverified", "docker-version-unverified",
    "colima-path-unverified", "docker-path-unverified",
]
RETAINED_BLOCKERS = [
    "docker-context-unverified", "vm-identity-unverified",
    "controller-image-digest-unresolved", "proxy-image-digest-unresolved",
    "executor-image-digest-unresolved", "evaluator-image-digest-unresolved",
    "checker-image-digest-unresolved", "release-digest-unresolved",
    "host-headroom-unmeasured", "disposable-lifecycle-unrun",
    "pressure-behavior-unverified", "future-io-sources-unresolved",
    "output-promotion-root-unresolved", "future-io-conformance-unverified",
    "internal-network-identity-unresolved", "egress-network-identity-unresolved",
    "dual-network-conformance-unverified", "stable-lifecycle-conformance-unverified",
    "linux-userspace-base-release-unresolved", "oci-architecture-unresolved",
    "in-image-verifier-digests-unresolved", "image-contract-conformance-unverified",
    "official-source-live-verification-receipts-unavailable", "runtime-acceptance-unrun",
]


class V2ContractError(ValueError):
    """Stable sanitized validation failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise V2ContractError(code)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "V2_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw: bytes | str) -> Any:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "V2_JSON_SIZE")
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                V2ContractError("V2_JSON_NONFINITE")
            ),
        )
    except V2ContractError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise V2ContractError("V2_JSON_INVALID") from None


def load_json(path: Path | str) -> Any:
    try:
        return loads_strict(Path(path).read_bytes())
    except OSError:
        raise V2ContractError("V2_JSON_UNAVAILABLE") from None


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise V2ContractError("V2_JSON_INVALID") from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _exact(value: Any, expected: Any, code: str) -> None:
    require(type(value) is type(expected), code)
    if isinstance(expected, dict):
        require(set(value) == set(expected), code)
        for key in expected:
            _exact(value[key], expected[key], code)
    elif isinstance(expected, list):
        require(len(value) == len(expected), code)
        for actual, wanted in zip(value, expected):
            _exact(actual, wanted, code)
    else:
        require(value == expected, code)


def validate_exact_schema(instance: Any, schema: Any) -> None:
    require(type(schema) is dict, "V2_SCHEMA_DOCUMENT")
    if "const" in schema:
        _exact(instance, schema["const"], "V2_SCHEMA_CONST")
        return
    if schema.get("type") == "null":
        require(instance is None, "V2_SCHEMA_TYPE")
        return
    require(schema.get("type") == "object" and schema.get("additionalProperties") is False,
            "V2_SCHEMA_NOT_CLOSED")
    properties = schema.get("properties")
    required = schema.get("required")
    require(type(properties) is dict and type(required) is list and
            set(required) == set(properties) and len(required) == len(properties),
            "V2_SCHEMA_REQUIRED")
    require(type(instance) is dict and set(instance) == set(properties),
            "V2_SCHEMA_PROPERTIES")
    for key, subschema in properties.items():
        validate_exact_schema(instance[key], subschema)


def _validate_schema(name: str, instance: Any) -> None:
    schema = load_json(PACKAGE / name)
    require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema" and
            type(schema.get("$id")) is str, "V2_SCHEMA_HEADER")
    body = {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}
    validate_exact_schema(instance, body)


def v1_tree() -> tuple[int, str]:
    paths = sorted(
        path for path in V1_ROOT.rglob("*")
        if path.is_file() and "v2" not in path.relative_to(V1_ROOT).parts
        and "__pycache__" not in path.parts
    )
    tree = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(V1_ROOT).as_posix()
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(file_hash.encode("ascii"))
        tree.update(b"\n")
    return len(paths), tree.hexdigest()


def validate_receipt(value: Any) -> dict[str, Any]:
    _validate_schema("installation-receipt-v2.schema.json", value)
    require(digest(value) == EXPECTED_RECEIPT_SHA256, "V2_RECEIPT_DIGEST")
    require(value["source"] == "installed-tool-observation" and
            value["credentials_recorded"] is False, "V2_RECEIPT_PROVENANCE")
    require(value["installation_state"] == "homebrew-packages-installed-not-activated",
            "V2_RECEIPT_INSTALL_VS_ACTIVATION")
    for name, (version, path, sha256) in EXPECTED_TOOLS.items():
        tool = value["tools"][name]
        require((tool["version"], tool["executable_path"], tool["sha256"]) ==
                (version, path, sha256), f"V2_TOOL_{name.upper()}")
    require(value["tools"]["colima"]["commit"].startswith("00f6c297"),
            "V2_COLIMA_COMMIT")
    require(value["tools"]["docker"]["build"] == "5457199aa5", "V2_DOCKER_BUILD")
    activation = value["activation_observation"]
    require(activation["colima_service_status"] == "none" and
            activation["matching_processes"] == [] and
            activation["daemon_queried"] is False and
            activation["docker_context_inspected_or_mutated"] is False and
            activation["vm_identity"] is None, "V2_ACTIVATION_NONCLAIM")
    home = activation["home_docker_config"]
    require(home["state_before"] == "absent" and home["state_after"] == "absent" and
            home["contents_and_metadata_unchanged"] is True and
            home["before_aggregate_sha256"] == home["after_aggregate_sha256"],
            "V2_DOCKER_HOME_UNCHANGED")
    return value


def validate_profile(value: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    _validate_schema("runtime-profile-v2.schema.json", value)
    require(value["status"] == "selected-disabled" and value["runnable"] is False and
            value["apply_allowed"] is False, "V2_PROFILE_APPLY_FENCE")
    require(value["resolved_blockers"] == RESOLVED_BLOCKERS and
            value["blockers"] == RETAINED_BLOCKERS, "V2_PROFILE_BLOCKERS")
    require(value["installation_evidence"]["canonical_sha256"] == digest(receipt),
            "V2_PROFILE_RECEIPT_BINDING")
    host = value["host_state"]
    require(host["colima_environment"] == {
        "COLIMA_HOME": "$WORKSPACE/factor/runtime/local/colima",
        "COLIMA_PROFILE": "factor-mining",
    } and host["colima_config"] == {"autoActivate": False} and
            host["expected_future_docker_context"] == "colima-factor-mining" and
            host["docker_context"] is None and host["vm_identity"] is None and
            host["change_global_current_docker_context"] is False,
            "V2_PROFILE_HOST_FENCE")
    count, tree_hash = v1_tree()
    frozen = value["frozen_v1"]
    require((count, tree_hash) == (frozen["file_count"], frozen["tree_sha256"]) ==
            (18, EXPECTED_V1_TREE_SHA256), "V2_V1_TREE_FREEZE")
    require(hashlib.sha256((V1_ROOT / "runtime-profile.json").read_bytes()).hexdigest() ==
            frozen["contract_profile_sha256"] == EXPECTED_V1_PROFILE_SHA256,
            "V2_V1_PROFILE_FREEZE")
    return value


def validate_bundle(receipt_path: Path | str = RECEIPT_PATH,
                    profile_path: Path | str = PROFILE_PATH) -> dict[str, str]:
    receipt = validate_receipt(load_json(receipt_path))
    profile = validate_profile(load_json(profile_path), receipt)
    return {
        "installation-receipt.json": digest(receipt),
        "runtime-profile-v2.json": digest(profile),
        "frozen-v1-tree": v1_tree()[1],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate read-only local installation evidence")
    parser.add_argument("--receipt", type=Path, default=RECEIPT_PATH)
    parser.add_argument("--profile", type=Path, default=PROFILE_PATH)
    args = parser.parse_args(argv)
    try:
        hashes = validate_bundle(args.receipt, args.profile)
    except V2ContractError as exc:
        print(f"INVALID {exc}")
        return 2
    print(json.dumps({"valid": True, "status": "selected-disabled",
                      "runnable": False, "apply_allowed": False,
                      "sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
