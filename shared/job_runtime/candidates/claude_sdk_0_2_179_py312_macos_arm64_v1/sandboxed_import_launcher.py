#!/usr/bin/env python3
"""Trusted in-process seatbelt launcher for the sealed import preflight."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import sys

PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(deny process-fork)
(deny process-exec)
"""
PROFILE_SHA256 = hashlib.sha256(PROFILE.encode()).hexdigest()


def activate_sandbox() -> dict[str, object]:
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    sandbox_init = library.sandbox_init
    sandbox_init.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_char_p)]
    sandbox_init.restype = ctypes.c_int
    sandbox_free_error = library.sandbox_free_error
    sandbox_free_error.argtypes = [ctypes.c_char_p]
    sandbox_free_error.restype = None
    error = ctypes.c_char_p()
    rc = sandbox_init(PROFILE.encode(), 0, ctypes.byref(error))
    detail = None
    if error.value:
        detail = error.value.decode("utf-8", "replace")
        sandbox_free_error(error)
    evidence = {
        "sandbox_init_rc": rc,
        "profile_sha256": PROFILE_SHA256,
        "network_denied": True,
        "file_writes_denied": True,
        "process_fork_denied": True,
        "process_exec_denied": True,
    }
    if rc != 0:
        evidence["error"] = detail or f"errno={ctypes.get_errno()}"
        print("SANDBOX_INIT_BLOCKED " + json.dumps(evidence, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)
        raise SystemExit(70)
    print("SANDBOX_INIT_OK " + json.dumps(evidence, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)
    return evidence


def run_preflight(requirements: Path, lock: Path) -> int:
    # This is the exact plan import, deliberately after sandbox activation.
    from shared.job_runtime.claude_sdk_preflight import inspect_environment
    result = inspect_environment(requirements, lock)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return 0 if result["status"] == "READY_OFFLINE" else 2


def run_self_test(mode: str, write_path: Path | None) -> int:
    try:
        if mode == "read_import":
            import fractions
            Path(__file__).read_bytes()
            print(json.dumps({"mode": mode, "status": "ALLOWED", "fraction": str(fractions.Fraction(1, 2))}, sort_keys=True))
            return 0
        if mode == "network":
            socket.create_connection(("127.0.0.1", 9), timeout=0.1)
        elif mode == "write":
            assert write_path is not None
            write_path.write_text("forbidden")
        elif mode == "fork":
            os.fork()
        elif mode == "exec":
            os.execv("/usr/bin/true", ["/usr/bin/true"])
        else:
            raise ValueError("unknown self-test")
    except OSError as exc:
        print(json.dumps({"mode": mode, "status": "DENIED", "errno": exc.errno}, sort_keys=True))
        return 0
    print(json.dumps({"mode": mode, "status": "UNEXPECTEDLY_ALLOWED"}, sort_keys=True))
    return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--self-test", choices=("read_import", "network", "write", "fork", "exec"))
    parser.add_argument("--write-path", type=Path)
    args = parser.parse_args(argv)
    activate_sandbox()
    if args.self_test:
        return run_self_test(args.self_test, args.write_path)
    if args.requirements is None or args.lock is None:
        parser.error("--requirements and --lock are required")
    return run_preflight(args.requirements, args.lock)


if __name__ == "__main__":
    raise SystemExit(main())
