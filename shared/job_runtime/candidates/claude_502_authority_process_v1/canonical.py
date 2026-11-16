"""Strict canonical JSON shared by frame and signature contracts."""
import json
from .errors import ProtocolError

MAX_DEPTH = 24


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ProtocolError("JSON_DUPLICATE_KEY")
        out[key] = value
    return out


def _reject_constant(_value):
    raise ProtocolError("JSON_NONFINITE_NUMBER")


def _check(value, depth=0):
    if depth > MAX_DEPTH:
        raise ProtocolError("JSON_DEPTH_EXCEEDED")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is list:
        for item in value:
            _check(item, depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ProtocolError("JSON_KEY_TYPE")
            _check(item, depth + 1)
        return
    raise ProtocolError("JSON_TYPE_REJECTED")


def dumps(value):
    _check(value)
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ProtocolError("JSON_ENCODING_INVALID")


def loads_exact(raw):
    if type(raw) is not bytes:
        raise ProtocolError("JSON_BYTES_REQUIRED")
    try:
        text = raw.decode("utf-8", "strict")
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant,
                           parse_float=lambda _x: (_ for _ in ()).throw(ProtocolError("JSON_FLOAT_REJECTED")))
    except ProtocolError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise ProtocolError("JSON_INVALID")
    _check(value)
    if dumps(value) != raw:
        raise ProtocolError("JSON_NONCANONICAL")
    return value
