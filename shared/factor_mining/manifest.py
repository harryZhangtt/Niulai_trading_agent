"""Immutable, content-addressed factor-mining RunManifest v1/v2 registry.

The mutable head is navigation only. Evidence identity is always the immutable
manifest SHA-256 returned by :func:`publish`. Version 1 remains frozen; version 2
adds structured, hash-bound performance observations.
"""
from contextlib import contextmanager
from datetime import date, datetime
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_MANIFEST_BYTES = 1024 * 1024
RUN_STATUSES = {"planned", "running", "succeeded", "failed", "timed_out", "cancelled"}
STAGE_STATUSES = {"pending", "running", "succeeded", "failed", "timed_out", "skipped"}
FACTOR_STATUSES = {"pending", "evaluated", "failed", "unavailable"}
GATE_STATUSES = {"pending", "pass", "fail", "inconclusive", "withheld"}
DIMENSIONS = {"implementation", "predictive", "economic", "publication"}
PROVENANCE = {
    ("reported_external", "unverified"),
    ("reproduced_local", "hash_bound"),
    ("synthetic_fixture", "fixture_only"),
}
BASE_KEYS = {"schema_version", "kind", "run_id", "revision",
             "previous_manifest_sha256", "created_at", "status", "provenance",
             "engine", "protocol_sha256", "dataset_snapshot_sha256", "stages",
             "artifacts", "factors", "gates", "failures", "resources", "limitations"}
MAX_SAFE_INTEGER = 2**53 - 1
PERFORMANCE_KINDS = {"standalone", "combination", "leave_one_out"}
PERFORMANCE_AVAILABILITY = {"available", "unavailable"}
RUN_TRANSITIONS = {
    "planned": {"running", "failed", "cancelled"},
    "running": {"running", "succeeded", "failed", "timed_out", "cancelled"},
}
STAGE_TRANSITIONS = {
    "pending": {"pending", "running", "failed", "skipped"},
    "running": {"running", "succeeded", "failed", "timed_out"},
}
FACTOR_TRANSITIONS = {"pending": FACTOR_STATUSES, "evaluated": {"evaluated"},
                      "failed": {"failed"}, "unavailable": {"unavailable"}}
GATE_TRANSITIONS = {"pending": GATE_STATUSES, "pass": {"pass"}, "fail": {"fail"},
                    "inconclusive": {"inconclusive"}, "withheld": {"withheld"}}


class ManifestError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ManifestError(code)


def _name(value, code="FACTOR_MANIFEST_ID_INVALID"):
    require(isinstance(value, str) and NAME.fullmatch(value), code)
    return value


def _sha(value, code="FACTOR_MANIFEST_SHA_INVALID", *, optional=False, length=64):
    if optional and value is None:
        return None
    pattern = SHA64 if length == 64 else SHA40
    require(isinstance(value, str) and pattern.fullmatch(value), code)
    return value


def _strict(value, keys, code):
    require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "FACTOR_MANIFEST_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ManifestError("FACTOR_MANIFEST_NONFINITE")


def loads_strict(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except ManifestError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise ManifestError("FACTOR_MANIFEST_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        raise ManifestError("FACTOR_MANIFEST_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _timestamp(value):
    require(isinstance(value, str) and value.endswith("Z"), "FACTOR_MANIFEST_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ManifestError("FACTOR_MANIFEST_TIME_INVALID") from None
    require(parsed.isoformat().endswith("+00:00"), "FACTOR_MANIFEST_TIME_INVALID")


def _relative_path(value):
    require(isinstance(value, str) and value and len(value) <= 512,
            "FACTOR_MANIFEST_ARTIFACT_PATH_INVALID")
    path = Path(value)
    require(path.parts and not path.is_absolute() and ".." not in path.parts and
            all(part not in {"", "."} for part in path.parts) and not value.startswith("~"),
            "FACTOR_MANIFEST_ARTIFACT_PATH_INVALID")
    return path


def _day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value),
            "FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ManifestError("FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID") from None


def _performance(records, factor_ids, artifacts, provenance):
    require(isinstance(records, list) and len(records) <= 256,
            "FACTOR_MANIFEST_PERFORMANCE_INVALID")
    record_ids = set()
    evaluation_hashes = {item["sha256"] for item in artifacts if item["kind"] == "evaluation"}
    for record in records:
        _strict(record, {"id", "subject", "availability", "reason_code", "metric_id",
                         "estimate_unit", "point_estimate", "uncertainty", "sample",
                         "period", "baseline_id", "evidence_sha256"},
                "FACTOR_MANIFEST_PERFORMANCE_SCHEMA")
        _name(record["id"], "FACTOR_MANIFEST_PERFORMANCE_ID_INVALID")
        require(record["id"] not in record_ids, "FACTOR_MANIFEST_PERFORMANCE_DUPLICATE")
        record_ids.add(record["id"])
        subject = _strict(record["subject"], {"kind", "factor_ids", "omitted_factor_id"},
                          "FACTOR_MANIFEST_PERFORMANCE_SUBJECT_SCHEMA")
        kind = subject["kind"]
        members = subject["factor_ids"]
        omitted = subject["omitted_factor_id"]
        require(isinstance(kind, str) and kind in PERFORMANCE_KINDS and
                isinstance(members, list) and len(members) <= 128 and
                all(isinstance(item, str) and NAME.fullmatch(item) and item in factor_ids
                    for item in members) and len(members) == len(set(members)),
                "FACTOR_MANIFEST_PERFORMANCE_SUBJECT_INVALID")
        if kind == "standalone":
            require(len(members) == 1 and omitted is None,
                    "FACTOR_MANIFEST_PERFORMANCE_SUBJECT_INVALID")
        elif kind == "combination":
            require(len(members) >= 2 and omitted is None,
                    "FACTOR_MANIFEST_PERFORMANCE_SUBJECT_INVALID")
        else:
            require(len(members) >= 1 and isinstance(omitted, str) and NAME.fullmatch(omitted) and
                    omitted in factor_ids and omitted not in members,
                    "FACTOR_MANIFEST_PERFORMANCE_SUBJECT_INVALID")
        availability = record["availability"]
        require(isinstance(availability, str) and availability in PERFORMANCE_AVAILABILITY,
                "FACTOR_MANIFEST_PERFORMANCE_AVAILABILITY_INVALID")
        for field in ("reason_code", "metric_id", "estimate_unit", "baseline_id"):
            value = record[field]
            require(value is None or isinstance(value, str) and NAME.fullmatch(value),
                    "FACTOR_MANIFEST_PERFORMANCE_FIELD_INVALID")
        _sha(record["evidence_sha256"], optional=True)
        if availability == "available":
            require(record["reason_code"] is None and record["metric_id"] is not None and
                    record["estimate_unit"] is not None and _finite(record["point_estimate"]) and
                    record["baseline_id"] is not None and record["evidence_sha256"] is not None,
                    "FACTOR_MANIFEST_PERFORMANCE_AVAILABLE_INVALID")
            uncertainty = _strict(record["uncertainty"], {"kind", "lower", "upper", "level"},
                                  "FACTOR_MANIFEST_PERFORMANCE_UNCERTAINTY_SCHEMA")
            _name(uncertainty["kind"], "FACTOR_MANIFEST_PERFORMANCE_UNCERTAINTY_INVALID")
            require(_finite(uncertainty["lower"]) and _finite(uncertainty["upper"]) and
                    uncertainty["lower"] <= uncertainty["upper"] and
                    (uncertainty["level"] is None or _finite(uncertainty["level"]) and
                     0 < uncertainty["level"] < 1),
                    "FACTOR_MANIFEST_PERFORMANCE_UNCERTAINTY_INVALID")
            sample = _strict(record["sample"], {"size", "unit"},
                             "FACTOR_MANIFEST_PERFORMANCE_SAMPLE_SCHEMA")
            require(type(sample["size"]) is int and 0 < sample["size"] <= MAX_SAFE_INTEGER,
                    "FACTOR_MANIFEST_PERFORMANCE_SAMPLE_INVALID")
            _name(sample["unit"], "FACTOR_MANIFEST_PERFORMANCE_SAMPLE_INVALID")
            period = _strict(record["period"], {"id", "start", "end"},
                             "FACTOR_MANIFEST_PERFORMANCE_PERIOD_SCHEMA")
            _name(period["id"], "FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID")
            require(_day(period["start"]) < _day(period["end"]),
                    "FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID")
            require(record["evidence_sha256"] in evaluation_hashes,
                    "FACTOR_MANIFEST_PERFORMANCE_EVIDENCE_INVALID")
            require(provenance["origin"] != "synthetic_fixture",
                    "FACTOR_MANIFEST_SYNTHETIC_PERFORMANCE_FORBIDDEN")
        else:
            require(record["reason_code"] is not None and record["point_estimate"] is None and
                    record["uncertainty"] is None and record["sample"] is None and
                    record["evidence_sha256"] is None and
                    (record["period"] is None or
                     isinstance(record["period"], dict) and
                     set(record["period"]) == {"id", "start", "end"}),
                    "FACTOR_MANIFEST_PERFORMANCE_UNAVAILABLE_INVALID")
            if record["period"] is not None:
                period = record["period"]
                _name(period["id"], "FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID")
                require(_day(period["start"]) < _day(period["end"]),
                        "FACTOR_MANIFEST_PERFORMANCE_PERIOD_INVALID")


def validate(manifest):
    require(isinstance(manifest, dict), "FACTOR_MANIFEST_SCHEMA")
    version = manifest.get("schema_version")
    require(type(version) is int and version in {1, 2}, "FACTOR_MANIFEST_VERSION")
    keys = BASE_KEYS if version == 1 else BASE_KEYS | {"performance"}
    _strict(manifest, keys, "FACTOR_MANIFEST_SCHEMA")
    require(manifest["kind"] == "factor_run_manifest", "FACTOR_MANIFEST_VERSION")
    _name(manifest["run_id"], "FACTOR_MANIFEST_RUN_ID_INVALID")
    require(type(manifest["revision"]) is int and manifest["revision"] > 0,
            "FACTOR_MANIFEST_REVISION_INVALID")
    _sha(manifest["previous_manifest_sha256"], optional=True)
    require((manifest["revision"] == 1) == (manifest["previous_manifest_sha256"] is None),
            "FACTOR_MANIFEST_PREVIOUS_INVALID")
    _timestamp(manifest["created_at"])
    require(isinstance(manifest["status"], str) and manifest["status"] in RUN_STATUSES,
            "FACTOR_MANIFEST_STATUS_INVALID")

    provenance = _strict(manifest["provenance"], {"origin", "evidence"},
                         "FACTOR_MANIFEST_PROVENANCE_SCHEMA")
    require((provenance["origin"], provenance["evidence"]) in PROVENANCE,
            "FACTOR_MANIFEST_PROVENANCE_INVALID")
    engine = _strict(manifest["engine"],
                     {"rdagent_revision", "rdagent_tree", "qlib_profile", "qlib_revision",
                      "qlib_tree", "adapter_version"}, "FACTOR_MANIFEST_ENGINE_SCHEMA")
    _sha(engine["rdagent_revision"], length=40); _sha(engine["rdagent_tree"], length=40)
    _name(engine["qlib_profile"], "FACTOR_MANIFEST_QLIB_PROFILE_INVALID")
    _sha(engine["qlib_revision"], length=40); _sha(engine["qlib_tree"], length=40)
    _name(engine["adapter_version"], "FACTOR_MANIFEST_ADAPTER_INVALID")
    _sha(manifest["protocol_sha256"], optional=True)
    _sha(manifest["dataset_snapshot_sha256"], optional=True)
    if provenance["origin"] == "reproduced_local":
        require(manifest["protocol_sha256"] is not None and
                manifest["dataset_snapshot_sha256"] is not None,
                "FACTOR_MANIFEST_REPRODUCTION_BINDING_REQUIRED")

    require(isinstance(manifest["stages"], list) and 1 <= len(manifest["stages"]) <= 64,
            "FACTOR_MANIFEST_STAGES_INVALID")
    stage_ids = set()
    for stage in manifest["stages"]:
        _strict(stage, {"id", "status", "attempt_count", "receipt_sha256", "failure_code"},
                "FACTOR_MANIFEST_STAGE_SCHEMA")
        _name(stage["id"], "FACTOR_MANIFEST_STAGE_ID_INVALID")
        require(stage["id"] not in stage_ids and isinstance(stage["status"], str) and
                stage["status"] in STAGE_STATUSES and type(stage["attempt_count"]) is int and
                stage["attempt_count"] >= 0, "FACTOR_MANIFEST_STAGE_INVALID")
        _sha(stage["receipt_sha256"], optional=True)
        require(stage["failure_code"] is None or
                isinstance(stage["failure_code"], str) and NAME.fullmatch(stage["failure_code"]),
                "FACTOR_MANIFEST_FAILURE_CODE_INVALID")
        if stage["status"] == "succeeded":
            require(stage["receipt_sha256"] is not None and stage["failure_code"] is None,
                    "FACTOR_MANIFEST_STAGE_SUCCESS_INVALID")
        if stage["status"] in {"failed", "timed_out"}:
            require(stage["failure_code"] is not None, "FACTOR_MANIFEST_STAGE_FAILURE_INVALID")
        stage_ids.add(stage["id"])

    require(isinstance(manifest["artifacts"], list) and len(manifest["artifacts"]) <= 256,
            "FACTOR_MANIFEST_ARTIFACTS_INVALID")
    artifact_ids = set()
    for artifact in manifest["artifacts"]:
        _strict(artifact, {"id", "kind", "path", "sha256", "size_bytes"},
                "FACTOR_MANIFEST_ARTIFACT_SCHEMA")
        _name(artifact["id"], "FACTOR_MANIFEST_ARTIFACT_ID_INVALID")
        _name(artifact["kind"], "FACTOR_MANIFEST_ARTIFACT_KIND_INVALID")
        require(artifact["id"] not in artifact_ids and type(artifact["size_bytes"]) is int and
                0 < artifact["size_bytes"] <= 1024 * 1024 * 1024,
                "FACTOR_MANIFEST_ARTIFACT_INVALID")
        _relative_path(artifact["path"]); _sha(artifact["sha256"])
        artifact_ids.add(artifact["id"])

    require(isinstance(manifest["factors"], list) and len(manifest["factors"]) <= 128,
            "FACTOR_MANIFEST_FACTORS_INVALID")
    factor_ids = set()
    for factor in manifest["factors"]:
        _strict(factor, {"id", "family", "formula_sha256", "status", "metrics"},
                "FACTOR_MANIFEST_FACTOR_SCHEMA")
        _name(factor["id"]); _name(factor["family"])
        _sha(factor["formula_sha256"], optional=True)
        require(factor["id"] not in factor_ids and isinstance(factor["status"], str) and
                factor["status"] in FACTOR_STATUSES and isinstance(factor["metrics"], dict) and
                len(factor["metrics"]) <= 64 and all(isinstance(key, str) and NAME.fullmatch(key) and _finite(value)
                for key, value in factor["metrics"].items()), "FACTOR_MANIFEST_FACTOR_INVALID")
        if factor["status"] == "evaluated":
            require(factor["formula_sha256"] is not None and factor["metrics"],
                    "FACTOR_MANIFEST_FACTOR_EVIDENCE_REQUIRED")
        factor_ids.add(factor["id"])

    if version == 2:
        _performance(manifest["performance"], factor_ids, manifest["artifacts"], provenance)

    require(isinstance(manifest["gates"], list) and len(manifest["gates"]) <= 128,
            "FACTOR_MANIFEST_GATES_INVALID")
    gate_ids = set()
    for gate in manifest["gates"]:
        _strict(gate, {"id", "dimension", "status", "reason_code", "evidence_sha256"},
                "FACTOR_MANIFEST_GATE_SCHEMA")
        _name(gate["id"]); require(gate["id"] not in gate_ids and
            isinstance(gate["dimension"], str) and gate["dimension"] in DIMENSIONS and
            isinstance(gate["status"], str) and gate["status"] in GATE_STATUSES,
            "FACTOR_MANIFEST_GATE_INVALID")
        require(gate["reason_code"] is None or
                isinstance(gate["reason_code"], str) and NAME.fullmatch(gate["reason_code"]),
                "FACTOR_MANIFEST_GATE_REASON_INVALID")
        _sha(gate["evidence_sha256"], optional=True)
        if gate["status"] != "pending":
            require(gate["reason_code"] is not None, "FACTOR_MANIFEST_GATE_REASON_REQUIRED")
        if gate["status"] in {"pass", "fail"}:
            require(gate["evidence_sha256"] is not None,
                    "FACTOR_MANIFEST_GATE_EVIDENCE_REQUIRED")
        gate_ids.add(gate["id"])

    require(isinstance(manifest["failures"], list) and len(manifest["failures"]) <= 128,
            "FACTOR_MANIFEST_FAILURES_INVALID")
    for failure in manifest["failures"]:
        _strict(failure, {"code", "stage_id", "evidence_sha256"},
                "FACTOR_MANIFEST_FAILURE_SCHEMA")
        _name(failure["code"]); _name(failure["stage_id"])
        require(failure["stage_id"] in stage_ids, "FACTOR_MANIFEST_FAILURE_STAGE_UNKNOWN")
        _sha(failure["evidence_sha256"], optional=True)

    resources = _strict(manifest["resources"],
                        {"wall_seconds", "cpu_seconds", "peak_rss_bytes", "cache_hit"},
                        "FACTOR_MANIFEST_RESOURCES_SCHEMA")
    require(_finite(resources["wall_seconds"]) and resources["wall_seconds"] >= 0 and
            _finite(resources["cpu_seconds"]) and resources["cpu_seconds"] >= 0 and
            type(resources["peak_rss_bytes"]) is int and resources["peak_rss_bytes"] >= 0 and
            type(resources["cache_hit"]) is bool, "FACTOR_MANIFEST_RESOURCES_INVALID")
    require(isinstance(manifest["limitations"], list) and len(manifest["limitations"]) <= 64 and
            all(isinstance(item, str) and 1 <= len(item) <= 1000 for item in manifest["limitations"]),
            "FACTOR_MANIFEST_LIMITATIONS_INVALID")
    if manifest["status"] == "succeeded":
        require(all(stage["status"] in {"succeeded", "skipped"} for stage in manifest["stages"]),
                "FACTOR_MANIFEST_RUN_SUCCESS_INVALID")
    return manifest


def _read_regular(path, maximum, code):
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ManifestError(code) from None
    try:
        details = os.fstat(descriptor)
        require(stat.S_ISREG(details.st_mode) and 0 < details.st_size <= maximum, code)
        chunks = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            require(chunk, code)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _safe_root(path, create=True):
    root = Path(path).absolute()
    require(root.parent.is_dir() and root.parent.resolve() == root.parent,
            "FACTOR_MANIFEST_ROOT_PARENT_INVALID")
    if create and not root.exists():
        try:
            os.mkdir(root, 0o700)
        except FileExistsError:
            pass
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
            "FACTOR_MANIFEST_ROOT_INVALID")
    if create:
        parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    return root


@contextmanager
def _lock(root, run_id):
    lock_dir = root / "locks"
    _ensure_directory(lock_dir)
    require(not lock_dir.is_symlink(), "FACTOR_MANIFEST_LOCK_DIR_INVALID")
    descriptor = os.open(lock_dir / (run_id + ".lock"),
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _head_path(root, run_id):
    return root / "heads" / (run_id + ".json")


def _manifest_path(root, run_id, manifest_sha256):
    return root / "manifests" / run_id / (manifest_sha256 + ".json")


def _validate_head(head, run_id):
    require(isinstance(head, dict) and set(head) ==
            {"schema_version", "run_id", "revision", "manifest_sha256"} and
            head["schema_version"] == 1 and head["run_id"] == run_id and
            type(head["revision"]) is int and head["revision"] > 0,
            "FACTOR_MANIFEST_HEAD_INVALID")
    _sha(head["manifest_sha256"], "FACTOR_MANIFEST_HEAD_INVALID")
    return head


def _load_head(root, run_id):
    path = _head_path(root, run_id)
    if not path.exists():
        return None
    return _validate_head(loads_strict(_read_regular(path, 4096,
                                                     "FACTOR_MANIFEST_HEAD_INVALID")), run_id)


def _load_manifest(root, run_id, manifest_sha256):
    path = _manifest_path(root, run_id, manifest_sha256)
    raw = _read_regular(path, MAX_MANIFEST_BYTES, "FACTOR_MANIFEST_NOT_FOUND")
    require(hashlib.sha256(raw).hexdigest() == manifest_sha256, "FACTOR_MANIFEST_BYTES_CHANGED")
    value = validate(loads_strict(raw))
    require(value["run_id"] == run_id, "FACTOR_MANIFEST_RUN_ID_MISMATCH")
    return value


def _transition(previous, current):
    require(current["run_id"] == previous["run_id"] and
            current["schema_version"] == previous["schema_version"] and
            current["revision"] == previous["revision"] + 1 and
            current["previous_manifest_sha256"] == digest(previous) and
            current["engine"] == previous["engine"] and
            current["protocol_sha256"] == previous["protocol_sha256"] and
            current["dataset_snapshot_sha256"] == previous["dataset_snapshot_sha256"] and
            current["provenance"] == previous["provenance"], "FACTOR_MANIFEST_REVISION_CONFLICT")
    require(current["status"] in RUN_TRANSITIONS.get(previous["status"], set()),
            "FACTOR_MANIFEST_STATUS_TRANSITION_INVALID")
    require([stage["id"] for stage in current["stages"]] ==
            [stage["id"] for stage in previous["stages"]], "FACTOR_MANIFEST_STAGE_ROSTER_CHANGED")
    for before, after in zip(previous["stages"], current["stages"]):
        require(after["status"] in STAGE_TRANSITIONS.get(before["status"], {before["status"]}),
                "FACTOR_MANIFEST_STAGE_TRANSITION_INVALID")
        if before["status"] in {"succeeded", "failed", "timed_out", "skipped"}:
            require(after == before, "FACTOR_MANIFEST_TERMINAL_STAGE_CHANGED")
        else:
            require(after["attempt_count"] >= before["attempt_count"],
                    "FACTOR_MANIFEST_ATTEMPT_COUNT_REGRESSED")
    previous_artifacts = {item["id"]: item for item in previous["artifacts"]}
    current_artifacts = {item["id"]: item for item in current["artifacts"]}
    require(all(current_artifacts.get(key) == value for key, value in previous_artifacts.items()),
            "FACTOR_MANIFEST_ARTIFACT_CHANGED")
    require([factor["id"] for factor in current["factors"]] ==
            [factor["id"] for factor in previous["factors"]], "FACTOR_MANIFEST_FACTOR_ROSTER_CHANGED")
    for before, after in zip(previous["factors"], current["factors"]):
        require(after["family"] == before["family"] and
                after["status"] in FACTOR_TRANSITIONS[before["status"]],
                "FACTOR_MANIFEST_FACTOR_TRANSITION_INVALID")
        if before["status"] != "pending":
            require(after == before, "FACTOR_MANIFEST_TERMINAL_FACTOR_CHANGED")
        if before["formula_sha256"] is not None:
            require(after["formula_sha256"] == before["formula_sha256"],
                    "FACTOR_MANIFEST_FACTOR_FORMULA_CHANGED")
        require(all(after["metrics"].get(key) == value for key, value in before["metrics"].items()),
                "FACTOR_MANIFEST_FACTOR_METRIC_CHANGED")
    require([gate["id"] for gate in current["gates"]] ==
            [gate["id"] for gate in previous["gates"]], "FACTOR_MANIFEST_GATE_ROSTER_CHANGED")
    for before, after in zip(previous["gates"], current["gates"]):
        require(after["dimension"] == before["dimension"] and
                after["status"] in GATE_TRANSITIONS[before["status"]],
                "FACTOR_MANIFEST_GATE_TRANSITION_INVALID")
        if before["status"] != "pending":
            require(after == before, "FACTOR_MANIFEST_TERMINAL_GATE_CHANGED")
    require(current["failures"][:len(previous["failures"])] == previous["failures"],
            "FACTOR_MANIFEST_FAILURE_HISTORY_CHANGED")
    if current["schema_version"] == 2:
        require(current["performance"][:len(previous["performance"])] == previous["performance"],
                "FACTOR_MANIFEST_PERFORMANCE_HISTORY_CHANGED")


def _open_artifact(root_fd, relative):
    current = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=current)
            os.close(current)
            current = next_fd
        return os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=current)
    except OSError:
        raise ManifestError("FACTOR_MANIFEST_ARTIFACT_PATH_INVALID") from None
    finally:
        os.close(current)


def _verify_artifacts(manifest, artifact_root):
    if not manifest["artifacts"]:
        return
    require(artifact_root is not None, "FACTOR_MANIFEST_ARTIFACT_ROOT_REQUIRED")
    root = Path(artifact_root).absolute()
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
            "FACTOR_MANIFEST_ARTIFACT_ROOT_INVALID")
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for artifact in manifest["artifacts"]:
            relative = _relative_path(artifact["path"])
            descriptor = _open_artifact(root_fd, relative)
            try:
                details = os.fstat(descriptor)
                initial = (details.st_dev, details.st_ino, details.st_size,
                           details.st_mtime_ns, details.st_ctime_ns)
                require(stat.S_ISREG(details.st_mode) and
                        details.st_size == artifact["size_bytes"],
                        "FACTOR_MANIFEST_ARTIFACT_INVALID")
                observed = hashlib.sha256()
                remaining = details.st_size
                while remaining:
                    chunk = os.read(descriptor, min(65536, remaining))
                    require(chunk, "FACTOR_MANIFEST_ARTIFACT_INVALID")
                    observed.update(chunk)
                    remaining -= len(chunk)
                require(os.read(descriptor, 1) == b"", "FACTOR_MANIFEST_ARTIFACT_MUTATED")
                final = os.fstat(descriptor)
                require((final.st_dev, final.st_ino, final.st_size,
                         final.st_mtime_ns, final.st_ctime_ns) == initial,
                        "FACTOR_MANIFEST_ARTIFACT_MUTATED")
                require(observed.hexdigest() == artifact["sha256"],
                        "FACTOR_MANIFEST_ARTIFACT_MISMATCH")
            finally:
                os.close(descriptor)
    finally:
        os.close(root_fd)


def _ensure_directory(path):
    path = Path(path)
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    require(cursor.is_dir() and not cursor.is_symlink(), "FACTOR_MANIFEST_DIRECTORY_INVALID")
    for directory in reversed(missing):
        try:
            os.mkdir(directory, 0o700)
        except FileExistsError:
            pass
        require(directory.is_dir() and not directory.is_symlink(),
                "FACTOR_MANIFEST_DIRECTORY_INVALID")
        parent_fd = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)


def _atomic_write(path, payload, replace=False):
    _ensure_directory(path.parent)
    require(not path.parent.is_symlink(), "FACTOR_MANIFEST_DIRECTORY_INVALID")
    token = hashlib.sha256(payload).hexdigest()[:16]
    temporary = None
    descriptor = None
    for suffix in range(16):
        candidate = path.parent / f".tmp-{os.getpid()}-{token}-{suffix}"
        try:
            descriptor = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600)
            temporary = candidate
            break
        except FileExistsError:
            continue
    require(descriptor is not None and temporary is not None, "FACTOR_MANIFEST_TEMP_EXHAUSTED")
    try:
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                require(written > 0, "FACTOR_MANIFEST_WRITE_FAILED")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
            descriptor = None
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                existing = _read_regular(path, max(len(payload), 1),
                                         "FACTOR_MANIFEST_EXISTING_INVALID")
                require(existing == payload, "FACTOR_MANIFEST_EXISTS_CONFLICT")
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def publish(manifest, registry_root, artifact_root=None):
    manifest = validate(manifest)
    payload = canonical(manifest)
    require(len(payload) <= MAX_MANIFEST_BYTES, "FACTOR_MANIFEST_SIZE_LIMIT")
    manifest_sha256 = hashlib.sha256(payload).hexdigest()
    root = _safe_root(registry_root)
    with _lock(root, manifest["run_id"]):
        head = _load_head(root, manifest["run_id"])
        if head is None:
            require(manifest["revision"] == 1, "FACTOR_MANIFEST_FIRST_REVISION_REQUIRED")
        else:
            previous = _load_manifest(root, manifest["run_id"], head["manifest_sha256"])
            require(previous["revision"] == head["revision"], "FACTOR_MANIFEST_HEAD_MISMATCH")
            if manifest_sha256 == head["manifest_sha256"]:
                require(previous == manifest, "FACTOR_MANIFEST_HEAD_MISMATCH")
                return {"manifest_sha256": manifest_sha256, "head": head}
            _transition(previous, manifest)
        _verify_artifacts(manifest, artifact_root)
        manifest_path = _manifest_path(root, manifest["run_id"], manifest_sha256)
        _atomic_write(manifest_path, payload)
        head = {"schema_version": 1, "run_id": manifest["run_id"],
                "revision": manifest["revision"], "manifest_sha256": manifest_sha256}
        _atomic_write(_head_path(root, manifest["run_id"]), canonical(head), replace=True)
    return {"manifest_sha256": manifest_sha256, "head": head}


def load_manifest(registry_root, run_id, manifest_sha256):
    _name(run_id, "FACTOR_MANIFEST_RUN_ID_INVALID")
    _sha(manifest_sha256, "FACTOR_MANIFEST_SHA_INVALID")
    root = _safe_root(registry_root, create=False)
    return _load_manifest(root, run_id, manifest_sha256)


def load_head(registry_root, run_id):
    _name(run_id, "FACTOR_MANIFEST_RUN_ID_INVALID")
    root = _safe_root(registry_root, create=False)
    head = _load_head(root, run_id)
    require(head is not None, "FACTOR_MANIFEST_HEAD_NOT_FOUND")
    require(set(head) == {"schema_version", "run_id", "revision", "manifest_sha256"} and
            head["schema_version"] == 1 and head["run_id"] == run_id,
            "FACTOR_MANIFEST_HEAD_INVALID")
    manifest = _load_manifest(root, run_id, head["manifest_sha256"])
    require(manifest["revision"] == head["revision"], "FACTOR_MANIFEST_HEAD_MISMATCH")
    return {"head": head, "manifest": manifest}
