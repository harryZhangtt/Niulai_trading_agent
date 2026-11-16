#!/usr/bin/env python3
"""Checked-in provider-free producer verification for the direct catalog candidate."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CLOSURE = ROOT / "tuning/architecture/r6_one_off_codex_direct_catalog_v1/source-closure-v1.json"

def main() -> int:
    closure = json.loads(CLOSURE.read_text())
    checked = 0
    for member in closure["members"]:
        raw = (ROOT / member["path"]).read_bytes()
        if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
            raise SystemExit("source closure mismatch")
        checked += 1
    command = [sys.executable, "-m", "unittest", "-v",
               "shared.job_runtime.tests.candidates.r6_one_off_codex_direct_catalog_v1.test_direct_catalog"]
    run = subprocess.run(command, cwd=str(ROOT), env={**dict(__import__("os").environ), "PYTHONDONTWRITEBYTECODE": "1"},
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tests = sum(1 for line in run.stdout.splitlines() if line.rstrip().endswith("... ok"))
    print(json.dumps({"closure_members": checked, "provider_free": True, "returncode": run.returncode,
                      "tests_observed": tests}, separators=(",", ":"), sort_keys=True))
    return run.returncode

if __name__ == "__main__":
    raise SystemExit(main())
