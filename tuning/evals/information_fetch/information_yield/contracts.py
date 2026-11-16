"""Closed contracts and bounded artifact loading for EIY v1."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
from typing import Any

VERSION = "information-yield-evaluation-1"
RESULT_VERSION = "information-yield-result-1"
CASE_VERSION = "information-yield-case-1"
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_RESULT_BYTES = 512 * 1024
MAX_CASES = 64
MAX_UNITS = 4096
MAX_FIELDS = 1024
MAX_STRING = 512
SHA = re.compile(r"[a-f0-9]{64}")
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
SECRET = re.compile(r"(?i)(?:bearer\s+\S+|github_pat_|(?:ghp|gho|ghu|ghs|ghr)_|sk-proj-|access[_-]?token|refresh[_-]?token|password|private[_-]?key)")
FORBIDDEN_PATH_TOKENS = frozenset({"auth", "authentication", "oauth", "oauth2", "credential", "credentials", "secret", "secrets", "env"})

HARD_FAILURES = frozenset({
    "FUTURE_EXPOSURE", "UNKNOWN_EXPOSURE", "FABRICATED_SUPPORT",
    "OPENLESS_SUPPORT", "UNKNOWN_OUTCOME_REPLAY", "DUPLICATE_DISPATCH",
    "BUDGET_VIOLATION", "DEADLINE_VIOLATION", "SOURCE_MISMATCH",
    "VERSION_MISMATCH", "URL_MISMATCH", "QUOTE_MISMATCH", "SECRET_LEAK",
    "HOLDOUT_LEAK", "MISSING_TRACE", "SILENT_CASE_REMOVAL",
    "UNCLASSIFIED_FAILURE", "UNRECONCILED_CHECKPOINT",
})
STATES = {"unknown": 0, "partial": 1, "resolved": 2}
NOVELTY = frozenset({"new_fact", "refinement", "counterevidence"})

class InformationYieldError(ValueError):
    pass

@dataclass(frozen=True)
class ArtifactRef:
    path: str
    sha256: str

    @classmethod
    def parse(cls, value: Any) -> "ArtifactRef":
        exact_keys(value, {"path", "sha256"}, "EIY_REF_FIELDS")
        path = safe_rel(value["path"])
        digest = value["sha256"]
        need(isinstance(digest, str) and SHA.fullmatch(digest), "EIY_REF_SHA")
        return cls(path, digest)


def need(condition: bool, code: str) -> None:
    if not condition:
        raise InformationYieldError(code)


def exact_keys(value: Any, keys: set[str], code: str) -> None:
    need(isinstance(value, dict) and set(value) == keys, code)


def safe_id(value: Any, code: str = "EIY_ID") -> str:
    need(isinstance(value, str) and IDENT.fullmatch(value) is not None, code)
    need(not SECRET.search(value), code)
    return value


def safe_text(value: Any, code: str, maximum: int = MAX_STRING) -> str:
    need(isinstance(value, str) and 0 < len(value) <= maximum, code)
    need("\x00" not in value and "<" not in value and ">" not in value and not SECRET.search(value), code)
    return value


def safe_rel(value: Any) -> str:
    need(isinstance(value, str) and 0 < len(value) <= 255, "EIY_PATH")
    need(not value.startswith(("/", "~")) and "\\" not in value, "EIY_PATH")
    parts = Path(value).parts
    need(parts and all(p not in ("", ".", "..") for p in parts), "EIY_PATH")
    need(not any(SECRET.search(p) for p in parts), "EIY_PATH")
    for part in parts:
        tokens = {t.lower() for t in re.split(r"[._-]+", part) if t}
        need(not (tokens & FORBIDDEN_PATH_TOKENS), "EIY_PATH")
    return value


def integer(value: Any, low: int, high: int, code: str) -> int:
    need(type(value) is int and low <= value <= high, code)
    return value


def number(value: Any, low: float, high: float, code: str) -> float:
    need(type(value) in (int, float) and math.isfinite(value) and low <= float(value) <= high, code)
    return float(value)


def unique_strings(value: Any, maximum: int, code: str, *, allow_empty: bool = True) -> list[str]:
    need(isinstance(value, list) and len(value) <= maximum, code)
    if not allow_empty:
        need(bool(value), code)
    out = [safe_id(v, code) for v in value]
    need(len(set(out)) == len(out), code)
    return out


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InformationYieldError("EIY_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise InformationYieldError("EIY_JSON_INVALID") from exc


def decode(data: bytes, limit: int, code: str) -> Any:
    need(0 < len(data) <= limit, code)
    try:
        return json.loads(data, object_pairs_hook=_object_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(InformationYieldError("EIY_JSON_NONFINITE")))
    except InformationYieldError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise InformationYieldError(code) from exc


def read_relative(root: Path, relative: str, *, max_bytes: int) -> bytes:
    """Read a workspace-relative regular file through held no-follow descriptors."""
    rel = safe_rel(relative)
    root = root.resolve()
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root, flags_dir)
    try:
        parts = Path(rel).parts
        for part in parts[:-1]:
            nxt = os.open(part, flags_dir, dir_fd=current)
            os.close(current)
            current = nxt
        fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
        try:
            before = os.fstat(fd)
            need((before.st_mode & 0o170000) == 0o100000 and before.st_nlink == 1,
                 "EIY_PATH_TYPE")
            need(before.st_uid == os.getuid() and before.st_size <= max_bytes,
                 "EIY_PATH_TYPE")
            chunks = []
            remaining = max_bytes + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(fd)
            need((before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                  before.st_nlink, before.st_size, before.st_mtime_ns,
                  before.st_ctime_ns) ==
                 (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                  after.st_nlink, after.st_size, after.st_mtime_ns,
                  after.st_ctime_ns), "EIY_PATH_CHANGED")
            data = b"".join(chunks)
            need(len(data) <= max_bytes, "EIY_ARTIFACT_SIZE")
            return data
        finally:
            os.close(fd)
    except InformationYieldError:
        raise
    except OSError as exc:
        raise InformationYieldError("EIY_PATH_UNAVAILABLE") from exc
    finally:
        os.close(current)


def reopen(root: Path, ref_value: Any, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> tuple[Any, ArtifactRef]:
    ref = ArtifactRef.parse(ref_value)
    data = read_relative(root, ref.path, max_bytes=max_bytes)
    need(sha256(data).hexdigest() == ref.sha256, "EIY_ARTIFACT_DRIFT")
    return decode(data, max_bytes, "EIY_ARTIFACT_JSON"), ref

def digest(value: Any) -> str:
    return sha256(canonical(value)).hexdigest()


def write_once(path: Path, payload: bytes, *, workspace_root: Path) -> bool:
    """Publish one immutable result relative to a held workspace directory."""
    root = workspace_root.absolute()
    path = path.absolute() if path.is_absolute() else root / path
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise InformationYieldError("EIY_OUTPUT_PATH") from exc
    parts = relative.parts
    need(parts and all(p not in ("", ".", "..") for p in parts), "EIY_OUTPUT_PATH")
    flags_dir = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current = os.open(root, flags_dir)
    temp_name = f".{parts[-1]}.{os.getpid()}.tmp"

    def existing_exact() -> bool:
        try:
            fd = os.open(parts[-1], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=current)
        except FileNotFoundError:
            return False
        try:
            before = os.fstat(fd)
            need((before.st_mode & 0o170000) == 0o100000 and before.st_uid == os.getuid()
                 and before.st_nlink == 1 and (before.st_mode & 0o077) == 0,
                 "EIY_OUTPUT_CONFLICT")
            data = b""
            while len(data) <= len(payload):
                chunk = os.read(fd, min(65536, len(payload) + 1 - len(data)))
                if not chunk:
                    break
                data += chunk
            after = os.fstat(fd)
            need((before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                  before.st_nlink, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                 (after.st_dev, after.st_ino, after.st_mode, after.st_uid,
                  after.st_nlink, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                 "EIY_OUTPUT_CONFLICT")
            need(data == payload, "EIY_OUTPUT_CONFLICT")
            return True
        finally:
            os.close(fd)

    try:
        for part in parts[:-1]:
            try:
                nxt = os.open(part, flags_dir, dir_fd=current)
            except FileNotFoundError:
                os.mkdir(part, 0o700, dir_fd=current)
                nxt = os.open(part, flags_dir, dir_fd=current)
            st = os.fstat(nxt)
            need(st.st_uid == os.getuid() and (st.st_mode & 0o077) == 0,
                 "EIY_OUTPUT_PATH")
            os.close(current)
            current = nxt
        if existing_exact():
            return True
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=current)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.link(temp_name, parts[-1], src_dir_fd=current, dst_dir_fd=current,
                    follow_symlinks=False)
            os.unlink(temp_name, dir_fd=current)
            os.fsync(current)
            return False
        except FileExistsError:
            os.unlink(temp_name, dir_fd=current)
            need(existing_exact(), "EIY_OUTPUT_CONFLICT")
            return True
    except InformationYieldError:
        raise
    except OSError as exc:
        raise InformationYieldError("EIY_OUTPUT_UNKNOWN") from exc
    finally:
        try:
            os.unlink(temp_name, dir_fd=current)
        except (FileNotFoundError, OSError):
            pass
        os.close(current)

