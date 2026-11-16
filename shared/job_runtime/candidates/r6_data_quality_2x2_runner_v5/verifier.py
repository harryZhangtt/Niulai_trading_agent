"""Standalone stdlib-only descriptor verifier for durable v5 state."""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_regular_at(directory_fd, name, maximum=1_048_576):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, dir_fd=directory_fd)
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1:
            raise RuntimeError("RUNNER_V5_DURABLE_FILE_UNSAFE")
        chunks, total = [], 0
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            total += len(part)
            if total > maximum:
                raise RuntimeError("RUNNER_V5_DURABLE_FILE_SIZE")
            chunks.append(part)
        return b"".join(chunks)
    finally:
        os.close(fd)


def open_safe_dir(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(str(path), flags)
    meta = os.fstat(fd)
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
        os.close(fd)
        raise RuntimeError("RUNNER_V5_DURABLE_DIRECTORY_UNSAFE")
    return fd


def main():
    try:
        raw_req = sys.stdin.buffer.read(262145)
        if len(raw_req) > 262144:
            raise RuntimeError("RUNNER_V5_VERIFY_REQUEST_SIZE")
        req = json.loads(raw_req.decode("ascii"))
        if canonical(req) != raw_req or set(req) != {"key", "manifest_sha256", "owner_root", "request_sha256"}:
            raise RuntimeError("RUNNER_V5_VERIFY_REQUEST")
        root_fd = open_safe_dir(Path(req["owner_root"]).absolute())
        state_fd = -1
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            state_fd = os.open(".r6-data-quality-runner-v5", flags, dir_fd=root_fd)
            meta = os.fstat(state_fd)
            if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
                raise RuntimeError("RUNNER_V5_STATE_DIRECTORY_UNSAFE")
            raw = read_regular_at(state_fd, "state-" + req["key"] + ".json")
            state = json.loads(raw.decode("ascii"))
            if canonical(state) != raw:
                raise RuntimeError("RUNNER_V5_STATE_NOT_CANONICAL")
            if state.get("status") != "COMPLETED":
                raise RuntimeError("RUNNER_V5_UNKNOWN_NO_REPLAY")
            if state.get("manifest_sha256") != req["manifest_sha256"] or state.get("request_sha256") != req["request_sha256"] or state.get("key") != req["key"]:
                raise RuntimeError("RUNNER_V5_STATE_BINDING")
            result = state["result"]
            receipt = state.get("underlying_receipt")
            if receipt is not None:
                receipt_dir = os.open("receipt", flags, dir_fd=root_fd)
                try:
                    body = read_regular_at(receipt_dir, "block-v6.json")
                finally:
                    os.close(receipt_dir)
                if len(body) != receipt["bytes"] or sha(body) != receipt["sha256"]:
                    raise RuntimeError("RUNNER_V5_UNDERLYING_RECEIPT_BINDING")
            sys.stdout.buffer.write(canonical(result))
            sys.stdout.buffer.flush()
            return 0
        finally:
            if state_fd >= 0:
                os.close(state_fd)
            os.close(root_fd)
    except BaseException:
        return 70


if __name__ == "__main__":
    raise SystemExit(main())
