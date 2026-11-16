"""Deterministic verifier for the inert v9 evidence-only successor."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[3]
ARCH = pathlib.Path(__file__).resolve().parent
V8_ARCH = ROOT / "tuning/architecture/r6_one_off_claude_live_integration_v8"
V8_CLOSURE = V8_ARCH / "source-closure-v8.json"
V8_REVIEW = ROOT / "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v8-independent-review-open-fable-20261113-8e9a8076.json"
V7_REVIEW_REL = "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v7-independent-review-open-fable-20261112-8e9a8076.json"
V8_REVIEW_REL = "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-claude-live-integration-v8-independent-review-open-fable-20261113-8e9a8076.json"
ADDITIVE_PATHS = {
    V8_REVIEW_REL,
    "tuning/architecture/r6_one_off_claude_live_integration_v9/verify_v9.py",
    "tuning/architecture/r6_one_off_claude_live_integration_v9/test_verify_v9.py",
}
DOC_TYPES = {
    "architecture-v9.json": "architecture",
    "lineage-v9.json": "append_only_supersession_lineage",
    "protocol-v9.json": "protocol",
    "source-closure-v9.json": "recursive_source_closure",
    "decision-v9.json": "decision",
    "producer-verification-v9-final.json": "distinct_producer_verification",
}


def identity(path: pathlib.Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "bytes": len(raw),
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def aggregate(items: list[dict[str, Any]]) -> str:
    chunks = [f'{item["path"]}\0{item["bytes"]}\0{item["sha256"]}\n' for item in items]
    return hashlib.sha256("".join(sorted(chunks)).encode()).hexdigest()


def _verify_descriptors(value: Any, location: str = "$") -> int:
    count = 0
    if isinstance(value, dict):
        if {"path", "bytes", "sha256"} <= value.keys():
            expected = {key: value[key] for key in ("bytes", "path", "sha256")}
            path = ROOT / expected["path"]
            if not path.is_file():
                raise RuntimeError(f"DESCRIPTOR_MISSING:{location}:{expected['path']}")
            if identity(path) != expected:
                raise RuntimeError(f"DESCRIPTOR_IDENTITY_MISMATCH:{location}:{expected['path']}")
            count += 1
        for key, child in value.items():
            count += _verify_descriptors(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            count += _verify_descriptors(child, f"{location}[{index}]")
    return count


def verify_all() -> dict[str, Any]:
    docs = {name: json.loads((ARCH / name).read_text()) for name in DOC_TYPES}
    for name, artifact_type in DOC_TYPES.items():
        doc = docs[name]
        if doc.get("artifact_type") != artifact_type or doc.get("version") != 9:
            raise RuntimeError(f"VERSION_OR_TYPE_MISMATCH:{name}")
        if doc.get("activation") is not False or doc.get("registration") is not False:
            raise RuntimeError(f"ACTIVATION_OR_REGISTRATION_MISMATCH:{name}")
        if doc.get("p0_v10_reclosure") != "P0_V10_RECLOSURE_REQUIRED":
            raise RuntimeError(f"P0_GATE_MISMATCH:{name}")

    v8_review = identity(V8_REVIEW)
    if v8_review != {"bytes": 10896, "path": V8_REVIEW_REL,
                     "sha256": "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d"}:
        raise RuntimeError("V8_REVIEW_IDENTITY_MISMATCH")
    review_doc = json.loads(V8_REVIEW.read_text())
    if review_doc.get("verdict") != "OPEN" or review_doc["findings"][0]["id"] != "OPEN-CLAUDE-V8-001":
        raise RuntimeError("V8_REVIEW_SEMANTICS_MISMATCH")

    closure = docs["source-closure-v9.json"]
    v8_closure = json.loads(V8_CLOSURE.read_text())
    baseline = v8_closure["artifacts"]
    baseline_by_path = {item["path"]: item for item in baseline}
    actual_by_path = {item["path"]: item for item in closure["artifacts"]}
    if len(actual_by_path) != len(closure["artifacts"]):
        raise RuntimeError("DUPLICATE_CLOSURE_MEMBER")
    if {path: actual_by_path.get(path) for path in baseline_by_path} != baseline_by_path:
        raise RuntimeError("V8_BASELINE_CLOSURE_DELTA")
    if set(actual_by_path) - set(baseline_by_path) != ADDITIVE_PATHS:
        raise RuntimeError("UNEXPECTED_ADDITIVE_CLOSURE_MEMBER")
    if set(baseline_by_path) - set(actual_by_path):
        raise RuntimeError("MISSING_V8_BASELINE_CLOSURE_MEMBER")
    if closure["artifact_count"] != len(actual_by_path) or closure["artifact_count"] != 36:
        raise RuntimeError("CLOSURE_COUNT_MISMATCH")
    if aggregate(closure["artifacts"]) != closure["aggregate_sha256"]:
        raise RuntimeError("CLOSURE_AGGREGATE_MISMATCH")
    if closure["dynamic_inputs"] != [
        "five pinned authority artifacts",
        "grant-selected fake executable",
        "recursive local Python imports",
        "unchanged v8 schemas and tests",
        "v7 OPEN review",
        "OPEN v8 predecessor review",
        "v9 deterministic verifier and test",
    ]:
        raise RuntimeError("DYNAMIC_INPUT_DESCRIPTOR_MISMATCH")
    if closure["corrected_descriptor"]["exact_member"]["path"] != V7_REVIEW_REL:
        raise RuntimeError("CORRECTED_V7_DESCRIPTOR_PATH_MISMATCH")
    if closure["corrected_descriptor"]["exact_member"]["bytes"] != 10536:
        raise RuntimeError("CORRECTED_V7_DESCRIPTOR_SIZE_MISMATCH")
    if closure["corrected_descriptor"]["exact_member"]["sha256"] != "3ebc954c253ae104f97ef5fe52e0fb96ac6d70a0eb273677e022145962dc258a":
        raise RuntimeError("CORRECTED_V7_DESCRIPTOR_HASH_MISMATCH")
    if "v6 OPEN review" in closure["dynamic_inputs"]:
        raise RuntimeError("STALE_V6_DESCRIPTOR")

    if (ROOT / "shared/job_runtime/candidates/r6_one_off_claude_live_integration_v9").exists():
        raise RuntimeError("UNEXPECTED_V9_RUNTIME_SOURCE_PACKAGE")
    if (ROOT / "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v9").exists():
        raise RuntimeError("UNEXPECTED_V9_RUNTIME_TEST_PACKAGE")

    descriptor_count = 0
    for name, doc in docs.items():
        descriptor_count += _verify_descriptors(doc, name)
    return {
        "aggregate_sha256": closure["aggregate_sha256"],
        "artifact_count": closure["artifact_count"],
        "descriptor_count": descriptor_count,
        "semantic_source_delta_count": 0,
        "status": "PASS",
    }


def main() -> int:
    summary = verify_all()
    python = ROOT / ".research-sources/.venv/bin/python3.12"
    tests = [
        "tuning/architecture/r6_one_off_claude_live_integration_v9/test_verify_v9.py",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_integration.py",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_schemas_closure.py",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_z_public_boundary.py",
    ]
    results = []
    for relative in tests:
        completed = subprocess.run(
            [str(python), "-I", str(ROOT / relative), "-v"],
            cwd=ROOT, capture_output=True, text=True, timeout=180,
        )
        results.append({"path": relative, "returncode": completed.returncode})
        if completed.returncode:
            sys.stderr.write(completed.stdout + completed.stderr)
            return completed.returncode
    summary["tests"] = results
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
