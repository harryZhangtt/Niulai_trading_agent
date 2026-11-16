#!/usr/bin/env python3
"""Validate an architecture-escalation decision record without changing it.

Exit 0: declaration is structurally valid and internally consistent.
Exit 1: declaration is well-formed JSON but fails the deterministic contract.
Exit 2: input is missing, unsafe, too large, or malformed JSON.

This validator checks declarations and trigger arithmetic only. It does not verify
scientific truth, source authority, implementation quality, or completion.
"""
from __future__ import annotations

import json
import math
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

MAX_BYTES = 256 * 1024
HEX64 = re.compile(r"[a-f0-9]{64}")
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}")
TRIGGER_CODES = (
    "critical_boundary",
    "clustered_high",
    "breadth",
    "reopen",
    "candidate_instability",
    "green_suite_contradiction",
)
COUNTER_KEYS = {
    "critical_cross_module",
    "clustered_high_same_root",
    "confirmed_findings",
    "module_count",
    "owner_count",
    "critical_reopens",
    "high_boundary_reopens",
    "lower_root_reopens",
    "invalidated_reviews",
    "post_green_high_findings",
}
ROOT_KEYS = {
    "version", "candidate_sha256", "candidate_family", "owner", "counters",
    "triggered", "trigger_codes", "external_semantics", "evidence", "options",
    "vertical_experiment", "decision", "stop_rules",
}
CANDIDATE_KEYS = {"path", "sha256", "owner", "module_boundary"}
EVIDENCE_KEYS = {
    "finding_ids", "candidate_hashes", "module_boundaries", "reproducer_refs",
    "schema_refs", "state_map_refs", "chronology_refs", "web_sources",
}
OPTION_KEYS = {
    "id", "summary", "trust", "contract_fit", "migration_failure_radius",
    "maintenance_runtime_cost", "fixture_realism", "rollback",
}
EXPERIMENT_KEYS = {
    "falsifiable_hypothesis", "falsifier", "nominal", "failure", "assertions",
    "no_external_effects",
}
DECISION_KEYS = {"selected", "rationale", "rollback_owner", "allowed_claim", "unresolved"}
WEB_KEYS = {
    "url", "role", "route", "source_version_or_date", "semantics",
    "applicability_limits", "accessed_at",
}


class Invalid(ValueError):
    pass


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise Invalid("duplicate_key")
        result[key] = value
    return result


def _parse(raw: bytes) -> Any:
    try:
        return json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(Invalid("nonfinite")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, Invalid) as exc:
        raise Invalid("malformed_json") from exc


def _exact_dict(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise Invalid(code)
    return value


def _text(value: Any, code: str) -> str:
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise Invalid(code)
    return value


def _safe_ref(value: Any, code: str) -> str:
    value = _text(value, code)
    if not SAFE_ID.fullmatch(value):
        raise Invalid(code)
    return value


def _list(value: Any, code: str, *, nonempty: bool = False, limit: int = 128) -> list[Any]:
    if type(value) is not list or len(value) > limit or (nonempty and not value):
        raise Invalid(code)
    return value


def _text_list(value: Any, code: str, *, nonempty: bool = False) -> list[str]:
    return [_text(item, code) for item in _list(value, code, nonempty=nonempty)]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def compute_triggers(counters: dict[str, Any]) -> list[str]:
    _exact_dict(counters, COUNTER_KEYS, "counter_fields")
    for key, value in counters.items():
        if type(value) is not int or value < 0 or value > 1_000_000:
            raise Invalid(f"counter_{key}")
    result: list[str] = []
    if counters["critical_cross_module"] >= 1:
        result.append("critical_boundary")
    if counters["clustered_high_same_root"] >= 2:
        result.append("clustered_high")
    if counters["confirmed_findings"] >= 4 and (
        counters["module_count"] >= 3 or counters["owner_count"] >= 2
    ):
        result.append("breadth")
    if (
        counters["critical_reopens"] >= 1
        or counters["high_boundary_reopens"] >= 1
        or counters["lower_root_reopens"] >= 2
    ):
        result.append("reopen")
    if counters["invalidated_reviews"] >= 2:
        result.append("candidate_instability")
    if counters["post_green_high_findings"] >= 2:
        result.append("green_suite_contradiction")
    return result


def validate(value: Any) -> None:
    root = _exact_dict(value, ROOT_KEYS, "root_fields")
    if root["version"] != "architecture-escalation-1":
        raise Invalid("version")
    if type(root["candidate_sha256"]) is not str or not HEX64.fullmatch(root["candidate_sha256"]):
        raise Invalid("candidate_sha256")
    family = _list(root["candidate_family"], "candidate_family", nonempty=True)
    family_paths: list[str] = []
    family_owners: set[str] = set()
    for item in family:
        item = _exact_dict(item, CANDIDATE_KEYS, "candidate_family_fields")
        path = _safe_ref(item["path"], "candidate_path")
        if type(item["sha256"]) is not str or not HEX64.fullmatch(item["sha256"]):
            raise Invalid("candidate_member_sha256")
        family_paths.append(path)
        family_owners.add(_safe_ref(item["owner"], "candidate_owner"))
        _text(item["module_boundary"], "candidate_boundary")
    if family_paths != sorted(family_paths) or len(family_paths) != len(set(family_paths)):
        raise Invalid("candidate_family_order")
    import hashlib
    if hashlib.sha256(_canonical(family)).hexdigest() != root["candidate_sha256"]:
        raise Invalid("candidate_family_sha256")
    _safe_ref(root["owner"], "owner")

    computed = compute_triggers(root["counters"])
    if root["counters"]["module_count"] != len(family):
        raise Invalid("module_count_mismatch")
    if root["counters"]["owner_count"] != len(family_owners):
        raise Invalid("owner_count_mismatch")
    if type(root["triggered"]) is not bool or root["triggered"] is not bool(computed):
        raise Invalid("triggered_mismatch")
    supplied_codes = _list(root["trigger_codes"], "trigger_codes")
    if any(type(code) is not str or code not in TRIGGER_CODES for code in supplied_codes):
        raise Invalid("trigger_code")
    if supplied_codes != computed:
        raise Invalid("trigger_codes_mismatch")
    if type(root["external_semantics"]) is not bool:
        raise Invalid("external_semantics")

    evidence = _exact_dict(root["evidence"], EVIDENCE_KEYS, "evidence_fields")
    required = bool(computed)
    finding_ids = [_safe_ref(item, "finding_id") for item in
                   _list(evidence["finding_ids"], "finding_ids", nonempty=required)]
    if len(finding_ids) != len(set(finding_ids)):
        raise Invalid("finding_id_duplicate")
    if root["counters"]["confirmed_findings"] != len(finding_ids):
        raise Invalid("finding_count_mismatch")
    for key in EVIDENCE_KEYS - {"finding_ids", "web_sources"}:
        _text_list(evidence[key], f"evidence_{key}", nonempty=required)
    web_sources = _list(evidence["web_sources"], "web_sources")
    kinds: set[str] = set()
    for source in web_sources:
        source = _exact_dict(source, WEB_KEYS, "web_source_fields")
        url = _text(source["url"], "web_url")
        if not url.startswith("https://") or len(url) > 2048:
            raise Invalid("web_url")
        if source["role"] not in ("primary", "independent"):
            raise Invalid("web_role")
        kinds.add(source["role"])
        if source["route"] not in ("native_websearch_webfetch", "chatgpt_work_browser"):
            raise Invalid("web_route")
        for key in ("source_version_or_date", "semantics", "applicability_limits"):
            _text(source[key], f"web_{key}")
        _safe_ref(source["accessed_at"], "web_accessed_at")
    if root["external_semantics"] and kinds != {"primary", "independent"}:
        raise Invalid("web_source_coverage")

    options = _list(root["options"], "options", nonempty=required, limit=4)
    option_ids: list[str] = []
    for option in options:
        option = _exact_dict(option, OPTION_KEYS, "option_fields")
        if option["id"] not in ("O0", "O1", "O2", "O3"):
            raise Invalid("option_id")
        option_ids.append(option["id"])
        for key in OPTION_KEYS - {"id"}:
            _text(option[key], f"option_{key}")
    if required and not {"O0", "O1", "O2"}.issubset(option_ids):
        raise Invalid("option_minimum")
    if len(option_ids) != len(set(option_ids)):
        raise Invalid("option_duplicate")

    experiment = _exact_dict(root["vertical_experiment"], EXPERIMENT_KEYS, "experiment_fields")
    for key in ("falsifiable_hypothesis", "falsifier", "nominal", "failure"):
        text = experiment[key]
        if required:
            _text(text, f"experiment_{key}")
        elif type(text) is not str:
            raise Invalid(f"experiment_{key}")
    _text_list(experiment["assertions"], "experiment_assertions", nonempty=required)
    if type(experiment["no_external_effects"]) is not bool or (
        required and experiment["no_external_effects"] is not True
    ):
        raise Invalid("experiment_no_external_effects")

    decision = _exact_dict(root["decision"], DECISION_KEYS, "decision_fields")
    if decision["selected"] not in option_ids and not (
        not required and decision["selected"] == "none"
    ):
        raise Invalid("decision_selected")
    for key in ("rationale", "rollback_owner", "allowed_claim"):
        text = decision[key]
        if required:
            _text(text, f"decision_{key}")
        elif type(text) is not str:
            raise Invalid(f"decision_{key}")
    _text_list(decision["unresolved"], "decision_unresolved")
    _text_list(root["stop_rules"], "stop_rules", nonempty=required)


def _read(path: Path) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_size < 2 or info.st_size > MAX_BYTES:
            raise Invalid("unsafe_input")
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise Invalid("unsafe_input")
        return raw
    except (OSError, Invalid) as exc:
        raise Invalid("unsafe_input") from exc


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("ARCHITECTURE_ESCALATION_MALFORMED usage", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        value = _parse(_read(path))
    except Invalid as exc:
        print(f"ARCHITECTURE_ESCALATION_MALFORMED {exc}", file=sys.stderr)
        return 2
    try:
        validate(value)
    except Invalid as exc:
        print(f"ARCHITECTURE_ESCALATION_INVALID {exc}")
        return 1
    print("ARCHITECTURE_ESCALATION_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
