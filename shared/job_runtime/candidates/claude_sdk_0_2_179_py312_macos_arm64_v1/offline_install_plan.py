#!/usr/bin/env python3
"""Emit a sealed offline-install plan; this utility cannot install."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wheel_gate import read_fd_all, stable_identity, validate_owned, verify_frozen

CANDIDATE = Path(__file__).resolve().parent
WORKSPACE = CANDIDATE.parents[3]
WHEELHOUSE = (CANDIDATE / "wheelhouse").resolve()
LOCK = (CANDIDATE / "seal-v4/requirements.lock.txt").resolve()
EMPTY_PIP_CONFIG = CANDIDATE / "pip-empty.conf"
SHA_RE = re.compile(r"[0-9a-f]{64}")
ARM64_MACHO64_MAGIC = b"\xcf\xfa\xed\xfe"
ARM64_CPU_TYPE_LE = b"\x0c\x00\x00\x01"
UNSET_ENV = [
    "ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
    "all_proxy", "https_proxy", "http_proxy", "no_proxy",
    "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PIP_CACHE_DIR",
    "UV_INDEX", "UV_DEFAULT_INDEX", "UV_EXTRA_INDEX_URL", "UV_FIND_LINKS",
    "UV_CACHE_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
]


def open_project_file(path: Path, *, require_executable: bool = False) -> tuple[int, os.stat_result]:
    if not path.is_absolute():
        raise ValueError("interpreter path must be absolute")
    try:
        relative = path.relative_to(WORKSPACE)
    except ValueError:
        raise ValueError("interpreter must be project-local")
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("unsafe interpreter path")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(WORKSPACE, flags_dir)
    try:
        validate_owned(os.fstat(current), directory=True)
        for component in relative.parts[:-1]:
            child = os.open(component, flags_dir, dir_fd=current)
            os.close(current)
            current = child
            validate_owned(os.fstat(current), directory=True)
        fd = os.open(relative.parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
    finally:
        os.close(current)
    info = os.fstat(fd)
    validate_owned(info, directory=False)
    if require_executable and not info.st_mode & stat.S_IXUSR:
        os.close(fd)
        raise ValueError("interpreter is not owner-executable")
    return fd, info


def inspect_interpreter(path: Path, expected_sha256: str, expected_version: str) -> dict:
    if not SHA_RE.fullmatch(expected_sha256):
        raise ValueError("expected interpreter SHA256 must be 64 lowercase hex characters")
    if not re.fullmatch(r"3\.12\.[0-9]+", expected_version):
        raise ValueError("expected interpreter version must be exact Python 3.12.x")
    fd, before = open_project_file(path, require_executable=True)
    try:
        data = read_fd_all(fd, 64 * 1024 * 1024)
        if data[:4] != ARM64_MACHO64_MAGIC or data[4:8] != ARM64_CPU_TYPE_LE:
            raise ValueError("interpreter must be a thin arm64 Mach-O 64 executable")
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_sha256:
            raise ValueError("interpreter SHA256 mismatch")
        probe_env = {"PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1"}
        path_before=os.stat(path,follow_symlinks=False)
        if stable_identity(before)!=stable_identity(path_before): raise ValueError("interpreter pathname identity mismatch before probe")
        probe = subprocess.run(
            [str(path), "-I", "--version"],
            check=True, capture_output=True, text=True, env=probe_env, timeout=10,
        )
        path_after=os.stat(path,follow_symlinks=False)
        if stable_identity(before)!=stable_identity(path_after): raise ValueError("interpreter pathname identity mismatch after probe")
        reported = (probe.stdout or probe.stderr).strip()
        if reported != f"Python {expected_version}":
            raise ValueError(f"interpreter version mismatch: {reported!r}")
        if stable_identity(before) != stable_identity(os.fstat(fd)):
            raise ValueError("interpreter identity changed during validation")
    finally:
        os.close(fd)
    return {
        "path": str(path), "sha256": digest, "version": expected_version,
        "format": "Mach-O 64-bit arm64", "size": before.st_size,
    }


def validate_empty_pip_config() -> dict:
    fd, before = open_project_file(EMPTY_PIP_CONFIG)
    try:
        data = read_fd_all(fd, 1)
        if data != b"" or hashlib.sha256(data).hexdigest() != hashlib.sha256(b"").hexdigest():
            raise ValueError("reviewed pip config must be empty")
        if stable_identity(before) != stable_identity(os.fstat(fd)):
            raise ValueError("pip config identity changed during validation")
    finally:
        os.close(fd)
    return {"path": str(EMPTY_PIP_CONFIG), "sha256": hashlib.sha256(b"").hexdigest(), "bytes": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-seal-sha256", required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--expected-python-sha256", required=True)
    parser.add_argument("--expected-python-version", required=True)
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    gate = verify_frozen(CANDIDATE, args.expected_seal_sha256)
    interpreter = inspect_interpreter(args.python, args.expected_python_sha256, args.expected_python_version)
    pip_config = validate_empty_pip_config()
    if WHEELHOUSE != (CANDIDATE / "wheelhouse").resolve() or LOCK != (CANDIDATE / "seal-v4/requirements.lock.txt").resolve():
        raise ValueError("candidate directory binding mismatch")
    if args.venv.exists() or args.receipt.exists():
        raise ValueError("target venv and receipt must not exist")
    venv_python = args.venv / "bin/python"
    fixed_env = {
        "PATH": f"{args.venv / 'bin'}:/usr/bin:/bin",
        "PIP_CONFIG_FILE": str(EMPTY_PIP_CONFIG),
        "PIP_NO_INDEX": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_CACHE_DIR": "1",
        "PYTHONNOUSERSITE": "1",
    }
    commands = [
        [str(args.python), "-I", "-m", "venv", str(args.venv)],
        [
            str(venv_python), "-I", "-m", "pip", "install",
            "--isolated", "--no-cache-dir", "--disable-pip-version-check",
            "--no-index", "--find-links", str(WHEELHOUSE), "--require-hashes",
            "--only-binary=:all:", "-r", str(LOCK),
        ],
    ]
    plan = {
        "schema_version": 2,
        "status": "PLAN_ONLY_NOT_EXECUTED",
        "execution_available": False,
        "candidate": str(CANDIDATE),
        "expected_seal_sha256": args.expected_seal_sha256,
        "wheelhouse": str(WHEELHOUSE),
        "wheelhouse_sha256": gate["wheelhouse_sha256"],
        "control_sha256": gate["control_sha256"],
        "interpreter": interpreter,
        "pip_config": pip_config,
        "commands": commands,
        "environment": {"set": fixed_env, "unset": UNSET_ENV, "inherit": []},
        "network_policy": {
            "index": "disabled",
            "required_flags": [
                "--isolated", "--no-cache-dir", "--disable-pip-version-check",
                "--no-index", "--find-links", "--require-hashes",
                "--only-binary=:all:",
            ],
        },
        "receipt_path": str(args.receipt),
        "receipt_requirements": [
            "exact interpreter path, SHA256, arm64 Mach-O format, and Python version",
            "external reviewed seal SHA256 and all frozen control hashes",
            "installed RECORD SHA256",
            "installed distribution tree SHA256",
            "provider-free preflight surface result",
            "explicit statement that production lock was not activated",
        ],
    }
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
