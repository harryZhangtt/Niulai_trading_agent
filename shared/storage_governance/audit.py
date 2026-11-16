"""Read-only, metadata-only storage governance audit and retention planning.

The scanner deliberately opens directories only.  It never opens a file below a
registered store, follows a symlink, mutates a source root, or executes a planned
retention action.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import secrets
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import (
    RegistryError,
    WorkspaceSnapshot,
    open_registry_snapshot,
    open_workspace_snapshot,
    validate_registry,
)


REPORT_SCHEMA = "storage-governance-audit-v1"
PLAN_SCHEMA = "storage-governance-retention-plan-v1"
_ALLOWED_ACTIONS = {
    "retain",
    "archive",
    "rebuildable-cache-review",
    "manual-review",
}


@dataclass(frozen=True)
class ScanLimits:
    """Hard per-store traversal limits; all values must be positive."""

    max_files: int = 10_000
    max_depth: int = 20
    max_bytes: int = 1 << 40

    def __post_init__(self) -> None:
        for name in ("max_files", "max_depth", "max_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def as_dict(self) -> dict[str, int]:
        return {
            "max_files": self.max_files,
            "max_depth": self.max_depth,
            "max_bytes": self.max_bytes,
        }


def _registry_stores(registry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = registry.get("stores")
    if isinstance(raw, Mapping):
        stores: list[Mapping[str, Any]] = []
        for store_id, item in raw.items():
            if not isinstance(item, Mapping):
                raise RegistryError("registry store must be an object")
            merged = dict(item)
            merged.setdefault("id", store_id)
            stores.append(merged)
        return stores
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        if not all(isinstance(item, Mapping) for item in raw):
            raise RegistryError("registry stores must be objects")
        return list(raw)
    raise RegistryError("registry stores must be a list or object")


def _store_id(store: Mapping[str, Any]) -> str:
    value = store.get("id", store.get("store_id", store.get("name")))
    if not isinstance(value, str) or not value or any(ord(ch) < 32 for ch in value):
        raise RegistryError("registry store id is invalid")
    return value


def _store_relative_path(store: Mapping[str, Any]) -> str:
    value = store.get("path", store.get("relative_path", store.get("root")))
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RegistryError("registry store path is invalid")
    return value


def _contained_store_path(workspace: Path, raw_path: str) -> tuple[Path, tuple[str, ...]]:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        absolute = Path(os.path.abspath(os.fspath(candidate)))
    else:
        absolute = Path(os.path.abspath(os.path.join(os.fspath(workspace), raw_path)))
    try:
        common = os.path.commonpath((os.fspath(workspace), os.fspath(absolute)))
    except ValueError as exc:
        raise RegistryError("registry path escapes workspace") from exc
    if common != os.fspath(workspace) or absolute == workspace:
        raise RegistryError("registry path escapes workspace or names the workspace root")
    relative = absolute.relative_to(workspace)
    if any(part in ("", ".", "..") for part in relative.parts):
        raise RegistryError("registry path is not a normalized workspace-relative path")
    return absolute, relative.parts


def _classifications(store: Mapping[str, Any]) -> dict[str, str]:
    roles = store.get("roles")
    if isinstance(roles, Sequence) and not isinstance(roles, (str, bytes, bytearray)):
        role_set = set(roles)
        return {name: "yes" if name in role_set else "no" for name in ("authority", "evidence", "cache")}

    # Compatibility for validated registry projections used by callers.
    nested = store.get("classifications")
    source = nested if isinstance(nested, Mapping) else store
    return {
        name: ("yes" if source.get(name) is True else "no" if source.get(name) is False else
               str(source[name]) if isinstance(source.get(name), str) and source[name] else "unspecified")
        for name in ("authority", "evidence", "cache")
    }


def _is_private(store: Mapping[str, Any]) -> bool:
    values: list[Any] = [
        store.get("sensitivity"),
        store.get("privacy"),
        store.get("classification"),
    ]
    nested = store.get("classifications")
    if isinstance(nested, Mapping):
        values.extend((nested.get("sensitivity"), nested.get("privacy")))
    roles = store.get("roles", [])
    return "credential" in roles or any(
        isinstance(value, str)
        and value.lower() in {"private", "credential", "credentials", "secret", "restricted", "confidential"}
        for value in values
    )


def _empty_scan(store_id: str, classifications: Mapping[str, str]) -> dict[str, Any]:
    return {
        "store_id": store_id,
        "exists": False,
        "root_type": "missing",
        "file_count": 0,
        "directory_count": 0,
        "other_count": 0,
        "aggregate_bytes": 0,
        "permission_findings": [],
        "symlink_findings": {"present": False, "count": 0, "root_is_symlink": False},
        "scan_error_findings": {
            "permission_unreadable": 0,
            "resource_limit": 0,
            "other": 0,
        },
        "sqlite_sidecars": {
            "count": 0,
            "aggregate_bytes": 0,
            "permission_findings": [],
            "symlink_findings": {"present": False, "count": 0},
            "error_findings": {
                "permission_unreadable": 0,
                "resource_limit": 0,
                "other": 0,
            },
        },
        "scan_truncated": False,
        "truncation_reasons": [],
        "classifications": dict(classifications),
        "location_scope": "workspace",
        "status": "current",
        "retention_class": "unspecified",
        "migration_trigger_observations": [],
    }


def _entry_type(mode: int) -> str:
    if stat.S_ISREG(mode):
        return "regular_file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _permission_kinds(
    metadata: os.stat_result,
    private: bool,
    root: bool,
    *,
    expected_uid: int,
    generated_file_mode: str | None,
) -> set[str]:
    scope = "root" if root else "entry"
    entry_type = _entry_type(metadata.st_mode)
    typed = f"{scope}_{entry_type}"
    findings: set[str] = set()
    if metadata.st_uid != expected_uid:
        findings.update({f"{scope}_owner_mismatch", f"{typed}_owner_mismatch"})
    if metadata.st_mode & stat.S_IWOTH:
        findings.update({f"{scope}_world_writable", f"{typed}_world_writable"})
    if metadata.st_mode & stat.S_IWGRP:
        findings.update({f"{scope}_group_writable", f"{typed}_group_writable"})
    if private and metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        findings.update({
            f"private_{scope}_group_or_world_accessible",
            f"private_{typed}_group_or_world_accessible",
        })
    if stat.S_ISREG(metadata.st_mode) and generated_file_mode is not None:
        expected_mode = int(generated_file_mode, 8)
        if stat.S_IMODE(metadata.st_mode) != expected_mode:
            findings.add(f"{typed}_generated_mode_mismatch")
    return findings

def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _scan_error_kind(error: OSError) -> str:
    if error.errno in (errno.ELOOP, errno.ENOTDIR):
        return "symlink_or_race"
    if error.errno in (errno.EACCES, errno.EPERM):
        return "permission_unreadable"
    if error.errno == errno.EMFILE:
        return "resource_limit"
    return "other"


def _open_registered_root(
    workspace_fd: int,
    parts: tuple[str, ...],
) -> tuple[int | None, int | None, os.stat_result | None, str]:
    """Open a store root without following components.

    The returned descriptors are owned by the caller.  Directory stores return a
    root descriptor.  Non-directory stores return the held parent descriptor so
    exact SQLite sidecars can be metadata-statted relative to it.
    """
    try:
        current = os.dup(workspace_fd)
    except OSError as error:
        return None, None, None, _scan_error_kind(error)
    try:
        for index, part in enumerate(parts):
            last = index == len(parts) - 1
            try:
                metadata = os.stat(part, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                os.close(current)
                return None, None, None, "missing"
            except OSError as error:
                os.close(current)
                return None, None, None, _scan_error_kind(error)
            if stat.S_ISLNK(metadata.st_mode):
                os.close(current)
                return None, None, metadata, "symlink_or_race"
            if not stat.S_ISDIR(metadata.st_mode):
                if last:
                    return None, current, metadata, "ok"
                os.close(current)
                return None, None, metadata, "symlink_or_race"
            try:
                child = os.open(part, _directory_open_flags(), dir_fd=current)
            except FileNotFoundError:
                os.close(current)
                return None, None, None, "missing"
            except OSError as error:
                os.close(current)
                return None, None, metadata, _scan_error_kind(error)
            os.close(current)
            current = child
        try:
            metadata = os.fstat(current)
        except OSError as error:
            os.close(current)
            return None, None, None, _scan_error_kind(error)
        return current, None, metadata, "ok"
    except BaseException:
        try:
            os.close(current)
        except OSError:
            pass
        raise


def _record_scan_error(
    error: OSError,
    *,
    permission_findings: set[str],
    scan_errors: dict[str, int],
    truncation: set[str],
    sidecar_errors: dict[str, int] | None = None,
    root: bool = False,
) -> str:
    kind = _scan_error_kind(error)
    if kind == "permission_unreadable":
        permission_findings.add("root_unreadable" if root else "entry_unreadable")
        scan_errors[kind] += 1
        truncation.add(kind)
    elif kind == "resource_limit":
        scan_errors[kind] += 1
        truncation.add(kind)
    elif kind == "other":
        scan_errors[kind] += 1
        truncation.add("scan_error")
    elif kind == "symlink_or_race":
        truncation.add(kind)
    if sidecar_errors is not None and kind != "symlink_or_race":
        sidecar_errors[kind] += 1
    return kind


def _apply_root_open_failure(result: dict[str, Any], outcome: str) -> None:
    if outcome == "missing":
        return
    if outcome == "symlink_or_race":
        result["exists"] = None
        result["root_type"] = "symlink_or_race"
        result["symlink_findings"] = {
            "present": True,
            "count": 1,
            "root_is_symlink": False,
        }
        return
    result["exists"] = None
    result["root_type"] = "unreadable"
    if outcome == "permission_unreadable":
        result["permission_findings"] = ["root_unreadable"]
        result["scan_error_findings"][outcome] = 1
        result["truncation_reasons"] = [outcome]
    elif outcome == "resource_limit":
        result["scan_error_findings"][outcome] = 1
        result["truncation_reasons"] = [outcome]
    else:
        result["scan_error_findings"]["other"] = 1
        result["truncation_reasons"] = ["scan_error"]
    result["scan_truncated"] = True


def _scan_sqlite_sidecars(
    parent_fd: int,
    leaf_name: str,
    result: dict[str, Any],
    *,
    private: bool,
    limits: ScanLimits,
    permission_findings: set[str],
    expected_uid: int,
    generated_file_mode: str | None,
    truncation: set[str],
) -> None:
    sidecars = result["sqlite_sidecars"]
    sidecar_permissions: set[str] = set()
    for suffix in ("-journal", "-wal", "-shm"):
        candidate = leaf_name + suffix
        try:
            metadata = os.stat(candidate, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        except OSError as error:
            kind = _record_scan_error(
                error,
                permission_findings=permission_findings,
                scan_errors=result["scan_error_findings"],
                truncation=truncation,
                sidecar_errors=sidecars["error_findings"],
            )
            if kind == "symlink_or_race":
                sidecars["symlink_findings"]["count"] += 1
            continue

        if 1 + sidecars["count"] >= limits.max_files:
            truncation.add("max_files")
            break
        sidecars["count"] += 1
        mode = metadata.st_mode
        findings = _permission_kinds(
            metadata, private, False, expected_uid=expected_uid,
            generated_file_mode=generated_file_mode,
        )
        permission_findings.update(findings)
        sidecar_permissions.update(findings)
        if stat.S_ISLNK(mode):
            sidecars["symlink_findings"]["count"] += 1
            continue
        if stat.S_ISREG(mode):
            result["file_count"] += 1
            result["aggregate_bytes"] += metadata.st_size
            sidecars["aggregate_bytes"] += metadata.st_size
            if result["aggregate_bytes"] > limits.max_bytes:
                truncation.add("max_bytes")
                break
        else:
            result["other_count"] += 1
    sidecars["permission_findings"] = sorted(sidecar_permissions)
    sidecars["symlink_findings"]["present"] = (
        sidecars["symlink_findings"]["count"] > 0
    )


def _scan_store(snapshot: WorkspaceSnapshot, store: Mapping[str, Any], limits: ScanLimits) -> dict[str, Any]:
    store_id = _store_id(store)
    classifications = _classifications(store)
    result = _empty_scan(store_id, classifications)
    result["location_scope"] = str(store.get("location_scope", "workspace"))
    result["status"] = str(store.get("status", "current"))
    result["retention_class"] = str(store.get("retention_class", "unspecified"))
    if result["location_scope"] != "workspace":
        result["exists"] = None
        result["root_type"] = "external_unverified"
        return result
    if result["status"] == "unverified":
        result["exists"] = None
        result["root_type"] = "workspace_unverified"
        return result

    _, parts = _contained_store_path(snapshot.workspace_path, _store_relative_path(store))
    private = _is_private(store)
    snapshot.verify()
    root_fd, parent_fd, root_stat, outcome = _open_registered_root(snapshot.workspace_fd, parts)
    if outcome != "ok":
        _apply_root_open_failure(result, outcome)
        if root_stat is not None and stat.S_ISLNK(root_stat.st_mode):
            result["exists"] = True
            result["root_type"] = "symlink"
            result["symlink_findings"]["root_is_symlink"] = True
            result["permission_findings"] = sorted(_permission_kinds(
                root_stat, private, True, expected_uid=snapshot.workspace_uid,
                generated_file_mode=store.get("generated_file_mode"),
            ))
        return result
    if root_stat is None:
        return result

    result["exists"] = True
    permission_findings = _permission_kinds(
        root_stat, private, True, expected_uid=snapshot.workspace_uid,
        generated_file_mode=store.get("generated_file_mode"),
    )
    truncation: set[str] = set()
    if root_fd is None:
        try:
            if stat.S_ISREG(root_stat.st_mode):
                result["root_type"] = "file"
                result["file_count"] = 1
                result["aggregate_bytes"] = root_stat.st_size
                if root_stat.st_size > limits.max_bytes:
                    truncation.add("max_bytes")
                if (
                    store.get("format") == "sqlite"
                    and parent_fd is not None
                    and "max_bytes" not in truncation
                ):
                    _scan_sqlite_sidecars(
                        parent_fd,
                        parts[-1],
                        result,
                        private=private,
                        limits=limits,
                        permission_findings=permission_findings,
                        truncation=truncation,
                        expected_uid=snapshot.workspace_uid,
                        generated_file_mode=store.get("generated_file_mode"),
                    )
            else:
                result["root_type"] = "other"
                result["other_count"] = 1
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
        sidecar_symlinks = result["sqlite_sidecars"]["symlink_findings"]["count"]
        result["permission_findings"] = sorted(permission_findings)
        result["symlink_findings"] = {
            "present": sidecar_symlinks > 0,
            "count": sidecar_symlinks,
            "root_is_symlink": False,
        }
        result["scan_truncated"] = bool(truncation)
        result["truncation_reasons"] = sorted(truncation)
        return result

    result["root_type"] = "directory"
    symlink_count = 0
    examined = 0

    def walk(directory_fd: int, depth: int) -> bool:
        nonlocal examined, symlink_count
        directories: list[tuple[str, int]] = []
        limit_reached = False
        resource_exhausted = False
        try:
            iterator = os.scandir(directory_fd)
        except OSError as error:
            kind = _record_scan_error(
                error,
                permission_findings=permission_findings,
                scan_errors=result["scan_error_findings"],
                truncation=truncation,
            )
            return kind == "resource_limit"
        with iterator as entries:
            while True:
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                except OSError as error:
                    kind = _record_scan_error(
                        error,
                        permission_findings=permission_findings,
                        scan_errors=result["scan_error_findings"],
                        truncation=truncation,
                    )
                    resource_exhausted = kind == "resource_limit"
                    break
                if examined >= limits.max_files:
                    truncation.add("max_files")
                    limit_reached = True
                    break
                examined += 1
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError as error:
                    kind = _record_scan_error(
                        error,
                        permission_findings=permission_findings,
                        scan_errors=result["scan_error_findings"],
                        truncation=truncation,
                    )
                    if kind == "symlink_or_race":
                        symlink_count += 1
                    if kind == "resource_limit":
                        resource_exhausted = True
                        break
                    continue
                mode = metadata.st_mode
                permission_findings.update(_permission_kinds(
                    metadata, private, False, expected_uid=snapshot.workspace_uid,
                    generated_file_mode=store.get("generated_file_mode"),
                ))
                if stat.S_ISLNK(mode):
                    symlink_count += 1
                    continue
                if stat.S_ISDIR(mode):
                    result["directory_count"] += 1
                    child_depth = depth + 1
                    if child_depth >= max(1, limits.max_depth - 1):
                        truncation.add("max_depth")
                    else:
                        directories.append((entry.name, child_depth))
                    continue
                if stat.S_ISREG(mode):
                    result["file_count"] += 1
                    result["aggregate_bytes"] += metadata.st_size
                    if result["aggregate_bytes"] > limits.max_bytes:
                        truncation.add("max_bytes")
                        limit_reached = True
                        break
                    continue
                result["other_count"] += 1

        if limit_reached or resource_exhausted:
            return True
        # The scandir iterator is closed before descent, so only the directory
        # descriptors on the current depth-first path remain open.
        for name, child_depth in directories:
            try:
                child_fd = os.open(name, _directory_open_flags(), dir_fd=directory_fd)
            except OSError as error:
                kind = _record_scan_error(
                    error,
                    permission_findings=permission_findings,
                    scan_errors=result["scan_error_findings"],
                    truncation=truncation,
                )
                if kind == "symlink_or_race":
                    symlink_count += 1
                if kind == "resource_limit":
                    return True
                continue
            try:
                if walk(child_fd, child_depth):
                    return True
            finally:
                os.close(child_fd)
        return False

    try:
        walk(root_fd, 0)
    finally:
        os.close(root_fd)

    result["permission_findings"] = sorted(permission_findings)
    result["symlink_findings"] = {
        "present": symlink_count > 0,
        "count": symlink_count,
        "root_is_symlink": False,
    }
    result["scan_truncated"] = bool(truncation)
    result["truncation_reasons"] = sorted(truncation)
    return result

def _compare(actual: int | bool, operator: str, threshold: int | bool) -> bool:
    if operator in (">=", "at_least"):
        return actual >= threshold
    if operator in (">", "above"):
        return actual > threshold
    if operator in ("<=", "at_most"):
        return actual <= threshold
    if operator in ("<", "below"):
        return actual < threshold
    if operator in ("==", "equals"):
        return actual == threshold
    raise RegistryError("migration trigger operator is unsupported")


def _migration_observations(store: Mapping[str, Any], result: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = store.get("migration_triggers", store.get("migration_trigger", []))
    if isinstance(raw, (str, Mapping)):
        triggers: Sequence[Any] = [raw]
    elif isinstance(raw, Sequence):
        triggers = raw
    elif raw is None:
        triggers = []
    else:
        raise RegistryError("migration triggers must be a list")

    inspected_snapshot = (
        result.get("location_scope") == "workspace"
        and result.get("status") != "unverified"
    )
    complete_snapshot = (
        inspected_snapshot
        and result.get("exists") is True
        and result.get("root_type") not in {
            "missing", "unreadable", "symlink", "symlink_or_race",
        }
        and result.get("scan_truncated") is False
    )
    observations: list[dict[str, Any]] = []
    for index, trigger in enumerate(triggers):
        if isinstance(trigger, str):
            observations.append({
                "trigger_id": trigger,
                "observed": None,
                "status": "not_evaluable_from_metadata",
            })
            continue
        if not isinstance(trigger, Mapping):
            raise RegistryError("migration trigger must be a string or object")
        trigger_id = trigger.get("id", trigger.get("name", f"trigger-{index + 1}"))
        if not isinstance(trigger_id, str) or not trigger_id:
            raise RegistryError("migration trigger id is invalid")
        metric = trigger.get("metric", trigger.get("kind"))
        operator = trigger.get("operator", ">=")
        threshold = trigger.get("threshold", trigger.get("value", True))
        aliases = {
            "file_count_at_least": "file_count",
            "aggregate_bytes_at_least": "aggregate_bytes",
            "symlink": "symlink_present",
            "permissions": "permission_finding",
        }
        metric = aliases.get(metric, metric)
        metrics: dict[str, int | bool] = {
            "exists": result.get("exists") is True,
            "missing": result.get("exists") is False,
            "file_count": int(result["file_count"]),
            "aggregate_bytes": int(result["aggregate_bytes"]),
            "scan_truncated": bool(result["scan_truncated"]),
            "symlink_present": bool(result["symlink_findings"]["present"]),
            "permission_finding": bool(result["permission_findings"]),
        }
        if metric not in metrics:
            observations.append({
                "trigger_id": trigger_id,
                "observed": None,
                "status": "not_evaluable_from_metadata",
            })
            continue

        actual = metrics[metric]
        if metric in {"exists", "missing"}:
            evaluable = type(result.get("exists")) is bool
        elif metric == "scan_truncated":
            evaluable = inspected_snapshot
        elif metric in {"symlink_present", "permission_finding"}:
            evaluable = inspected_snapshot and (actual is True or complete_snapshot)
        else:
            evaluable = complete_snapshot
        if not evaluable:
            observations.append({
                "trigger_id": trigger_id,
                "observed": None,
                "status": "not_evaluable_from_metadata",
                "metric": str(metric),
            })
            continue
        if not isinstance(threshold, (int, bool)) or isinstance(threshold, float):
            raise RegistryError("migration trigger threshold is invalid")
        observed = _compare(actual, str(operator), threshold)
        observations.append({
            "trigger_id": trigger_id,
            "observed": observed,
            "status": "observed" if observed else "not_observed",
            "metric": str(metric),
        })
    return observations


def audit_snapshot(
    snapshot: WorkspaceSnapshot,
    *,
    limits: ScanLimits | None = None,
) -> dict[str, Any]:
    """Audit every store through one retained workspace descriptor."""
    scan_limits = limits or ScanLimits()
    snapshot.verify()
    registry = snapshot.registry
    if registry is None:
        raise RegistryError("registry snapshot is missing registry data")
    checked = validate_registry(registry)
    if not isinstance(checked, Mapping):
        raise RegistryError("validated registry must be an object")

    stores: list[dict[str, Any]] = []
    for store in _registry_stores(checked):
        snapshot.verify()
        result = _scan_store(snapshot, store, scan_limits)
        result["migration_trigger_observations"] = _migration_observations(store, result)
        stores.append(result)
    snapshot.verify()
    stores.sort(key=lambda value: value["store_id"])
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "limits": scan_limits.as_dict(),
        "stores": stores,
    }


def audit_registry(
    registry_path: str | os.PathLike[str],
    workspace: str | os.PathLike[str],
    *,
    limits: ScanLimits | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper that closes its retained workspace snapshot."""
    with open_registry_snapshot(registry_path, workspace) as snapshot:
        return audit_snapshot(snapshot, limits=limits)

def _classification_is_positive(value: Any) -> bool:
    return isinstance(value, str) and value.lower() not in {
        "", "no", "none", "false", "unspecified", "not_applicable", "n/a"
    }


def plan_retention(audit_report: Mapping[str, Any]) -> dict[str, Any]:
    """Return advisory actions only; no filesystem action is performed."""
    stores = audit_report.get("stores")
    if not isinstance(stores, Sequence) or isinstance(stores, (str, bytes, bytearray)):
        raise ValueError("audit report stores must be a list")
    actions: list[dict[str, Any]] = []
    for store in stores:
        if not isinstance(store, Mapping) or not isinstance(store.get("store_id"), str):
            raise ValueError("audit report store is invalid")
        reasons: list[str] = []
        classifications = store.get("classifications", {})
        observed_trigger = any(
            isinstance(item, Mapping) and item.get("observed") is True
            for item in store.get("migration_trigger_observations", [])
        )
        retention_class = store.get("retention_class")
        status = store.get("status")
        if retention_class == "manual_review" or status != "current":
            action = "manual-review"
            reasons.append("manual_review_retention_or_non_current_status")
        elif (
            store.get("location_scope") == "external"
            or store.get("scan_truncated")
            or store.get("symlink_findings", {}).get("present")
            or store.get("permission_findings")
            or store.get("exists") is not True
        ):
            action = "manual-review"
            reasons.append("metadata_audit_requires_review")
        elif retention_class == "rebuildable_cache":
            action = "rebuildable-cache-review"
            reasons.append("rebuildable_cache_retention")
        elif retention_class == "ephemeral_artifact" or observed_trigger:
            action = "archive"
            reasons.append("archive_retention_or_migration_trigger")
        elif isinstance(classifications, Mapping) and (
            _classification_is_positive(classifications.get("authority"))
            or _classification_is_positive(classifications.get("evidence"))
        ):
            action = "retain"
            reasons.append("authority_or_evidence_store")
        elif isinstance(classifications, Mapping) and _classification_is_positive(classifications.get("cache")):
            action = "rebuildable-cache-review"
            reasons.append("cache_classification")
        else:
            action = "retain"
            reasons.append("no_change_indicated")
        if action not in _ALLOWED_ACTIONS:  # defensive invariant
            raise AssertionError("unknown retention action")
        actions.append({"store_id": store["store_id"], "action": action, "reasons": reasons})
    return {"schema": PLAN_SCHEMA, "performed": False, "actions": actions}


def _validate_workspace_directory(
    descriptor: int,
    snapshot: WorkspaceSnapshot,
) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise RegistryError("report workspace is not a directory")
    if (metadata.st_dev, metadata.st_ino) != snapshot.workspace_identity:
        raise RegistryError("report workspace identity changed")
    if metadata.st_uid != os.geteuid():
        raise RegistryError("report workspace owner is invalid")
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RegistryError("report workspace is group or world writable")
    return metadata


def _validate_private_directory(descriptor: int) -> os.stat_result:
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        raise RegistryError("report output component is not a directory")
    if metadata.st_uid != os.geteuid():
        raise RegistryError("report output directory owner is invalid")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RegistryError("report output directory mode must be 0700")
    return metadata


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _assert_child_binding(parent_fd: int, name: str, child_fd: int) -> None:
    try:
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(child_fd)
    except OSError as error:
        raise RegistryError("report output parent changed during publication") from error
    if stat.S_ISLNK(current.st_mode) or not _same_file(current, opened):
        raise RegistryError("report output parent changed during publication")


def _open_private_child(parent_fd: int, name: str) -> int:
    flags = _directory_open_flags()
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise RegistryError("report output directory creation failed") from error
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise RegistryError("report output directory is unsafe") from error
    except OSError as error:
        raise RegistryError("report output directory is unsafe") from error
    try:
        os.fsync(parent_fd)
        _validate_private_directory(descriptor)
        _assert_child_binding(parent_fd, name, descriptor)
        return descriptor
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _close_report_descriptors(descriptors: Sequence[int], *, suppress_errors: bool) -> OSError | None:
    first_error: OSError | None = None
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        try:
            os.close(descriptor)
        except OSError as error:
            if first_error is None:
                first_error = error
    if first_error is not None and not suppress_errors:
        return first_error
    return None


def _open_report_directories(snapshot: WorkspaceSnapshot) -> tuple[int, int, int]:
    snapshot.verify_path_binding()
    workspace_fd = os.dup(snapshot.workspace_fd)
    runtime_fd = -1
    output_fd = -1
    try:
        _validate_workspace_directory(workspace_fd, snapshot)
        runtime_fd = _open_private_child(workspace_fd, ".job-runtime")
        output_fd = _open_private_child(runtime_fd, "storage-governance")
        return workspace_fd, runtime_fd, output_fd
    except BaseException:
        _close_report_descriptors(
            (output_fd, runtime_fd, workspace_fd), suppress_errors=True)
        raise


def _assert_report_chain(
    snapshot: WorkspaceSnapshot,
    workspace_fd: int,
    runtime_fd: int,
    output_fd: int,
) -> None:
    snapshot.verify_path_binding()
    _validate_workspace_directory(workspace_fd, snapshot)
    _assert_child_binding(workspace_fd, ".job-runtime", runtime_fd)
    _assert_child_binding(runtime_fd, "storage-governance", output_fd)
    _validate_private_directory(runtime_fd)
    _validate_private_directory(output_fd)


def _create_private_temporary(output_fd: int) -> tuple[int, str]:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    for _ in range(128):
        name = f".audit-{secrets.token_hex(16)}.tmp"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=output_fd)
        except FileExistsError:
            continue
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or metadata.st_nlink != 1
            ):
                raise RegistryError("temporary report file metadata is invalid")
            return descriptor, name
        except BaseException:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                os.unlink(name, dir_fd=output_fd)
            except OSError:
                pass
            raise
    raise RegistryError("could not allocate a temporary report file")


def write_report(
    report: Mapping[str, Any],
    workspace: str | os.PathLike[str],
    *,
    filename: str = "audit.json",
    snapshot: WorkspaceSnapshot | None = None,
) -> Path:
    """Atomically write one private JSON report through one workspace snapshot."""
    if (
        Path(filename).name != filename
        or not filename.endswith(".json")
        or filename in ("", ".json")
        or any(ord(character) < 32 for character in filename)
    ):
        raise ValueError("report filename must be a simple .json name")
    workspace_path = Path(os.path.abspath(os.fspath(workspace)))
    owned_snapshot = snapshot is None
    active_snapshot = snapshot or open_workspace_snapshot(workspace_path)
    if workspace_path != active_snapshot.workspace_path:
        if owned_snapshot:
            active_snapshot.close()
        raise RegistryError("report workspace does not match retained snapshot")

    workspace_fd = runtime_fd = output_fd = temporary_fd = -1
    temporary_name: str | None = None
    try:
        workspace_fd, runtime_fd, output_fd = _open_report_directories(active_snapshot)
        _assert_report_chain(active_snapshot, workspace_fd, runtime_fd, output_fd)
        temporary_fd, temporary_name = _create_private_temporary(output_fd)
        with os.fdopen(temporary_fd, "w", encoding="utf-8") as handle:
            temporary_fd = -1
            json.dump(report, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _assert_report_chain(active_snapshot, workspace_fd, runtime_fd, output_fd)
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=output_fd,
            dst_dir_fd=output_fd,
        )
        temporary_name = None
        os.fsync(output_fd)
        _assert_report_chain(active_snapshot, workspace_fd, runtime_fd, output_fd)
    finally:
        primary_active = sys.exc_info()[0] is not None
        cleanup_error: OSError | None = None
        if temporary_fd >= 0:
            try:
                os.close(temporary_fd)
            except OSError as error:
                cleanup_error = error
        if temporary_name is not None and output_fd >= 0:
            try:
                os.unlink(temporary_name, dir_fd=output_fd)
            except FileNotFoundError:
                pass
            except OSError as error:
                if cleanup_error is None:
                    cleanup_error = error
        close_error = _close_report_descriptors(
            (output_fd, runtime_fd, workspace_fd), suppress_errors=primary_active)
        if cleanup_error is None:
            cleanup_error = close_error
        if owned_snapshot:
            try:
                active_snapshot.close()
            except OSError as error:
                if cleanup_error is None:
                    cleanup_error = error
        if cleanup_error is not None and not primary_active:
            raise cleanup_error
    return active_snapshot.workspace_path / ".job-runtime" / "storage-governance" / filename

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only storage governance auditor")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--output-name", default="audit.json")
    parser.add_argument("--max-files", type=int, default=ScanLimits.max_files)
    parser.add_argument("--max-depth", type=int, default=ScanLimits.max_depth)
    parser.add_argument("--max-bytes", type=int, default=ScanLimits.max_bytes)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        limits = ScanLimits(args.max_files, args.max_depth, args.max_bytes)
        with open_registry_snapshot(args.registry, args.workspace) as snapshot:
            audit = audit_snapshot(snapshot, limits=limits)
            report = dict(audit)
            report["retention_plan"] = plan_retention(audit)
            write_report(
                report,
                args.workspace,
                filename=args.output_name,
                snapshot=snapshot,
            )
    except (OSError, RegistryError, ValueError):
        print("storage governance audit failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
