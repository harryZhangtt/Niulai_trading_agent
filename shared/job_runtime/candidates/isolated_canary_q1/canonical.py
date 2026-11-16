"""Strict canonical JSON helpers for the inert isolated-canary candidate."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any


class CanonicalError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len(pairs) != len({key for key, _ in pairs}):
        raise CanonicalError("CANARY_JSON_DUPLICATE_KEY")
    return dict(pairs)


def _invalid_number(_value: str) -> None:
    raise CanonicalError("CANARY_JSON_NUMBER_INVALID")


def _validate(value: Any) -> None:
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if not -(2**63) <= value <= 2**63 - 1:
            raise CanonicalError("CANARY_JSON_INTEGER_RANGE")
        return
    if type(value) is str:
        if unicodedata.normalize("NFC", value) != value:
            raise CanonicalError("CANARY_JSON_NON_NFC")
        return
    if type(value) is list:
        for item in value:
            _validate(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or unicodedata.normalize("NFC", key) != key:
                raise CanonicalError("CANARY_JSON_KEY_INVALID")
            _validate(item)
        return
    raise CanonicalError("CANARY_JSON_TYPE_INVALID")


def strict_json_loads(raw: bytes, *, maximum: int) -> Any:
    if type(raw) is not bytes or type(maximum) is not int or maximum < 1 or not 1 <= len(raw) <= maximum:
        raise CanonicalError("CANARY_JSON_SIZE_INVALID")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise CanonicalError("CANARY_JSON_ENCODING_INVALID") from None
    if text.startswith("﻿"):
        raise CanonicalError("CANARY_JSON_ENCODING_INVALID")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_invalid_number,
            parse_constant=_invalid_number,
        )
    except CanonicalError:
        raise
    except (json.JSONDecodeError, ValueError, TypeError):
        raise CanonicalError("CANARY_JSON_INVALID") from None
    _validate(value)
    return value


def canonical_json_bytes(value: Any) -> bytes:
    _validate(value)
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n").encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise CanonicalError("CANARY_BYTES_REQUIRED")
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))
