#!/usr/bin/env python3
"""Checked-in provider-free v4 producer verification."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
CLOSURE = ROOT / "tuning/architecture/r6_one_off_codex_direct_catalog_v1/source-closure-v4.json"

def main() -> int:
    closure = json.loads(CLOSURE.read_text())
    checked = 0
    for member in closure["members"]:
        raw = (ROOT / member["path"]).read_bytes()
        if len(raw) != member["bytes"] or hashlib.sha256(raw).hexdigest() != member["sha256"]:
            raise SystemExit("v4 source closure mismatch")
        checked += 1
    command = [sys.executable, "-m", "unittest", "-v",
               "shared.job_runtime.tests.candidates.r6_one_off_codex_direct_catalog_v1.test_direct_catalog"]
    run = subprocess.run(command, cwd=str(ROOT), env={**dict(os.environ), "PYTHONDONTWRITEBYTECODE": "1"},
                         stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True)
    passed = sum(1 for line in run.stdout.splitlines() if line.rstrip().endswith("... ok"))
    skipped = sum(1 for line in run.stdout.splitlines() if "... skipped " in line)
    print(json.dumps({"closure_members": checked, "passed": passed, "provider_free": True,
                      "returncode": run.returncode, "skipped": skipped},
                     separators=(",", ":"), sort_keys=True))
    return run.returncode

if __name__ == "__main__":
    raise SystemExit(main())
