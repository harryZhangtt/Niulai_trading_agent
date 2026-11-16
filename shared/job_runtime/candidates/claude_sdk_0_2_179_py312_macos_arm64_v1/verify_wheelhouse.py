#!/usr/bin/env python3
"""Strictly read-only verification against a caller-supplied reviewed seal hash."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from wheel_gate import verify_frozen


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--expected-seal-sha256",required=True)
    args=parser.parse_args()
    print(json.dumps(verify_frozen(args.candidate,args.expected_seal_sha256),sort_keys=True,separators=(",",":")))
    return 0

if __name__=="__main__": raise SystemExit(main())
