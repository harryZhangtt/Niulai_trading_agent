#!/usr/bin/env python3
"""Observed, provider-free import preflight for the sealed SDK candidate.

The candidate SDK is launched only by an operator invoking this file.  Importing
this module performs no candidate import, subprocess launch, or evidence write.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any

CANDIDATE_DIR = Path(__file__).resolve().parent
WORKSPACE = CANDIDATE_DIR.parents[3]
PLAN_PATH = CANDIDATE_DIR / "provider_free_preflight_plan_v2.json"
CANDIDATE_LOCK_PATH = CANDIDATE_DIR / "post_install_runtime_lock_v2.json"
PRODUCTION_LOCK_PATH = WORKSPACE / "shared/job_runtime/claude-requirements.lock.json"
EXPECTED_PLAN_SHA256 = "3c64d3ad28fc9aa98ad707444dbe9754ee73718bece7c1553150dfaff27495cf"
EXPECTED_CANDIDATE_LOCK_SHA256 = "f6334dd1ef9b696ef397feeedf20c3777c8ab7e19cdd2d978876bb3abcdef9c5"
EXPECTED_OUTPUT_KEY_COUNT = 23
ALLOWED_CHILD_ENV_KEYS = frozenset({"PYTHONPATH", "PYTHONNOUSERSITE", "PATH"})
SENSITIVE_ENV_RE = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|PROXY|AUTH|COOKIE|SESSION)", re.I
)
BUNDLED_CLI_RE = re.compile(r"(?:^|\s)(?:[^\s]*/)?(?:claude|bytecli)(?:\s|$)", re.I)
PLAN_KEYS = frozenset({
    "bindings", "contract", "environment", "execution_contract",
    "expected_output_schema", "expected_ready_bindings", "invocation",
    "production_activated", "receipt_template", "schema_version", "status",
})
LOCK_KEYS = frozenset({
    "contract", "direct_requirement", "effects", "expected_distribution_tree_sha256",
    "expected_record_raw_bytes_sha256", "expected_record_importlib_text_utf8_sha256", "installability", "installable",
    "installed_sdk_custody", "network_used", "official_wheel",
    "official_wheel_sha256", "production_activated", "provider_calls",
    "python_requires", "receipts", "schema_version", "sealed_environment",
    "status", "target_runtime_python", "timestamp_evidence",
    "transitive_requirements", "verified_from_local_artifact",
})
MANIFEST_KEYS = frozenset({
    "artifacts", "dependency_edges", "direct_requirement", "limits",
    "record_tree_digest_plan", "resolution", "schema_version", "security",
    "status", "target",
})
PACKAGE_KEYS = frozenset({"name", "version", "wheel_filename", "wheel_sha256"})
EDGE_KEYS = frozenset({"from", "requirement", "to"})
PREFLIGHT_BINDING_KEYS = frozenset({
    "path", "sha256", "record_raw_bytes_semantics",
    "record_importlib_text_semantics",
})
CUSTODY_KEYS = frozenset({
    "dist_info", "distribution", "distribution_tree_sha256",
    "record_digest_semantics", "record_importlib_text_utf8_sha256",
    "record_raw_bytes_sha256", "record_rows", "tree_digest_semantics", "version",
})
REFLECTED_REQUIRED = {
    "query_parameters": {"prompt", "options"},
    "assistant_fields": {"model", "error"},
    "result_fields": {
        "model_usage", "usage", "total_cost_usd", "stop_reason",
        "api_error_status", "terminal_reason", "subtype", "is_error",
        "result", "session_id",
    },
    "model_usage_required_keys": {
        "inputTokens", "outputTokens", "cacheReadInputTokens",
        "cacheCreationInputTokens", "webSearchRequests", "costUSD",
        "contextWindow", "maxOutputTokens",
    },
    "model_usage_optional_keys": {"canonicalModel", "provider"},
}


class PreflightError(RuntimeError):
    """A stable, sanitized preflight failure."""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PreflightError(f"DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def _load_strict_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PreflightError(f"NONFINITE_JSON_NUMBER:{value}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PreflightError(f"INVALID_JSON:{path.name}:{type(exc).__name__}") from exc


def _closed_keys(value: Any, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict) or frozenset(value) != expected:
        raise PreflightError(f"NONCANONICAL_SCHEMA:{label}")


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _snapshot_tree(root: Path) -> dict[str, Any]:
    rows: list[list[Any]] = []
    if not root.exists() and not root.is_symlink():
        return {"exists": False, "sha256": hashlib.sha256(b"[]").hexdigest(), "entries": 0}
    paths = [root]
    if root.is_dir():
        paths.extend(sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()))
    for path in paths:
        rel = "." if path == root else path.relative_to(root).as_posix()
        stat = path.lstat()
        if path.is_symlink():
            rows.append([rel, "symlink", stat.st_mode & 0o7777, os.readlink(path)])
        elif path.is_file():
            rows.append([rel, "file", stat.st_mode & 0o7777, stat.st_size, _sha256(path)])
        elif path.is_dir():
            rows.append([rel, "dir", stat.st_mode & 0o7777])
        else:
            rows.append([rel, "other", stat.st_mode & 0o7777, stat.st_size])
    digest = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return {"exists": True, "sha256": digest, "entries": len(rows)}


def _distribution_hashes(target: Path, custody: dict[str, Any]) -> tuple[str, str, str, list[str]]:
    dist_info = target / custody["dist_info"]
    record_path = dist_info / "RECORD"
    record_raw = record_path.read_bytes()
    record_raw_sha = hashlib.sha256(record_raw).hexdigest()
    with io.TextIOWrapper(io.BytesIO(record_raw), encoding="utf-8", newline=None) as stream:
        record_text_sha = hashlib.sha256(stream.read().encode("utf-8")).hexdigest()
    site_packages = dist_info.parent
    rows: list[tuple[str, str]] = []
    recorded: set[str] = set()
    with record_path.open(newline="", encoding="utf-8") as stream:
        for row in csv.reader(stream):
            if not row:
                continue
            relative = row[0]
            recorded.add(relative)
            candidate = site_packages / relative
            if candidate.is_file():
                rows.append((relative, _sha256(candidate)))
    rows.sort(key=lambda item: item[0])
    tree_sha = hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    # RECORD is authoritative only for its distribution. Reject extra importable
    # content in the SDK package/dist-info roots rather than accepting a clean
    # digest beside a contaminated baseline.
    unrecorded: list[str] = []
    roots = [site_packages / "claude_agent_sdk", dist_info]
    for root in roots:
        if root.exists():
            for candidate in root.rglob("*"):
                if candidate.is_file() or candidate.is_symlink():
                    relative = candidate.relative_to(site_packages).as_posix()
                    if relative not in recorded:
                        parts = Path(relative).parts
                        if "__pycache__" in parts and relative.endswith(".pyc"):
                            continue
                        unrecorded.append(relative)
    top_level_module = site_packages / "claude_agent_sdk.py"
    if top_level_module.exists() and "claude_agent_sdk.py" not in recorded:
        unrecorded.append("claude_agent_sdk.py")
    return record_raw_sha, record_text_sha, tree_sha, sorted(set(unrecorded))


def _json_type_matches(value: Any, declared: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
    }.get(declared, False)


def _validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    declared = schema.get("type")
    types = [declared] if isinstance(declared, str) else declared
    if isinstance(types, list) and not any(_json_type_matches(value, item) for item in types):
        return [f"SCHEMA_TYPE_MISMATCH:{path}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"SCHEMA_CONST_MISMATCH:{path}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"SCHEMA_ENUM_MISMATCH:{path}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            return [f"SCHEMA_DEFINITION_INVALID:{path}"]
        for key in required:
            if key not in value:
                errors.append(f"SCHEMA_REQUIRED_MISSING:{path}.{key}")
        if schema.get("additionalProperties") is False:
            for key in set(value) - set(properties):
                errors.append(f"SCHEMA_ADDITIONAL_PROPERTY:{path}.{key}")
        for key in set(value) & set(properties):
            errors.extend(_validate_json_schema(value[key], properties[key], f"{path}.{key}"))
    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(_validate_json_schema(item, item_schema, f"{path}[{index}]"))
        if schema.get("uniqueItems") is True:
            canonical = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(canonical) != len(set(canonical)):
                errors.append(f"SCHEMA_UNIQUE_ITEMS:{path}")
    return errors


def _validate_plan(plan: Any) -> list[str]:
    blockers: list[str] = []
    _closed_keys(plan, PLAN_KEYS, "plan")
    if plan.get("schema_version") != 2 or plan.get("contract") != "claude-agent-sdk-provider-free-import-preflight-plan-v2":
        blockers.append("PLAN_IDENTITY_INVALID")
    bindings = plan.get("bindings")
    if not isinstance(bindings, dict):
        blockers.append("PLAN_BINDINGS_INVALID")
    else:
        preflight_binding = bindings.get("preflight_implementation")
        if not isinstance(preflight_binding, dict) or frozenset(preflight_binding) != PREFLIGHT_BINDING_KEYS:
            blockers.append("PREFLIGHT_IMPLEMENTATION_BINDING_SCHEMA_INVALID")
    schema = plan.get("expected_output_schema")
    if not isinstance(schema, dict):
        blockers.append("OUTPUT_SCHEMA_INVALID")
        return blockers
    required = schema.get("required")
    properties = schema.get("properties")
    if (schema.get("type") != "object" or schema.get("additionalProperties") is not False
            or not isinstance(required, list) or len(required) != len(set(required))
            or not isinstance(properties, dict) or set(required) != set(properties)):
        blockers.append("OUTPUT_SCHEMA_NOT_CLOSED")
    if not isinstance(required, list) or len(required) != EXPECTED_OUTPUT_KEY_COUNT:
        blockers.append("OUTPUT_SCHEMA_KEY_COUNT_NOT_23")
    ready_bindings = plan.get("expected_ready_bindings")
    if not isinstance(ready_bindings, dict) or not set(REFLECTED_REQUIRED) <= set(ready_bindings):
        blockers.append("REFLECTED_SURFACE_BINDINGS_MISSING")
    invocation = plan.get("invocation", {})
    argv = invocation.get("argv") if isinstance(invocation, dict) else None
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        blockers.append("PLAN_ARGV_INVALID")
    else:
        if argv[:2] != ["/usr/bin/env", "-i"]:
            blockers.append("PLAN_ENV_NOT_CLEARED")
        assignments: dict[str, str] = {}
        for item in argv[2:]:
            if "=" not in item:
                break
            key, value = item.split("=", 1)
            assignments[key] = value
        if not set(assignments) <= ALLOWED_CHILD_ENV_KEYS:
            blockers.append("PLAN_ENV_ALLOWLIST_VIOLATION")
        if any(SENSITIVE_ENV_RE.search(key) for key in assignments):
            blockers.append("PLAN_SENSITIVE_ENV_PRESENT")
        expected_env = plan.get("environment", {}).get("set_exactly")
        if assignments != expected_env:
            blockers.append("PLAN_ENV_BINDING_MISMATCH")
    return blockers


def _validate_lock(lock: Any, plan: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    _closed_keys(lock, LOCK_KEYS, "candidate_lock")
    if lock.get("schema_version") != 2 or lock.get("contract") != "claude-agent-sdk-canonical-post-install-runtime-lock-v2":
        blockers.append("LOCK_IDENTITY_INVALID")
    custody = lock.get("installed_sdk_custody")
    if not isinstance(custody, dict) or frozenset(custody) != CUSTODY_KEYS:
        blockers.append("LOCK_CUSTODY_SCHEMA_INVALID")
    else:
        semantics = custody.get("record_digest_semantics")
        expected_semantics = {
            "authoritative": "raw_bytes_descriptor_safe_no_follow",
            "compatibility": 'importlib.metadata.Distribution.read_text("RECORD") UTF-8 with universal-newline normalization',
        }
        if semantics != expected_semantics:
            blockers.append("LOCK_RECORD_DIGEST_SEMANTICS_INVALID")
        if custody.get("record_raw_bytes_sha256") != lock.get("expected_record_raw_bytes_sha256"):
            blockers.append("LOCK_RAW_RECORD_BINDING_MISMATCH")
        if custody.get("record_importlib_text_utf8_sha256") != lock.get("expected_record_importlib_text_utf8_sha256"):
            blockers.append("LOCK_TEXT_RECORD_BINDING_MISMATCH")
        if custody.get("distribution_tree_sha256") != lock.get("expected_distribution_tree_sha256"):
            blockers.append("LOCK_TREE_BINDING_MISMATCH")
    ready = plan.get("expected_ready_bindings", {})
    for lock_key, output_key in (
        ("expected_distribution_tree_sha256", "expected_distribution_tree_sha256"),
        ("expected_record_raw_bytes_sha256", "expected_record_raw_bytes_sha256"),
        ("expected_record_importlib_text_utf8_sha256", "expected_record_importlib_text_utf8_sha256"),
    ):
        if lock.get(lock_key) != ready.get(output_key):
            blockers.append(f"PLAN_LOCK_DIGEST_BINDING_MISMATCH:{lock_key}")
    sealed = lock.get("sealed_environment")
    if not isinstance(sealed, dict) or frozenset(sealed) != frozenset({
        "dependency_edge_count", "dependency_edges", "installed_target",
        "interpreter", "package_count", "packages", "seal", "target",
    }):
        return ["LOCK_SEALED_ENVIRONMENT_SCHEMA_INVALID"]
    packages = sealed.get("packages")
    edges = sealed.get("dependency_edges")
    if (not isinstance(packages, list) or len(packages) != 30
            or sealed.get("package_count") != 30
            or any(not isinstance(item, dict) or frozenset(item) != PACKAGE_KEYS for item in packages)):
        blockers.append("LOCK_PACKAGE_SET_NOT_EXACT_30")
    if (not isinstance(edges, list) or len(edges) != 52
            or sealed.get("dependency_edge_count") != 52
            or any(not isinstance(item, dict) or frozenset(item) != EDGE_KEYS for item in edges)):
        blockers.append("LOCK_EDGE_SET_NOT_EXACT_52")
    if plan.get("bindings", {}).get("candidate_lock", {}).get("sha256") != EXPECTED_CANDIDATE_LOCK_SHA256:
        blockers.append("PLAN_LOCK_HASH_BINDING_INVALID")
    return blockers


def _verify_static(plan: dict[str, Any], lock: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    blockers = _validate_plan(plan) + _validate_lock(lock, plan)
    evidence: dict[str, Any] = {}
    if _sha256(PLAN_PATH) != EXPECTED_PLAN_SHA256:
        blockers.append("PLAN_HASH_MISMATCH")
    if _sha256(CANDIDATE_LOCK_PATH) != EXPECTED_CANDIDATE_LOCK_SHA256:
        blockers.append("CANDIDATE_LOCK_HASH_MISMATCH")
    preflight_binding = plan.get("bindings", {}).get("preflight_implementation", {})
    preflight_path = Path(preflight_binding.get("path", ""))
    preflight_sha = _sha256(preflight_path) if preflight_path.is_file() else None
    evidence["preflight_implementation_sha256"] = preflight_sha
    if preflight_sha != preflight_binding.get("sha256"):
        blockers.append("PREFLIGHT_IMPLEMENTATION_HASH_MISMATCH")
    if preflight_binding.get("record_raw_bytes_semantics") != "descriptor_safe_no_follow_authoritative":
        blockers.append("PREFLIGHT_RAW_RECORD_SEMANTICS_INVALID")
    if preflight_binding.get("record_importlib_text_semantics") != "utf8_universal_newline_normalized_compatibility":
        blockers.append("PREFLIGHT_TEXT_RECORD_SEMANTICS_INVALID")
    launcher_binding = plan.get("bindings", {}).get("trusted_launcher", {})
    launcher_path = Path(launcher_binding.get("path", ""))
    launcher_sha = _sha256(launcher_path) if launcher_path.is_file() else None
    evidence["trusted_launcher_sha256"] = launcher_sha
    if launcher_sha != launcher_binding.get("sha256"):
        blockers.append("TRUSTED_LAUNCHER_HASH_MISMATCH")
    reflected_binding = plan.get("bindings", {}).get("reflected_surface_source", {})
    if reflected_binding.get("derivation") != "python-ast-static-no-import":
        blockers.append("REFLECTED_SURFACE_DERIVATION_INVALID")
    for name, binding in reflected_binding.get("files", {}).items():
        source_path = Path(binding.get("path", ""))
        actual_source = _sha256(source_path) if source_path.is_file() else None
        evidence.setdefault("reflected_surface_source_sha256", {})[name] = actual_source
        if actual_source != binding.get("sha256"):
            blockers.append(f"REFLECTED_SURFACE_SOURCE_HASH_MISMATCH:{name}")
    if set(reflected_binding.get("files", {})) != {"types.py", "query.py"}:
        blockers.append("REFLECTED_SURFACE_SOURCE_SET_INVALID")
    sealed = lock["sealed_environment"]
    seal = sealed["seal"]
    controls = {
        "seal": (Path(seal["path"]), seal["sha256"]),
        "manifest": (Path(seal["manifest"]["path"]), seal["manifest"]["sha256"]),
        "requirements_lock": (Path(seal["requirements_lock"]["path"]), seal["requirements_lock"]["sha256"]),
        "sha256sums": (Path(seal["sha256sums"]["path"]), seal["sha256sums"]["sha256"]),
    }
    evidence["control_sha256"] = {}
    for name, (path, expected) in controls.items():
        actual = _sha256(path) if path.is_file() else None
        evidence["control_sha256"][name] = actual
        if actual != expected:
            blockers.append(f"CONTROL_HASH_MISMATCH:{name}")
    manifest = _load_strict_json(controls["manifest"][0])
    _closed_keys(manifest, MANIFEST_KEYS, "seal_manifest")
    manifest_artifacts = manifest.get("artifacts")
    package_map = {item["wheel_filename"]: item for item in sealed["packages"]}
    if not isinstance(manifest_artifacts, list) or len(manifest_artifacts) != 30:
        blockers.append("MANIFEST_ARTIFACT_SET_NOT_EXACT_30")
    else:
        for artifact in manifest_artifacts:
            filename = artifact.get("filename") if isinstance(artifact, dict) else None
            package = package_map.get(filename)
            wheel = CANDIDATE_DIR / "wheelhouse" / str(filename)
            actual = _sha256(wheel) if wheel.is_file() else None
            if package is None or actual != artifact.get("sha256") or actual != package.get("wheel_sha256"):
                blockers.append(f"WHEEL_HASH_MISMATCH:{filename}")
    for receipt_name, receipt in lock["receipts"].items():
        path = Path(receipt["path"])
        actual = _sha256(path) if path.is_file() else None
        evidence.setdefault("receipt_sha256", {})[receipt_name] = actual
        if actual != receipt["file_sha256"]:
            blockers.append(f"SOURCE_RECEIPT_HASH_MISMATCH:{receipt_name}")
    interpreter = sealed["interpreter"]
    interpreter_path = Path(interpreter["path"])
    actual_interpreter = _sha256(interpreter_path) if interpreter_path.is_file() else None
    evidence["interpreter_sha256"] = actual_interpreter
    if actual_interpreter != interpreter["sha256"]:
        blockers.append("INTERPRETER_HASH_MISMATCH")
    target = Path(sealed["installed_target"])
    try:
        record_raw_sha, record_text_sha, tree_sha, unrecorded = _distribution_hashes(target, lock["installed_sdk_custody"])
    except (OSError, UnicodeError, KeyError, csv.Error):
        record_raw_sha, record_text_sha, tree_sha, unrecorded = None, None, None, []
    evidence["record_raw_bytes_sha256"] = record_raw_sha
    evidence["record_importlib_text_utf8_sha256"] = record_text_sha
    evidence["distribution_tree_sha256"] = tree_sha
    evidence["unrecorded_sdk_paths"] = unrecorded
    if unrecorded:
        blockers.append("UNRECORDED_SDK_PATHS_PRESENT")
    if record_raw_sha != lock["expected_record_raw_bytes_sha256"]:
        blockers.append("RECORD_RAW_BYTES_HASH_MISMATCH")
    if record_text_sha != lock["expected_record_importlib_text_utf8_sha256"]:
        blockers.append("RECORD_IMPORTLIB_TEXT_HASH_MISMATCH")
    if tree_sha != lock["expected_distribution_tree_sha256"]:
        blockers.append("DISTRIBUTION_TREE_HASH_MISMATCH")
    production = _load_strict_json(PRODUCTION_LOCK_PATH)
    production_sha = _sha256(PRODUCTION_LOCK_PATH)
    evidence["production_lock_pre_sha256"] = production_sha
    for key in ("direct_requirement", "python_requires", "target_runtime_python"):
        if production.get(key) != lock.get(key):
            blockers.append(f"PRODUCTION_LOCK_IDENTITY_MISMATCH:{key}")
    return sorted(set(blockers)), evidence


def _observe_process(pid: int, stop: threading.Event, observation: dict[str, Any]) -> None:
    seen: dict[int, str] = {}
    failures = 0
    while not stop.is_set():
        try:
            result = subprocess.run(
                ["/bin/ps", "-axo", "pid=,ppid=,command="],
                text=True, capture_output=True, timeout=1.0,
                env={"PATH": "/usr/bin:/bin"}, check=False,
            )
            if result.returncode != 0:
                failures += 1
            rows: dict[int, tuple[int, str]] = {}
            for line in result.stdout.splitlines():
                parts = line.strip().split(None, 2)
                if len(parts) == 3:
                    try:
                        rows[int(parts[0])] = (int(parts[1]), parts[2])
                    except ValueError:
                        pass
            descendants = {pid}
            changed = True
            while changed:
                changed = False
                for child, (parent, command) in rows.items():
                    if parent in descendants and child not in descendants:
                        descendants.add(child); seen[child] = command; changed = True
            root_command = rows.get(pid, (0, ""))[1]
            if root_command:
                observation.setdefault("root_commands", set()).add(root_command)
        except (OSError, subprocess.SubprocessError):
            failures += 1
        stop.wait(0.002)
    observation["descendants"] = seen
    observation["observer_failures"] = failures


def _parse_sandbox_activation(stderr: str) -> dict[str, Any] | None:
    markers = [line for line in stderr.splitlines() if line.startswith("SANDBOX_INIT_OK ")]
    if len(markers) != 1:
        return None
    try:
        value = json.loads(markers[0].removeprefix("SANDBOX_INIT_OK "))
    except json.JSONDecodeError:
        return None
    expected = {
        "sandbox_init_rc": 0, "network_denied": True,
        "file_writes_denied": True, "process_fork_denied": True,
        "process_exec_denied": True,
    }
    if not isinstance(value, dict) or any(value.get(k) != v for k, v in expected.items()):
        return None
    return value


def _run_observed_child(argv: list[str], timeout_seconds: float = 60.0) -> dict[str, Any]:
    if platform.system() != "Darwin":
        raise PreflightError("MACOS_SANDBOX_INIT_UNAVAILABLE")
    command = list(argv)
    started_utc = _utc_now(); started_mono = time.monotonic_ns()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=False,
        env={"PATH": "/usr/bin:/bin"}, start_new_session=True,
    )
    observation: dict[str, Any] = {}
    stop = threading.Event()
    thread = threading.Thread(target=_observe_process, args=(process.pid, stop, observation), daemon=True)
    thread.start()
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, 9)
        stdout, stderr = process.communicate()
    finally:
        stop.set(); thread.join(timeout=2.0)
    ended_mono = time.monotonic_ns(); ended_utc = _utc_now()
    stderr_text = stderr.decode("utf-8", "replace")
    descendants = observation.get("descendants", {})
    commands = list(descendants.values()) + list(observation.get("root_commands", set()))
    activation = _parse_sandbox_activation(stderr_text)
    return {
        "started_at_utc": started_utc, "ended_at_utc": ended_utc,
        "started_monotonic_ns": started_mono, "ended_monotonic_ns": ended_mono,
        "duration_monotonic_ns": ended_mono - started_mono,
        "argv": argv, "environment": {"PATH": "/usr/bin:/bin"},
        "stdout": stdout.decode("utf-8", "replace"), "stderr": stderr_text,
        "exit_code": process.returncode, "timed_out": timed_out,
        "sandbox_activation": activation,
        "child_processes_observed": len(descendants),
        "observed_child_commands": sorted(commands),
        "bundled_cli_or_bytecli_observed": any(BUNDLED_CLI_RE.search(item) for item in commands),
        "observer_failures": observation.get("observer_failures", 0),
        "process_control": {
            "sandbox_init_in_process": activation is not None,
            "kernel_process_fork_denied": bool(activation and activation.get("process_fork_denied")),
            "kernel_process_exec_denied": bool(activation and activation.get("process_exec_denied")),
            "parent_descendant_polling_defense_in_depth": True,
        },
    }


def _validate_output(stdout: str, plan: dict[str, Any]) -> tuple[Any, list[str]]:
    blockers: list[str] = []
    try:
        output = json.loads(
            stdout, object_pairs_hook=_pairs_no_duplicates,
            parse_constant=lambda value: (_ for _ in ()).throw(
                PreflightError(f"NONFINITE_JSON_NUMBER:{value}")
            ),
        )
    except (json.JSONDecodeError, PreflightError):
        return None, ["CHILD_STDOUT_NOT_SINGLE_STRICT_JSON"]
    schema = plan["expected_output_schema"]
    required = schema["required"]
    blockers.extend(_validate_json_schema(output, schema))
    if not isinstance(output, dict) or set(output) != set(required) or len(output) != EXPECTED_OUTPUT_KEY_COUNT:
        blockers.append("OUTPUT_KEYS_NOT_EXACT_23")
        return output, blockers
    for key, expected in plan["expected_ready_bindings"].items():
        if output.get(key) != expected:
            blockers.append(f"READY_BINDING_MISMATCH:{key}")
    for key in REFLECTED_REQUIRED:
        expected = plan["expected_ready_bindings"].get(key)
        value = output.get(key)
        if not isinstance(value, list) or value != expected:
            blockers.append(f"REFLECTED_SURFACE_MISMATCH:{key}")
    model_keys = output.get("model_usage_keys")
    required_keys = output.get("model_usage_required_keys")
    optional_keys = output.get("model_usage_optional_keys")
    if all(isinstance(item, list) for item in (model_keys, required_keys, optional_keys)):
        if set(model_keys) != set(required_keys) | set(optional_keys):
            blockers.append("MODEL_USAGE_PARTITION_MISMATCH")
    return output, blockers


def _reserve_evidence_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    claim = path.parent / (path.name + ".claim")
    fd = os.open(claim, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, b"reserved\n"); os.fsync(fd)
        os.mkdir(path, 0o700)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
    finally:
        os.close(fd)
        try: claim.unlink()
        except FileNotFoundError: pass


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    payload = _canonical_bytes(receipt)
    temp = path.parent / ("." + path.name + ".pending")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    linked = False
    complete = False
    try:
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("receipt short write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd); fd = -1
        if temp.read_bytes() != payload:
            raise OSError("receipt readback mismatch")
        # Hard-link publication is atomic and fails if the final O_EXCL path
        # already exists; the final name is never exposed partially written.
        os.link(temp, path)
        linked = True
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
        if path.read_bytes() != payload:
            raise OSError("published receipt readback mismatch")
        temp.unlink()
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
        complete = True
    finally:
        if fd >= 0:
            os.close(fd)
        if linked and not complete:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        if linked and not complete:
            try:
                dir_fd = os.open(path.parent, os.O_RDONLY)
                try: os.fsync(dir_fd)
                finally: os.close(dir_fd)
            except OSError:
                pass


def run(evidence_dir: Path, timeout_seconds: float = 60.0) -> dict[str, Any]:
    evidence_dir = evidence_dir.resolve()
    _reserve_evidence_dir(evidence_dir)
    receipt_path = evidence_dir / "receipt.json"
    overall_start_utc = _utc_now(); overall_start_mono = time.monotonic_ns()
    plan = _load_strict_json(PLAN_PATH)
    lock = _load_strict_json(CANDIDATE_LOCK_PATH)
    target = Path(lock["sealed_environment"]["installed_target"])
    target_before = _snapshot_tree(target)
    production_before = _snapshot_tree(PRODUCTION_LOCK_PATH)
    blockers, static = _verify_static(plan, lock)
    child = None
    output = None
    if not blockers:
        child = _run_observed_child(plan["invocation"]["argv"], timeout_seconds)
        expected_profile = plan["bindings"]["trusted_launcher"]["sandbox_profile_sha256"]
        activation = child.get("sandbox_activation")
        if activation is None or activation.get("profile_sha256") != expected_profile:
            blockers.append("SANDBOX_INIT_NOT_CONFIRMED")
        if child["observer_failures"]:
            blockers.append("PROCESS_OBSERVER_FAILURE")
        if child["child_processes_observed"]:
            blockers.append("CHILD_PROCESS_OBSERVED")
        if child["bundled_cli_or_bytecli_observed"]:
            blockers.append("BUNDLED_CLI_OR_BYTECLI_OBSERVED")
        if child["timed_out"]:
            blockers.append("CHILD_TIMEOUT")
        if child["exit_code"] != 0:
            blockers.append("CHILD_EXIT_NONZERO")
        output, output_blockers = _validate_output(child["stdout"], plan)
        blockers.extend(output_blockers)
    target_after = _snapshot_tree(target)
    production_after = _snapshot_tree(PRODUCTION_LOCK_PATH)
    if target_before != target_after:
        blockers.append("TARGET_WRITE_OR_DRIFT_OBSERVED")
    if production_before != production_after:
        blockers.append("PRODUCTION_LOCK_WRITE_OR_DRIFT_OBSERVED")
    overall_end_mono = time.monotonic_ns(); overall_end_utc = _utc_now()
    receipt = {
        "contract": "claude-agent-sdk-observed-import-preflight-receipt-v3",
        "schema_version": 3,
        "status": "PASS" if not blockers else "BLOCKED",
        "blockers": sorted(set(blockers)),
        "started_at_utc": overall_start_utc, "ended_at_utc": overall_end_utc,
        "started_monotonic_ns": overall_start_mono, "ended_monotonic_ns": overall_end_mono,
        "duration_monotonic_ns": overall_end_mono - overall_start_mono,
        "plan_sha256": _sha256(PLAN_PATH),
        "candidate_lock_sha256": _sha256(CANDIDATE_LOCK_PATH),
        "production_lock_pre_sha256": static.get("production_lock_pre_sha256"),
        "production_lock_post_sha256": _sha256(PRODUCTION_LOCK_PATH),
        "static_evidence": static,
        "target_snapshot_before": target_before, "target_snapshot_after": target_after,
        "production_lock_snapshot_before": production_before,
        "production_lock_snapshot_after": production_after,
        "planned_argv": plan.get("invocation", {}).get("argv"),
        "planned_environment": plan.get("environment", {}).get("set_exactly"),
        "child_execution": child,
        "validated_output": output,
        "production_activated": False,
        "provider_queries_observed": 0,
        "network_calls_observed": 0,
        "bundled_cli_executions_observed": 0 if child is None else int(child["bundled_cli_or_bytecli_observed"]),
        "child_processes_observed": 0 if child is None else child["child_processes_observed"],
        "receipt_path": str(receipt_path),
    }
    _write_receipt(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args(argv)
    try:
        receipt = run(args.evidence_dir, args.timeout_seconds)
    except (PreflightError, FileExistsError, OSError, KeyError, TypeError, ValueError) as exc:
        # If reservation succeeded but a later static gate failed, preserve an
        # immutable canonical BLOCKED result rather than only an ephemeral error.
        evidence_dir = args.evidence_dir.resolve()
        receipt_path = evidence_dir / "receipt.json"
        blocked = {
            "contract": "claude-agent-sdk-observed-import-preflight-receipt-v3",
            "schema_version": 3, "status": "BLOCKED",
            "blockers": [f"HARNESS_ERROR:{type(exc).__name__}"],
            "detail": str(exc), "completed_at_utc": _utc_now(),
            "production_activated": False, "provider_queries_observed": 0,
            "network_calls_observed": 0, "bundled_cli_executions_observed": 0,
            "child_processes_observed": 0, "receipt_path": str(receipt_path),
        }
        if evidence_dir.is_dir() and not receipt_path.exists():
            try:
                _write_receipt(receipt_path, blocked)
            except OSError:
                pass
        print(json.dumps({"status": "BLOCKED", "error": type(exc).__name__, "detail": str(exc), "receipt": str(receipt_path) if receipt_path.exists() else None}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps({"status": receipt["status"], "blockers": receipt["blockers"], "receipt": receipt["receipt_path"]}, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
