"""Fail-closed validation for the Colima v3 short-path activation repair.

This module reads local contracts only. It never invokes Colima, Docker, a VM,
a daemon, a context, a container, or a network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parent
WORKSPACE = PACKAGE.parents[3]
PROFILE_PATH = PACKAGE / "runtime-profile-v3.json"
COMMAND_PATH = PACKAGE / "activation-command-v3.json"
MAX_BYTES = 256 * 1024
EXPECTED_WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
SOCKET_SUFFIX = Path("_lima/colima-factor-mining/ssh.sock.1234567890123456")
UNIX_PATH_MAX = 104
EXPECTED_V1_TREE = "ba79cf54ea34bdd09f063c1809060d6f9564b5d8f46aa726aff750ffea8c7908"
EXPECTED_V2_RECEIPT = "c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327"
EXPECTED_V2_PROFILE = "40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d"


class V3ContractError(ValueError):
    """Stable sanitized validation failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise V3ContractError(code)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "V3_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw: bytes | str) -> Any:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "V3_JSON_SIZE")
    try:
        return json.loads(
            raw, object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                V3ContractError("V3_JSON_NONFINITE")),
        )
    except V3ContractError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise V3ContractError("V3_JSON_INVALID") from None


def load_json(path: Path | str) -> Any:
    try:
        return loads_strict(Path(path).read_bytes())
    except OSError:
        raise V3ContractError("V3_JSON_UNAVAILABLE") from None


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise V3ContractError("V3_JSON_INVALID") from None


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


def validate_schema(instance: Any, schema_name: str) -> None:
    schema = load_json(PACKAGE / schema_name)
    require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema" and
            type(schema.get("$id")) is str and set(schema) == {"$schema", "$id", "const"},
            "V3_SCHEMA_DOCUMENT")
    _exact(instance, schema["const"], "V3_SCHEMA_CONST")


def _no_symlink_ancestor(workspace: Path, candidate: Path) -> None:
    relative = candidate.relative_to(workspace)
    current = workspace
    require(workspace.exists() and workspace.is_dir() and not workspace.is_symlink(),
            "V3_WORKSPACE_INVALID")
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            require(not current.is_symlink(), "V3_STATE_ROOT_SYMLINK")


def validate_state_root(workspace: Path, state_root: Path, *, require_absent: bool = True) -> int:
    require(isinstance(workspace, Path) and isinstance(state_root, Path), "V3_PATH_TYPE")
    require(workspace == EXPECTED_WORKSPACE and workspace.is_absolute(), "V3_WORKSPACE_INVALID")
    require(state_root.is_absolute(), "V3_STATE_ROOT_INVALID")
    try:
        state_root.relative_to(workspace)
    except ValueError:
        raise V3ContractError("V3_STATE_ROOT_OUTSIDE_WORKSPACE") from None
    require(state_root == workspace / ".c", "V3_STATE_ROOT_INVALID")
    _no_symlink_ancestor(workspace, state_root)
    if require_absent:
        require(not state_root.exists() and not state_root.is_symlink(),
                "V3_STATE_ROOT_NOT_ABSENT")
    socket_path = state_root / SOCKET_SUFFIX
    length = len(str(socket_path).encode("utf-8"))
    require(length < UNIX_PATH_MAX, "V3_SOCKET_PATH_TOO_LONG")
    return length


def predecessor_v1_tree() -> tuple[int, str]:
    root = PACKAGE.parent
    paths = sorted(path for path in root.rglob("*")
                   if path.is_file() and not ({"v2", "v3"} & set(path.relative_to(root).parts))
                   and "__pycache__" not in path.parts)
    tree = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix()
        tree.update(relative.encode("utf-8"))
        tree.update(b"\0")
        tree.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        tree.update(b"\n")
    return len(paths), tree.hexdigest()


def validate_profile(value: Any, *, workspace: Path = EXPECTED_WORKSPACE,
                     state_root: Path | None = None, require_absent: bool = True) -> dict[str, Any]:
    validate_schema(value, "runtime-profile-v3.schema.json")
    require(value["status"] == "selected-disabled" and value["runnable"] is False and
            value["apply_allowed"] is False, "V3_APPLY_FENCE")
    frozen = value["frozen_predecessors"]
    require(predecessor_v1_tree() == (18, EXPECTED_V1_TREE), "V3_V1_TREE_DRIFT")
    require(frozen == {
        "v1_tree_sha256": EXPECTED_V1_TREE,
        "v2_installation_receipt_canonical_sha256": EXPECTED_V2_RECEIPT,
        "v2_runtime_profile_canonical_sha256": EXPECTED_V2_PROFILE,
    }, "V3_PREDECESSOR_BINDING")
    failure = value["observed_failure"]
    require(failure["classification"] == "permanent-pre-dispatch" and
            failure["retry_same_command"] is False and failure["vm_created"] is False and
            failure["vm_running"] is False and failure["old_main_socket_path_length"] == 119 and
            failure["observed_worktree_socket_path_length"] == 160,
            "V3_FAILURE_EVIDENCE")
    host = value["host_state"]
    require(host["workspace"] == str(EXPECTED_WORKSPACE) and host["colima_environment"] == {
        "COLIMA_HOME": "$WORKSPACE/.c", "COLIMA_PROFILE": "factor-mining"} and
            host["docker_config"] == "$WORKSPACE/factor/runtime/local/docker-config" and
            host["colima_config"] == {"autoActivate": False} and
            host["expected_docker_context"] == "colima-factor-mining" and
            host["change_global_current_docker_context"] is False and
            host["docker_context"] is None and host["vm_identity"] is None,
            "V3_HOST_FENCE")
    selected_root = state_root if state_root is not None else workspace / ".c"
    length = validate_state_root(workspace, selected_root, require_absent=require_absent)
    require(length == host["worst_socket_path_length"] == 94 and
            host["socket_path_limit_exclusive"] == UNIX_PATH_MAX,
            "V3_SOCKET_EVIDENCE")
    platform = value["platform"]
    require(platform == {
        "provider": "colima", "runtime": "docker", "vm_type": "vz", "cpu": 6,
        "memory_gib": 12, "disk_gib": 40, "root_disk_gib": 20,
        "mounts": "none", "ssh_config": False, "kubernetes": False,
    }, "V3_PLATFORM_DRIFT")
    return value


def validate_command(value: Any) -> dict[str, Any]:
    validate_schema(value, "activation-command-v3.schema.json")
    require(value["status"] == "selected-disabled" and value["apply_allowed"] is False and
            value["executed"] is False, "V3_COMMAND_APPLY_FENCE")
    require(value["environment"] == {
        "COLIMA_HOME": "$WORKSPACE/.c", "COLIMA_PROFILE": "factor-mining",
        "DOCKER_CONFIG": "$WORKSPACE/factor/runtime/local/docker-config",
    }, "V3_COMMAND_ENVIRONMENT")
    require(value["argv"] == [
        "/opt/homebrew/bin/colima", "start", "factor-mining", "--activate=false",
        "--runtime", "docker", "--vm-type", "vz", "--cpus", "6", "--memory", "12",
        "--disk", "40", "--root-disk", "20", "--mount", "none",
        "--ssh-config=false", "--kubernetes=false", "--save-config=true",
    ], "V3_COMMAND_ARGV")
    require(value["rollback_argv"] == [
        "/opt/homebrew/bin/colima", "delete", "factor-mining", "--force"],
        "V3_ROLLBACK_ARGV")
    return value


def validate_bundle(*, workspace: Path = EXPECTED_WORKSPACE,
                    state_root: Path | None = None, require_absent: bool = True) -> dict[str, str]:
    profile = validate_profile(load_json(PROFILE_PATH), workspace=workspace,
                               state_root=state_root, require_absent=require_absent)
    command = validate_command(load_json(COMMAND_PATH))
    return {"runtime-profile-v3.json": digest(profile),
            "activation-command-v3.json": digest(command)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate disabled Colima v3 path repair")
    parser.parse_args(argv)
    try:
        hashes = validate_bundle()
    except V3ContractError as exc:
        print(f"INVALID {exc}")
        return 2
    print(json.dumps({"valid": True, "status": "selected-disabled", "runnable": False,
                      "apply_allowed": False, "socket_path_length": 94,
                      "sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
