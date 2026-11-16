#!/usr/bin/env python3
"""Materialize the sanitized receipt from the exact frozen owner-private input."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.job_runtime.candidates.r6_one_off_claude_catalog_parser_v1 import interpret_frozen_catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    value = interpret_frozen_catalog(args.workspace)
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=args.output.name + ".", dir=str(args.output.parent))
    try:
        os.write(fd, raw)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, args.output)
    finally:
        if fd >= 0:
            os.close(fd)
        if os.path.exists(temporary):
            os.unlink(temporary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
