"""Secure, non-executing Colima activation preflight.

The default path validates and returns a plan only. ``apply=True`` may create the
three empty private state roots; it still never invokes Colima or Docker.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any

PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "runtime-profile-v4.json"
COMMAND_PATH = PACKAGE / "activation-command-v4.json"
EXPECTED_WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
MAX_BYTES = 256 * 1024
SOCKET_SUFFIX = Path("_lima/colima-factor-mining/ssh.sock.1234567890123456")
UNIX_PATH_MAX = 104
ROOTS = {
    "COLIMA_HOME": Path(".c"),
    "COLIMA_CACHE_HOME": Path("factor/runtime/local/colima-cache"),
    "DOCKER_CONFIG": Path("factor/runtime/local/docker-config"),
}
V2_BINDINGS = {
    "v2_installation_receipt": {
        "path": "factor/docker/local/v2/installation-receipt.json",
        "physical_sha256": "cf552b48d3511ae0116d0554d3035e911aa6425fceebd7a8c8f8a4fc93164908",
        "canonical_sha256": "c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327",
    },
    "v2_runtime_profile": {
        "path": "factor/docker/local/v2/runtime-profile-v2.json",
        "physical_sha256": "81d42def01f98ec29b4f12fb5cb587114c0b28bc1705598e8a04570ecfbc7d3f",
        "canonical_sha256": "40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d",
    },
}


class V4ContractError(ValueError):
    """Stable sanitized preflight failure."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise V4ContractError(code)


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        require(key not in result, "V4_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str):
        require(not any(0xD800 <= ord(char) <= 0xDFFF for char in value),
                "V4_JSON_UNICODE")
    elif isinstance(value, list):
        for item in value:
            _reject_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)


def loads_strict(raw: bytes | str) -> Any:
    if isinstance(raw, str):
        try:
            raw = raw.encode("utf-8")
        except UnicodeError:
            raise V4ContractError("V4_JSON_UNICODE") from None
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "V4_JSON_SIZE")
    try:
        value = json.loads(
            raw, object_pairs_hook=_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                V4ContractError("V4_JSON_NONFINITE")),
        )
    except V4ContractError:
        raise
    except UnicodeError:
        raise V4ContractError("V4_JSON_UNICODE") from None
    except (TypeError, ValueError):
        raise V4ContractError("V4_JSON_INVALID") from None
    _reject_surrogates(value)
    return value


def load_json(path: Path | str) -> Any:
    try:
        return loads_strict(Path(path).read_bytes())
    except OSError:
        raise V4ContractError("V4_JSON_UNAVAILABLE") from None


def canonical(value: Any) -> bytes:
    _reject_surrogates(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise V4ContractError("V4_JSON_INVALID") from None


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value: Any) -> str:
    return sha256(canonical(value))


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


def validate_schema_value(instance: Any, schema: Any) -> None:
    require(type(schema) is dict, "V4_SCHEMA_DOCUMENT")
    if "const" in schema:
        _exact(instance, schema["const"], "V4_SCHEMA_CONST")
        return
    kind = schema.get("type")
    if kind == "null":
        require(instance is None, "V4_SCHEMA_TYPE")
    elif kind == "boolean":
        require(type(instance) is bool, "V4_SCHEMA_TYPE")
    elif kind == "integer":
        require(type(instance) is int, "V4_SCHEMA_TYPE")
    elif kind == "string":
        require(type(instance) is str, "V4_SCHEMA_TYPE")
        _reject_surrogates(instance)
    elif kind == "array":
        require(type(instance) is list and type(schema.get("items")) is dict,
                "V4_SCHEMA_TYPE")
        for item in instance:
            validate_schema_value(item, schema["items"])
    elif kind == "object":
        properties = schema.get("properties")
        required = schema.get("required")
        require(schema.get("additionalProperties") is False and type(properties) is dict and
                type(required) is list and set(required) == set(properties) and
                type(instance) is dict and set(instance) == set(properties),
                "V4_SCHEMA_TYPE")
        for key, child in properties.items():
            validate_schema_value(instance[key], child)
    else:
        raise V4ContractError("V4_SCHEMA_TYPE")


def validate_schema(instance: Any, name: str) -> None:
    schema = load_json(PACKAGE / name)
    require(schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema" and
            type(schema.get("$id")) is str, "V4_SCHEMA_HEADER")
    body = {key: value for key, value in schema.items() if key not in {"$schema", "$id"}}
    validate_schema_value(instance, body)


def validate_workspace(workspace: Path) -> Path:
    require(isinstance(workspace, Path) and workspace.is_absolute(), "V4_WORKSPACE_PATH")
    try:
        resolved = workspace.resolve(strict=True)
    except OSError:
        raise V4ContractError("V4_WORKSPACE_UNAVAILABLE") from None
    require(resolved == workspace and workspace.is_dir() and not workspace.is_symlink(),
            "V4_WORKSPACE_UNSAFE")
    return workspace


def _validate_predecessors(workspace: Path, expected: dict[str, Any]) -> None:
    require(expected == V2_BINDINGS, "V4_PREDECESSOR_DECLARATION")
    for binding in V2_BINDINGS.values():
        path = workspace / binding["path"]
        try:
            raw = path.read_bytes()
        except OSError:
            raise V4ContractError("V4_PREDECESSOR_UNAVAILABLE") from None
        require(sha256(raw) == binding["physical_sha256"], "V4_PREDECESSOR_PHYSICAL_DRIFT")
        require(digest(loads_strict(raw)) == binding["canonical_sha256"],
                "V4_PREDECESSOR_CANONICAL_DRIFT")


def _secure_root(workspace_fd: int, workspace: Path, relative: Path, *, apply: bool) -> dict[str, Any]:
    require(not relative.is_absolute() and ".." not in relative.parts and relative.parts,
            "V4_ROOT_RELATIVE")
    current_fd = os.dup(workspace_fd)
    current_path = workspace
    final_created = False
    try:
        for index, part in enumerate(relative.parts):
            final = index == len(relative.parts) - 1
            current_path = current_path / part
            created = False
            try:
                entry = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
                require(not stat.S_ISLNK(entry.st_mode), "V4_ROOT_SYMLINK")
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=current_fd)
            except FileNotFoundError:
                if not apply:
                    return {"path": str(workspace / relative), "action": "would-create", "created": False}
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                    created = True
                except FileExistsError:
                    created = False
                try:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=current_fd)
                except OSError:
                    raise V4ContractError("V4_ROOT_RACE_OR_SYMLINK") from None
            except (NotADirectoryError, OSError):
                raise V4ContractError("V4_ROOT_RACE_OR_SYMLINK") from None
            os.close(current_fd)
            current_fd = next_fd
            metadata = os.fstat(current_fd)
            require(stat.S_ISDIR(metadata.st_mode), "V4_ROOT_NOT_DIRECTORY")
            require(metadata.st_uid == os.geteuid(), "V4_ROOT_OWNER")
            if final:
                require(stat.S_IMODE(metadata.st_mode) == 0o700, "V4_ROOT_MODE")
                require(os.listdir(current_fd) == [], "V4_ROOT_NOT_EMPTY")
                final_created = created
            elif created:
                require(stat.S_IMODE(metadata.st_mode) == 0o700, "V4_PARENT_MODE")
        return {"path": str(current_path), "action": "created" if final_created else "existing-empty",
                "created": final_created}
    finally:
        os.close(current_fd)


def _prepare_roots(workspace: Path, *, apply: bool, check_socket: bool) -> dict[str, Any]:
    require(type(apply) is bool and type(check_socket) is bool, "V4_APPLY_TYPE")
    workspace = validate_workspace(workspace)
    try:
        workspace_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise V4ContractError("V4_WORKSPACE_RACE_OR_SYMLINK") from None
    try:
        roots = {name: _secure_root(workspace_fd, workspace, relative, apply=apply)
                 for name, relative in ROOTS.items()}
    finally:
        os.close(workspace_fd)
    colima_path = Path(roots["COLIMA_HOME"]["path"]) / SOCKET_SUFFIX
    length = len(str(colima_path).encode("utf-8"))
    if check_socket:
        require(length < UNIX_PATH_MAX, "V4_SOCKET_PATH_TOO_LONG")
    return {"roots": roots, "socket_path_bytes": length, "applied": apply}


def prepare_roots(workspace: Path, *, apply: bool = False) -> dict[str, Any]:
    """Public preflight; socket-length enforcement cannot be disabled."""
    return _prepare_roots(workspace, apply=apply, check_socket=True)


def validate_profile(value: Any, workspace: Path) -> dict[str, Any]:
    validate_schema(value, "runtime-profile-v4.schema.json")
    require(value["status"] == "selected-disabled" and value["runnable"] is False and
            value["apply_allowed"] is False, "V4_APPLY_FENCE")
    workspace = validate_workspace(workspace)
    require(value["workspace"] == str(workspace), "V4_WORKSPACE_BINDING")
    _validate_predecessors(workspace, value["predecessors"])
    expected_env = {name: str(workspace / relative) for name, relative in ROOTS.items()}
    expected_env["COLIMA_PROFILE"] = "factor-mining"
    require(value["environment"] == expected_env, "V4_ENVIRONMENT_BINDING")
    require(value["platform"] == {
        "runtime": "docker", "vm_type": "vz", "cpu": 6, "memory_gib": 12,
        "disk_gib": 40, "root_disk_gib": 20, "mounts": "none",
        "ssh_config": False, "kubernetes": False, "auto_activate": False,
        "template": False,
    }, "V4_PLATFORM_DRIFT")
    require(value["socket_contract"]["actual_bytes"] == 94 and
            value["socket_contract"]["exclusive_max_bytes"] == UNIX_PATH_MAX,
            "V4_SOCKET_DECLARATION")
    require(value["failure_policy"] == {
        "path_or_config_error": "permanent-pre-dispatch", "retry_unchanged": False,
        "rollback_required_after_partial_creation": True,
    }, "V4_FAILURE_POLICY")
    return value


def validate_command(value: Any, workspace: Path) -> dict[str, Any]:
    validate_schema(value, "activation-command-v4.schema.json")
    require(value["status"] == "selected-disabled" and value["apply_allowed"] is False and
            value["executed"] is False and value["workspace"] == str(workspace),
            "V4_COMMAND_FENCE")
    expected_env = {name: str(workspace / relative) for name, relative in ROOTS.items()}
    expected_env["COLIMA_PROFILE"] = "factor-mining"
    require(value["environment"] == expected_env, "V4_COMMAND_ENV")
    require(value["argv"] == [
        "/opt/homebrew/bin/colima", "start", "factor-mining", "--activate=false",
        "--runtime", "docker", "--vm-type", "vz", "--cpus", "6", "--memory", "12",
        "--disk", "40", "--root-disk", "20", "--mount", "none",
        "--ssh-config=false", "--kubernetes=false", "--template=false", "--save-config=true",
    ], "V4_COMMAND_ARGV")
    require(value["rollback"] == {
        "argv": ["/opt/homebrew/bin/colima", "delete", "factor-mining", "--force"],
        "same_environment_required": True,
    }, "V4_ROLLBACK")
    return value


def build_plan(workspace: Path, *, apply: bool = False) -> dict[str, Any]:
    workspace = validate_workspace(workspace)
    profile = validate_profile(load_json(PROFILE_PATH), workspace)
    command = validate_command(load_json(COMMAND_PATH), workspace)
    prepared = prepare_roots(workspace, apply=apply)
    return {
        "schema_version": 1,
        "status": "prepared-roots" if apply else "selected-disabled",
        "apply_allowed": apply,
        "environment": command["environment"],
        "argv": command["argv"],
        "rollback": command["rollback"],
        "preflight": prepared,
        "profile_sha256": digest(profile),
        "command_sha256": digest(command),
    }
