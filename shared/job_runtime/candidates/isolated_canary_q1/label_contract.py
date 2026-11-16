"""Pure unique-label and launchd-target contract; performs no I/O."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePath, PurePosixPath
import re
from typing import Any, Mapping

from .frozen import freeze


class CanaryContractError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LabelScope:
    service_label: str
    watchdog_label: str
    service_plist_filename: str
    watchdog_plist_filename: str


@dataclass(frozen=True, slots=True)
class PlistSpec:
    filename: str
    label: str
    program_arguments: tuple[str, ...]
    working_directory: str
    environment: tuple[tuple[str, str], ...]
    standard_out_path: str
    standard_error_path: str
    keep_alive: bool | None
    run_at_load: bool
    start_interval: int | None
    throttle_interval: int | None
    exit_timeout: int


@dataclass(frozen=True, slots=True)
class LinkTarget:
    link_path: str
    plist_path: str


@dataclass(frozen=True, slots=True)
class LifecycleTargets:
    domain: str
    generate_paths: tuple[str, str]
    install_print_targets: tuple[str, str]
    install_bootstrap_paths: tuple[str, str]
    watchdog_print_target: str
    watchdog_bootstrap_path: str
    watchdog_kill_target: str
    reload_target: str
    status_targets: tuple[str, str]
    uninstall_targets: tuple[str, str]
    persistent_links: tuple[LinkTarget, ...]


@dataclass(frozen=True, slots=True)
class LaunchdPlan:
    schema_version: int
    scope: LabelScope
    service_plist: PlistSpec
    watchdog_plist: PlistSpec
    targets: LifecycleTargets


def _valid_label(value: str) -> bool:
    try:
        raw = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    if len(raw) > 240 or "." not in value:
        return False
    parts = value.split(".")
    return bool(parts and re.fullmatch(r"[a-z][a-z0-9-]{0,62}", parts[0]) and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p) for p in parts[1:]))


def label_scope(service_label: object, *, production_service_label: str) -> LabelScope:
    if type(production_service_label) is not str or not _valid_label(production_service_label):
        raise CanaryContractError("CANARY_PRODUCTION_LABEL_POLICY_INVALID")
    if type(service_label) is not str:
        raise CanaryContractError("CANARY_SERVICE_LABEL_TYPE_INVALID")
    if not service_label:
        raise CanaryContractError("CANARY_SERVICE_LABEL_EMPTY")
    try:
        length = len(service_label.encode("ascii"))
    except UnicodeEncodeError:
        raise CanaryContractError("CANARY_SERVICE_LABEL_MALFORMED") from None
    if length > 240:
        raise CanaryContractError("CANARY_SERVICE_LABEL_TOO_LONG")
    if service_label.endswith(".watchdog") or not _valid_label(service_label):
        raise CanaryContractError("CANARY_SERVICE_LABEL_MALFORMED")
    watchdog = service_label + ".watchdog"
    if len((watchdog + ".plist").encode("ascii")) > 255:
        raise CanaryContractError("CANARY_SERVICE_LABEL_TOO_LONG")
    if service_label in {production_service_label, production_service_label + ".watchdog"} or watchdog in {production_service_label, production_service_label + ".watchdog"}:
        raise CanaryContractError("CANARY_SERVICE_LABEL_RESERVED")
    return LabelScope(service_label, watchdog, service_label + ".plist", watchdog + ".plist")


def parse_config(value: object, *, production_service_label: str) -> LabelScope:
    if not isinstance(value, Mapping):
        raise CanaryContractError("CANARY_CONFIG_OBJECT_REQUIRED")
    if set(value) != {"schema_version", "service_label"}:
        raise CanaryContractError("CANARY_CONFIG_KEYS_INVALID")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise CanaryContractError("CANARY_CONFIG_VERSION_INVALID")
    return label_scope(value["service_label"], production_service_label=production_service_label)


def _absolute(path: PurePath, workspace: PurePath | None = None) -> PurePosixPath:
    if type(path) is not PurePosixPath or not path.is_absolute() or ".." in path.parts or any(not part or any(ord(ch) < 32 for ch in part) or "\\" in part for part in path.parts):
        raise CanaryContractError("CANARY_PLAN_PATH_INVALID")
    if workspace is not None:
        try:
            path.relative_to(workspace)
        except ValueError:
            raise CanaryContractError("CANARY_PLAN_PATH_INVALID") from None
    return path


def build_launchd_plan(value: object, *, production_service_label: str, workspace: PurePath, config_path: PurePath, python_bin: PurePath, launcher_path: PurePath, uid: int, home_directory: PurePath) -> LaunchdPlan:
    scope = parse_config(value, production_service_label=production_service_label)
    if type(uid) is not int or uid < 0:
        raise CanaryContractError("CANARY_PLAN_UID_INVALID")
    workspace = _absolute(workspace)
    config_path = _absolute(config_path, workspace)
    python_bin = _absolute(python_bin, workspace)
    launcher_path = _absolute(launcher_path, workspace)
    home_directory = _absolute(home_directory)
    launchd = workspace / ".job-runtime" / "launchd"
    logs = workspace / ".job-runtime" / "logs"
    service_path = launchd / scope.service_plist_filename
    watchdog_path = launchd / scope.watchdog_plist_filename
    env = (("PYTHONPATH", str(workspace)),)
    service_args = ("/usr/bin/caffeinate", "-i", str(python_bin), str(launcher_path), "--workspace", str(workspace), "--config", str(config_path), "--service-label", scope.service_label)
    watchdog_args = (str(python_bin), "-m", "shared.job_runtime.host", "watchdog", "--workspace", str(workspace), "--config", str(config_path), "--service-label", scope.service_label)
    service = PlistSpec(scope.service_plist_filename, scope.service_label, service_args, str(workspace), env, str(logs / (scope.service_label + ".stdout.log")), str(logs / (scope.service_label + ".stderr.log")), True, True, None, 15, 15)
    watchdog = PlistSpec(scope.watchdog_plist_filename, scope.watchdog_label, watchdog_args, str(workspace), env, str(logs / (scope.watchdog_label + ".stdout.log")), str(logs / (scope.watchdog_label + ".stderr.log")), None, True, 60, 15, 15)
    domain = f"gui/{uid}"
    service_target = f"{domain}/{scope.service_label}"
    watchdog_target = f"{domain}/{scope.watchdog_label}"
    targets = LifecycleTargets(domain=domain, generate_paths=(str(service_path), str(watchdog_path)), install_print_targets=(service_target, watchdog_target), install_bootstrap_paths=(str(service_path), str(watchdog_path)), watchdog_print_target=watchdog_target, watchdog_bootstrap_path=str(watchdog_path), watchdog_kill_target=watchdog_target, reload_target=service_target, status_targets=(service_target, watchdog_target), uninstall_targets=(watchdog_target, service_target), persistent_links=())
    return LaunchdPlan(1, scope, service, watchdog, targets)


def as_closed_mapping(plan: LaunchdPlan) -> Mapping[str, Any]:
    if type(plan) is not LaunchdPlan:
        raise CanaryContractError("CANARY_CONFIG_OBJECT_REQUIRED")
    return freeze({"schema_version": 1, "labels": asdict(plan.scope), "plists": {"service": asdict(plan.service_plist), "watchdog": asdict(plan.watchdog_plist)}, "operations": asdict(plan.targets)})
