"""Strict JSON parser whose string values remain synchronously wipeable."""
from __future__ import annotations

from typing import Any, Iterable, Optional


class MutableJSONError(ValueError):
    pass


class JSONObject(list):
    pass


class JSONArray(list):
    pass


_NUMBER = object()
_HEX = b"0123456789abcdefABCDEF"


def wipe(value: Any) -> None:
    if isinstance(value, bytearray):
        for index in range(len(value)):
            value[index] = 0
        value.clear()
    elif isinstance(value, JSONObject):
        for key, child in value:
            wipe(key)
            wipe(child)
        value.clear()
    elif isinstance(value, JSONArray):
        for child in value:
            wipe(child)
        value.clear()


def field(value: JSONObject, name: bytes) -> Any:
    for key, child in value:
        if key == name:
            return child
    return None


def has_field(value: JSONObject, name: bytes) -> bool:
    return any(key == name for key, _ in value)


def keys_exact(value: JSONObject, required: Iterable[bytes], optional: Iterable[bytes] = ()) -> bool:
    required_values = tuple(required)
    allowed = required_values + tuple(optional)
    return all(any(key == candidate for candidate in allowed) for key, _ in value) and all(has_field(value, name) for name in required_values)


class _Parser:
    def __init__(self, raw: bytearray) -> None:
        if type(raw) is not bytearray:
            raise MutableJSONError("JSON_SOURCE_REJECTED")
        self.raw = raw
        self.index = 0
        self.depth = 0
        self.entries = 0

    def parse(self) -> Any:
        self._space()
        value = self._value()
        self._space()
        if self.index != len(self.raw):
            wipe(value)
            raise MutableJSONError("JSON_TRAILING_DATA")
        return value

    def _space(self) -> None:
        while self.index < len(self.raw) and self.raw[self.index] in b" \t\r\n":
            self.index += 1

    def _value(self) -> Any:
        if self.index >= len(self.raw):
            raise MutableJSONError("JSON_TRUNCATED")
        current = self.raw[self.index]
        if current == 0x22:
            return self._string()
        if current == 0x7B:
            return self._object()
        if current == 0x5B:
            return self._array()
        for literal, value in ((b"true", True), (b"false", False), (b"null", None)):
            if self.raw[self.index:self.index + len(literal)] == literal:
                self.index += len(literal)
                return value
        if current == 0x2D or 0x30 <= current <= 0x39:
            self._number()
            return _NUMBER
        raise MutableJSONError("JSON_TOKEN_REJECTED")

    def _enter(self) -> None:
        self.depth += 1
        if self.depth > 64:
            raise MutableJSONError("JSON_DEPTH_REJECTED")

    def _leave(self) -> None:
        self.depth -= 1

    def _object(self) -> JSONObject:
        self._enter()
        value = JSONObject()
        self.index += 1
        self._space()
        try:
            if self.index < len(self.raw) and self.raw[self.index] == 0x7D:
                self.index += 1
                return value
            while True:
                if self.index >= len(self.raw) or self.raw[self.index] != 0x22:
                    raise MutableJSONError("JSON_OBJECT_KEY_REJECTED")
                key = self._string()
                if any(existing == key for existing, _ in value):
                    wipe(key)
                    raise MutableJSONError("DUPLICATE_JSON_KEY")
                self._space()
                if self.index >= len(self.raw) or self.raw[self.index] != 0x3A:
                    wipe(key)
                    raise MutableJSONError("JSON_OBJECT_COLON_REJECTED")
                self.index += 1
                self._space()
                try:
                    child = self._value()
                except BaseException:
                    wipe(key)
                    raise
                value.append((key, child))
                self.entries += 1
                if self.entries > 4096:
                    raise MutableJSONError("JSON_ENTRY_LIMIT_REJECTED")
                self._space()
                if self.index >= len(self.raw):
                    raise MutableJSONError("JSON_TRUNCATED")
                separator = self.raw[self.index]
                self.index += 1
                if separator == 0x7D:
                    return value
                if separator != 0x2C:
                    raise MutableJSONError("JSON_OBJECT_SEPARATOR_REJECTED")
                self._space()
        except BaseException:
            wipe(value)
            raise
        finally:
            self._leave()

    def _array(self) -> JSONArray:
        self._enter()
        value = JSONArray()
        self.index += 1
        self._space()
        try:
            if self.index < len(self.raw) and self.raw[self.index] == 0x5D:
                self.index += 1
                return value
            while True:
                child = self._value()
                value.append(child)
                self.entries += 1
                if self.entries > 4096:
                    raise MutableJSONError("JSON_ENTRY_LIMIT_REJECTED")
                self._space()
                if self.index >= len(self.raw):
                    raise MutableJSONError("JSON_TRUNCATED")
                separator = self.raw[self.index]
                self.index += 1
                if separator == 0x5D:
                    return value
                if separator != 0x2C:
                    raise MutableJSONError("JSON_ARRAY_SEPARATOR_REJECTED")
                self._space()
        except BaseException:
            wipe(value)
            raise
        finally:
            self._leave()

    def _string(self) -> bytearray:
        value = bytearray()
        self.index += 1
        try:
            while self.index < len(self.raw):
                current = self.raw[self.index]
                self.index += 1
                if current == 0x22:
                    return value
                if current < 0x20:
                    raise MutableJSONError("JSON_STRING_CONTROL_REJECTED")
                if current == 0x5C:
                    if self.index >= len(self.raw):
                        raise MutableJSONError("JSON_TRUNCATED")
                    escaped = self.raw[self.index]
                    self.index += 1
                    simple = {0x22: 0x22, 0x5C: 0x5C, 0x2F: 0x2F, 0x62: 0x08, 0x66: 0x0C, 0x6E: 0x0A, 0x72: 0x0D, 0x74: 0x09}
                    if escaped in simple:
                        value.append(simple[escaped])
                    elif escaped == 0x75:
                        codepoint = self._unicode_escape()
                        if 0xD800 <= codepoint <= 0xDBFF:
                            if self.raw[self.index:self.index + 2] != b"\\u":
                                raise MutableJSONError("JSON_SURROGATE_REJECTED")
                            self.index += 2
                            low = self._unicode_escape()
                            if not 0xDC00 <= low <= 0xDFFF:
                                raise MutableJSONError("JSON_SURROGATE_REJECTED")
                            codepoint = 0x10000 + ((codepoint - 0xD800) << 10) + (low - 0xDC00)
                        elif 0xDC00 <= codepoint <= 0xDFFF:
                            raise MutableJSONError("JSON_SURROGATE_REJECTED")
                        self._append_codepoint(value, codepoint)
                    else:
                        raise MutableJSONError("JSON_ESCAPE_REJECTED")
                elif current < 0x80:
                    value.append(current)
                else:
                    self._copy_utf8(value, current)
            raise MutableJSONError("JSON_TRUNCATED")
        except BaseException:
            wipe(value)
            raise

    def _unicode_escape(self) -> int:
        if self.index + 4 > len(self.raw):
            raise MutableJSONError("JSON_TRUNCATED")
        digits = self.raw[self.index:self.index + 4]
        if any(digit not in _HEX for digit in digits):
            raise MutableJSONError("JSON_UNICODE_ESCAPE_REJECTED")
        self.index += 4
        result = 0
        for digit in digits:
            result <<= 4
            result |= digit - 48 if digit <= 57 else (digit | 32) - 87
        return result

    @staticmethod
    def _append_codepoint(target: bytearray, codepoint: int) -> None:
        if codepoint <= 0x7F:
            target.append(codepoint)
        elif codepoint <= 0x7FF:
            target.extend((0xC0 | (codepoint >> 6), 0x80 | (codepoint & 0x3F)))
        elif codepoint <= 0xFFFF:
            target.extend((0xE0 | (codepoint >> 12), 0x80 | ((codepoint >> 6) & 0x3F), 0x80 | (codepoint & 0x3F)))
        else:
            target.extend((0xF0 | (codepoint >> 18), 0x80 | ((codepoint >> 12) & 0x3F), 0x80 | ((codepoint >> 6) & 0x3F), 0x80 | (codepoint & 0x3F)))

    def _copy_utf8(self, target: bytearray, first: int) -> None:
        if 0xC2 <= first <= 0xDF:
            count, minimum = 1, 0x80
            codepoint = first & 0x1F
        elif 0xE0 <= first <= 0xEF:
            count, minimum = 2, 0x800
            codepoint = first & 0x0F
        elif 0xF0 <= first <= 0xF4:
            count, minimum = 3, 0x10000
            codepoint = first & 0x07
        else:
            raise MutableJSONError("JSON_UTF8_REJECTED")
        if self.index + count > len(self.raw):
            raise MutableJSONError("JSON_TRUNCATED")
        sequence = [first]
        for _ in range(count):
            current = self.raw[self.index]
            self.index += 1
            if not 0x80 <= current <= 0xBF:
                raise MutableJSONError("JSON_UTF8_REJECTED")
            sequence.append(current)
            codepoint = (codepoint << 6) | (current & 0x3F)
        if codepoint < minimum or codepoint > 0x10FFFF or 0xD800 <= codepoint <= 0xDFFF:
            raise MutableJSONError("JSON_UTF8_REJECTED")
        target.extend(sequence)

    def _number(self) -> None:
        start = self.index
        if self.raw[self.index] == 0x2D:
            self.index += 1
        if self.index >= len(self.raw):
            raise MutableJSONError("JSON_NUMBER_REJECTED")
        if self.raw[self.index] == 0x30:
            self.index += 1
            if self.index < len(self.raw) and 0x30 <= self.raw[self.index] <= 0x39:
                raise MutableJSONError("JSON_NUMBER_REJECTED")
        elif 0x31 <= self.raw[self.index] <= 0x39:
            while self.index < len(self.raw) and 0x30 <= self.raw[self.index] <= 0x39:
                self.index += 1
        else:
            raise MutableJSONError("JSON_NUMBER_REJECTED")
        if self.index < len(self.raw) and self.raw[self.index] == 0x2E:
            self.index += 1
            fraction = self.index
            while self.index < len(self.raw) and 0x30 <= self.raw[self.index] <= 0x39:
                self.index += 1
            if self.index == fraction:
                raise MutableJSONError("JSON_NUMBER_REJECTED")
        if self.index < len(self.raw) and self.raw[self.index] in b"eE":
            self.index += 1
            if self.index < len(self.raw) and self.raw[self.index] in b"+-":
                self.index += 1
            exponent = self.index
            while self.index < len(self.raw) and 0x30 <= self.raw[self.index] <= 0x39:
                self.index += 1
            if self.index == exponent:
                raise MutableJSONError("JSON_NUMBER_REJECTED")
        if self.index == start:
            raise MutableJSONError("JSON_NUMBER_REJECTED")


def parse_mutable_json(raw: bytearray) -> Any:
    return _Parser(raw).parse()


def extract_access_token(value: Any) -> bytearray:
    top_required = (b"tokens",)
    top_optional = (b"auth_mode", b"OPENAI_API_KEY", b"last_refresh", b"agent_identity", b"personal_access_token", b"bedrock_api_key", b"bedrock_access_keys")
    if not isinstance(value, JSONObject) or not keys_exact(value, top_required, top_optional):
        raise MutableJSONError("AUTH_DOCUMENT_SCHEMA_REJECTED")
    tokens = field(value, b"tokens")
    required = (b"id_token", b"access_token", b"refresh_token")
    optional = (b"oauth_provenance", b"login_owner_id", b"account_id")
    if not isinstance(tokens, JSONObject) or not keys_exact(tokens, required, optional):
        raise MutableJSONError("TOKEN_DOCUMENT_SCHEMA_REJECTED")
    for name in required:
        if type(field(tokens, name)) is not bytearray:
            raise MutableJSONError("TOKEN_FIELD_TYPE_REJECTED")
    for name in (b"login_owner_id", b"account_id"):
        child = field(tokens, name)
        if has_field(tokens, name) and child is not None and type(child) is not bytearray:
            raise MutableJSONError("TOKEN_FIELD_TYPE_REJECTED")
    provenance = field(tokens, b"oauth_provenance")
    if has_field(tokens, b"oauth_provenance") and provenance is not None:
        if not isinstance(provenance, JSONObject) or not keys_exact(provenance, (b"issuer", b"client_id")):
            raise MutableJSONError("TOKEN_PROVENANCE_REJECTED")
        if any(type(field(provenance, name)) is not bytearray for name in (b"issuer", b"client_id")):
            raise MutableJSONError("TOKEN_PROVENANCE_REJECTED")
    source = field(tokens, b"access_token")
    if not source:
        raise MutableJSONError("ACCESS_TOKEN_MISSING")
    return bytearray(source)


__all__ = ["MutableJSONError", "extract_access_token", "parse_mutable_json", "wipe"]
