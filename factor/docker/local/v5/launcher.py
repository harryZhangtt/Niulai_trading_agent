"""One-shot, receipt-producing Colima activation transaction.

Default use is plan-only. Tests inject a fake process runner and status probe. The
real subprocess path requires explicit apply, capability and parent approval.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
from typing import Any, Callable

from factor.docker.local.v4 import launcher as v4

PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "runtime-profile-v5.json"
EXPECTED_WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
LOCK_RELATIVE = Path(".factor-colima-activation.lock")
LOCK_MODE = 0o600
CAPABILITY = "factor-local-v5-start"
PATH_VALUE = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
EXPECTED_V4 = {
    "v4_profile_physical_sha256": "705c78e004d206c98c4d30de38384e3d75b72c2525efecc1cd7c7cbac3667ac3",
    "v4_profile_canonical_sha256": "5be9d1827441ba81c8d30beac9ee1090a2866320141940b526997bcf7e8a6407",
    "v4_command_physical_sha256": "5380a6d65d756fc4f36a69c5f1f1414d896cdc042c66b11fc3af33c5c8853ba9",
    "v4_command_canonical_sha256": "7f89bb6c2f9cc4fa7e6a93b063a32d7cf24eeacf85c9318844a85a13ba61a3df",
    "v2_receipt_physical_sha256": "cf552b48d3511ae0116d0554d3035e911aa6425fceebd7a8c8f8a4fc93164908",
    "v2_receipt_canonical_sha256": "c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327",
    "v2_profile_physical_sha256": "81d42def01f98ec29b4f12fb5cb587114c0b28bc1705598e8a04570ecfbc7d3f",
    "v2_profile_canonical_sha256": "40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d",
}


class V5ContractError(ValueError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise V5ContractError(code)


def load_json(path: Path) -> Any:
    try:
        return v4.loads_strict(path.read_bytes())
    except v4.V4ContractError as exc:
        raise V5ContractError(str(exc).replace("V4_", "V5_")) from None
    except OSError:
        raise V5ContractError("V5_JSON_UNAVAILABLE") from None


def canonical(value: Any) -> bytes:
    try:
        return v4.canonical(value)
    except v4.V4ContractError as exc:
        raise V5ContractError(str(exc).replace("V4_", "V5_")) from None


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_profile(value: Any, workspace: Path) -> dict[str, Any]:
    schema = load_json(PACKAGE / "runtime-profile-v5.schema.json")
    try:
        v4.validate_schema_value(value, {"const": schema["const"]})
    except v4.V4ContractError as exc:
        raise V5ContractError(str(exc).replace("V4_", "V5_")) from None
    require(value["status"] == "selected-disabled" and value["runnable"] is False and
            value["apply_allowed"] is False and
            value["workspace_policy"] == "explicit-absolute-no-symlink" and
            value["execution"]["cwd_policy"] == "explicit-workspace",
            "V5_PROFILE_FENCE")
    require(value["predecessors"] == EXPECTED_V4, "V5_PREDECESSOR_DECLARATION")
    bindings = [
        (workspace / "factor/docker/local/v4/runtime-profile-v4.json",
         EXPECTED_V4["v4_profile_physical_sha256"], EXPECTED_V4["v4_profile_canonical_sha256"]),
        (workspace / "factor/docker/local/v4/activation-command-v4.json",
         EXPECTED_V4["v4_command_physical_sha256"], EXPECTED_V4["v4_command_canonical_sha256"]),
        (workspace / "factor/docker/local/v2/installation-receipt.json",
         EXPECTED_V4["v2_receipt_physical_sha256"], EXPECTED_V4["v2_receipt_canonical_sha256"]),
        (workspace / "factor/docker/local/v2/runtime-profile-v2.json",
         EXPECTED_V4["v2_profile_physical_sha256"], EXPECTED_V4["v2_profile_canonical_sha256"]),
    ]
    for path, physical, semantic in bindings:
        raw = path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == physical, "V5_PREDECESSOR_PHYSICAL_DRIFT")
        require(digest(v4.loads_strict(raw)) == semantic, "V5_PREDECESSOR_CANONICAL_DRIFT")
    require(value["authorization"] == {"capability": CAPABILITY,
            "profile_id": "factor-local-docker-colima-v5",
            "explicit_apply_required": True, "parent_approval_required": True},
            "V5_AUTHORIZATION")
    require(value["threat_model"] == {"lock_is_cooperative": True,
            "malicious_same_user_mutation_prevented": False,
            "same_user_hostile_mutation_out_of_scope": True}, "V5_THREAT_MODEL")
    return value


def _environment(workspace: Path) -> dict[str, str]:
    return {
        "COLIMA_HOME": str(workspace / ".c"),
        "COLIMA_CACHE_HOME": str(workspace / "factor/runtime/local/colima-cache"),
        "COLIMA_PROFILE": "factor-mining",
        "DOCKER_CONFIG": str(workspace / "factor/runtime/local/docker-config"),
        "PATH": PATH_VALUE,
    }


def _argv() -> list[str]:
    return [
        "/opt/homebrew/bin/colima", "start", "factor-mining", "--activate=false",
        "--runtime", "docker", "--vm-type", "vz", "--cpus", "6", "--memory", "12",
        "--disk", "40", "--root-disk", "20", "--mount", "none",
        "--ssh-config=false", "--kubernetes=false", "--template=false", "--save-config=true",
    ]


def _open_lock(workspace_fd: int) -> tuple[int, tuple[int, int]]:
    try:
        fd = os.open(LOCK_RELATIVE.as_posix(), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                     LOCK_MODE, dir_fd=workspace_fd)
    except OSError:
        raise V5ContractError("V5_LOCK_UNAVAILABLE") from None
    try:
        metadata = os.fstat(fd)
        require(stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) == LOCK_MODE and
                metadata.st_uid == os.geteuid(), "V5_LOCK_METADATA")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise V5ContractError("V5_LOCK_CONTENDED") from None
        return fd, (metadata.st_dev, metadata.st_ino)
    except Exception:
        os.close(fd)
        raise


def _create_roots(workspace_fd: int, workspace: Path, created: list[Path]) -> tuple[dict[str, int], dict[str, tuple[int, int]]]:
    fds: dict[str, int] = {}
    identities: dict[str, tuple[int, int]] = {}
    try:
        for name, relative in v4.ROOTS.items():
            current_fd = os.dup(workspace_fd)
            current = workspace
            for index, part in enumerate(relative.parts):
                final = index == len(relative.parts) - 1
                current = current / part
                made = False
                try:
                    entry = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
                    require(not stat.S_ISLNK(entry.st_mode), "V5_ROOT_SYMLINK")
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                      dir_fd=current_fd)
                except FileNotFoundError:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current_fd)
                        made = True
                        created.append(current)
                        next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                          dir_fd=current_fd)
                    except OSError:
                        raise V5ContractError("V5_ROOT_CREATE_OR_RACE") from None
                except OSError:
                    raise V5ContractError("V5_ROOT_OPEN_OR_RACE") from None
                os.close(current_fd)
                current_fd = next_fd
                metadata = os.fstat(current_fd)
                require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == os.geteuid(),
                        "V5_ROOT_OWNER_OR_TYPE")
                if made:
                    require(stat.S_IMODE(metadata.st_mode) == 0o700, "V5_ROOT_MODE")
                if final:
                    require(stat.S_IMODE(metadata.st_mode) == 0o700 and os.listdir(current_fd) == [],
                            "V5_ROOT_NOT_PRIVATE_EMPTY")
                    fds[name] = current_fd
                    identities[name] = (metadata.st_dev, metadata.st_ino)
            if name not in fds:
                raise V5ContractError("V5_ROOT_MISSING")
        socket_length = len(str(workspace / ".c" / v4.SOCKET_SUFFIX).encode("utf-8"))
        require(socket_length < v4.UNIX_PATH_MAX, "V5_SOCKET_PATH_TOO_LONG")
        return fds, identities
    except Exception:
        for fd in fds.values():
            os.close(fd)
        raise


def _revalidate_roots(workspace_fd: int, fds: dict[str, int], identities: dict[str, tuple[int, int]]) -> None:
    for name, relative in v4.ROOTS.items():
        current_fd = os.dup(workspace_fd)
        try:
            for index, part in enumerate(relative.parts):
                entry = os.stat(part, dir_fd=current_fd, follow_symlinks=False)
                require(not stat.S_ISLNK(entry.st_mode), "V5_PRESPAWN_SYMLINK")
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            live = os.fstat(current_fd)
            held = os.fstat(fds[name])
            require((live.st_dev, live.st_ino) == identities[name] == (held.st_dev, held.st_ino),
                    "V5_PRESPAWN_IDENTITY_DRIFT")
            require(live.st_uid == os.geteuid() and stat.S_IMODE(live.st_mode) == 0o700,
                    "V5_PRESPAWN_METADATA_DRIFT")
            require(os.listdir(current_fd) == [], "V5_PRESPAWN_NOT_EMPTY")
        except OSError:
            raise V5ContractError("V5_PRESPAWN_RACE") from None
        finally:
            os.close(current_fd)


def _cleanup_created(created: list[Path]) -> bool:
    clean = True
    for path in sorted(created, key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            clean = False
    return clean


def _status_valid(status: Any, env: dict[str, str]) -> bool:
    return type(status) is dict and status == {
        "profile": "factor-mining", "running": True,
        "context": "colima-factor-mining", "context_config_root": env["DOCKER_CONFIG"],
        "global_context_before": status.get("global_context_before"),
        "global_context_after": status.get("global_context_before"),
    } and type(status.get("global_context_before")) is str


def _status_proves_absent(status: Any) -> bool:
    return (type(status) is dict and status.get("profile") == "factor-mining" and
            status.get("running") is False)


def _receipt(status: str, code: str, *, spawned: bool, child_exit: int | None,
             timed_out: bool, vm_running: bool | None, created: list[Path], retained: list[Path],
             cleanup_complete: bool) -> dict[str, Any]:
    value = {
        "schema_version": 1, "kind": "factor_local_colima_activation_receipt",
        "status": status, "code": code, "spawned": spawned, "child_exit": child_exit,
        "timed_out": timed_out, "vm_running": vm_running,
        "created_roots": [str(path) for path in created],
        "retained_roots": [str(path) for path in retained],
        "cleanup_complete": cleanup_complete, "retry_allowed": False,
        "diagnostic": "sanitized",
    }
    validate_receipt(value)
    return value


def _schema_type_matches(value: Any, name: str) -> bool:
    return {"null": value is None, "boolean": type(value) is bool,
            "integer": type(value) is int, "string": type(value) is str,
            "array": type(value) is list, "object": type(value) is dict}.get(name, False)


def _validate_schema(value: Any, schema: Any) -> None:
    require(type(schema) is dict, "V5_SCHEMA_DOCUMENT")
    if "const" in schema:
        require(type(value) is type(schema["const"]) and value == schema["const"], "V5_SCHEMA_CONST")
        return
    if "enum" in schema:
        require(value in schema["enum"], "V5_SCHEMA_ENUM")
    kinds = schema.get("type")
    if type(kinds) is str:
        kinds = [kinds]
    require(type(kinds) is list and all(type(item) is str for item in kinds) and
            any(_schema_type_matches(value, item) for item in kinds), "V5_SCHEMA_TYPE")
    if type(value) is list:
        require(type(schema.get("items")) is dict, "V5_SCHEMA_ITEMS")
        for item in value:
            _validate_schema(item, schema["items"])
    elif type(value) is dict:
        props, required = schema.get("properties"), schema.get("required")
        require(schema.get("additionalProperties") is False and type(props) is dict and
                type(required) is list and set(required) == set(props) == set(value),
                "V5_SCHEMA_PROPERTIES")
        for key, child in props.items():
            _validate_schema(value[key], child)


def validate_receipt(value: Any) -> None:
    schema = load_json(PACKAGE / "activation-receipt-v5.schema.json")
    body = {key: item for key, item in schema.items() if key not in {"$schema", "$id"}}
    _validate_schema(value, body)
    require(value["status"] in {"success", "failed", "unknown"} and
            value["code"] in {"V5_STARTED_RECONCILED", "V5_START_FAILED_NO_VM",
                              "V5_START_OUTCOME_UNKNOWN", "V5_PRESPAWN_FAILED"},
            "V5_RECEIPT_VOCABULARY")


def default_runner(argv: list[str], env: dict[str, str], cwd: Path, timeout: int):
    return subprocess.run(argv, env=env, cwd=cwd, shell=False, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
                          timeout=timeout, check=False)


def activate(workspace: Path, *, apply: bool = False, capability: str | None = None,
             parent_approved: bool = False,
             runner: Callable[[list[str], dict[str, str], Path, int], Any] | None = None,
             status_probe: Callable[[dict[str, str]], Any] | None = None,
             before_spawn: Callable[[Path], None] | None = None) -> dict[str, Any]:
    workspace = v4.validate_workspace(workspace)
    profile = validate_profile(load_json(PROFILE_PATH), workspace)
    if not apply:
        return {"schema_version": 1, "status": "selected-disabled", "apply_allowed": False,
                "profile_sha256": digest(profile), "environment": _environment(workspace),
                "argv": _argv()}
    require(type(parent_approved) is bool and parent_approved is True and capability == CAPABILITY,
            "V5_ACTIVATION_UNAUTHORIZED")
    require(runner is not None and status_probe is not None, "V5_DEPENDENCY_MISSING")
    workspace_fd = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock_fd = -1
    lock_identity: tuple[int, int] | None = None
    roots: dict[str, int] = {}
    created: list[Path] = []
    spawned = False
    try:
        lock_fd, lock_identity = _open_lock(workspace_fd)
        roots, identities = _create_roots(workspace_fd, workspace, created)
        if before_spawn is not None:
            before_spawn(workspace)
        _revalidate_roots(workspace_fd, roots, identities)
        current_lock = os.stat(LOCK_RELATIVE.as_posix(), dir_fd=workspace_fd, follow_symlinks=False)
        require((current_lock.st_dev, current_lock.st_ino) == lock_identity, "V5_LOCK_IDENTITY_DRIFT")
        env = _environment(workspace)
        try:
            spawned = True
            result = runner(_argv(), env, workspace, profile["execution"]["timeout_seconds"])
            child_exit = result.returncode
            timed_out = False
        except subprocess.TimeoutExpired:
            child_exit = None
            timed_out = True
        except OSError:
            child_exit = None
            timed_out = False
        try:
            observed = status_probe(env)
        except Exception:
            observed = None
        running = observed.get("running") if type(observed) is dict and type(observed.get("running")) is bool else None
        if child_exit == 0 and _status_valid(observed, env):
            return _receipt("success", "V5_STARTED_RECONCILED", spawned=True, child_exit=0,
                            timed_out=False, vm_running=True, created=created,
                            retained=created, cleanup_complete=False)
        if _status_proves_absent(observed):
            cleaned = _cleanup_created(created)
            return _receipt("failed", "V5_START_FAILED_NO_VM", spawned=spawned,
                            child_exit=child_exit, timed_out=timed_out, vm_running=False,
                            created=created, retained=[] if cleaned else created,
                            cleanup_complete=cleaned)
        return _receipt("unknown", "V5_START_OUTCOME_UNKNOWN", spawned=spawned,
                        child_exit=child_exit, timed_out=timed_out, vm_running=running,
                        created=created, retained=created, cleanup_complete=False)
    except V5ContractError:
        cleaned = _cleanup_created(created)
        return _receipt("failed", "V5_PRESPAWN_FAILED", spawned=False, child_exit=None,
                        timed_out=False, vm_running=False, created=created,
                        retained=[] if cleaned else created, cleanup_complete=cleaned)
    finally:
        for fd in roots.values():
            os.close(fd)
        if lock_fd >= 0:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(workspace_fd)
        try:
            lock_path = workspace / LOCK_RELATIVE
            metadata = lock_path.lstat()
            if (lock_identity is not None and stat.S_ISREG(metadata.st_mode) and
                    not lock_path.is_symlink() and
                    (metadata.st_dev, metadata.st_ino) == lock_identity):
                lock_path.unlink()
        except OSError:
            pass
