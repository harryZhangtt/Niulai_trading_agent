#!/usr/bin/env python3
"""Explicit opt-in for this native Codex conversation, backed by target state."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from session import session

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default=str(Path.cwd()))
    args = parser.parse_args()
    result = session(args.project, 'enable')
    print(json.dumps(result, indent=2))
    raise SystemExit(result['status'] != 'HARRY_UI_SESSION_ENABLED')
