"""Map one sanitized adapter receipt into a fixture-only RunManifest v1 value."""
from pathlib import Path

from shared.factor_mining import manifest as run_manifest
from . import contracts


def _reason(code):
    return code.lower().replace("_", "-") if code is not None else None


def build(request, runner_result, created_at):
    request = contracts.validate_request(request)
    receipt = contracts.validate_receipt(runner_result["receipt"], request)
    receipt_sha = runner_result["receipt_sha256"]
    contracts._sha(receipt_sha, "ADAPTER_RECEIPT_SHA_INVALID")
    stage_records = []
    for stage in receipt["stages"]:
        stage_records.append({
            "id": stage["id"],
            "status": stage["status"],
            "attempt_count": 1,
            "receipt_sha256": stage["evidence_sha256"],
            "failure_code": _reason(receipt["failure_code"]) if stage["status"] in {"failed", "timed_out"} else None,
        })
    artifacts = []
    for artifact in receipt["artifacts"]:
        artifacts.append({
            "id": artifact["id"], "kind": artifact["kind"],
            "path": artifact["path"],
            "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"],
        })
    receipt_path = Path(runner_result["receipt_path"])
    artifacts.append({
        "id": "adapter-receipt", "kind": "adapter-receipt", "path": str(receipt_path),
        "sha256": receipt_sha, "size_bytes": None,
    })
    failures = []
    if receipt["failure_code"] is not None:
        failed_stage = next(stage["id"] for stage in receipt["stages"]
                            if stage["status"] in {"failed", "timed_out"})
        failures.append({"code": _reason(receipt["failure_code"]),
                         "stage_id": failed_stage, "evidence_sha256": receipt_sha})
    status = receipt["status"]
    value = {
        "schema_version": 1,
        "kind": "factor_run_manifest",
        "run_id": request["request_id"],
        "revision": 1,
        "previous_manifest_sha256": None,
        "created_at": created_at,
        "status": status,
        "provenance": {"origin": "synthetic_fixture", "evidence": "fixture_only"},
        "engine": request["engine"],
        "protocol_sha256": None,
        "dataset_snapshot_sha256": None,
        "stages": stage_records,
        "artifacts": artifacts,
        "factors": [],
        "gates": [
            {"id": "implementation", "dimension": "implementation",
             "status": "pass" if status == "succeeded" else "fail",
             "reason_code": "synthetic-boundary-passed" if status == "succeeded" else
                            _reason(receipt["failure_code"]),
             "evidence_sha256": receipt_sha},
            {"id": "predictive", "dimension": "predictive", "status": "withheld",
             "reason_code": "fixture-only", "evidence_sha256": None},
            {"id": "economic", "dimension": "economic", "status": "withheld",
             "reason_code": "fixture-only", "evidence_sha256": None},
            {"id": "publication", "dimension": "publication", "status": "withheld",
             "reason_code": "fixture-only", "evidence_sha256": None},
        ],
        "failures": failures,
        "resources": dict(receipt["resources"], cache_hit=False),
        "limitations": [
            "Synthetic subprocess boundary only; RD-Agent and Qlib were not imported or executed.",
            "No market data, factor metric, alpha, EV, Kelly, or production readiness is established.",
        ],
    }
    run_manifest._timestamp(created_at)
    return value


def bind_receipt_size(value, artifact_root):
    """Fill the one host-known receipt size before immutable publication."""
    updated = {**value, "artifacts": [dict(artifact) for artifact in value["artifacts"]]}
    receipt = next(item for item in updated["artifacts"] if item["id"] == "adapter-receipt")
    path = Path(artifact_root) / receipt["path"]
    receipt["size_bytes"] = path.stat().st_size
    return run_manifest.validate(updated)
