"""Strict, dependency-free validation for the storage-governance registry."""

from __future__ import annotations

import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Any


MAX_REGISTRY_BYTES = 1024 * 1024
MAX_STORES = 128
ID_PATTERN = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
FORMAT_PATTERN = re.compile(r"[a-z0-9][a-z0-9+_.-]{0,63}\Z")
ROLES = ("authority", "evidence", "cache", "credential", "projection", "reference")
STATUSES = {"current", "planned", "unverified"}
LOCATION_SCOPES = {"workspace", "external"}
SENSITIVITIES = {"public", "internal", "confidential", "restricted"}
WRITER_MODELS = {
    "append_only",
    "external_managed",
    "generated_output",
    "immutable_publish",
    "read_only",
    "single_writer",
    "transactional_multi_writer",
}
DURABILITIES = {
    "ephemeral",
    "external_unverified",
    "immutable_content_addressed",
    "local_durable",
    "source_controlled",
}
BACKUP_UNITS = {"artifact_set", "database", "directory", "external_store", "file", "none"}
RETENTION_CLASSES = {
    "credential_lifecycle",
    "ephemeral_artifact",
    "evidence_record",
    "external_policy",
    "manual_review",
    "operational_record",
    "rebuildable_cache",
    "source_history",
}
TOP_LEVEL_KEYS = {"schema_version", "kind", "stores"}
STORE_KEYS = {
    "id",
    "root",
    "location_scope",
    "status",
    "roles",
    "sensitivity",
    "owner",
    "format",
    "writer_model",
    "durability",
    "backup_unit",
    "retention_class",
    "generated_file_mode",
    "derived_from",
    "migration_triggers",
}
TRIGGER_KEYS = {"id", "metric", "operator", "threshold", "rationale"}
BOOLEAN_TRIGGER_METRICS = {
    "exists",
    "missing",
    "permission_finding",
    "scan_truncated",
    "symlink_present",
}
INTEGER_TRIGGER_METRICS = {"aggregate_bytes", "file_count"}
BOOLEAN_TRIGGER_OPERATORS = {"=="}
INTEGER_TRIGGER_OPERATORS = {"==", ">", ">=", "<", "<="}
MAX_TRIGGER_THRESHOLD = 2**63 - 1
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|client[_-]?secret|secret|password)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(?:authorization\s*:\s*(?:basic|bearer)|cookie\s*:)"),
    re.compile(r"(?:sk|ghp|xox[baprs])[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gho_[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{35}"),
    re.compile(r"xapp-[A-Za-z0-9-]{10,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{20,}"),
    re.compile(r"npm_[A-Za-z0-9]{36,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
)
_PRIVATE_PATH = re.compile(r"(?:~(?:/|\Z)|/(?:Users|home|root)/|[A-Za-z]:[\\/])")


class RegistryError(ValueError):
    """Stable rejection raised for malformed or unsafe registry input."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise RegistryError(code)


def _strict_object(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, code)
    return value


def _identifier(value: Any, code: str) -> str:
    _require(isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None, code)
    return value


def _safe_string(value: Any, code: str, *, maximum: int = 512) -> str:
    # This finite detector is defense-in-depth for a metadata-only registry, not
    # a complete secret scanner or a substitute for keeping credentials out.
    _require(isinstance(value, str) and 0 < len(value) <= maximum, code)
    _require(not any(ord(character) < 32 or ord(character) == 127 for character in value), code)
    _require(_PRIVATE_PATH.search(value) is None, "STORAGE_REGISTRY_PRIVATE_PATH_FORBIDDEN")
    _require(not any(pattern.search(value) for pattern in _SECRET_PATTERNS),
             "STORAGE_REGISTRY_CREDENTIAL_MATERIAL_FORBIDDEN")
    return value


def _root(value: Any) -> str:
    value = _safe_string(value, "STORAGE_REGISTRY_ROOT_INVALID", maximum=240)
    _require("\\" not in value and not value.startswith(("/", "~")) and "//" not in value,
             "STORAGE_REGISTRY_ROOT_INVALID")
    path = PurePosixPath(value)
    _require(path.parts and all(part not in {"", ".", ".."} for part in path.parts)
             and str(path) == value and ":" not in path.parts[0],
             "STORAGE_REGISTRY_ROOT_INVALID")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "STORAGE_REGISTRY_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise RegistryError("STORAGE_REGISTRY_JSON_INVALID")


def _loads_strict(raw: str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=_invalid_constant)
    except RegistryError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise RegistryError("STORAGE_REGISTRY_JSON_INVALID") from None


def _migration_trigger(trigger: Any) -> tuple[str, str]:
    if isinstance(trigger, str):
        return ("policy", _safe_string(
            trigger, "STORAGE_REGISTRY_MIGRATION_TRIGGER_INVALID", maximum=240))
    trigger = _strict_object(
        trigger, TRIGGER_KEYS, "STORAGE_REGISTRY_MIGRATION_TRIGGER_SCHEMA")
    trigger_id = _identifier(
        trigger["id"], "STORAGE_REGISTRY_MIGRATION_TRIGGER_ID_INVALID")
    metric = trigger["metric"]
    _require(isinstance(metric, str)
             and metric in BOOLEAN_TRIGGER_METRICS | INTEGER_TRIGGER_METRICS,
             "STORAGE_REGISTRY_MIGRATION_TRIGGER_METRIC_INVALID")
    operator = trigger["operator"]
    allowed_operators = (BOOLEAN_TRIGGER_OPERATORS if metric in BOOLEAN_TRIGGER_METRICS
                         else INTEGER_TRIGGER_OPERATORS)
    _require(isinstance(operator, str) and operator in allowed_operators,
             "STORAGE_REGISTRY_MIGRATION_TRIGGER_OPERATOR_INVALID")
    threshold = trigger["threshold"]
    if metric in BOOLEAN_TRIGGER_METRICS:
        _require(type(threshold) is bool,
                 "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID")
    else:
        _require(type(threshold) is int and 0 <= threshold <= MAX_TRIGGER_THRESHOLD,
                 "STORAGE_REGISTRY_MIGRATION_TRIGGER_THRESHOLD_INVALID")
    _safe_string(
        trigger["rationale"], "STORAGE_REGISTRY_MIGRATION_TRIGGER_RATIONALE_INVALID",
        maximum=240)
    return ("structured", trigger_id)


def _validate_store(store: Any) -> dict[str, Any]:
    store = _strict_object(store, STORE_KEYS, "STORAGE_REGISTRY_STORE_SCHEMA")
    _identifier(store["id"], "STORAGE_REGISTRY_STORE_ID_INVALID")
    _root(store["root"])
    _require(isinstance(store["location_scope"], str)
             and store["location_scope"] in LOCATION_SCOPES,
             "STORAGE_REGISTRY_LOCATION_SCOPE_INVALID")
    _require(isinstance(store["status"], str) and store["status"] in STATUSES,
             "STORAGE_REGISTRY_STATUS_INVALID")

    roles = store["roles"]
    _require(isinstance(roles, list) and roles and len(roles) <= len(ROLES)
             and all(isinstance(role, str) and role in ROLES for role in roles)
             and len(roles) == len(set(roles))
             and roles == sorted(roles, key=ROLES.index),
             "STORAGE_REGISTRY_ROLES_INVALID")
    _require(isinstance(store["sensitivity"], str)
             and store["sensitivity"] in SENSITIVITIES,
             "STORAGE_REGISTRY_SENSITIVITY_INVALID")
    _identifier(store["owner"], "STORAGE_REGISTRY_OWNER_INVALID")
    _require(isinstance(store["format"], str)
             and FORMAT_PATTERN.fullmatch(store["format"]) is not None,
             "STORAGE_REGISTRY_FORMAT_INVALID")
    _require(isinstance(store["writer_model"], str)
             and store["writer_model"] in WRITER_MODELS,
             "STORAGE_REGISTRY_WRITER_MODEL_INVALID")
    _require(isinstance(store["durability"], str)
             and store["durability"] in DURABILITIES,
             "STORAGE_REGISTRY_DURABILITY_INVALID")
    _require(isinstance(store["backup_unit"], str)
             and store["backup_unit"] in BACKUP_UNITS,
             "STORAGE_REGISTRY_BACKUP_UNIT_INVALID")
    _require(isinstance(store["retention_class"], str)
             and store["retention_class"] in RETENTION_CLASSES,
             "STORAGE_REGISTRY_RETENTION_CLASS_INVALID")

    mode = store["generated_file_mode"]
    _require(mode is None or mode == "0600", "STORAGE_REGISTRY_FILE_MODE_INVALID")
    if mode == "0600":
        _require(store["sensitivity"] in {"confidential", "restricted"}
                 and store["writer_model"] not in {"read_only", "external_managed"},
                 "STORAGE_REGISTRY_FILE_MODE_INVALID")
    if (store["sensitivity"] in {"confidential", "restricted"}
            and store["location_scope"] == "workspace"
            and store["writer_model"] not in {"read_only", "external_managed"}):
        _require(mode == "0600", "STORAGE_REGISTRY_PRIVATE_MODE_REQUIRED")

    derived = store["derived_from"]
    _require(isinstance(derived, list) and len(derived) <= MAX_STORES
             and all(isinstance(item, str) and ID_PATTERN.fullmatch(item) for item in derived)
             and len(derived) == len(set(derived)) and derived == sorted(derived),
             "STORAGE_REGISTRY_DERIVED_FROM_INVALID")
    triggers = store["migration_triggers"]
    _require(isinstance(triggers, list) and 0 < len(triggers) <= 16,
             "STORAGE_REGISTRY_MIGRATION_TRIGGERS_INVALID")
    trigger_identities = [_migration_trigger(trigger) for trigger in triggers]
    _require(len(trigger_identities) == len(set(trigger_identities)),
             "STORAGE_REGISTRY_MIGRATION_TRIGGERS_INVALID")

    if "credential" in roles:
        _require(roles == ["credential"] and store["sensitivity"] == "restricted"
                 and store["retention_class"] == "credential_lifecycle"
                 and store["generated_file_mode"] == "0600",
                 "STORAGE_REGISTRY_CREDENTIAL_STORE_INVALID")
    _require(not ({"cache", "projection"} & set(roles) and "authority" in roles),
             "STORAGE_REGISTRY_AUTHORITY_ROLE_CONFLICT")
    if store["status"] == "planned":
        _require("authority" not in roles, "STORAGE_REGISTRY_PLANNED_AUTHORITY_FORBIDDEN")
    if store["status"] == "unverified":
        _require("authority" not in roles, "STORAGE_REGISTRY_UNVERIFIED_AUTHORITY_FORBIDDEN")
    if store["location_scope"] == "external":
        _require(store["status"] == "unverified"
                 and store["writer_model"] == "external_managed"
                 and store["durability"] == "external_unverified"
                 and store["backup_unit"] == "external_store"
                 and store["generated_file_mode"] is None,
                 "STORAGE_REGISTRY_EXTERNAL_STORE_INVALID")
    return store


def _roots_overlap(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    common = min(len(left_parts), len(right_parts))
    return left_parts[:common] == right_parts[:common]


def validate_registry(value: Any) -> dict[str, Any]:
    """Validate and return a Storage Governance Registry v1 object.

    Validation is structural and side-effect free. It validates logical roots but
    does not require planned or externally managed stores to exist.
    """

    registry = _strict_object(value, TOP_LEVEL_KEYS, "STORAGE_REGISTRY_SCHEMA")
    _require(type(registry["schema_version"]) is int and registry["schema_version"] == 1
             and registry["kind"] == "storage_governance_registry",
             "STORAGE_REGISTRY_VERSION_INVALID")
    stores = registry["stores"]
    _require(isinstance(stores, list) and 0 < len(stores) <= MAX_STORES,
             "STORAGE_REGISTRY_STORES_INVALID")
    for store in stores:
        _validate_store(store)

    by_id = {store["id"]: store for store in stores}
    _require(len(by_id) == len(stores), "STORAGE_REGISTRY_DUPLICATE_STORE_ID")
    root_keys = [(store["location_scope"], store["root"]) for store in stores]
    _require(len(set(root_keys)) == len(root_keys), "STORAGE_REGISTRY_DUPLICATE_ROOT")

    for store in stores:
        _require(store["id"] not in store["derived_from"],
                 "STORAGE_REGISTRY_DERIVATION_CYCLE")
        for source_id in store["derived_from"]:
            _require(source_id in by_id, "STORAGE_REGISTRY_DERIVED_FROM_UNKNOWN")
            source = by_id[source_id]
            if "authority" in store["roles"]:
                _require(source["owner"] == store["owner"],
                         "STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(store_id: str) -> None:
        if store_id in visiting:
            raise RegistryError("STORAGE_REGISTRY_DERIVATION_CYCLE")
        if store_id in visited:
            return
        visiting.add(store_id)
        for source_id in by_id[store_id]["derived_from"]:
            visit(source_id)
        visiting.remove(store_id)
        visited.add(store_id)

    for store_id in by_id:
        visit(store_id)

    for store in stores:
        if "authority" not in store["roles"]:
            continue
        pending = list(store["derived_from"])
        ancestors: set[str] = set()
        while pending:
            source_id = pending.pop()
            if source_id in ancestors:
                continue
            ancestors.add(source_id)
            source = by_id[source_id]
            _require(source["owner"] == store["owner"],
                     "STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN")
            pending.extend(source["derived_from"])

    workspace_stores = [store for store in stores if store["location_scope"] == "workspace"]
    for index, left in enumerate(workspace_stores):
        for right in workspace_stores[index + 1:]:
            if left["owner"] == right["owner"] or not _roots_overlap(left["root"], right["root"]):
                continue
            _require("authority" not in left["roles"] and "authority" not in right["roles"],
                     "STORAGE_REGISTRY_CROSS_OWNER_AUTHORITY_FORBIDDEN")
    return registry


_DIRECTORY_OPEN_FLAGS = (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                         | getattr(os, "O_CLOEXEC", 0))
_FILE_OPEN_FLAGS = (os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NONBLOCK", 0))


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return metadata.st_dev, metadata.st_ino


def _close_descriptors(descriptors: list[int], *, suppress_errors: bool) -> None:
    first_error: OSError | None = None
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError as error:
            if first_error is None:
                first_error = error
    descriptors.clear()
    if first_error is not None and not suppress_errors:
        raise first_error


def _open_directory_no_follow(path: Path, code: str) -> int:
    """Open an absolute directory from filesystem root without following links."""

    _require(path.is_absolute() and path.anchor and path.parts, code)
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(path.anchor, _DIRECTORY_OPEN_FLAGS))
        for component in path.parts[1:]:
            descriptors.append(os.open(
                component, _DIRECTORY_OPEN_FLAGS, dir_fd=descriptors[-1]))
        result = descriptors.pop()
        try:
            _close_descriptors(descriptors, suppress_errors=False)
        except OSError:
            try:
                os.close(result)
            except OSError:
                pass
            raise RegistryError(code) from None
        return result
    except RegistryError:
        _close_descriptors(descriptors, suppress_errors=True)
        raise
    except OSError:
        _close_descriptors(descriptors, suppress_errors=True)
        raise RegistryError(code) from None


class WorkspaceSnapshot:
    """Retained descriptor and identity for one no-follow workspace snapshot."""

    def __init__(
        self,
        workspace_path: Path,
        workspace_fd: int,
        registry: dict[str, Any] | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.workspace_fd = workspace_fd
        self.workspace_identity = _identity(os.fstat(workspace_fd))
        self.workspace_uid = os.fstat(workspace_fd).st_uid
        self.registry = registry

    @property
    def closed(self) -> bool:
        return self.workspace_fd < 0

    def verify(self) -> os.stat_result:
        if self.closed:
            raise RegistryError("STORAGE_REGISTRY_SNAPSHOT_CLOSED")
        try:
            metadata = os.fstat(self.workspace_fd)
        except OSError as error:
            raise RegistryError("STORAGE_REGISTRY_WORKSPACE_CHANGED") from error
        if _identity(metadata) != self.workspace_identity or not stat.S_ISDIR(metadata.st_mode):
            raise RegistryError("STORAGE_REGISTRY_WORKSPACE_CHANGED")
        return metadata

    def verify_path_binding(self) -> None:
        """Fail closed if the caller-visible workspace path was retargeted."""
        self.verify()
        descriptor = _open_directory_no_follow(
            self.workspace_path, "STORAGE_REGISTRY_WORKSPACE_CHANGED")
        try:
            if _identity(os.fstat(descriptor)) != self.workspace_identity:
                raise RegistryError("STORAGE_REGISTRY_WORKSPACE_CHANGED")
        finally:
            try:
                os.close(descriptor)
            except OSError:
                if sys.exc_info()[0] is None:
                    raise

    def close(self) -> None:
        if self.closed:
            return
        descriptor = self.workspace_fd
        self.workspace_fd = -1
        os.close(descriptor)

    def __enter__(self) -> "WorkspaceSnapshot":
        self.verify()
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        try:
            self.close()
        except OSError:
            if exc_type is None:
                raise
        return False


def open_workspace_snapshot(workspace: os.PathLike[str] | str) -> WorkspaceSnapshot:
    """Open and retain one component-safe workspace descriptor."""
    workspace_value = os.fspath(workspace)
    _require(isinstance(workspace_value, str) and workspace_value,
             "STORAGE_REGISTRY_WORKSPACE_INVALID")
    workspace_input = Path(workspace_value)
    _require(".." not in workspace_input.parts, "STORAGE_REGISTRY_WORKSPACE_INVALID")
    workspace_path = Path(os.path.abspath(workspace_value))
    descriptor = _open_directory_no_follow(
        workspace_path, "STORAGE_REGISTRY_WORKSPACE_INVALID")
    try:
        return WorkspaceSnapshot(workspace_path, descriptor)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _registry_relative_path(
    path: os.PathLike[str] | str,
    workspace_path: Path,
) -> Path:
    candidate_value = os.fspath(path)
    _require(isinstance(candidate_value, str) and candidate_value,
             "STORAGE_REGISTRY_PATH_INVALID")
    candidate = Path(candidate_value)
    if candidate.is_absolute():
        candidate_path = Path(os.path.abspath(candidate_value))
        try:
            relative = candidate_path.relative_to(workspace_path)
        except ValueError:
            raise RegistryError("STORAGE_REGISTRY_PATH_INVALID") from None
    else:
        relative = candidate
    _require(relative.parts and all(part not in {"", ".", ".."}
                                    for part in relative.parts),
             "STORAGE_REGISTRY_PATH_INVALID")
    return relative


def _read_registry_descriptor(descriptor: int) -> bytes:
    """Bound the read and reject mutation of the opened registry descriptor."""

    before = os.fstat(descriptor)
    _require(stat.S_ISREG(before.st_mode) and 0 <= before.st_size <= MAX_REGISTRY_BYTES,
             "STORAGE_REGISTRY_PATH_INVALID")
    chunks: list[bytes] = []
    remaining = MAX_REGISTRY_BYTES + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    raw = b"".join(chunks)
    after = os.fstat(descriptor)
    before_identity = (before.st_dev, before.st_ino, before.st_mode, before.st_size,
                       before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_mode, after.st_size,
                      after.st_mtime_ns)
    _require(before_identity == after_identity and len(raw) == before.st_size
             and len(raw) <= MAX_REGISTRY_BYTES,
             "STORAGE_REGISTRY_PATH_INVALID")
    return raw


def open_registry_snapshot(
    path: os.PathLike[str] | str,
    workspace: os.PathLike[str] | str,
) -> WorkspaceSnapshot:
    """Retain the workspace FD used to read and validate one registry."""
    snapshot = open_workspace_snapshot(workspace)
    descriptors: list[int] = []
    primary = False
    try:
        relative = _registry_relative_path(path, snapshot.workspace_path)
        parent_fd = snapshot.workspace_fd
        for component in relative.parts[:-1]:
            descriptor = os.open(component, _DIRECTORY_OPEN_FLAGS, dir_fd=parent_fd)
            descriptors.append(descriptor)
            parent_fd = descriptor
        registry_fd = os.open(relative.parts[-1], _FILE_OPEN_FLAGS, dir_fd=parent_fd)
        descriptors.append(registry_fd)
        raw = _read_registry_descriptor(registry_fd)
        snapshot.verify()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise RegistryError("STORAGE_REGISTRY_JSON_INVALID") from None
        snapshot.registry = validate_registry(_loads_strict(text))
    except RegistryError:
        primary = True
        raise
    except (OSError, RuntimeError, TypeError, ValueError):
        primary = True
        raise RegistryError("STORAGE_REGISTRY_PATH_INVALID") from None
    finally:
        active_exception = primary or sys.exc_info()[0] is not None
        try:
            _close_descriptors(descriptors, suppress_errors=active_exception)
        except OSError as error:
            try:
                snapshot.close()
            except OSError:
                pass
            raise RegistryError("STORAGE_REGISTRY_PATH_INVALID") from error
        if active_exception:
            try:
                snapshot.close()
            except OSError:
                pass
    return snapshot


def load_registry(path: os.PathLike[str] | str,
                  workspace: os.PathLike[str] | str) -> dict[str, Any]:
    """Load and close a retained registry snapshot for compatibility callers."""
    snapshot = open_registry_snapshot(path, workspace)
    try:
        if snapshot.registry is None:  # defensive invariant
            raise RegistryError("STORAGE_REGISTRY_PATH_INVALID")
        return snapshot.registry
    finally:
        primary_active = sys.exc_info()[0] is not None
        try:
            snapshot.close()
        except OSError:
            if not primary_active:
                raise

