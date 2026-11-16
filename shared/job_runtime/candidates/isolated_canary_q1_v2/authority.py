"""Exact reviewed authority-v2 loader. It exposes no provider invocation path."""
from __future__ import annotations
from pathlib import Path
import json, os, re, stat
from types import MappingProxyType
from typing import Any, Mapping
from .contracts import AuthorityV2Error, CapabilityGateV2

WORKSPACE = Path(__file__).resolve().parents[4]
MANIFEST = WORKSPACE / "shared/job_runtime/candidates/isolated_canary_q1/authority-manifest-v2.json"
EXPECTED_SHA256 = "b542ec00324f58137f7ff7662ae6c980e8df8990f3a14a2c9f759339ad9209b6"
EXPECTED_BYTES = 2911
SHA = re.compile(r"[0-9a-f]{64}")


def _sha(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path, *, expected_sha: str, expected_bytes: int) -> bytes:
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) & 0o022 or before.st_size != expected_bytes:
            raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
        chunks = []
        remaining = expected_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        current = path.lstat()
        signature = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink, info.st_size, info.st_mtime_ns)
        if signature(before) != signature(after) or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino):
            raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    except (OSError, AuthorityV2Error):
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID") from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(data) != expected_bytes or _sha(data) != expected_sha:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    return data


def _strict(data: bytes) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
            value[key] = item
        return value
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except Exception:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID") from None
    if type(value) is not dict:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    return value


def _frozen(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_frozen(item) for item in value)
    return value


def load_authority_manifest(path: Path | None = None, *, workspace: Path = WORKSPACE) -> Mapping[str, Any]:
    target = path or MANIFEST
    data = _read_regular(target, expected_sha=EXPECTED_SHA256, expected_bytes=EXPECTED_BYTES)
    value = _strict(data)
    keys = {"schema_version","candidate_id","repository","tag","commit","tree_sha","archive_sha256","binary","source_blocks","source_block_algorithm","grammar_inventory_sha256","source_authority_complete","source_authority_receipts","retry","predecessor","capabilities","claim_limits"}
    if set(value) != keys or value["schema_version"] != 2 or value["candidate_id"] != "codex-rust-0.167-isolated-canary-q1-v2" or value["repository"] != "openai/codex" or value["tag"] != "rust-v0.167.0" or value["commit"] != "086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a" or value["tree_sha"] != "930790b05c58ba0be420a4abe240d206f5dfd48e" or value["archive_sha256"] != "313e49728fba6c3d44683554c28018f36781f9f9b6bd09eaa65dccdd6c13b1a7" or value["source_block_algorithm"] != "raw-member-byte-slice-sha256-v1" or value["source_authority_complete"] is not True:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    binary = value["binary"]
    if type(binary) is not dict or set(binary) != {"version","sha256","size","asset_binding_verified","asset_binding_receipt"} or binary["version"] != "0.167.0" or binary["sha256"] != "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc" or binary["size"] != 270815376 or binary["asset_binding_verified"] is not True:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    blocks = value["source_blocks"]
    if blocks != {"thread_event_sha256":"ea2a8bb1b0de89d67ab87bd2eecae2ca4534ff2ca5d056e58869ac6311374eb5","thread_item_details_sha256":"fc6199acbb1e9ebfcdbe9a44fe5e434f745dde308ed66cebeebb6962dc8b3c8f"}:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    if value["grammar_inventory_sha256"] != '3bf7bb8c87f51472ab726d7c791e2a0dc8359621ab00a338517220f3186910ff' or value["source_authority_receipts"] != [{'bytes': 1626, 'path': 'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-codex-0167-source-archive-receipt.json', 'sha256': '2edd4ff3cdedbca16c03c32f1954b0cf7827e02f6954b2b8a59f5559b2af6421'}, {'bytes': 2349, 'path': 'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-codex-0167-grammar-source-blocks-v2.json', 'sha256': '3bf7bb8c87f51472ab726d7c791e2a0dc8359621ab00a338517220f3186910ff'}, {'bytes': 952, 'path': 'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-codex-0167-git-metadata-receipt.json', 'sha256': '9ba9ab055ce90f88801551aa4653760573ee2a43c51885778d57aa0a07e5b46b'}] or value["predecessor"] != {'bytes': 956, 'path': 'shared/job_runtime/candidates/isolated_canary_q1/authority-manifest-v1.json', 'sha256': '1cf1d9000e282eebe0ac067f156876ffd1db3e113eab66aef0bacf7ee035eb34', 'superseded_source_block_claims': {'thread_event_sha256': '6f5dd0c113373078eef82c96bf8c6c2644dc8f08222e2fc2a96b170539cc5c44', 'thread_item_details_sha256': 'f7a252acd64c2c71a51eb88ecefb9c3793193f7fff598e57372d912e56d340a9'}} or value["claim_limits"] != ['official source/tag/archive/grammar and official-page/enclosed/installed binary identity only', 'no reproducible-build claim', 'no live provider/retry/capture/gateway/observer/reconciliation proof', 'does not authorize invocation']:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    if value["retry"] != {"request_default":4,"stream_default":5,"request_key":"request_max_retries","stream_key":"stream_max_retries","request_target":0,"stream_target":0}:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    capabilities = value["capabilities"]
    expected_caps = {"source_authority_verified":True,"source_grammar_verified":True,"binary_asset_verified":True,"source_to_binary_reproducible_build_verified":False,"retry_zero_live_verified":False,"sanitized_live_capture_verified":False,"gateway_observer_reconciliation_verified":False,"capability_open":False}
    if capabilities != expected_caps:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    if binary["asset_binding_receipt"] != {'bytes': 4097, 'path': 'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-codex-0167-asset-binding-v2.json', 'sha256': 'f20a2e979d680326a26f564e1c1103ea1f11f2620617a4f447be810f6e8d5729'}:
        raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
    refs = [binary["asset_binding_receipt"], *value["source_authority_receipts"]]
    for ref in refs:
        if type(ref) is not dict or set(ref) != {"path","sha256","bytes"} or SHA.fullmatch(str(ref["sha256"])) is None or type(ref["bytes"]) is not int or ref["bytes"] < 1:
            raise AuthorityV2Error("CODEX_Q1_V2_AUTHORITY_INVALID")
        _read_regular(workspace / ref["path"], expected_sha=ref["sha256"], expected_bytes=ref["bytes"])
    return _frozen(value)


def capability_gate() -> CapabilityGateV2:
    try:
        value = load_authority_manifest()
        return CapabilityGateV2(**dict(value["capabilities"]))
    except (AuthorityV2Error, OSError, TypeError, ValueError):
        return CapabilityGateV2(False, False, False, False, False, False, False, False)
