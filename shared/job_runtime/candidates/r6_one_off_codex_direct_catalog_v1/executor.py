"""Disabled, unregistered direct authenticated Codex catalog executor."""
from __future__ import annotations
from typing import Any, Mapping, Optional
from .capability import _consume_transient_bearer, _revoke_transient_bearer
from .contracts import (CatalogExecutionError, CatalogResult, ContractError,
                        OriginEvidence, load_fixed_authority, parse_catalog, sha256)
from .transport import TransportError, forward_once


def _receipt(status: str, http_status: int, body: bytes, model_count: int) -> Mapping[str, Any]:
    return {"status": status, "http_status": http_status,
            "body_sha256": sha256(body) if body else None,
            "body_bytes": len(body), "model_count": model_count}

def _transport_receipt(error: TransportError) -> Mapping[str, Any]:
    return {"status": "REJECTED", "http_status": error.status,
            "body_sha256": error.body_sha256, "body_bytes": error.body_bytes,
            "model_count": 0}

def _consume_boundary(capability):
    try:
        return _consume_transient_bearer(capability), None
    except TypeError as caught:
        caught.__traceback__ = None
        caught.__cause__ = None
        caught.__context__ = None
        _revoke_transient_bearer(capability)
        return None, "CAPABILITY_REJECTED"

def _forward_boundary(material: bytearray):
    try:
        return forward_once(material), None
    except TransportError as caught:
        failure = (caught.code, _transport_receipt(caught))
        caught.__traceback__ = None
        caught.__cause__ = None
        caught.__context__ = None
        return None, failure

def _status_boundary(forwarded):
    if forwarded.status == 200:
        return forwarded, None
    failure = ("HTTP_STATUS_REJECTED",
               _receipt("REJECTED", forwarded.status, forwarded.body, 0))
    forwarded = None
    return None, failure

def _parse_boundary(forwarded):
    try:
        models = parse_catalog(forwarded.body)
    except ContractError as caught:
        failure = (caught.args[0],
                   _receipt("REJECTED", forwarded.status, forwarded.body, 0))
        caught.__traceback__ = None
        caught.__cause__ = None
        caught.__context__ = None
        forwarded = None
        return None, None, failure
    return forwarded, models, None

class DirectCatalogExecutor:
    """A single-use executor. It is intentionally not wired into any runtime."""
    __slots__ = ("_used",)
    def __init__(self) -> None:
        load_fixed_authority()
        self._used = False

    def execute(self, capability: object, *, include_owner_private_raw: bool = False) -> CatalogResult:
        if self._used:
            _revoke_transient_bearer(capability)
            capability = None
            raise CatalogExecutionError("SECOND_EXECUTION_REJECTED")
        if type(include_owner_private_raw) is not bool:
            _revoke_transient_bearer(capability)
            capability = None
            raise CatalogExecutionError("RAW_CUSTODY_FLAG_REJECTED")
        self._used = True
        material, capability_failure = _consume_boundary(capability)
        if capability_failure is not None:
            capability = None
            raise CatalogExecutionError(capability_failure)
        try:
            forwarded, failure = _forward_boundary(material)
            if failure is not None:
                code, receipt = failure
                failure = None
                raise CatalogExecutionError(code, receipt)
            forwarded, failure = _status_boundary(forwarded)
            if failure is not None:
                code, receipt = failure
                failure = None
                raise CatalogExecutionError(code, receipt)
            forwarded, models, failure = _parse_boundary(forwarded)
            if failure is not None:
                code, receipt = failure
                failure = None
                raise CatalogExecutionError(code, receipt)
            origin = OriginEvidence(forwarded.origin_kind, forwarded.host,
                                    forwarded.tls_hostname_verified)
            return CatalogResult(models=models,
                                 receipt=_receipt("PASS", forwarded.status, forwarded.body, len(models)),
                                 origin=origin,
                                 owner_private_raw=bytes(forwarded.body) if include_owner_private_raw else None)
        finally:
            for index in range(len(material)):
                material[index] = 0
