"""Source-pinned fixture authority verifier with no caller-selected trust inputs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, STATUS, canonical_bytes, exact, require, validate_grant

_ROOT = Path(__file__).resolve().parent

@dataclass(frozen=True)
class _PinnedSource:
    relative_path: str
    size: int
    sha256: str

_REGISTRY = _PinnedSource("fixtures/authority/source-registry-v1.json", 410, "f16071dc937a5adba060b36df3034f40e298092eae43c645cb622a5b2baa816f")
_GRANT = _PinnedSource("fixtures/authority/block-grant-v1.json", 1783, "bbb189e5f04e0c109a1bdd4fc4119645c2c1c54d2bff0776e8012041f849e9e2")
_REVIEW = _PinnedSource("fixtures/authority/block-grant-review-v1.json", 183, "77073ec4c10efe2fb135c3ddf60869bbb51bc212b5b286608b6d2087da61eb8e")


def _verify_pinned_bytes(source: _PinnedSource, raw: bytes) -> Mapping[str, Any]:
    require(len(raw) == source.size, "PINNED_SOURCE_SIZE_DRIFT")
    require(hashlib.sha256(raw).hexdigest() == source.sha256, "PINNED_SOURCE_HASH_DRIFT")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("PINNED_SOURCE_JSON") from exc
    require(canonical_bytes(value) == raw, "PINNED_SOURCE_NOT_CANONICAL")
    return value


def _read(source: _PinnedSource) -> Mapping[str, Any]:
    path = _ROOT / source.relative_path
    require(path.is_file() and not path.is_symlink(), "PINNED_SOURCE_NOT_REGULAR")
    return _verify_pinned_bytes(source, path.read_bytes())


def verify_authority() -> Mapping[str, Any]:
    """Verify the fixed fixture sources; this function cannot issue live authority."""
    registry = exact(_read(_REGISTRY), ("version", "candidate_status", "activation", "block_grant", "block_grant_review"), "REGISTRY_SHAPE")
    require(registry["version"] == 1 and registry["candidate_status"] == STATUS and registry["activation"] is False, "REGISTRY_STATUS")
    for name, pinned in (("block_grant", _GRANT), ("block_grant_review", _REVIEW)):
        ref = exact(registry[name], ("path", "sha256", "bytes"), "REGISTRY_REF_SHAPE")
        require(ref == {"path": pinned.relative_path, "sha256": pinned.sha256, "bytes": pinned.size}, "REGISTRY_REF_DRIFT")
    grant = validate_grant(_read(_GRANT))
    review = exact(_read(_REVIEW), ("version", "status", "subject_sha256", "authority_issued", "live_approved"), "REVIEW_SHAPE")
    require(review == {"version": 1, "status": "CLEAN_FIXTURE_CONTRACT_ONLY", "subject_sha256": _GRANT.sha256, "authority_issued": False, "live_approved": False}, "REVIEW_DRIFT")
    return {"registry": registry, "grant": grant, "review": review}


__all__ = ["verify_authority"]
