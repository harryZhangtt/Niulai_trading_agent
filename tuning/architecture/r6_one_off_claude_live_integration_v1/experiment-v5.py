"""Provider-free v5 verification entrypoint; never supplies live authority or effects."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
def main() -> int:
    command = [sys.executable, "-I", "-m", "unittest", "discover", "-s",
        "shared/job_runtime/tests/candidates/r6_one_off_claude_live_integration_v5", "-v"]
    return subprocess.run(command, cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        check=False).returncode
if __name__ == "__main__":
    raise SystemExit(main())
