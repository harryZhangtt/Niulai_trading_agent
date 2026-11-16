"""Staged live-capable additive v3 Codex credential broker with one fixed live entrypoint."""

__all__ = ["execute_live"]

# These are fixed, non-callable production bindings. Provider-free tests may replace
# them with synthetic fixed bindings; callers cannot pass paths, roots, tokens, or
# execution machinery through the public API.
_OWNER_UID = 501
_ROOT_SPEC = (0, 0o755)
_WORKSPACE_CHAIN = (
    ("Users", 0, 0o755),
    ("bytedance", 501, 0o750),
    ("Desktop", 501, 0o700),
    ("Trading Agent", 501, 0o755),
)
_AUTH_CHAIN = _WORKSPACE_CHAIN + ((".job-runtime", 501, 0o700), ("codex-home", 501, 0o700))
_OUTPUT_BASE_CHAIN = _WORKSPACE_CHAIN + ((".job-runtime", 501, 0o700),)
_OUTPUT_PARENT_SPEC = ("private", 501, 0o700)
_OUTPUT_SPEC = ("r6-one-off-codex-credential-broker-v2", 501, 0o700)
_AUTH_NAME = "auth.json"
_MAX_AUTH_BYTES = 1024 * 1024
_MODEL = "gpt-6.1-sol"
_CREDENTIAL_FORMAT = "codex-auth-dot-json-v0.167.0"
_DIRECT_PRODUCER_SHA256 = "0acfd52223e9bef05550963c7ac69075e5fa7885094b49f778090e7bb54565f4"
_DIRECT_REVIEW_SHA256 = "479a177b63c1bd255de6a81af61ecc74d8e6dca27a6602ee62e32b27386650fa"
_PINNED_ARTIFACTS = (
    ("/Users/bytedance/Desktop/Trading Agent/tuning/architecture/r6_one_off_codex_direct_catalog_v1/producer-verification-v5.json", 5801, _DIRECT_PRODUCER_SHA256, "verdict", "PRODUCER_PASS_V5_DISABLED_UNWIRED_PROVIDER_FREE_ONLY"),
    ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-direct-catalog-v5-independent-review-fable-20261111.json", 8509, _DIRECT_REVIEW_SHA256, "verdict", "CLEAN_DIRECT_CODEX_CATALOG_V5"),
    ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-v1-independent-review-fable-20261111-8e9a8076-open.json", 9687, "247853762db3ee1cc3666671b252319d3f5d054b6a2f7f5010f3d6ef6899a3ae", "verdict", "OPEN_CODEX_CREDENTIAL_BROKER_V1"),
)
# Exact byte pins plus semantic review bindings must all validate before
# execution can reach workspace/auth descriptors.
_PINNED_ARTIFACTS = _PINNED_ARTIFACTS + (
    ("/Users/bytedance/Desktop/Trading Agent/tuning/architecture/r6_one_off_codex_credential_broker_v2/producer-verification-v2.json", 5161, "073a0001889ab00ef37811b08ad2d0afa94c8616b9e69ca23a9a7f6048ffaaa2", "verdict", "PRODUCER_PASS_V2_DISABLED_PROVIDER_FREE_OPEN_FINDINGS_SUPERSEDED_PENDING_FRESH_REVIEW"),
    ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-v2-independent-review-fable-20261111-8e9a8076-clean.json", 11292, "c69167d0cb8ac48fd8555ea32f0f5ac2ed529ced2b383166f0cca0066341f2b0", "verdict", "CLEAN_CODEX_CREDENTIAL_BROKER_V2"),
)
_LIVE_GRANT_PIN = ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-live-grant-v2.json", 499, "b580b5ca3227bd11a52838b0b4b58d168ff80c0123d6a755c90d0325bed1b916")
_LIVE_REVIEW_PIN = ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-live-grant-review-v2.json", 232, "8bd40aa9c3cb07d1976f5adde4ee91364e491725ee97d05a070b8ebf9606e9bc")
_LIVE_DETAILED_REVIEW_PIN = ("/Users/bytedance/Desktop/Trading Agent/mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-live-grant-v2-independent-review-fable-20261111-8e9a8076.json", 8574, "24c58b37a1fb512658c16476db110a0605d6dee7d586dadf74b6009ffec55c04")


def execute_live():
    """Execute the fixed one-shot catalog acquisition after exact live authority."""
    import contextlib
    import hashlib
    import json
    import os
    from pathlib import Path
    import stat
    from types import SimpleNamespace
    from typing import Any, Iterable

    class BrokerError(RuntimeError):
        __slots__ = ("code", "state", "receipt")

        def __init__(self, code, state="REJECTED", receipt=None):
            RuntimeError.__init__(self, code)
            self.code = code
            self.state = state
            self.receipt = dict(receipt) if type(receipt) is dict else None

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
            try:
                value.clear()
            except BufferError:
                # Outstanding read-only views cannot prevent synchronous overwrite.
                pass
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

    def _nullable_string(container, name):
        child = field(container, name)
        return not has_field(container, name) or child is None or type(child) is bytearray

    def _exact_string_object(value, required, optional=()):
        return isinstance(value, JSONObject) and keys_exact(value, required, optional) and all(type(field(value, name)) is bytearray for name in required) and all(_nullable_string(value, name) for name in optional)

    def extract_access_token(value: Any) -> bytearray:
        allowed_top = (b"auth_mode", b"OPENAI_API_KEY", b"tokens", b"last_refresh", b"agent_identity", b"personal_access_token", b"bedrock_api_key", b"bedrock_access_keys")
        if not isinstance(value, JSONObject) or not keys_exact(value, (b"tokens",), tuple(name for name in allowed_top if name != b"tokens")):
            raise MutableJSONError("AUTH_DOCUMENT_SCHEMA_REJECTED")
        auth_mode = field(value, b"auth_mode")
        modes = (b"apikey", b"chatgpt", b"chatgptAuthTokens", b"headers", b"agentIdentity", b"personalAccessToken", b"bedrockApiKey", b"bedrockAccessKeys")
        if has_field(value, b"auth_mode") and auth_mode is not None and (type(auth_mode) is not bytearray or not any(auth_mode == mode for mode in modes)):
            raise MutableJSONError("AUTH_MODE_REJECTED")
        for name in (b"OPENAI_API_KEY", b"last_refresh", b"personal_access_token"):
            if not _nullable_string(value, name):
                raise MutableJSONError("AUTH_FIELD_TYPE_REJECTED")
        identity = field(value, b"agent_identity")
        if has_field(value, b"agent_identity") and identity is not None:
            if type(identity) is not bytearray:
                record_required = (b"agent_runtime_id", b"agent_private_key", b"account_id", b"chatgpt_user_id", b"plan_type", b"chatgpt_account_is_fedramp")
                if not isinstance(identity, JSONObject) or not keys_exact(identity, record_required, (b"email", b"task_id")):
                    raise MutableJSONError("AGENT_IDENTITY_REJECTED")
                if any(type(field(identity, name)) is not bytearray for name in record_required[:-1]):
                    raise MutableJSONError("AGENT_IDENTITY_REJECTED")
                if type(field(identity, b"chatgpt_account_is_fedramp")) is not bool:
                    raise MutableJSONError("AGENT_IDENTITY_REJECTED")
                if not _nullable_string(identity, b"email") or not _nullable_string(identity, b"task_id"):
                    raise MutableJSONError("AGENT_IDENTITY_REJECTED")
        bedrock_key = field(value, b"bedrock_api_key")
        if has_field(value, b"bedrock_api_key") and bedrock_key is not None and not _exact_string_object(bedrock_key, (b"api_key", b"region")):
            raise MutableJSONError("BEDROCK_API_KEY_REJECTED")
        bedrock_access = field(value, b"bedrock_access_keys")
        if has_field(value, b"bedrock_access_keys") and bedrock_access is not None and not _exact_string_object(bedrock_access, (b"access_key_id", b"secret_access_key"), (b"session_token",)):
            raise MutableJSONError("BEDROCK_ACCESS_KEYS_REJECTED")
        tokens = field(value, b"tokens")
        token_required = (b"id_token", b"access_token", b"refresh_token")
        token_optional = (b"oauth_provenance", b"login_owner_id", b"account_id")
        if not isinstance(tokens, JSONObject) or not keys_exact(tokens, token_required, token_optional):
            raise MutableJSONError("TOKEN_DOCUMENT_SCHEMA_REJECTED")
        if any(type(field(tokens, name)) is not bytearray for name in token_required):
            raise MutableJSONError("TOKEN_FIELD_TYPE_REJECTED")
        for name in (b"login_owner_id", b"account_id"):
            if not _nullable_string(tokens, name):
                raise MutableJSONError("TOKEN_FIELD_TYPE_REJECTED")
        provenance = field(tokens, b"oauth_provenance")
        if has_field(tokens, b"oauth_provenance") and provenance is not None and not _exact_string_object(provenance, (b"issuer", b"client_id")):
            raise MutableJSONError("TOKEN_PROVENANCE_REJECTED")
        access = field(tokens, b"access_token")
        if not access:
            raise MutableJSONError("ACCESS_TOKEN_MISSING")
        return bytearray(access)

    def _canonical(value):
        return (json.dumps(value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True) + "\n").encode("ascii")

    def _read_exact_file(path, expected_size, expected_sha):
        flags = os.O_RDONLY | os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError:
            raise BrokerError("PINNED_ARTIFACT_UNAVAILABLE") from None
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or info.st_nlink != 1 or info.st_mode & 0o022 or info.st_size != expected_size:
                raise BrokerError("PINNED_ARTIFACT_IDENTITY_REJECTED")
            chunks = []
            remaining = expected_size
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    raise BrokerError("PINNED_ARTIFACT_SHORT_READ")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise BrokerError("PINNED_ARTIFACT_SIZE_CHANGED")
            raw = b"".join(chunks)
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                raise BrokerError("PINNED_ARTIFACT_HASH_REJECTED")
            return raw
        finally:
            os.close(descriptor)

    def _strict_json(raw):
        def pairs(values):
            result = {}
            for key, child in values:
                if key in result:
                    raise ValueError("duplicate")
                result[key] = child
            return result
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))

    def _verify_frozen_contracts():
        for path, size, digest, key, expected in _PINNED_ARTIFACTS:
            raw = _read_exact_file(path, size, digest)
            try:
                document = _strict_json(raw)
            except (UnicodeError, ValueError, json.JSONDecodeError):
                raise BrokerError("PINNED_ARTIFACT_JSON_REJECTED") from None
            if document.get(key) != expected:
                raise BrokerError("PINNED_ARTIFACT_SEMANTICS_REJECTED")
        open_review = _strict_json(_read_exact_file(_PINNED_ARTIFACTS[2][0], _PINNED_ARTIFACTS[2][1], _PINNED_ARTIFACTS[2][2]))
        findings = open_review.get("open_findings")
        if type(findings) is not list or {item.get("id") for item in findings if type(item) is dict} != {"OPEN-CB-001", "OPEN-CB-002", "OPEN-CB-003"}:
            raise BrokerError("OPEN_REVIEW_BINDING_REJECTED")

    def _verify_exact_live_grant():
        if _LIVE_GRANT_PIN is None or _LIVE_REVIEW_PIN is None or _LIVE_DETAILED_REVIEW_PIN is None:
            raise BrokerError("SEPARATE_EXACT_LIVE_GRANT_AND_REVIEW_REQUIRED")
        grant_raw = _read_exact_file(*_LIVE_GRANT_PIN)
        review_raw = _read_exact_file(*_LIVE_REVIEW_PIN)
        detailed_review_raw = _read_exact_file(*_LIVE_DETAILED_REVIEW_PIN)
        try:
            grant = _strict_json(grant_raw)
            review = _strict_json(review_raw)
            detailed_review = _strict_json(detailed_review_raw)
        except (UnicodeError, ValueError, json.JSONDecodeError):
            raise BrokerError("LIVE_AUTHORITY_JSON_REJECTED") from None
        expected_grant = {
            "version": "r6-one-off-codex-credential-broker-live-grant-v2",
            "status": "APPROVED_EXACT_ONE_SHOT_LIVE",
            "activation": True,
            "credential_path": "/Users/bytedance/Desktop/Trading Agent/.job-runtime/codex-home/auth.json",
            "output_root": "/Users/bytedance/Desktop/Trading Agent/.job-runtime/private/r6-one-off-codex-credential-broker-v2",
            "physical_forwards": 1,
            "retry": 0,
            "replay": 0,
            "auth_recovery": 0,
            "status_queries": 0,
            "inference_requests": 0,
            "bytedcli_calls": 0,
        }
        if grant != expected_grant:
            raise BrokerError("LIVE_GRANT_SEMANTICS_REJECTED")
        expected_review = {
            "version": "r6-one-off-codex-credential-broker-live-grant-review-v2",
            "independent": True,
            "grant_sha256": _LIVE_GRANT_PIN[2],
            "verdict": "CLEAN_EXACT_ONE_SHOT_LIVE_GRANT",
        }
        if review != expected_review:
            raise BrokerError("LIVE_REVIEW_SEMANTICS_REJECTED")
        expected_subject = {
            "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-live-grant-v2.json",
            "bytes": _LIVE_GRANT_PIN[1],
            "sha256": _LIVE_GRANT_PIN[2],
            "mode": "0600",
            "strict_json": True,
            "exact_closed_dict": True,
        }
        expected_runtime_review = {
            "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-live-grant-review-v2.json",
            "bytes": _LIVE_REVIEW_PIN[1],
            "sha256": _LIVE_REVIEW_PIN[2],
            "mode": "0600",
            "field_count": 4,
            **expected_review,
        }
        bound_broker = detailed_review.get("bound_evidence", {}).get("broker_v2", {}) if type(detailed_review) is dict else {}
        if (
            type(detailed_review) is not dict
            or detailed_review.get("version") != "r6-one-off-codex-credential-broker-live-grant-v2-independent-review-fable-20261111-8e9a8076-1"
            or detailed_review.get("review_scope") != "INDEPENDENT_STATIC_METADATA_ONLY_EXACT_ONE_SHOT_LIVE_GRANT_REVIEW_WITH_TWO_AUTHORIZED_OWNER_PRIVATE_REVIEW_WRITES"
            or detailed_review.get("verdict") != "CLEAN_EXACT_ONE_SHOT_LIVE_GRANT"
            or detailed_review.get("subject") != expected_subject
            or detailed_review.get("runtime_review") != expected_runtime_review
            or bound_broker.get("producer") != {
                "path": "tuning/architecture/r6_one_off_codex_credential_broker_v2/producer-verification-v2.json",
                "bytes": _PINNED_ARTIFACTS[3][1],
                "sha256": _PINNED_ARTIFACTS[3][2],
            }
            or bound_broker.get("clean_review") != {
                "path": "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-one-off-codex-credential-broker-v2-independent-review-fable-20261111-8e9a8076-clean.json",
                "bytes": _PINNED_ARTIFACTS[4][1],
                "sha256": _PINNED_ARTIFACTS[4][2],
                "verdict": "CLEAN_CODEX_CREDENTIAL_BROKER_V2",
            }
        ):
            raise BrokerError("LIVE_DETAILED_REVIEW_SEMANTICS_REJECTED")

    def _identity(info):
        return (info.st_dev, info.st_ino, info.st_uid, stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode))

    def _validate_directory(info, uid, mode, code):
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid or stat.S_IMODE(info.st_mode) != mode or info.st_mode & 0o022:
            raise BrokerError(code)

    def _open_chain(specs, create_from=None):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptors = []
        try:
            current = os.open("/", flags)
            descriptors.append(current)
            _validate_directory(os.fstat(current), _ROOT_SPEC[0], _ROOT_SPEC[1], "TRUSTED_ROOT_REJECTED")
            for index, (name, uid, mode) in enumerate(specs):
                if create_from is not None and index >= create_from:
                    try:
                        os.mkdir(name, mode, dir_fd=current)
                    except FileExistsError:
                        pass
                    except OSError:
                        raise BrokerError("FIXED_DIRECTORY_CREATE_FAILED", "UNKNOWN") from None
                try:
                    child = os.open(name, flags, dir_fd=current)
                except OSError:
                    raise BrokerError("FIXED_DIRECTORY_OPEN_REJECTED") from None
                descriptors.append(child)
                _validate_directory(os.fstat(child), uid, mode, "FIXED_DIRECTORY_IDENTITY_REJECTED")
                current = child
            return descriptors
        except BaseException:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
            raise

    def _verify_chain(descriptors, specs):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        _validate_directory(os.fstat(descriptors[0]), _ROOT_SPEC[0], _ROOT_SPEC[1], "TRUSTED_ROOT_DRIFT")
        for index, (name, uid, mode) in enumerate(specs):
            held = os.fstat(descriptors[index + 1])
            _validate_directory(held, uid, mode, "FIXED_DIRECTORY_DRIFT")
            try:
                probe = os.open(name, flags, dir_fd=descriptors[index])
            except OSError:
                raise BrokerError("FIXED_DIRECTORY_PATH_DRIFT", "UNKNOWN") from None
            try:
                visible = os.fstat(probe)
                _validate_directory(visible, uid, mode, "FIXED_DIRECTORY_PATH_DRIFT")
                if _identity(held) != _identity(visible):
                    raise BrokerError("FIXED_DIRECTORY_PATH_DRIFT", "UNKNOWN")
            finally:
                os.close(probe)

    def _read_auth_token():
        descriptors = _open_chain(_AUTH_CHAIN)
        raw = bytearray()
        probe = bytearray(1)
        tree = None
        token = bytearray()
        descriptor = -1
        try:
            _verify_chain(descriptors, _AUTH_CHAIN)
            try:
                descriptor = os.open(_AUTH_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
            except OSError:
                raise BrokerError("CREDENTIAL_SOURCE_OPEN_REJECTED") from None
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_uid != _OWNER_UID or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1 or before.st_size <= 0 or before.st_size > _MAX_AUTH_BYTES:
                raise BrokerError("CREDENTIAL_SOURCE_IDENTITY_REJECTED")
            before_identity = (before.st_dev, before.st_ino, before.st_uid, stat.S_IFMT(before.st_mode), stat.S_IMODE(before.st_mode), before.st_nlink, before.st_size, before.st_mtime_ns)
            raw = bytearray(before.st_size)
            offset = 0
            while offset < before.st_size:
                count = os.readv(descriptor, [memoryview(raw)[offset:]])
                if count <= 0:
                    raise BrokerError("CREDENTIAL_SOURCE_SHORT_READ")
                offset += count
            if os.readv(descriptor, [probe]) != 0:
                raise BrokerError("CREDENTIAL_SOURCE_SIZE_CHANGED", "UNKNOWN")
            after = os.fstat(descriptor)
            after_identity = (after.st_dev, after.st_ino, after.st_uid, stat.S_IFMT(after.st_mode), stat.S_IMODE(after.st_mode), after.st_nlink, after.st_size, after.st_mtime_ns)
            try:
                visible_fd = os.open(_AUTH_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=descriptors[-1])
            except OSError:
                raise BrokerError("CREDENTIAL_SOURCE_DRIFT", "UNKNOWN") from None
            try:
                visible = os.fstat(visible_fd)
                visible_identity = (visible.st_dev, visible.st_ino, visible.st_uid, stat.S_IFMT(visible.st_mode), stat.S_IMODE(visible.st_mode), visible.st_nlink, visible.st_size, visible.st_mtime_ns)
            finally:
                os.close(visible_fd)
            _verify_chain(descriptors, _AUTH_CHAIN)
            if before_identity != after_identity or before_identity != visible_identity:
                raise BrokerError("CREDENTIAL_SOURCE_DRIFT", "UNKNOWN")
            try:
                tree = parse_mutable_json(raw)
                token = extract_access_token(tree)
            except MutableJSONError as caught:
                caught.__traceback__ = None
                caught.__cause__ = None
                caught.__context__ = None
                raise BrokerError("CREDENTIAL_FORMAT_REJECTED") from None
            return token
        except BaseException:
            wipe(token)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            wipe(tree)
            wipe(raw)
            wipe(probe)
            for item in reversed(descriptors):
                os.close(item)

    def _write_full(descriptor, content):
        view = memoryview(content)
        try:
            offset = 0
            while offset < len(view):
                try:
                    written = os.write(descriptor, view[offset:])
                except OSError:
                    raise BrokerError("PUBLICATION_WRITE_FAILED", "UNKNOWN") from None
                if type(written) is not int or written <= 0 or written > len(view) - offset:
                    raise BrokerError("PUBLICATION_ZERO_OR_INVALID_WRITE", "UNKNOWN")
                offset += written
        finally:
            view.release()

    def _output_descriptors():
        specs = _OUTPUT_BASE_CHAIN + (_OUTPUT_PARENT_SPEC, _OUTPUT_SPEC)
        return specs, _open_chain(specs, create_from=len(_OUTPUT_BASE_CHAIN))

    def _claim_one_shot(descriptors, specs):
        directory_fd = descriptors[-1]
        _verify_chain(descriptors, specs)
        try:
            names = tuple(os.listdir(directory_fd))
        except OSError:
            raise BrokerError("OUTPUT_ROOT_UNAVAILABLE", "UNKNOWN") from None
        if "COMMITTED.json" in names:
            raise BrokerError("SECOND_EXECUTION_REJECTED")
        if names:
            raise BrokerError("UNKNOWN_EXISTING_EXECUTION_FENCE", "UNKNOWN")
        try:
            lock = os.open("execution.lock", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        except FileExistsError:
            raise BrokerError("UNKNOWN_EXISTING_EXECUTION_FENCE", "UNKNOWN") from None
        except OSError:
            raise BrokerError("ONE_SHOT_CLAIM_FAILED", "UNKNOWN") from None
        try:
            _write_full(lock, b"one-shot\n")
            os.fsync(lock)
        finally:
            os.close(lock)
        os.fsync(directory_fd)
        _verify_chain(descriptors, specs)

    def _reopen_hash(directory_fd, name, expected_size):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
        except OSError:
            raise BrokerError("PUBLICATION_REOPEN_FAILED", "UNKNOWN") from None
        content = bytearray(expected_size)
        one = bytearray(1)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != _OWNER_UID or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != expected_size:
                raise BrokerError("PUBLICATION_REOPEN_IDENTITY_REJECTED", "UNKNOWN")
            offset = 0
            while offset < expected_size:
                count = os.readv(descriptor, [memoryview(content)[offset:]])
                if count <= 0:
                    raise BrokerError("PUBLICATION_REOPEN_SHORT_READ", "UNKNOWN")
                offset += count
            if os.readv(descriptor, [one]) != 0:
                raise BrokerError("PUBLICATION_REOPEN_SIZE_CHANGED", "UNKNOWN")
            return hashlib.sha256(content).hexdigest()
        finally:
            wipe(content)
            wipe(one)
            os.close(descriptor)

    def _commit_one(directory_fd, name, content):
        staging = "." + name + ".staging"
        try:
            descriptor = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        except OSError:
            raise BrokerError("PUBLICATION_STAGING_OPEN_FAILED", "UNKNOWN") from None
        try:
            _write_full(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(staging, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd, follow_symlinks=False)
        except FileExistsError:
            raise BrokerError("PUBLICATION_NO_REPLACE_REJECTED", "UNKNOWN") from None
        except OSError:
            raise BrokerError("PUBLICATION_LINK_FAILED", "UNKNOWN") from None
        os.unlink(staging, dir_fd=directory_fd)
        os.fsync(directory_fd)
        digest = _reopen_hash(directory_fd, name, len(content))
        if digest != hashlib.sha256(content).hexdigest():
            raise BrokerError("PUBLICATION_REOPEN_HASH_MISMATCH", "UNKNOWN")
        return digest, len(content)

    def _membership(result):
        receipt = result.receipt
        models = result.models
        origin = result.origin
        if type(models) is not tuple or models.count(_MODEL) != 1 or type(receipt) is not dict or receipt.get("status") != "PASS" or type(receipt.get("body_sha256")) is not str or type(receipt.get("body_bytes")) is not int or type(receipt.get("model_count")) is not int or receipt.get("model_count") != len(models):
            raise BrokerError("DIRECT_CATALOG_RESULT_REJECTED", "UNKNOWN")
        if type(origin.kind) is not str or type(origin.host) is not str or type(origin.tls_hostname_verified) is not bool:
            raise BrokerError("DIRECT_CATALOG_ORIGIN_REJECTED", "UNKNOWN")
        return {"origin": {"kind": origin.kind, "host": origin.host, "tls_hostname_verified": origin.tls_hostname_verified}, "status": "PASS", "body_sha256": receipt["body_sha256"], "body_bytes": receipt["body_bytes"], "model_count": receipt["model_count"], "gpt_6_1_sol_membership": {"model": _MODEL, "count": 1, "exact": True}}

    _verify_frozen_contracts()
    _verify_exact_live_grant()
    specs, output_descriptors = _output_descriptors()
    token_material = bytearray()
    raw_response = bytearray()
    result = None
    try:
        _claim_one_shot(output_descriptors, specs)
        token_material = _read_auth_token()
        from shared.job_runtime.candidates import r6_one_off_codex_direct_catalog_v1 as direct_catalog
        try:
            with direct_catalog.transient_bearer_scope(token_material) as capability:
                token_material = bytearray()
                executor = direct_catalog.DirectCatalogExecutor()
                try:
                    result = executor.execute(capability, include_owner_private_raw=True)
                except direct_catalog.CatalogExecutionError as caught:
                    code = caught.code
                    receipt = caught.receipt
                    caught.__traceback__ = None
                    caught.__cause__ = None
                    caught.__context__ = None
                    capability = None
                    executor = None
                    raise BrokerError(code, "UNKNOWN", receipt) from None
        finally:
            wipe(token_material)
        membership = _membership(result)
        owner_raw = result.owner_private_raw
        if type(owner_raw) is not bytes or not owner_raw:
            owner_raw = None
            result = None
            raise BrokerError("RAW_CATALOG_MISSING", "UNKNOWN")
        raw_response = bytearray(owner_raw)
        owner_raw = None
        result = None
        membership_bytes = _canonical(membership)
        raw_digest = hashlib.sha256(raw_response).hexdigest()
        membership_digest = hashlib.sha256(membership_bytes).hexdigest()
        execution = {"schema_version": "r6-one-off-codex-credential-broker-execution-receipt-v2", "outcome": "PASS", "credential_format": _CREDENTIAL_FORMAT, "physical_forwards": 1, "retry": 0, "replay": 0, "auth_recovery": 0, "status_queries": 0, "inference_requests": 0, "bytedcli_calls": 0, "direct_catalog_producer_sha256": _DIRECT_PRODUCER_SHA256, "direct_catalog_review_sha256": _DIRECT_REVIEW_SHA256, "artifact_sha256": {"raw_catalog": raw_digest, "membership": membership_digest}}
        execution_bytes = _canonical(execution)
        directory_fd = output_descriptors[-1]
        _verify_chain(output_descriptors, specs)
        raw_sha, raw_size = _commit_one(directory_fd, "catalog.raw.json", raw_response)
        membership_sha, membership_size = _commit_one(directory_fd, "catalog-membership.receipt.json", membership_bytes)
        execution_sha, execution_size = _commit_one(directory_fd, "execution.receipt.json", execution_bytes)
        marker = {"schema_version": "r6-one-off-codex-credential-broker-commit-v2", "committed": True, "artifacts": {"raw_catalog": {"bytes": raw_size, "sha256": raw_sha}, "membership_receipt": {"bytes": membership_size, "sha256": membership_sha}, "execution_receipt": {"bytes": execution_size, "sha256": execution_sha}}}
        marker_bytes = _canonical(marker)
        _commit_one(directory_fd, "COMMITTED.json", marker_bytes)
        _verify_chain(output_descriptors, specs)
        output_path = Path("/").joinpath(*(name for name, _, _ in specs))
        return SimpleNamespace(raw_catalog_path=output_path / "catalog.raw.json", membership_receipt_path=output_path / "catalog-membership.receipt.json", execution_receipt_path=output_path / "execution.receipt.json", commit_marker_path=output_path / "COMMITTED.json", raw_catalog_sha256=raw_sha, membership_receipt_sha256=membership_sha, execution_receipt_sha256=execution_sha)
    except BrokerError:
        raise
    except BaseException:
        raise
    finally:
        result = None
        wipe(token_material)
        wipe(raw_response)
        for descriptor in reversed(output_descriptors):
            os.close(descriptor)
