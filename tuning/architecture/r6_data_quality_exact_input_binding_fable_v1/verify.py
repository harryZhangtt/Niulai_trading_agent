#!/usr/bin/env python3
"""Dependency-independent strict verifier for the frozen R6 exact-input package."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Dict, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = Path(__file__).resolve().parent
MANIFEST = PACKAGE / "current-input-manifest-v1.json"
SCHEMA = PACKAGE / "input-manifest-v1.schema.json"
SHA = re.compile(r"^[0-9a-f]{64}$")
CELLS = {"R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3"}
ARTIFACT_EXPECTED = {
    "payload": (2065, "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a"),
    "source_cutoff": (1044, "32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072"),
    "rubric": (2259, "81069b2ce57f30e56d70e7a2edd4672991838ebce1e2369b48effb8adde53d8f"),
    "thresholds": (3597, "41bbb8c07c26aadb9fe0e795b1ac8e5d3a17c88d60cba77692845b135dd4b95b"),
    "evaluation_schema": (1876, "8f28c800b70c968af9ee02ec8ddbd897d33a253474273d20e7f9f5b4868b74d5"),
}
COMMON_SHA = "256084e6362d87549392d3b069ce77edb1b8197d58b4d4b9045bbd5eaaa63426"
PROMPT_SHA = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"


class VerificationError(ValueError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise VerificationError(code)


def strict_loads(raw: bytes) -> Any:
    require(not raw.startswith(b"\xef\xbb\xbf"), "UTF8_BOM")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise VerificationError("UTF8_INVALID") from exc

    def pairs_hook(pairs: Sequence[tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in pairs:
            require(key not in out, "JSON_DUPLICATE_KEY:" + key)
            out[key] = value
        return out

    def bad_constant(value: str) -> None:
        raise VerificationError("JSON_NONFINITE:" + value)

    try:
        return json.loads(text, object_pairs_hook=pairs_hook, parse_constant=bad_constant)
    except VerificationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise VerificationError("JSON_INVALID") from exc


def strict_load(path: Path) -> Any:
    return strict_loads(path.read_bytes())


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise VerificationError("CANONICAL_INVALID") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def resolve_ref(schema_root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    require(ref.startswith("#/"), "SCHEMA_REF_EXTERNAL")
    current: Any = schema_root
    for part in ref[2:].split("/"):
        require(isinstance(current, Mapping) and part in current, "SCHEMA_REF_MISSING")
        current = current[part]
    require(isinstance(current, Mapping), "SCHEMA_REF_NOT_OBJECT")
    return current


def validate_schema(instance: Any, schema: Mapping[str, Any], root: Mapping[str, Any], path: str = "$") -> None:
    if "$ref" in schema:
        validate_schema(instance, resolve_ref(root, schema["$ref"]), root, path)
        return
    if "const" in schema:
        require(instance == schema["const"], "SCHEMA_CONST:" + path)
    if "enum" in schema:
        require(instance in schema["enum"], "SCHEMA_ENUM:" + path)
    expected_type = schema.get("type")
    if expected_type == "object":
        require(isinstance(instance, dict), "SCHEMA_TYPE_OBJECT:" + path)
        required = set(schema.get("required", []))
        require(required <= set(instance), "SCHEMA_REQUIRED:" + path)
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            require(set(instance) <= set(props), "SCHEMA_EXTRA:" + path)
        for key, value in instance.items():
            if key in props:
                validate_schema(value, props[key], root, path + "." + key)
    elif expected_type == "array":
        require(isinstance(instance, list), "SCHEMA_TYPE_ARRAY:" + path)
        require(len(instance) >= schema.get("minItems", 0), "SCHEMA_MIN_ITEMS:" + path)
        if "maxItems" in schema:
            require(len(instance) <= schema["maxItems"], "SCHEMA_MAX_ITEMS:" + path)
        for index, value in enumerate(instance):
            validate_schema(value, schema.get("items", {}), root, f"{path}[{index}]")
    elif expected_type == "string":
        require(isinstance(instance, str), "SCHEMA_TYPE_STRING:" + path)
        require(len(instance) >= schema.get("minLength", 0), "SCHEMA_MIN_LENGTH:" + path)
        if "pattern" in schema:
            require(re.fullmatch(schema["pattern"], instance) is not None, "SCHEMA_PATTERN:" + path)
    elif expected_type == "integer":
        require(isinstance(instance, int) and not isinstance(instance, bool), "SCHEMA_TYPE_INTEGER:" + path)
        require(instance >= schema.get("minimum", instance), "SCHEMA_MINIMUM:" + path)
    elif expected_type == "boolean":
        require(isinstance(instance, bool), "SCHEMA_TYPE_BOOLEAN:" + path)


def token_hits(text: str, tokens: Iterable[str]) -> list[str]:
    lower = text.lower()
    return [token for token in tokens if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])", lower)]


def validate_semantics(manifest: Mapping[str, Any], artifacts: Mapping[str, Any]) -> None:
    payload = artifacts["payload"]
    cutoff = artifacts["source_cutoff"]
    rubric = artifacts["rubric"]
    thresholds = artifacts["thresholds"]
    prompt = payload["prompt_utf8"]
    prompt_raw = prompt.encode("utf-8")
    require(len(prompt_raw) == payload["payload_bytes"] == 526, "PROMPT_BYTES")
    require(hashlib.sha256(prompt_raw).hexdigest() == payload["payload_sha256"] == PROMPT_SHA, "PROMPT_HASH")
    require(payload["source_cutoff"]["bytes"] == ARTIFACT_EXPECTED["source_cutoff"][0], "PAYLOAD_CUTOFF_BYTES")
    require(payload["source_cutoff"]["sha256"] == ARTIFACT_EXPECTED["source_cutoff"][1], "PAYLOAD_CUTOFF_HASH")
    require(payload["bindings"]["rubric_sha256"] == ARTIFACT_EXPECTED["rubric"][1], "PAYLOAD_RUBRIC_BINDING")
    require(payload["bindings"]["thresholds_v2_sha256"] == ARTIFACT_EXPECTED["thresholds"][1], "PAYLOAD_THRESHOLDS_BINDING")
    require(payload["bindings"]["evidence_schema_sha256"] == ARTIFACT_EXPECTED["evaluation_schema"][1], "PAYLOAD_SCHEMA_BINDING")
    require(cutoff["cutoff_at"] == "2026-11-09T00:00:00Z", "CUTOFF_AT")
    allowed = cutoff["allowed_sources"]
    require(len(allowed) == 2 and all("official" in item.lower() for item in allowed), "OFFICIAL_SOURCE_ONLY")
    require("official sources only" in " ".join(payload["expected_output_contract"]["hard_rules"]).lower(), "PROMPT_OFFICIAL_POLICY")
    private_tokens = ("bytedcli", "private source", "internal source", "intranet", "employee-only")
    require(not token_hits(prompt + " " + json.dumps(cutoff), private_tokens), "PRIVATE_INTERNAL_DEPENDENCY")
    leak_tokens = ("claude", "codex", "gpt", "opus", "addon", "dq", "baseline", "treatment", "call order", "call_order")
    require(not token_hits(prompt, leak_tokens), "PROMPT_TREATMENT_LEAK")
    require("order" not in prompt.lower(), "PROMPT_ORDER_LEAK")

    cell_values = list(manifest["cell_bindings"].values())
    require(set(manifest["cell_bindings"]) == CELLS, "CELL_SET")
    require(len({canonical_bytes(value) for value in cell_values}) == 1, "CELL_INPUT_NOT_IDENTICAL")
    cell_text = json.dumps(manifest["cell_bindings"], sort_keys=True).lower()
    require(not token_hits(cell_text, leak_tokens), "CELL_TREATMENT_LEAK")
    require("order" not in cell_text, "CELL_ORDER_LEAK")
    require(all(value["common_input_canonical_sha256"] == COMMON_SHA for value in cell_values), "CELL_COMMON_DIGEST")

    quality_dimensions = {item["id"] for item in rubric["dimensions"]}
    require({"research_evidence_quality", "completeness", "citation_accuracy", "source_quality"} <= quality_dimensions, "RUBRIC_QUALITY_DIMENSIONS")
    return_tokens = ("financial return", "investment return", "pnl", "profit", "sharpe", "sortino", "alpha return")
    specific_identity_tokens = ("claude", "codex", "gpt", "opus")
    rubric_text = json.dumps(rubric, sort_keys=True)
    thresholds_text = json.dumps(thresholds, sort_keys=True)
    require(not token_hits(rubric_text, return_tokens + specific_identity_tokens), "RUBRIC_PREFERENCE_OR_RETURN")
    require(not token_hits(thresholds_text, return_tokens + specific_identity_tokens), "THRESHOLDS_PREFERENCE_OR_RETURN")
    require(thresholds["primary_thresholds"]["PASS"].count("primary") >= 1, "THRESHOLDS_PRIMARY")
    require(thresholds["comparative_claim_limit"].startswith("PASS means bounded exploratory signal only"), "THRESHOLDS_CLAIM_LIMIT")
    pins = manifest["unresolved_pins"]
    require([item["pin"] for item in pins] == ["tool_roster", "time_window", "final_grants"], "PENDING_PINS")
    require(manifest["countable"] is False and not any(manifest["effects"].values()), "NONCOUNTABLE_EFFECTS")
    require(not any(manifest["dependencies"].values()), "DEPENDENCY_EFFECTS")


def validate_manifest(manifest: Mapping[str, Any], check_mode: bool = True) -> Dict[str, Any]:
    schema = strict_load(SCHEMA)
    validate_schema(manifest, schema, schema)
    if check_mode:
        require(stat.S_IMODE(os.lstat(PACKAGE).st_mode) == 0o700, "PACKAGE_MODE")
        require(os.lstat(PACKAGE).st_uid == os.getuid(), "PACKAGE_OWNER")
        require(stat.S_IMODE(os.lstat(MANIFEST).st_mode) == 0o600, "MANIFEST_MODE")
        require(os.lstat(MANIFEST).st_uid == os.getuid(), "MANIFEST_OWNER")
        require(stat.S_ISREG(os.lstat(MANIFEST).st_mode) and not stat.S_ISLNK(os.lstat(MANIFEST).st_mode), "MANIFEST_REGULAR")
    artifacts: Dict[str, Any] = {}
    common: Dict[str, Any] = {}
    for name, ref in manifest["common_binding"]["artifacts"].items():
        path = ROOT / ref["path"]
        require(path.is_file() and not path.is_symlink(), "ARTIFACT_REGULAR:" + name)
        raw = path.read_bytes()
        expected_bytes, expected_hash = ARTIFACT_EXPECTED[name]
        require(len(raw) == ref["bytes"] == expected_bytes, "ARTIFACT_BYTES:" + name)
        require(hashlib.sha256(raw).hexdigest() == ref["sha256"] == expected_hash, "ARTIFACT_HASH:" + name)
        artifacts[name] = strict_loads(raw)
        entry: Dict[str, Any] = {"bytes": len(raw), "sha256": expected_hash}
        if name == "payload":
            prompt_raw = artifacts[name]["prompt_utf8"].encode("utf-8")
            entry.update(prompt_bytes=len(prompt_raw), prompt_sha256=hashlib.sha256(prompt_raw).hexdigest())
        elif name == "source_cutoff":
            entry["cutoff_at"] = artifacts[name]["cutoff_at"]
        common[name] = entry
    require(len(canonical_bytes(common)) == manifest["common_binding"]["canonical_utf8_bytes"] == 661, "COMMON_BYTES")
    require(digest(common) == manifest["common_binding"]["canonical_sha256"] == COMMON_SHA, "COMMON_HASH")
    validate_semantics(manifest, artifacts)
    return {"artifacts": {name: {"bytes": ref[0], "sha256": ref[1]} for name, ref in ARTIFACT_EXPECTED.items()}, "common_binding": {"canonical_utf8_bytes": 661, "canonical_sha256": COMMON_SHA}}


def expect_failure(name: str, action: Any) -> str:
    try:
        action()
    except (VerificationError, UnicodeError, ValueError, TypeError):
        return "PASS_DENIED"
    raise AssertionError("adversary accepted: " + name)


def run_adversaries(manifest: Mapping[str, Any]) -> Dict[str, str]:
    schema = strict_load(SCHEMA)
    results: Dict[str, str] = {}
    results["duplicate_key"] = expect_failure("duplicate_key", lambda: strict_loads(b'{"x":1,"x":2}'))
    results["invalid_utf8"] = expect_failure("invalid_utf8", lambda: strict_loads(b'{"x":"\xff"}'))
    results["nonfinite_json"] = expect_failure("nonfinite_json", lambda: strict_loads(b'{"x":NaN}'))
    bad = copy.deepcopy(manifest); bad["common_binding"]["artifacts"]["payload"]["sha256"] = "0" * 64
    results["payload_hash_substitution"] = expect_failure("payload_hash_substitution", lambda: validate_manifest(bad, False))
    bad = copy.deepcopy(manifest); bad["cell_bindings"]["R6DQ-7F2C91A4"]["prompt_sha256"] = "0" * 64
    results["single_cell_prompt_substitution"] = expect_failure("single_cell_prompt_substitution", lambda: validate_manifest(bad, False))
    bad = copy.deepcopy(manifest); bad["cell_bindings"]["R6DQ-1B8E43D7"]["source_cutoff_sha256"] = "0" * 64
    results["single_cell_cutoff_substitution"] = expect_failure("single_cell_cutoff_substitution", lambda: validate_manifest(bad, False))
    bad = copy.deepcopy(manifest); bad["cell_bindings"]["R6DQ-C4A7095E"]["provider"] = "hidden"
    results["cell_identity_leakage_field"] = expect_failure("cell_identity_leakage_field", lambda: validate_schema(bad, schema, schema))
    bad = copy.deepcopy(manifest); bad["unresolved_pins"] = bad["unresolved_pins"][:2]
    results["missing_final_grant_pin"] = expect_failure("missing_final_grant_pin", lambda: validate_manifest(bad, False))
    bad = copy.deepcopy(manifest); bad["dependencies"]["bytedcli"] = True
    results["bytedcli_dependency"] = expect_failure("bytedcli_dependency", lambda: validate_manifest(bad, False))
    bad = copy.deepcopy(manifest); bad["effects"]["network"] = True
    results["network_effect"] = expect_failure("network_effect", lambda: validate_manifest(bad, False))
    return results


def main() -> int:
    manifest = strict_load(MANIFEST)
    positive = validate_manifest(manifest)
    adversaries = run_adversaries(manifest)
    result = {
        "version": "r6-data-quality-exact-input-verification-v1",
        "status": "PASS_PROVIDER_FREE_NONCOUNTABLE",
        "strict_json_and_schema": "PASS",
        "positive_checks": positive,
        "adversarial_checks": adversaries,
        "adversarial_passed": sum(value == "PASS_DENIED" for value in adversaries.values()),
        "adversarial_total": len(adversaries),
        "effects": {"provider": False, "network": False, "account": False, "private_state": False, "email": False, "business": False, "host": False, "scheduler": False},
        "countable": False,
    }
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
