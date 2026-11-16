from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(WORKSPACE))

from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.runner import _commit_execution_receipt


def crash(_window: str) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


value = json.loads(Path(sys.argv[1]).read_text())
_commit_execution_receipt(Path(sys.argv[2]), value, 200, sys.argv[3], crash_hook=crash)
raise SystemExit(3)
