"""Frozen contracts for the disabled one-shot Codex credential broker."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Mapping, Optional, Tuple

MODEL = "gpt-6.1-sol"
CODEX_RELEASE = "0.167.0"
CREDENTIAL_FORMAT = "codex-auth-dot-json-v0.167.0"
FIXED_CREDENTIAL_PATH = Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/codex-home/auth.json")
FIXED_OUTPUT_ROOT = Path("/Users/bytedance/Desktop/Trading Agent/.job-runtime/private/r6-one-off-codex-credential-broker-v1")
MAX_AUTH_BYTES = 1024 * 1024

DIRECT_PRODUCER = ("tuning/architecture/r6_one_off_codex_direct_catalog_v1/producer-verification-v5.json", 5801, "0acfd52223e9bef05550963c7ac69075e5fa7885094b49f778090e7bb54565f4")
DIRECT_REVIEW = ("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-direct-catalog-v5-independent-review-fable-20261111.json", 8509, "479a177b63c1bd255de6a81af61ecc74d8e6dca27a6602ee62e32b27386650fa")
DISABLED_AUTHORIZATION = ("tuning/architecture/r6_one_off_codex_credential_broker_v1/fixed-disabled-authorization-v1.json", 743, "013d2ce412446f5fbb21ec771be8b681eba0b30a7ee66b7e9748e30cea2be8d9")
DISABLED_AUTHORIZATION_REVIEW = ("tuning/architecture/r6_one_off_codex_credential_broker_v1/fixed-disabled-authorization-review-v1.json", 436, "0f92f41e1c7c9aa07d623922b91d719aef961ea887197b8f7c669ff8a4d076e6")
BINARY_IDENTITY = ("tuning/architecture/r6_one_off_codex_credential_broker_v1/fixed-binary-identity-v1.json", 845, "6a66c5a001d22437a57b2cb92de071ad5731ed899a1a62471a6d1ee46637214b")
BINARY_IDENTITY_REVIEW = ("tuning/architecture/r6_one_off_codex_credential_broker_v1/fixed-binary-identity-review-v1.json", 471, "cddfd99dc0506fe74f58973f2120cf70851bd9e070b095ecf2b7566f728e105f")
PINNED_ARTIFACTS = (DIRECT_PRODUCER, DIRECT_REVIEW, DISABLED_AUTHORIZATION, DISABLED_AUTHORIZATION_REVIEW, BINARY_IDENTITY, BINARY_IDENTITY_REVIEW)


class BrokerError(RuntimeError):
    """Sanitized broker failure with an explicit terminal state."""

    def __init__(self, code: str, state: str = "REJECTED", receipt: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(code)
        self.code = code
        self.state = state
        self.receipt = dict(receipt) if receipt is not None else None


@dataclass(frozen=True)
class PublishedExecution:
    raw_catalog_path: Path
    membership_receipt_path: Path
    execution_receipt_path: Path
    commit_marker_path: Path
    raw_catalog_sha256: str
    membership_receipt_sha256: str
    execution_receipt_sha256: str


def workspace_root() -> Path:
    return Path(__file__).resolve().parents[4]


def sha256_buffer(value: Any) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), ensure_ascii=True, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n").encode("ascii")


def _open_regular_nofollow(path: Path, *, exact_mode: Optional[int] = None) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as caught:
        raise BrokerError("PINNED_ARTIFACT_UNAVAILABLE") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise BrokerError("PINNED_ARTIFACT_IDENTITY_REJECTED")
        if exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode:
            raise BrokerError("PINNED_ARTIFACT_MODE_REJECTED")
        if info.st_mode & 0o022:
            raise BrokerError("PINNED_ARTIFACT_MODE_REJECTED")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_pinned(ref: Tuple[str, int, str]) -> bytes:
    root = workspace_root().resolve()
    relative = Path(ref[0])
    if relative.is_absolute() or ".." in relative.parts:
        raise BrokerError("PINNED_ARTIFACT_PATH_REJECTED")
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        try:
            info = os.lstat(current)
        except OSError:
            raise BrokerError("PINNED_ARTIFACT_UNAVAILABLE") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise BrokerError("PINNED_ARTIFACT_PATH_REJECTED")
    descriptor = _open_regular_nofollow(root / relative)
    try:
        chunks = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if len(raw) != ref[1] or sha256_buffer(raw) != ref[2]:
        raise BrokerError("PINNED_ARTIFACT_HASH_REJECTED")
    return raw


def verify_frozen_contracts() -> None:
    values = []
    for ref in PINNED_ARTIFACTS:
        raw = read_pinned(ref)
        try:
            values.append(json.loads(raw.decode("utf-8"), parse_constant=lambda _: (_ for _ in ()).throw(ValueError())))
        except (UnicodeError, ValueError, json.JSONDecodeError):
            raise BrokerError("PINNED_ARTIFACT_JSON_REJECTED") from None
    producer, review, authorization, authorization_review, binary, binary_review = values
    if producer.get("verdict") != "PRODUCER_PASS_V5_DISABLED_UNWIRED_PROVIDER_FREE_ONLY":
        raise BrokerError("DIRECT_PRODUCER_REJECTED")
    if review.get("verdict") != "CLEAN_DIRECT_CODEX_CATALOG_V5":
        raise BrokerError("DIRECT_REVIEW_REJECTED")
    if authorization.get("activation") is not False or authorization.get("live_grant_present") is not False or authorization.get("live_review_present") is not False:
        raise BrokerError("DISABLED_AUTHORIZATION_REJECTED")
    if authorization.get("bytedcli") != {"allowed": False, "calls": 0}:
        raise BrokerError("BYTEDCLI_AUTHORIZATION_REJECTED")
    if authorization_review.get("verdict") != "CLEAN_DISABLED_NO_LIVE_GRANT_OR_REVIEW" or authorization_review.get("authorization", {}).get("sha256") != DISABLED_AUTHORIZATION[2]:
        raise BrokerError("DISABLED_AUTHORIZATION_REVIEW_REJECTED")
    identity = binary.get("binary", {})
    if identity.get("version") != CODEX_RELEASE or identity.get("sha256") != "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc":
        raise BrokerError("BINARY_IDENTITY_REJECTED")
    if binary_review.get("verdict") != "MATCHED_CODEX_0_167_0_ARM64" or binary_review.get("binary_identity", {}).get("sha256") != BINARY_IDENTITY[2]:
        raise BrokerError("BINARY_REVIEW_REJECTED")


__all__ = ["BrokerError", "PublishedExecution"]
