"""Trusted deterministic worker for testing the host boundary; never imports upstream code."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


ENGINE = {
    "rdagent_revision": "484776c211e4fbbeef03e0ec00d6bbee7362a4f4",
    "rdagent_tree": "d4444284fb4554f75f352ecb1f072cedbf4c6421",
    "qlib_profile": "qlib-rdagent-compatible",
    "qlib_revision": "2fb9380b342556ddb50a4b24e4fe8655d548b2b8",
    "qlib_tree": "0f541590a9efecb9bfb5342155be50461ad7d002",
    "adapter_version": "rdagent-adapter-v1",
}
STAGES = ("proposal", "coding", "factor-output", "feedback")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def artifact(path, artifact_id, kind, factor_ids):
    data = path.read_bytes()
    return {"id": artifact_id, "kind": kind, "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data),
            "factor_ids": factor_ids}


def success(request, mode):
    artifacts = Path("artifacts")
    code = artifacts / "factor.py"
    output = artifacts / "factor.json"
    code.write_text("def synthetic_factor(rows):\n    return [1.0 for _ in rows]\n", encoding="utf-8")
    output.write_text(json.dumps({"factor_ids": request["task"]["expected_factor_ids"],
                                  "rows": [["2026-01-02", 1.0]]}), encoding="utf-8")
    factor_ids = request["task"]["expected_factor_ids"]
    code_artifact = artifact(code, "generated-factor-code", "generated-code", factor_ids)
    output_artifact = artifact(output, "factor-output", "factor-data", factor_ids)
    if mode == "missing-output":
        output.unlink()
    if mode == "symlink":
        code.unlink()
        real = Path("tmp") / "real-factor.py"
        real.write_text("synthetic", encoding="utf-8")
        code.symlink_to(real.resolve())
    stages = [{"id": stage_id, "status": "succeeded", "duration_seconds": 0.001,
               "evidence_sha256": hashlib.sha256(stage_id.encode()).hexdigest()}
              for stage_id in STAGES]
    return {
        "schema_version": 1, "kind": "rdagent_factor_receipt",
        "request_sha256": hashlib.sha256(canonical(request)).hexdigest(),
        "status": "succeeded", "execution_mode": "synthetic-fixture", "engine": ENGINE,
        "stages": stages, "artifacts": [code_artifact, output_artifact], "failure_code": None,
        "resources": {"wall_seconds": 0.004, "cpu_seconds": 0.001, "peak_rss_bytes": 4096},
        "process_group_cleanup_verified": True,
    }


def main():
    mode = sys.argv[1]
    request = json.loads(sys.stdin.buffer.read())
    if mode == "nonzero":
        return 7
    if mode == "disk-canary-nonzero":
        Path("artifacts/leaked.txt").write_text("SECRET_CANARY_ON_DISK")
        return 7
    if mode == "reserved-names":
        Path(".receipt.tmp").write_text("child-controlled")
        Path("receipt.json").write_text("child-controlled")
        return 7
    if mode == "oversized":
        sys.stdout.write("X" * (2 * 1024 * 1024))
        return 0
    if mode == "secret-canary":
        sys.stdout.write("SECRET_CANARY_DO_NOT_PERSIST")
        return 0
    if mode == "timeout":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path("descendant.pid").write_text(str(child.pid))
        time.sleep(60)
        return 0
    sys.stdout.buffer.write(canonical(success(request, mode)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
