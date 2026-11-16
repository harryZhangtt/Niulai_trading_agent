"""Reproducible physical source-closure validation for the candidate package."""
from __future__ import annotations

import hashlib
from pathlib import Path
import stat
from typing import Any, Mapping

from .canonical import canonical_json_bytes, strict_json_loads


class ClosureError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _digest(files: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json_bytes({"schema_version": 1, "files": files})).hexdigest()


def load_source_closure(path: Path | None = None) -> Mapping[str, Any]:
    target = path or Path(__file__).with_name("source-closure-v1.json")
    try:
        value = strict_json_loads(target.read_bytes(), maximum=131_072)
    except Exception:
        raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH") from None
    if type(value) is not dict or set(value) != {"schema_version", "algorithm", "files", "closure_sha256"} or value["schema_version"] != 1 or value["algorithm"] != "sha256-canonical-path-sha-bytes-v1" or type(value["files"]) is not list or value["closure_sha256"] != _digest(value["files"]):
        raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
    return value


def verify_source_closure(root: Path, manifest: Mapping[str, Any]) -> str:
    if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink() or type(manifest) is not dict:
        raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
    expected = manifest.get("files")
    if type(expected) is not list:
        raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
    actual = []
    for path in sorted(root.rglob("*")):
        if path.name == "source-closure-v1.json" or "__pycache__" in path.parts:
            continue
        if path.is_symlink():
            raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
        if path.is_file():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
            raw = path.read_bytes()
            actual.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    if actual != expected or manifest.get("closure_sha256") != _digest(actual):
        raise ClosureError("CANARY_SOURCE_CLOSURE_MISMATCH")
    return manifest["closure_sha256"]
