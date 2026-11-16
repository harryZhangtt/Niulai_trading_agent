"""Strict contracts and source-pinned authority for the disabled candidate."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

RELEASE = "0.167.0"
MODEL = "gpt-6.1-sol"
TARGET = "/backend-api/codex/models?client_version=0.167.0"
MAX_BODY_BYTES = 1024 * 1024
MAX_MODELS = 512
GRANT = ("tuning/architecture/r6_one_off_codex_direct_catalog_v1/fixed-design-grant-v1.json", 592, "9971b5a996f3cec0363b6125ef6d79601580d2e4de1d425c141acafffc6f4b85")
REVIEW = ("tuning/architecture/r6_one_off_codex_direct_catalog_v1/fixed-design-grant-review-v1.json", 278, "885e0792e8667d8fb5bc083a6a290492c8428530848db3e2669d46237c4cef4c")

class ContractError(RuntimeError):
    pass

class CatalogExecutionError(RuntimeError):
    def __init__(self, code: str, receipt: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(code)
        self.code = code
        self.receipt = dict(receipt) if receipt is not None else None

@dataclass(frozen=True)
class OriginEvidence:
    kind: str
    host: str
    tls_hostname_verified: bool

@dataclass(frozen=True)
class CatalogResult:
    models: Tuple[str, ...]
    receipt: Mapping[str, Any]
    origin: OriginEvidence
    owner_private_raw: Optional[bytes] = field(default=None, repr=False)

def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def strict_json(raw: bytes) -> Any:
    def pairs(values: Sequence[Tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in values:
            if key in out:
                raise ContractError("DUPLICATE_JSON_KEY")
            out[key] = value
        return out
    try:
        return json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError("NONFINITE_JSON")))
    except ContractError:
        raise
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError("MALFORMED_JSON") from exc

def parse_catalog(raw: bytes) -> Tuple[str, ...]:
    if not raw or len(raw) > MAX_BODY_BYTES:
        raise ContractError("BODY_SIZE_REJECTED")
    value = strict_json(raw)
    if type(value) is not dict or set(value) != {"models"}:
        raise ContractError("CATALOG_SCHEMA_REJECTED")
    models = value["models"]
    if type(models) is not list or not (1 <= len(models) <= MAX_MODELS):
        raise ContractError("CATALOG_SCHEMA_REJECTED")
    slugs = []
    seen = set()
    for model in models:
        if type(model) is not dict or "slug" not in model or not model:
            raise ContractError("MODEL_SCHEMA_REJECTED")
        if not all(type(key) is str and 0 < len(key) <= 128 for key in model):
            raise ContractError("MODEL_SCHEMA_REJECTED")
        slug = model["slug"]
        if type(slug) is not str or not slug or slug != slug.strip() or len(slug) > 128 or slug in seen:
            raise ContractError("MODEL_SLUG_REJECTED")
        seen.add(slug)
        slugs.append(slug)
    if slugs.count(MODEL) != 1:
        raise ContractError("REQUIRED_MODEL_REJECTED")
    return tuple(slugs)

def _root() -> Path:
    return Path(__file__).resolve().parents[4]

def _read_bound(ref: Tuple[str, int, str]) -> bytes:
    root = _root().resolve()
    relative = Path(ref[0])
    if relative.is_absolute() or ".." in relative.parts:
        raise ContractError("AUTHORITY_PATH_REJECTED")
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise ContractError("AUTHORITY_UNAVAILABLE") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ContractError("AUTHORITY_PATH_REJECTED")
    path = root / relative
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(path), flags)
    except OSError as exc:
        raise ContractError("AUTHORITY_UNAVAILABLE") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ContractError("AUTHORITY_OWNERSHIP_REJECTED")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    raw = b"".join(chunks)
    if len(raw) != ref[1] or sha256(raw) != ref[2]:
        raise ContractError("AUTHORITY_IDENTITY_REJECTED")
    return raw

def load_fixed_authority() -> None:
    grant = strict_json(_read_bound(GRANT))
    review = strict_json(_read_bound(REVIEW))
    expected_endpoint = {"scheme": "https", "host": "chatgpt.com", "port": 443,
                         "method": "GET", "path_query": TARGET}
    expected_limits = {"physical_forwards": 1, "inference_requests": 0, "redirects": 0,
                       "retries": 0, "replays": 0, "body_bytes": 0, "timeout_seconds": 5}
    if type(grant) is not dict or set(grant) != {"version", "status", "grant_id", "activation", "provider", "release", "model", "endpoint", "limits", "auth"}:
        raise ContractError("GRANT_REJECTED")
    if grant["version"] != "r6-one-off-codex-direct-catalog-design-grant-v1" or grant["status"] != "APPROVED_DISABLED_DIRECT_CATALOG_ONLY":
        raise ContractError("GRANT_REJECTED")
    if grant["activation"] is not False or grant["provider"] != "codex" or grant["release"] != RELEASE or grant["model"] != MODEL:
        raise ContractError("GRANT_REJECTED")
    if grant["endpoint"] != expected_endpoint or grant["limits"] != expected_limits:
        raise ContractError("GRANT_REJECTED")
    if grant["auth"] != {"capability": "TransientBearer", "copies": 0, "persistence": False, "reuse": False}:
        raise ContractError("GRANT_REJECTED")
    if type(review) is not dict or set(review) != {"version", "review_id", "independent_from_executor", "grant_sha256", "verdict"}:
        raise ContractError("REVIEW_REJECTED")
    if review["version"] != "r6-one-off-codex-direct-catalog-grant-review-v1" or review["independent_from_executor"] is not True:
        raise ContractError("REVIEW_REJECTED")
    if review["grant_sha256"] != GRANT[2] or review["verdict"] != "CLEAN_DISABLED_DIRECT_CATALOG_ONLY":
        raise ContractError("REVIEW_REJECTED")
