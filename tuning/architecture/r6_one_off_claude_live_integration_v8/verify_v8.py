"""Distinct deterministic verifier for the disabled v8 producer candidate."""
from __future__ import annotations
import hashlib
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
ARCH = pathlib.Path(__file__).resolve().parent


def verify_closure() -> tuple[int, str]:
    from shared.job_runtime.tests.candidates.r6_one_off_claude_live_integration_v8.test_schemas_closure import expected_closure
    value = json.loads((ARCH / "source-closure-v8.json").read_text())
    expected = expected_closure()
    actual = {item["path"] for item in value["artifacts"]}
    if actual != expected:
        raise RuntimeError("CLOSURE_MEMBERSHIP_MISMATCH")
    chunks = []
    for item in value["artifacts"]:
        raw = (ROOT / item["path"]).read_bytes()
        if (len(raw), hashlib.sha256(raw).hexdigest()) != (item["bytes"], item["sha256"]):
            raise RuntimeError("CLOSURE_IDENTITY_MISMATCH:" + item["path"])
        chunks.append(f'{item["path"]}\0{item["bytes"]}\0{item["sha256"]}\n')
    aggregate = hashlib.sha256("".join(sorted(chunks)).encode()).hexdigest()
    if aggregate != value["aggregate_sha256"]:
        raise RuntimeError("CLOSURE_AGGREGATE_MISMATCH")
    return len(actual), aggregate


def main() -> int:
    count, aggregate = verify_closure()
    python = ROOT / ".research-sources/.venv/bin/python3.12"
    tests = [
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_integration.py",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_schemas_closure.py",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v8/test_z_public_boundary.py",
    ]
    results = []
    for relative in tests:
        completed = subprocess.run([str(python), "-I", str(ROOT / relative), "-v"],
                                   cwd=ROOT, capture_output=True, text=True, timeout=180)
        results.append({"path": relative, "returncode": completed.returncode})
        if completed.returncode:
            sys.stderr.write(completed.stdout + completed.stderr)
            return completed.returncode
    print(json.dumps({"aggregate_sha256": aggregate, "artifact_count": count,
                      "status": "PASS", "tests": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
