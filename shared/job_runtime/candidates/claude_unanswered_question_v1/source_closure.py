"""Physical package source-closure verification."""
from __future__ import annotations
import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Mapping
from .contracts import ContractError, canonical_bytes, digest, require


def load_source_closure(path=None):
    target = path or Path(__file__).with_name("source-closure-v1.json")
    try: value = json.loads(target.read_text(encoding="ascii"))
    except (OSError, ValueError, UnicodeError): raise ContractError("SOURCE_CLOSURE_MISMATCH") from None
    require(type(value) is dict and set(value) == {"schema_version", "algorithm", "files", "closure_sha256"}, "SOURCE_CLOSURE_MISMATCH")
    require(value["schema_version"] == 1 and value["algorithm"] == "sha256-canonical-path-sha-bytes-v1", "SOURCE_CLOSURE_MISMATCH")
    require(value["closure_sha256"] == digest({"schema_version": 1, "files": value["files"]}), "SOURCE_CLOSURE_MISMATCH")
    return value


def verify_source_closure(root: Path, manifest: Mapping[str, Any]) -> str:
    require(isinstance(root, Path) and root.is_absolute() and not root.is_symlink(), "SOURCE_CLOSURE_MISMATCH")
    actual = []
    for path in sorted(root.rglob("*")):
        if path.name == "source-closure-v1.json" or "__pycache__" in path.parts: continue
        require(not path.is_symlink(), "SOURCE_CLOSURE_MISMATCH")
        if path.is_file():
            info = path.stat(); require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "SOURCE_CLOSURE_MISMATCH")
            raw = path.read_bytes(); actual.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
    require(actual == manifest["files"], "SOURCE_CLOSURE_MISMATCH")
    require(manifest["closure_sha256"] == digest({"schema_version": 1, "files": actual}), "SOURCE_CLOSURE_MISMATCH")
    return manifest["closure_sha256"]
