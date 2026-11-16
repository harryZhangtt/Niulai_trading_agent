"""Raw-first immutable no-replace commit with restart recovery."""
from __future__ import annotations
from dataclasses import dataclass
import json, os, stat
from pathlib import Path
from typing import Any, Dict, Mapping, Optional
from .contracts import canonical_bytes, sha256_bytes, strict_json_loads, validate_bundle

class BundleError(ValueError):
    pass

@dataclass(frozen=True)
class BundleReceipt:
    raw_path: Path
    bundle_path: Path
    raw_sha256: str
    bundle_sha256: str
    raw_committed_before_decision: bool
    no_replace: bool
    recovered: bool

class RawDecisionStore:
    def __init__(self, root: Path, fault: Optional[str] = None) -> None:
        self.root = Path(root); self.fault = fault

    def _open_dir(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(self.root, 0o700)
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        meta = os.fstat(fd)
        if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o700:
            os.close(fd); raise BundleError("UNSAFE_DIRECTORY")
        return fd

    @staticmethod
    def _write_once(fd: int, name: str, raw: bytes) -> None:
        try: out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
        except FileExistsError: raise BundleError("NO_REPLACE") from None
        try:
            view = memoryview(raw)
            while view:
                n = os.write(out, view)
                if n <= 0: raise BundleError("SHORT_WRITE")
                view = view[n:]
            os.fsync(out)
        finally: os.close(out)
        os.fsync(fd)

    @staticmethod
    def _read(fd: int, name: str) -> bytes:
        try: inp = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        except OSError: raise BundleError("READ_FAILED") from None
        try:
            meta = os.fstat(inp)
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_nlink != 1:
                raise BundleError("UNSAFE_FILE")
            chunks = []
            while True:
                part = os.read(inp, 16384)
                if not part: break
                chunks.append(part)
                if sum(map(len, chunks)) > 1048576: raise BundleError("TOO_LARGE")
            return b"".join(chunks)
        finally: os.close(inp)

    def commit(self, raw: bytes, bundle: Mapping[str, Any]) -> BundleReceipt:
        if type(raw) is not bytes: raise BundleError("RAW_BYTES_REQUIRED")
        value = dict(bundle); validate_bundle(value)
        if sha256_bytes(raw) != value["raw_sha256"] or raw.decode("ascii") != value["raw_body_ascii"]: raise BundleError("RAW_BUNDLE_MISMATCH")
        cell_id = value["cell"]["plan"]["cell_id"]; raw_name = cell_id + ".raw"; bundle_name = cell_id + ".bundle.json"
        bundle_raw = canonical_bytes(value); fd = self._open_dir(); recovered = False
        try:
            try: self._write_once(fd, raw_name, raw)
            except BundleError as exc:
                if str(exc) != "NO_REPLACE" or self._read(fd, raw_name) != raw: raise
                recovered = True
            if self.fault == "after_raw": raise BundleError("CRASH_AFTER_RAW")
            try: self._write_once(fd, bundle_name, bundle_raw)
            except BundleError as exc:
                if str(exc) != "NO_REPLACE": raise
                existing = self._read(fd, bundle_name)
                if existing != bundle_raw: raise BundleError("COMPLETED_BUNDLE_CONFLICT") from None
                try:
                    parsed = strict_json_loads(existing.decode("ascii"), "COMPLETED_BUNDLE_NONCANONICAL")
                except (UnicodeError, ValueError): raise BundleError("COMPLETED_BUNDLE_NONCANONICAL") from None
                validate_bundle(parsed)
                if canonical_bytes(parsed) != existing: raise BundleError("COMPLETED_BUNDLE_NONCANONICAL")
                recovered = True
            if self._read(fd, raw_name) != raw or self._read(fd, bundle_name) != bundle_raw: raise BundleError("READBACK_MISMATCH")
            return BundleReceipt(self.root/raw_name, self.root/bundle_name, sha256_bytes(raw), sha256_bytes(bundle_raw), True, True, recovered)
        finally: os.close(fd)

def read_bundle(path: Path, expected_sha256: str) -> Dict[str, Any]:
    store = RawDecisionStore(Path(path).parent); fd = store._open_dir()
    try: raw = store._read(fd, Path(path).name)
    finally: os.close(fd)
    if sha256_bytes(raw) != expected_sha256: raise BundleError("READBACK_DIGEST")
    try: value = strict_json_loads(raw.decode("ascii"), "READBACK_JSON")
    except (UnicodeError, ValueError): raise BundleError("READBACK_JSON") from None
    validate_bundle(value)
    if canonical_bytes(value) != raw: raise BundleError("READBACK_CANONICAL")
    return value

__all__ = ["BundleError", "BundleReceipt", "RawDecisionStore", "read_bundle"]
