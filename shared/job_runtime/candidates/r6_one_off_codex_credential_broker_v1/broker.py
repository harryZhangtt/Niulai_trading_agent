"""Disabled public entrypoint and private synthetic seam for one-shot catalog execution."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Any, Callable, Mapping, Optional

from shared.job_runtime.candidates.r6_one_off_codex_direct_catalog_v1 import (
    CatalogExecutionError,
    DirectCatalogExecutor,
    transient_bearer_scope,
)

from .contracts import (
    BrokerError,
    CREDENTIAL_FORMAT,
    canonical_json,
    DIRECT_PRODUCER,
    DIRECT_REVIEW,
    FIXED_CREDENTIAL_PATH,
    FIXED_OUTPUT_ROOT,
    MAX_AUTH_BYTES,
    MODEL,
    PublishedExecution,
    sha256_buffer,
    verify_frozen_contracts,
    workspace_root,
)
from .mutable_json import MutableJSONError, extract_access_token, parse_mutable_json, wipe
from .publication import claim_one_shot, publish

_TEST_SEAM = object()


def _credential_parent(path: Path, expected_uid: int) -> None:
    parent = path.parent
    if path == FIXED_CREDENTIAL_PATH:
        anchor = workspace_root().resolve()
        try:
            relative = parent.relative_to(anchor)
        except ValueError:
            raise BrokerError("CREDENTIAL_PATH_OUTSIDE_WORKSPACE") from None
        current = anchor
        for component in relative.parts:
            current = current / component
            try:
                component_info = os.lstat(current)
            except OSError:
                raise BrokerError("CREDENTIAL_ANCESTOR_UNAVAILABLE") from None
            if stat.S_ISLNK(component_info.st_mode) or not stat.S_ISDIR(component_info.st_mode):
                raise BrokerError("CREDENTIAL_ANCESTOR_REJECTED")
    try:
        info = os.lstat(parent)
    except OSError:
        raise BrokerError("CREDENTIAL_PARENT_UNAVAILABLE") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or info.st_uid != expected_uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise BrokerError("CREDENTIAL_PARENT_REJECTED")


def _read_credential(path: Path, expected_uid: int) -> bytearray:
    _credential_parent(path, expected_uid)
    try:
        before_path = os.lstat(path)
    except OSError:
        raise BrokerError("CREDENTIAL_SOURCE_UNAVAILABLE") from None
    if stat.S_ISLNK(before_path.st_mode) or not stat.S_ISREG(before_path.st_mode):
        raise BrokerError("CREDENTIAL_SOURCE_TYPE_REJECTED")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError:
        raise BrokerError("CREDENTIAL_SOURCE_OPEN_REJECTED") from None
    raw = bytearray()
    probe = bytearray(1)
    tree: Any = None
    token = bytearray()
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != expected_uid
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_nlink != 1
            or before.st_size <= 0
            or before.st_size > MAX_AUTH_BYTES
            or (before.st_dev, before.st_ino) != (before_path.st_dev, before_path.st_ino)
        ):
            raise BrokerError("CREDENTIAL_SOURCE_IDENTITY_REJECTED")
        raw = bytearray(before.st_size)
        offset = 0
        while offset < before.st_size:
            count = os.readv(descriptor, [memoryview(raw)[offset:]])
            if count <= 0:
                raise BrokerError("CREDENTIAL_SOURCE_SHORT_READ")
            offset += count
        if os.readv(descriptor, [probe]) != 0:
            raise BrokerError("CREDENTIAL_SOURCE_SIZE_CHANGED")
        after = os.fstat(descriptor)
        try:
            after_path = os.lstat(path)
        except OSError:
            raise BrokerError("CREDENTIAL_SOURCE_DRIFT") from None
        identity_before = (before.st_dev, before.st_ino, before.st_uid, stat.S_IMODE(before.st_mode), before.st_nlink, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_uid, stat.S_IMODE(after.st_mode), after.st_nlink, after.st_size, after.st_mtime_ns)
        identity_path = (after_path.st_dev, after_path.st_ino, after_path.st_uid, stat.S_IMODE(after_path.st_mode), after_path.st_nlink, after_path.st_size, after_path.st_mtime_ns)
        if identity_before != identity_after or identity_before != identity_path:
            raise BrokerError("CREDENTIAL_SOURCE_DRIFT", "UNKNOWN")
        try:
            tree = parse_mutable_json(raw)
            token = extract_access_token(tree)
        except MutableJSONError:
            raise BrokerError("CREDENTIAL_FORMAT_REJECTED") from None
        return token
    except BaseException:
        wipe(token)
        raise
    finally:
        wipe(tree)
        wipe(raw)
        wipe(probe)
        os.close(descriptor)


def _membership(result: Any) -> Mapping[str, Any]:
    receipt = result.receipt
    models = result.models
    if (
        type(models) is not tuple
        or models.count(MODEL) != 1
        or type(receipt) is not dict
        or receipt.get("status") != "PASS"
        or type(receipt.get("body_sha256")) is not str
        or type(receipt.get("body_bytes")) is not int
        or type(receipt.get("model_count")) is not int
        or receipt.get("model_count") != len(models)
    ):
        raise BrokerError("DIRECT_CATALOG_RESULT_REJECTED", "UNKNOWN")
    origin = result.origin
    if type(origin.kind) is not str or type(origin.host) is not str or type(origin.tls_hostname_verified) is not bool:
        raise BrokerError("DIRECT_CATALOG_ORIGIN_REJECTED", "UNKNOWN")
    return {
        "origin": {"kind": origin.kind, "host": origin.host, "tls_hostname_verified": origin.tls_hostname_verified},
        "status": "PASS",
        "body_sha256": receipt["body_sha256"],
        "body_bytes": receipt["body_bytes"],
        "model_count": receipt["model_count"],
        "gpt_6_1_sol_membership": {"model": MODEL, "count": 1, "exact": True},
    }


def _execution(raw_digest: str, membership_digest: str) -> Mapping[str, Any]:
    return {
        "schema_version": "r6-one-off-codex-credential-broker-execution-receipt-v1",
        "outcome": "PASS",
        "credential_format": CREDENTIAL_FORMAT,
        "physical_forwards": 1,
        "retry": 0,
        "replay": 0,
        "auth_recovery": 0,
        "status_queries": 0,
        "inference_requests": 0,
        "bytedcli_calls": 0,
        "direct_catalog_producer_sha256": DIRECT_PRODUCER[2],
        "direct_catalog_review_sha256": DIRECT_REVIEW[2],
        "artifact_sha256": {"raw_catalog": raw_digest, "membership": membership_digest},
    }


def _execute_bound(
    source_path: Path,
    output_root: Path,
    *,
    expected_uid: int,
    executor_factory: Callable[[], Any],
    write_fn: Callable[[int, Any], int],
    fault: Optional[Callable[[str], None]],
) -> PublishedExecution:
    claim_one_shot(output_root)
    token_source = bytearray()
    raw_response = bytearray()
    result: Any = None
    try:
        token_source = _read_credential(source_path, expected_uid)
        try:
            with transient_bearer_scope(token_source) as capability:
                token_source = bytearray()
                executor = executor_factory()
                try:
                    result = executor.execute(capability, include_owner_private_raw=True)
                except CatalogExecutionError as caught:
                    code = caught.code
                    receipt = caught.receipt
                    caught.__traceback__ = None
                    caught.__cause__ = None
                    caught.__context__ = None
                    capability = None
                    executor = None
                    raise BrokerError(code, "UNKNOWN", receipt) from None
        finally:
            wipe(token_source)
        membership = _membership(result)
        owner_raw = result.owner_private_raw
        if type(owner_raw) is not bytes or not owner_raw:
            owner_raw = None
            result = None
            raise BrokerError("RAW_CATALOG_MISSING", "UNKNOWN")
        raw_response = bytearray(owner_raw)
        owner_raw = None
        result = None
        raw_digest = sha256_buffer(raw_response)
        membership_digest = sha256_buffer(canonical_json(membership))
        execution = _execution(raw_digest, membership_digest)
        return publish(output_root, raw_response, membership, execution, write_fn=write_fn, fault=fault)
    except BrokerError:
        raise
    except BaseException:
        raise
    finally:
        result = None
        wipe(token_source)
        wipe(raw_response)


def execute_live() -> PublishedExecution:
    """Public fixed-path entrypoint; intentionally disabled pending exact live grant and review."""
    verify_frozen_contracts()
    raise BrokerError("SEPARATE_EXACT_LIVE_GRANT_AND_REVIEW_REQUIRED")


def _execute_for_test(
    marker: object,
    source_path: Path,
    output_root: Path,
    *,
    executor_factory: Callable[[], Any] = DirectCatalogExecutor,
    expected_uid: Optional[int] = None,
    write_fn: Callable[[int, Any], int] = os.write,
    fault: Optional[Callable[[str], None]] = None,
) -> PublishedExecution:
    """Private provider-free seam. It is deliberately absent from the package API."""
    if marker is not _TEST_SEAM:
        raise BrokerError("PRIVATE_TEST_SEAM_REJECTED")
    return _execute_bound(source_path, output_root, expected_uid=os.getuid() if expected_uid is None else expected_uid, executor_factory=executor_factory, write_fn=write_fn, fault=fault)


__all__ = ["execute_live"]
