"""Fixed-path chronology and human-authority validator for blind-map v6.

No public API accepts a root, wrapper, store, callback, authority object, review
hash, packet, grade, metric, clock, map, or randomness. Authentic pins are empty
until independently reviewed live artifacts exist, so public opening deterministically
denies before reading the private map.
"""
from __future__ import annotations

import hashlib
import types
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence, Tuple

from . import transaction


class ChronologyError(ValueError):
    pass


def _require(value: bool, code: str) -> None:
    if not value:
        raise ChronologyError(code)


FIXED_WORKSPACE_ROOT = Path(__file__).resolve().parents[4]
WORKSPACE_ROOT = FIXED_WORKSPACE_ROOT
CELL_IDS = transaction.CELL_IDS
LABEL_RE = transaction.LABEL_RE
SHA_RE = transaction.SHA_RE
OPEN_REVIEW_IDENTITY = "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8"
HUMAN_VALIDATOR_MODULE = "shared.job_runtime.candidates.r6_human_grader_registry_v1.registry"

PINNED_SOURCES = (
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v5-independent-review-open-v1-fable-20261113.json", 23467, OPEN_REVIEW_IDENTITY),
    ("shared/job_runtime/candidates/r6_human_grader_registry_v1/registry.py", 14782, "63d2eaff7f331cb7227337e19e0eb0aa7cd9ed5a7021e7f8064f28ec1c78f431"),
    ("tuning/architecture/r6_human_grader_registry_v1/source-closure-v1.json", 5625, "7eea2c8867b61a1e0cc6a4741eda692b5ccf31f4c3b5294425ea1bb05dda004e"),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-human-grader-registry-v1-independent-review.json", 8428, "348f53abe20265432fd906a4e549420222b12db4cd09adbb2eafca9dbc518c36"),
    ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-human-grader-timing-countability-independent-audit-fable-20261111.json", 8743, "d76b44a5ed65f107bb0977632470f6178ceb787559552803158319d4f90b1861"),
)

RUNTIME = "mentor/runtime/scheduler-midresponse-recovery-20261107"
HUMAN_PATHS = {
    "REGISTRY": RUNTIME + "/r6-data-quality-human-grader-registry-subject-v1.json",
    "REGISTRY_REVIEW": RUNTIME + "/r6-data-quality-human-grader-registry-subject-v1-independent-review.json",
    "G1": RUNTIME + "/r6-data-quality-human-grader-g1-role-grant-subject-v1.json",
    "G1_REVIEW": RUNTIME + "/r6-data-quality-human-grader-g1-role-grant-subject-v1-independent-review.json",
    "G2": RUNTIME + "/r6-data-quality-human-grader-g2-role-grant-subject-v1.json",
    "G2_REVIEW": RUNTIME + "/r6-data-quality-human-grader-g2-role-grant-subject-v1-independent-review.json",
    "G3": RUNTIME + "/r6-data-quality-human-grader-g3-role-grant-subject-v1.json",
    "G3_REVIEW": RUNTIME + "/r6-data-quality-human-grader-g3-role-grant-subject-v1-independent-review.json",
}

BLOCK_GRANT_PATH = "chronology/final-block-grant-v6.json"
BLOCK_GRANT_REVIEW_PATH = "chronology/final-block-grant-review-v6.json"
METRICS_PATH = "chronology/derived-metrics-record-v6.json"
MANIFEST_PATH = "chronology/chain-manifest-v6.json"
ATTEMPT_PATHS = {cell: "chronology/attempt-%s-v6.json" % cell for cell in CELL_IDS}
PACKET_PATHS = {cell: "chronology/evaluation-packet-%s-v6.json" % cell for cell in CELL_IDS}
GRADE_PATHS = {(cell, role): "chronology/human-grade-%s-%s-v6.json" % (cell, role.lower()) for cell in CELL_IDS for role in ("G1", "G2", "G3")}
REQUEST_PATHS = {cell: "chronology/provider-request-%s-v6.json" % cell for cell in CELL_IDS}
RESULT_PATHS = {cell: "chronology/provider-result-%s-v6.json" % cell for cell in CELL_IDS}
EVALUATION_ARTIFACT_PATHS = {cell: "chronology/evaluation-artifact-%s-v6.json" % cell for cell in CELL_IDS}
GRADE_ARTIFACT_PATHS = {(cell, role): "chronology/grade-artifact-%s-%s-v6.json" % (cell, role.lower()) for cell in CELL_IDS for role in ("G1", "G2", "G3")}
DERIVED_METRIC_ARTIFACT_PATH = "chronology/derived-metric-artifact-v6.json"
BASE_EXTERNAL_ARTIFACT_PATHS = {*REQUEST_PATHS.values(), *RESULT_PATHS.values(), *EVALUATION_ARTIFACT_PATHS.values(), *[GRADE_ARTIFACT_PATHS[(cell, role)] for cell in CELL_IDS for role in ("G1", "G2")], DERIVED_METRIC_ARTIFACT_PATH}
G3_EXTERNAL_ARTIFACT_PATHS = {GRADE_ARTIFACT_PATHS[(cell, "G3")] for cell in CELL_IDS}
EXTERNAL_ARTIFACT_PATHS = BASE_EXTERNAL_ARTIFACT_PATHS | G3_EXTERNAL_ARTIFACT_PATHS

def _external_artifact_paths(g3_required: bool) -> set[str]:
    _require(isinstance(g3_required, bool), "EXTERNAL_G3_REQUIRED")
    return BASE_EXTERNAL_ARTIFACT_PATHS | (G3_EXTERNAL_ARTIFACT_PATHS if g3_required else set())

# Deliberately empty. Adding values is a separate reviewed trust-pin change.
AUTHENTIC_HUMAN_PINS: Mapping[str, Mapping[str, Any]] = {}
AUTHENTIC_CHAIN_PINS: Mapping[str, Mapping[str, Any]] = {}

ZERO_EFFECTS = {key: 0 for key in ("provider", "network", "account", "credential", "email", "business", "host", "scheduler", "live", "bytedcli")}

# Exact immutable chronology slots. Optional G3 occupies only its reserved tail.
GRANT_SEQUENCE = 1
GRANT_REVIEW_SEQUENCE = 2
ATTEMPT_SEQUENCES = {cell: (3 + 2 * index, 4 + 2 * index) for index, cell in enumerate(CELL_IDS)}
PACKET_SEQUENCES = {cell: 11 + index for index, cell in enumerate(CELL_IDS)}
GRADE_SEQUENCES = {
    **{(cell, "G1"): 15 + index for index, cell in enumerate(CELL_IDS)},
    **{(cell, "G2"): 19 + index for index, cell in enumerate(CELL_IDS)},
    **{(cell, "G3"): 23 + index for index, cell in enumerate(CELL_IDS)},
}
METRICS_SEQUENCES = {False: 23, True: 27}
MANIFEST_SEQUENCES = {False: 24, True: 28}


def _read_fixed_bytes(root: Path, relative: str, exact_bytes: int, expected_sha: str, code: str) -> bytes:
    parts = relative.split("/")
    _require(all(part not in ("", ".", "..") for part in parts) and "\\" not in relative, code + "_PATH")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    opened = []
    try:
        descriptor = os.open(str(root), flags_dir); opened.append(descriptor)
        for part in parts[:-1]:
            descriptor = os.open(part, flags_dir, dir_fd=descriptor); opened.append(descriptor)
            status = os.fstat(descriptor)
            _require(stat.S_ISDIR(status.st_mode) and status.st_uid == os.getuid(), code + "_PARENT")
        descriptor = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=descriptor); opened.append(descriptor)
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid(), code + "_FILE")
        _require(before.st_size == exact_bytes, code + "_BYTES")
        remaining = exact_bytes; chunks = []
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _require(bool(chunk), code + "_TRUNCATED")
            chunks.append(chunk); remaining -= len(chunk)
        _require(os.read(descriptor, 1) == b"", code + "_GREW")
        after = os.fstat(descriptor)
        _require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns), code + "_RACY")
        raw = b"".join(chunks)
    except ChronologyError:
        raise
    except OSError as exc:
        raise ChronologyError(code + "_NOFOLLOW") from exc
    finally:
        for descriptor in reversed(opened):
            try: os.close(descriptor)
            except OSError: pass
    _require(hashlib.sha256(raw).hexdigest() == expected_sha, code + "_SHA")
    return raw


def _read_fixed_validator_source() -> tuple[bytes, str]:
    """Read exactly the pinned validator bytes without unbounded allocation."""
    relative = "shared/job_runtime/candidates/r6_human_grader_registry_v1/registry.py"
    raw = _read_fixed_bytes(FIXED_WORKSPACE_ROOT, relative, 14782, "63d2eaff7f331cb7227337e19e0eb0aa7cd9ed5a7021e7f8064f28ec1c78f431", "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    return raw, str(FIXED_WORKSPACE_ROOT / relative)

def _load_fixed_human_validator():
    """Compile and execute only the nofollow-read pinned bytes in a private namespace."""
    raw, expected_path = _read_fixed_validator_source()
    module_name = "_r6_data_quality_fixed_human_validator_v6"
    module = types.ModuleType(module_name)
    module.__file__ = expected_path
    module.__package__ = ""
    code = compile(raw, expected_path, "exec", dont_inherit=True)
    exec(code, module.__dict__, module.__dict__)
    validator = module.__dict__.get("validate_registry_attestations")
    contract_error = module.__dict__.get("ContractError")
    _require(isinstance(validator, types.FunctionType), "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    _require(isinstance(contract_error, type) and issubclass(contract_error, ValueError), "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    _require(validator.__globals__ is module.__dict__, "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    _require(validator.__module__ == module_name, "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    _require(validator.__code__.co_filename == expected_path, "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    return module


def _human_pin_names(g3_required: bool) -> Tuple[str, ...]:
    base = ("REGISTRY", "REGISTRY_REVIEW", "G1", "G1_REVIEW", "G2", "G2_REVIEW")
    return base + (("G3", "G3_REVIEW") if g3_required else ())


def _validate_human_report(report: Mapping[str, Any], g3_required: bool) -> None:
    expected_roles = ["G1", "G2"] + (["G3"] if g3_required else [])
    _require(isinstance(report, Mapping), "HUMAN_VALIDATION_REPORT_TYPE")
    _require(report.get("decision") == "VALIDATED_FOR_SEPARATE_EXPLICIT_PINNING_NOT_LIVE", "HUMAN_VALIDATION_REJECTED")
    _require(report.get("g3_triggered") is g3_required, "HUMAN_VALIDATION_G3_MISMATCH")
    _require(report.get("validated_roles") == expected_roles, "HUMAN_VALIDATION_ROLES_MISMATCH")
    _require(report.get("activation") is False and report.get("countable") is False, "HUMAN_VALIDATION_POLICY")


def _validate_human_pins(registry: Any, g3_required: bool) -> None:
    required = {HUMAN_PATHS[x] for x in _human_pin_names(g3_required)}
    _require(set(AUTHENTIC_HUMAN_PINS) == required, "AUTHENTIC_HUMAN_PINS_ABSENT")
    for path in sorted(required):
        pin = AUTHENTIC_HUMAN_PINS[path]
        _validate_ref(pin, path, "AUTHENTIC_HUMAN_PIN")
        _, digest, length = registry._secure_read(FIXED_WORKSPACE_ROOT, path, 0o600, "V6_HUMAN_PIN")
        _require(digest == pin["sha256"] and length == pin["bytes"], "AUTHENTIC_HUMAN_PIN_MISMATCH")


def _verify_pinned_sources() -> None:
    for relative, expected_bytes, expected_sha in PINNED_SOURCES:
        _read_fixed_bytes(FIXED_WORKSPACE_ROOT, relative, expected_bytes, expected_sha, "PINNED_SOURCE")


def _ref(path: str, raw: bytes) -> Dict[str, Any]:
    return {"path": path, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "mode": "0600"}


def _value_ref(path: str, value: Mapping[str, Any]) -> Dict[str, Any]:
    return _ref(path, transaction.canonical_bytes(value))


def _validate_ref(value: Mapping[str, Any], expected_path: str, code: str) -> None:
    _require(isinstance(value, Mapping) and set(value) == {"path", "bytes", "sha256", "mode"}, code + "_FIELDS")
    _require(value["path"] == expected_path, code + "_PATH")
    _require(isinstance(value["bytes"], int) and value["bytes"] > 0, code + "_BYTES")
    _require(isinstance(value["sha256"], str) and SHA_RE.fullmatch(value["sha256"]) is not None, code + "_SHA")
    _require(value["mode"] == "0600", code + "_MODE")


def _validate_binding(value: Mapping[str, Any]) -> None:
    required = {"transaction_id", "receipt_ref", "commitment_ref", "canonical_digest", "canonical_bytes"}
    _require(isinstance(value, Mapping) and set(value) == required, "BINDING_FIELDS")
    _require(isinstance(value["transaction_id"], str) and re.fullmatch(r"[0-9a-f]{32}", value["transaction_id"]) is not None, "BINDING_TX")
    _validate_ref(value["receipt_ref"], transaction.RECEIPT_NAME, "BINDING_RECEIPT")
    _validate_ref(value["commitment_ref"], transaction.COMMITMENT_NAME, "BINDING_COMMITMENT")
    _require(isinstance(value["canonical_digest"], str) and SHA_RE.fullmatch(value["canonical_digest"]) is not None, "BINDING_DIGEST")
    _require(isinstance(value["canonical_bytes"], int) and value["canonical_bytes"] > 0, "BINDING_BYTES")


def _closed(value: Any, fields: Sequence[str], code: str) -> Mapping[str, Any]:
    _require(isinstance(value, Mapping), code + "_TYPE")
    _require(set(value) == set(fields), code + "_FIELDS")
    return value


def _nonempty(value: Any, code: str) -> str:
    _require(isinstance(value, str) and bool(value.strip()), code)
    return value


def _validate_grant(value: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "block_id", "commitment_binding", "human_authority_refs", "cell_ids", "issued_sequence", "one_attempt_per_cell", "immutable")
    _closed(value, fields, "GRANT")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-block-grant-v6", "GRANT_VERSION")
    _require(re.fullmatch(r"R6DQ-BLOCK-[A-Z0-9-]{8,64}", _nonempty(value["block_id"], "GRANT_ID")) is not None, "GRANT_ID")
    _validate_binding(value["commitment_binding"])
    expected_paths = [HUMAN_PATHS[x] for x in ("REGISTRY", "REGISTRY_REVIEW", "G1", "G1_REVIEW", "G2", "G2_REVIEW")]
    refs = value["human_authority_refs"]
    _require(isinstance(refs, list) and len(refs) == 6, "GRANT_HUMAN_REFS")
    for ref, path in zip(refs, expected_paths):
        _validate_ref(ref, path, "GRANT_HUMAN_REF")
    _require(value["cell_ids"] == list(CELL_IDS) and len(set(value["cell_ids"])) == 4, "GRANT_CELLS")
    _require(value["issued_sequence"] == GRANT_SEQUENCE, "GRANT_SEQUENCE")
    _require(value["one_attempt_per_cell"] is True and value["immutable"] is True, "GRANT_POLICY")


def _validate_grant_review(value: Mapping[str, Any], grant: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "review_id", "block_grant_ref", "status", "independent_reviewer_id", "reviewed_sequence", "immutable")
    _closed(value, fields, "GRANT_REVIEW")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-block-grant-review-v6", "GRANT_REVIEW_VERSION")
    _nonempty(value["review_id"], "GRANT_REVIEW_ID")
    _validate_ref(value["block_grant_ref"], BLOCK_GRANT_PATH, "GRANT_REVIEW_REF")
    _require(value["block_grant_ref"] == _value_ref(BLOCK_GRANT_PATH, grant), "GRANT_REVIEW_EXACT_REF")
    _require(value["status"] == "CLEAN" and re.fullmatch(r"HGRV-[0-9A-F]{4,16}", _nonempty(value["independent_reviewer_id"], "GRANT_REVIEWER")) is not None, "GRANT_REVIEW_STATUS")
    _require(value["reviewed_sequence"] == GRANT_REVIEW_SEQUENCE, "GRANT_REVIEW_SEQUENCE")
    _require(value["immutable"] is True, "GRANT_REVIEW_IMMUTABLE")


def _validate_attempt(value: Mapping[str, Any], cell: str, grant: Mapping[str, Any], review: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "attempt_id", "cell_id", "blind_alias", "block_grant_ref", "block_grant_review_ref", "commitment_binding", "provider_request_ref", "provider_result_ref", "admitted_sequence", "result_sequence", "attempt_number", "immutable")
    _closed(value, fields, "ATTEMPT")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-attempt-receipt-v6", "ATTEMPT_VERSION")
    _nonempty(value["attempt_id"], "ATTEMPT_ID")
    _require(value["cell_id"] == cell and isinstance(value["blind_alias"], str) and LABEL_RE.fullmatch(value["blind_alias"]) is not None, "ATTEMPT_CELL_ALIAS")
    _validate_ref(value["block_grant_ref"], BLOCK_GRANT_PATH, "ATTEMPT_GRANT")
    _validate_ref(value["block_grant_review_ref"], BLOCK_GRANT_REVIEW_PATH, "ATTEMPT_GRANT_REVIEW")
    _require(value["block_grant_ref"] == _value_ref(BLOCK_GRANT_PATH, grant), "ATTEMPT_EXACT_GRANT_REF")
    _require(value["block_grant_review_ref"] == _value_ref(BLOCK_GRANT_REVIEW_PATH, review), "ATTEMPT_EXACT_REVIEW_REF")
    _require(value["commitment_binding"] == grant["commitment_binding"], "ATTEMPT_COMMITMENT")
    _validate_ref(value["provider_request_ref"], REQUEST_PATHS[cell], "ATTEMPT_REQUEST")
    _validate_ref(value["provider_result_ref"], RESULT_PATHS[cell], "ATTEMPT_RESULT")
    _require((value["admitted_sequence"], value["result_sequence"]) == ATTEMPT_SEQUENCES[cell], "ATTEMPT_EXACT_SEQUENCE")
    _require(value["attempt_number"] == 1 and value["immutable"] is True, "ATTEMPT_POLICY")


def _validate_packet(value: Mapping[str, Any], cell: str, attempt: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "packet_record_id", "cell_id", "blind_alias", "attempt_receipt_ref", "evaluation_packet_ref", "produced_sequence", "immutable")
    _closed(value, fields, "PACKET")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-evaluation-packet-record-v6", "PACKET_VERSION")
    _nonempty(value["packet_record_id"], "PACKET_ID")
    _require(value["cell_id"] == cell and value["blind_alias"] == attempt["blind_alias"], "PACKET_CELL_ALIAS")
    _validate_ref(value["attempt_receipt_ref"], ATTEMPT_PATHS[cell], "PACKET_ATTEMPT")
    _require(value["attempt_receipt_ref"] == _value_ref(ATTEMPT_PATHS[cell], attempt), "PACKET_EXACT_ATTEMPT_REF")
    _validate_ref(value["evaluation_packet_ref"], EVALUATION_ARTIFACT_PATHS[cell], "PACKET_ARTIFACT")
    _require(value["produced_sequence"] == PACKET_SEQUENCES[cell], "PACKET_EXACT_SEQUENCE")
    _require(value["immutable"] is True, "PACKET_IMMUTABLE")


def _validate_grade(value: Mapping[str, Any], cell: str, role: str, packet: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "grade_record_id", "cell_id", "blind_alias", "grader_role", "packet_record_ref", "human_grant_ref", "human_grant_review_ref", "grade_artifact_ref", "produced_sequence", "immutable")
    _closed(value, fields, "GRADE")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-human-grade-record-v6", "GRADE_VERSION")
    _nonempty(value["grade_record_id"], "GRADE_ID")
    _require(value["cell_id"] == cell and value["blind_alias"] == packet["blind_alias"] and value["grader_role"] == role, "GRADE_CELL_ALIAS_ROLE")
    _validate_ref(value["packet_record_ref"], PACKET_PATHS[cell], "GRADE_PACKET")
    _require(value["packet_record_ref"] == _value_ref(PACKET_PATHS[cell], packet), "GRADE_EXACT_PACKET_REF")
    _validate_ref(value["human_grant_ref"], HUMAN_PATHS[role], "GRADE_HUMAN_GRANT")
    _validate_ref(value["human_grant_review_ref"], HUMAN_PATHS[role + "_REVIEW"], "GRADE_HUMAN_REVIEW")
    _validate_ref(value["grade_artifact_ref"], GRADE_ARTIFACT_PATHS[(cell, role)], "GRADE_ARTIFACT")
    _require(value["produced_sequence"] == GRADE_SEQUENCES[(cell, role)], "GRADE_EXACT_SEQUENCE")
    _require(value["immutable"] is True, "GRADE_IMMUTABLE")


def _validate_metrics(value: Mapping[str, Any], binding: Mapping[str, Any], packets: Mapping[str, Mapping[str, Any]], grades: Mapping[Tuple[str, str], Mapping[str, Any]]) -> None:
    fields = ("version", "schema", "metrics_record_id", "commitment_binding", "g3_required", "cells", "derived_metric_ref", "produced_sequence", "immutable")
    _closed(value, fields, "METRICS")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-derived-metrics-record-v6", "METRICS_VERSION")
    _nonempty(value["metrics_record_id"], "METRICS_ID")
    _require(value["commitment_binding"] == binding and isinstance(value["g3_required"], bool), "METRICS_BINDING")
    cells = value["cells"]
    _require(isinstance(cells, list) and len(cells) == 4, "METRICS_CELLS")
    max_grade_sequence = 0
    for expected_cell, item in zip(CELL_IDS, cells):
        _closed(item, ("cell_id", "blind_alias", "packet_record_ref", "grade_record_refs"), "METRICS_CELL")
        _require(item["cell_id"] == expected_cell and item["blind_alias"] == packets[expected_cell]["blind_alias"], "METRICS_CELL_ID")
        _validate_ref(item["packet_record_ref"], PACKET_PATHS[expected_cell], "METRICS_PACKET")
        _require(item["packet_record_ref"] == _value_ref(PACKET_PATHS[expected_cell], packets[expected_cell]), "METRICS_EXACT_PACKET_REF")
        expected_roles = ("G1", "G2", "G3") if value["g3_required"] else ("G1", "G2")
        refs = item["grade_record_refs"]
        _require(isinstance(refs, list) and len(refs) == len(expected_roles), "METRICS_GRADE_CARDINALITY")
        for ref, role in zip(refs, expected_roles):
            _validate_ref(ref, GRADE_PATHS[(expected_cell, role)], "METRICS_GRADE")
            _require(ref == _value_ref(GRADE_PATHS[(expected_cell, role)], grades[(expected_cell, role)]), "METRICS_EXACT_GRADE_REF")
            max_grade_sequence = max(max_grade_sequence, grades[(expected_cell, role)]["produced_sequence"])
        _require({ref["path"] for ref in refs} == {GRADE_PATHS[(expected_cell, role)] for role in expected_roles}, "METRICS_GRADE_PATH_SET")
    _validate_ref(value["derived_metric_ref"], DERIVED_METRIC_ARTIFACT_PATH, "METRICS_ARTIFACT")
    _require(value["produced_sequence"] == METRICS_SEQUENCES[value["g3_required"]], "METRICS_EXACT_SEQUENCE")
    _require(max_grade_sequence < value["produced_sequence"], "METRICS_GLOBAL_BARRIER")
    _require(value["immutable"] is True, "METRICS_IMMUTABLE")


def _validate_external_artifacts(attempts: Mapping[str, Mapping[str, Any]], packets: Mapping[str, Mapping[str, Any]], grades: Mapping[Tuple[str, str], Mapping[str, Any]], metrics: Mapping[str, Any], artifacts: Mapping[str, Mapping[str, Any]]) -> None:
    _require(set(artifacts) == _external_artifact_paths(metrics["g3_required"]), "EXTERNAL_ARTIFACT_PATH_SET")
    for path, value in artifacts.items():
        _closed(value, ("version", "artifact_id", "payload_sha256", "immutable"), "EXTERNAL_ARTIFACT")
        _require(value["version"] == 6 and bool(_nonempty(value["artifact_id"], "EXTERNAL_ARTIFACT_ID")), "EXTERNAL_ARTIFACT_VERSION")
        _require(isinstance(value["payload_sha256"], str) and SHA_RE.fullmatch(value["payload_sha256"]) is not None and value["immutable"] is True, "EXTERNAL_ARTIFACT_VALUE")
    for cell in CELL_IDS:
        _require(attempts[cell]["provider_request_ref"] == _value_ref(REQUEST_PATHS[cell], artifacts[REQUEST_PATHS[cell]]), "EXACT_PROVIDER_REQUEST_REF")
        _require(attempts[cell]["provider_result_ref"] == _value_ref(RESULT_PATHS[cell], artifacts[RESULT_PATHS[cell]]), "EXACT_PROVIDER_RESULT_REF")
        _require(packets[cell]["evaluation_packet_ref"] == _value_ref(EVALUATION_ARTIFACT_PATHS[cell], artifacts[EVALUATION_ARTIFACT_PATHS[cell]]), "EXACT_EVALUATION_ARTIFACT_REF")
    for key, grade in grades.items():
        _require(grade["grade_artifact_ref"] == _value_ref(GRADE_ARTIFACT_PATHS[key], artifacts[GRADE_ARTIFACT_PATHS[key]]), "EXACT_GRADE_ARTIFACT_REF")
    _require(metrics["derived_metric_ref"] == _value_ref(DERIVED_METRIC_ARTIFACT_PATH, artifacts[DERIVED_METRIC_ARTIFACT_PATH]), "EXACT_DERIVED_METRIC_REF")


def _validate_manifest(value: Mapping[str, Any], binding: Mapping[str, Any], grant: Mapping[str, Any], review: Mapping[str, Any], attempts: Mapping[str, Mapping[str, Any]], packets: Mapping[str, Mapping[str, Any]], grades: Mapping[Tuple[str, str], Mapping[str, Any]], metrics: Mapping[str, Any]) -> None:
    fields = ("version", "schema", "chain_id", "commitment_binding", "block_grant_ref", "block_grant_review_ref", "attempt_receipt_refs", "evaluation_packet_record_refs", "human_grade_record_refs", "g3_required", "derived_metrics_record_ref", "final_sequence", "immutable")
    _closed(value, fields, "MANIFEST")
    _require(value["version"] == 6 and value["schema"] == "r6-data-quality-blind-map-chronology-manifest-v6", "MANIFEST_VERSION")
    _nonempty(value["chain_id"], "MANIFEST_ID")
    _require(value["commitment_binding"] == binding, "MANIFEST_BINDING")
    _require(isinstance(value["g3_required"], bool) and value["g3_required"] is metrics["g3_required"], "MANIFEST_G3_REQUIRED")
    _validate_ref(value["block_grant_ref"], BLOCK_GRANT_PATH, "MANIFEST_GRANT")
    _validate_ref(value["block_grant_review_ref"], BLOCK_GRANT_REVIEW_PATH, "MANIFEST_GRANT_REVIEW")
    _require(value["block_grant_ref"] == _value_ref(BLOCK_GRANT_PATH, grant), "MANIFEST_EXACT_GRANT_REF")
    _require(value["block_grant_review_ref"] == _value_ref(BLOCK_GRANT_REVIEW_PATH, review), "MANIFEST_EXACT_REVIEW_REF")
    for key, expected_paths in (("attempt_receipt_refs", [ATTEMPT_PATHS[c] for c in CELL_IDS]), ("evaluation_packet_record_refs", [PACKET_PATHS[c] for c in CELL_IDS])):
        refs = value[key]
        _require(isinstance(refs, list) and len(refs) == 4, "MANIFEST_CARDINALITY")
        for ref, path in zip(refs, expected_paths):
            _validate_ref(ref, path, "MANIFEST_REF")
            actual = attempts[next(cell for cell in CELL_IDS if ATTEMPT_PATHS[cell] == path)] if key == "attempt_receipt_refs" else packets[next(cell for cell in CELL_IDS if PACKET_PATHS[cell] == path)]
            _require(ref == _value_ref(path, actual), "MANIFEST_EXACT_REF")
    expected_roles = ("G1", "G2", "G3") if metrics["g3_required"] else ("G1", "G2")
    expected_grades = [GRADE_PATHS[(cell, role)] for role in expected_roles for cell in CELL_IDS]
    refs = value["human_grade_record_refs"]
    _require(isinstance(refs, list) and len(refs) == len(expected_grades), "MANIFEST_GRADE_CARDINALITY")
    for ref, path in zip(refs, expected_grades):
        _validate_ref(ref, path, "MANIFEST_GRADE_REF")
        key = next(key for key, candidate in GRADE_PATHS.items() if candidate == path)
        _require(ref == _value_ref(path, grades[key]), "MANIFEST_EXACT_GRADE_REF")
    _require({ref["path"] for ref in refs} == set(expected_grades), "MANIFEST_GRADE_PATH_SET")
    _validate_ref(value["derived_metrics_record_ref"], METRICS_PATH, "MANIFEST_METRICS")
    _require(value["derived_metrics_record_ref"] == _value_ref(METRICS_PATH, metrics), "MANIFEST_EXACT_METRICS_REF")
    _require(value["final_sequence"] == MANIFEST_SEQUENCES[metrics["g3_required"]], "MANIFEST_EXACT_SEQUENCE")
    _require(metrics["produced_sequence"] < value["final_sequence"], "MANIFEST_GLOBAL_BARRIER")
    _require(value["immutable"] is True, "MANIFEST_IMMUTABLE")


def validate_chain_values(values: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate the complete exact chronology without opening or returning a map."""
    base = {BLOCK_GRANT_PATH, BLOCK_GRANT_REVIEW_PATH, METRICS_PATH, MANIFEST_PATH, *ATTEMPT_PATHS.values(), *PACKET_PATHS.values(), *[GRADE_PATHS[(cell, role)] for cell in CELL_IDS for role in ("G1", "G2")]}
    g3_required = values.get(MANIFEST_PATH, {}).get("g3_required")
    _require(isinstance(g3_required, bool), "CHAIN_MANIFEST_G3_REQUIRED")
    expected = base | ({GRADE_PATHS[(cell, "G3")] for cell in CELL_IDS} if g3_required else set())
    _require(set(values) == expected, "CHAIN_PATH_SET")
    grant = values[BLOCK_GRANT_PATH]
    review = values[BLOCK_GRANT_REVIEW_PATH]
    _validate_grant(grant)
    _validate_grant_review(review, grant)
    attempts = {}
    aliases = []
    for cell in CELL_IDS:
        attempt = values[ATTEMPT_PATHS[cell]]
        _validate_attempt(attempt, cell, grant, review)
        _require(attempt["blind_alias"] not in aliases, "CHAIN_ALIAS_DUPLICATE")
        aliases.append(attempt["blind_alias"])
        attempts[cell] = attempt
    _require(review["reviewed_sequence"] < min(attempt["admitted_sequence"] for attempt in attempts.values()), "GLOBAL_REVIEW_ATTEMPT_BARRIER")
    _require({attempt["admitted_sequence"] for attempt in attempts.values()} == {slot[0] for slot in ATTEMPT_SEQUENCES.values()}, "GLOBAL_ATTEMPT_ADMISSION_SET")
    _require({attempt["result_sequence"] for attempt in attempts.values()} == {slot[1] for slot in ATTEMPT_SEQUENCES.values()}, "GLOBAL_ATTEMPT_RESULT_SET")
    packets = {}
    for cell in CELL_IDS:
        packet = values[PACKET_PATHS[cell]]
        _validate_packet(packet, cell, attempts[cell])
        packets[cell] = packet
    _require(max(attempt["result_sequence"] for attempt in attempts.values()) < min(packet["produced_sequence"] for packet in packets.values()), "GLOBAL_ATTEMPT_PACKET_BARRIER")
    _require({packet["produced_sequence"] for packet in packets.values()} == set(PACKET_SEQUENCES.values()), "GLOBAL_PACKET_SEQUENCE_SET")
    metrics = values[METRICS_PATH]
    roles = ("G1", "G2", "G3") if g3_required else ("G1", "G2")
    grades = {}
    for role in roles:
        for cell in CELL_IDS:
            grade = values[GRADE_PATHS[(cell, role)]]
            _validate_grade(grade, cell, role, packets[cell])
            grades[(cell, role)] = grade
    _require(max(packet["produced_sequence"] for packet in packets.values()) < min(grade["produced_sequence"] for grade in grades.values()), "GLOBAL_PACKET_GRADE_BARRIER")
    _require({grade["produced_sequence"] for grade in grades.values()} == {GRADE_SEQUENCES[(cell, role)] for role in roles for cell in CELL_IDS}, "GLOBAL_GRADE_SEQUENCE_SET")
    _validate_metrics(metrics, grant["commitment_binding"], packets, grades)
    _require(max(grade["produced_sequence"] for grade in grades.values()) < metrics["produced_sequence"], "GLOBAL_GRADE_METRICS_BARRIER")
    manifest = values[MANIFEST_PATH]
    _validate_manifest(manifest, grant["commitment_binding"], grant, review, attempts, packets, grades, metrics)
    _require(metrics["produced_sequence"] < manifest["final_sequence"], "GLOBAL_METRICS_MANIFEST_BARRIER")
    return {"version": 6, "status": "VALID_CHAIN_VALUES_NOT_AUTHORITY", "activation": False, "countable": False}


CHAIN_SCHEMA_MAX_BYTES = {
    "grant": 262144,
    "review": 131072,
    "attempt": 262144,
    "packet": 131072,
    "grade": 262144,
    "metrics": 524288,
    "manifest": 524288,
    "external": 1048576,
}


def _chain_schema_max(path: str) -> int:
    if path == BLOCK_GRANT_PATH: return CHAIN_SCHEMA_MAX_BYTES["grant"]
    if path == BLOCK_GRANT_REVIEW_PATH: return CHAIN_SCHEMA_MAX_BYTES["review"]
    if path == METRICS_PATH: return CHAIN_SCHEMA_MAX_BYTES["metrics"]
    if path == MANIFEST_PATH: return CHAIN_SCHEMA_MAX_BYTES["manifest"]
    if path in ATTEMPT_PATHS.values(): return CHAIN_SCHEMA_MAX_BYTES["attempt"]
    if path in PACKET_PATHS.values(): return CHAIN_SCHEMA_MAX_BYTES["packet"]
    if path in GRADE_PATHS.values(): return CHAIN_SCHEMA_MAX_BYTES["grade"]
    if path in EXTERNAL_ARTIFACT_PATHS: return CHAIN_SCHEMA_MAX_BYTES["external"]
    raise ChronologyError("CHAIN_PATH_NOT_FIXED")


class _FixedArtifactStore:
    """No-argument bounded reader for exact source-pinned v6 chronology."""
    def __init__(self) -> None:
        self.root = transaction._root_path()
        status = os.lstat(self.root)
        _require(stat.S_ISDIR(status.st_mode) and not stat.S_ISLNK(status.st_mode), "CHAIN_ROOT")
        _require(status.st_uid == os.getuid() and stat.S_IMODE(status.st_mode) == 0o700, "CHAIN_ROOT_OWNER_MODE")

    def read(self, path: str) -> Mapping[str, Any]:
        _require(path in AUTHENTIC_CHAIN_PINS, "CHAIN_PIN_ABSENT")
        pin = AUTHENTIC_CHAIN_PINS[path]; _validate_ref(pin, path, "CHAIN_PIN")
        maximum = _chain_schema_max(path)
        _require(pin["bytes"] <= maximum, "CHAIN_SCHEMA_MAX_BYTES")
        parts = path.split("/")
        _require(all(part not in ("", ".", "..") for part in parts) and "\\" not in path, "CHAIN_PATH")
        opened = []
        try:
            fd = os.open(str(self.root), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)); opened.append(fd)
            for part in parts[:-1]:
                fd = os.open(part, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd); opened.append(fd)
                st = os.fstat(fd); _require(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700, "CHAIN_PARENT")
            fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd); opened.append(fd)
            before = os.fstat(fd)
            _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600, "CHAIN_FILE")
            _require(before.st_size == pin["bytes"] and before.st_size <= maximum, "CHAIN_SCHEMA_MAX_BYTES")
            remaining = before.st_size; chunks = []
            while remaining:
                chunk = os.read(fd, min(65536, remaining)); _require(bool(chunk), "CHAIN_TRUNCATED")
                chunks.append(chunk); remaining -= len(chunk)
            _require(os.read(fd, 1) == b"", "CHAIN_GREW")
            after = os.fstat(fd)
            named = os.stat(parts[-1], dir_fd=opened[-2], follow_symlinks=False)
            _require((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) == (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns), "CHAIN_RACY")
            _require((named.st_dev, named.st_ino) == (before.st_dev, before.st_ino), "CHAIN_RACY")
            raw = b"".join(chunks)
        except ChronologyError:
            raise
        except OSError as exc:
            raise ChronologyError("CHAIN_NOFOLLOW") from exc
        finally:
            for fd in reversed(opened):
                try: os.close(fd)
                except OSError: pass
        _require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "CHAIN_PIN_MISMATCH")
        try: value = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ChronologyError("CHAIN_JSON") from exc
        _require(transaction.canonical_bytes(value) == raw, "CHAIN_NOT_CANONICAL")
        return value

def _deny(reason: str) -> Dict[str, Any]:
    return {"version": 6, "decision": "DENY_BEFORE_PRIVATE_MAP_READ", "reason": reason, "activation": False, "countable": False, "private_map_read": False, "effects": dict(ZERO_EFFECTS)}


def authorize_opening() -> Dict[str, Any]:
    """Authenticate the full fixed chain and current transaction before map read."""
    _verify_pinned_sources()
    if MANIFEST_PATH not in AUTHENTIC_CHAIN_PINS:
        return _deny("AUTHENTIC_MANIFEST_PIN_ABSENT")
    try:
        store = _FixedArtifactStore(); manifest = store.read(MANIFEST_PATH)
    except (ChronologyError, OSError):
        return _deny("AUTHENTIC_MANIFEST_ABSENT_OR_INVALID")
    g3_required = manifest.get("g3_required")
    if not isinstance(g3_required, bool):
        return _deny("AUTHENTIC_MANIFEST_G3_REQUIRED_INVALID")
    base_records = {BLOCK_GRANT_PATH, BLOCK_GRANT_REVIEW_PATH, METRICS_PATH, MANIFEST_PATH, *ATTEMPT_PATHS.values(), *PACKET_PATHS.values(), *[GRADE_PATHS[(cell, role)] for cell in CELL_IDS for role in ("G1", "G2")]}
    required_records = base_records | ({GRADE_PATHS[(cell, "G3")] for cell in CELL_IDS} if g3_required else set())
    external_paths = _external_artifact_paths(g3_required)
    if set(AUTHENTIC_CHAIN_PINS) != required_records | external_paths:
        return _deny("AUTHENTIC_CHAIN_PINS_ABSENT")
    try: registry = _load_fixed_human_validator()
    except (ChronologyError, OSError): return _deny("FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
    try:
        report = registry.validate_registry_attestations(FIXED_WORKSPACE_ROOT, g3_triggered=g3_required)
        _validate_human_report(report, g3_required); _validate_human_pins(registry, g3_required)
    except (ChronologyError, registry.ContractError):
        return _deny("AUTHENTIC_HUMAN_AUTHORITY_ABSENT_OR_PENDING")
    loaded = {MANIFEST_PATH: manifest}
    try:
        for path in sorted(set(AUTHENTIC_CHAIN_PINS) - {MANIFEST_PATH}): loaded[path] = store.read(path)
        records = {path: loaded[path] for path in loaded if path not in external_paths}
        artifacts = {path: loaded[path] for path in external_paths}
        validate_chain_values(records)
        _require(records[MANIFEST_PATH]["g3_required"] is g3_required, "CHAIN_G3_REQUIRED_MISMATCH")
        grant = records[BLOCK_GRANT_PATH]
        base_pin_names = ("REGISTRY", "REGISTRY_REVIEW", "G1", "G1_REVIEW", "G2", "G2_REVIEW")
        _require(grant["human_authority_refs"] == [AUTHENTIC_HUMAN_PINS[HUMAN_PATHS[x]] for x in base_pin_names], "CHAIN_EXACT_HUMAN_PINS")
        attempts = {cell: records[ATTEMPT_PATHS[cell]] for cell in CELL_IDS}
        packets = {cell: records[PACKET_PATHS[cell]] for cell in CELL_IDS}
        roles = ("G1", "G2", "G3") if g3_required else ("G1", "G2")
        grades = {(cell, role): records[GRADE_PATHS[(cell, role)]] for cell in CELL_IDS for role in roles}
        for (_, role), grade in grades.items():
            _require(grade["human_grant_ref"] == AUTHENTIC_HUMAN_PINS[HUMAN_PATHS[role]], "GRADE_EXACT_HUMAN_GRANT_PIN")
            _require(grade["human_grant_review_ref"] == AUTHENTIC_HUMAN_PINS[HUMAN_PATHS[role + "_REVIEW"]], "GRADE_EXACT_HUMAN_REVIEW_PIN")
        _validate_external_artifacts(attempts, packets, grades, records[METRICS_PATH], artifacts)
    except ChronologyError:
        return _deny("AUTHENTIC_CHAIN_INVALID")
    # This public-only read and exact comparison must complete before any map read.
    try:
        _, _, _, current_binding = transaction._read_complete_pair(read_map=False)
        if grant["commitment_binding"] != current_binding:
            return _deny("CHAIN_TRANSACTION_BINDING")
        _, _, private_map, binding = transaction._read_complete_pair(read_map=True, expected_binding=grant["commitment_binding"])
    except transaction.CommitmentError:
        return _deny("CURRENT_TRANSACTION_ABSENT_OR_MISMATCH")
    _require(private_map is not None and binding == grant["commitment_binding"], "PRIVATE_MAP_BINDING")
    aliases = dict(zip(private_map["cell_order"], private_map["labels"]))
    for cell in CELL_IDS: _require(records[ATTEMPT_PATHS[cell]]["blind_alias"] == aliases[cell], "CHAIN_MAP_ALIAS")
    return {"version": 6, "decision": "FIXED_CHAIN_VALIDATED_STILL_DISABLED", "activation": False, "countable": False, "private_map_read": True, "effects": dict(ZERO_EFFECTS)}

MAX_LEAK_SCAN_FILE_BYTES = 10_000_000
_SCAN_EXCLUDED_DIRS = frozenset((".git", "__pycache__", ".pytest_cache", ".mypy_cache"))


def _scan_category(parts: Tuple[str, ...]) -> str:
    if parts and parts[0] in ("shared", "investment", "mentor", "docs", "ui", "factor"): return "source"
    if parts and parts[0] == "tuning": return "architecture"
    if (parts and parts[0] == "runtime") or any("log" in part.lower() for part in parts): return "logs"
    return "other"


def scan_label_leaks() -> Dict[str, Any]:
    """Fail closed on every unreadable, oversized, symlinked, or racy file."""
    _, _, private_map, _ = transaction._read_complete_pair(read_map=True)
    _require(private_map is not None, "LEAK_SCAN_MAP")
    labels = tuple(label.encode("ascii") for label in private_map["labels"])
    categories = {key: 0 for key in ("source", "architecture", "logs", "other")}
    scanned = {key: 0 for key in categories}
    errors = {key: 0 for key in ("symlink", "unreadable", "oversize", "racy", "special")}
    excluded_private = 0; excluded_dirs = 0
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)

    def walk(directory_fd: int, parts: Tuple[str, ...]) -> None:
        nonlocal excluded_private, excluded_dirs
        try: names = sorted(os.listdir(directory_fd))
        except OSError: errors["unreadable"] += 1; return
        for name in names:
            child_parts = parts + (name,)
            if name in _SCAN_EXCLUDED_DIRS:
                excluded_dirs += 1; continue
            try: before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError: errors["unreadable"] += 1; continue
            if stat.S_ISLNK(before.st_mode):
                errors["symlink"] += 1; continue
            if stat.S_ISDIR(before.st_mode):
                child_fd = -1
                try:
                    child_fd = os.open(name, flags_dir, dir_fd=directory_fd)
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino): errors["racy"] += 1; continue
                    walk(child_fd, child_parts)
                except OSError: errors["unreadable"] += 1
                finally:
                    if child_fd >= 0: os.close(child_fd)
                continue
            if not stat.S_ISREG(before.st_mode):
                errors["special"] += 1; continue
            if "owner-private-canonical-map-" in name:
                excluded_private += 1; continue
            if before.st_size > MAX_LEAK_SCAN_FILE_BYTES:
                errors["oversize"] += 1; continue
            fd = -1
            try:
                fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
                opened = os.fstat(fd)
                if (opened.st_dev, opened.st_ino, opened.st_size) != (before.st_dev, before.st_ino, before.st_size): errors["racy"] += 1; continue
                remaining = opened.st_size; chunks = []
                while remaining:
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk: errors["racy"] += 1; break
                    chunks.append(chunk); remaining -= len(chunk)
                else:
                    if os.read(fd, 1) != b"": errors["racy"] += 1; continue
                    after = os.fstat(fd)
                    named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino):
                        errors["racy"] += 1; continue
                    data = b"".join(chunks); category = _scan_category(child_parts); scanned[category] += 1
                    if any(label in data for label in labels): categories[category] += 1
            except OSError: errors["unreadable"] += 1
            finally:
                if fd >= 0: os.close(fd)

    root_fd = -1
    try:
        root_fd = os.open(str(WORKSPACE_ROOT), flags_dir); walk(root_fd, ())
    except OSError: errors["unreadable"] += 1
    finally:
        if root_fd >= 0: os.close(root_fd)
    error_count = sum(errors.values()); match_count = sum(categories.values())
    status = "ERROR" if error_count else ("FAIL" if match_count else "PASS")
    return {"version": 6, "decision": "DENY" if status != "PASS" else "CLEAN", "labels_checked": 4, "label_values_disclosed": False, "files_scanned_by_category": scanned, "matching_paths_by_category": categories, "total_matching_paths": match_count, "errors_by_kind": errors, "total_errors": error_count, "private_maps_excluded_without_read": excluded_private, "excluded_directory_roots": excluded_dirs, "status": status}

