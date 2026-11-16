"""Strict v6 contracts for the disabled provider-free Claude one-shot boundary."""
from __future__ import annotations
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

MODEL = "claude-opus-5-5"
PROVIDER = "claude_host"
FERRY = "claude_ferry"
EFFORT = "low"
NATIVE_PROMPT = "/model"
FERRY_HOST = "127.0.0.1"
FERRY_PATH = "/v1/messages"
CLOCK_ID = "system_utc_time_ns"
PUBLICATION_ORDERING = "WRITE_ALL_FILE_FSYNC_LINK_NO_REPLACE_STAGE_UNLINK_PARENT_FSYNC_REOPEN_NOFOLLOW_EXACT_READBACK_FILE_FSYNC_PARENT_FSYNC_MARKER_LAST_AUTHORITY_PROMOTION_LAST"
STATE_PROTOCOL = "SQLITE_FULL_SYNC_GENERATION_AUTHORITY_V1"
SAFE_ARGV = (
    "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
    "--model", MODEL, "--effort", EFFORT, "--permission-mode", "dontAsk",
    "--permission-prompts", "none", "--no-session-persistence", "--safe-mode",
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--tools", "",
    "--setting-sources", "", "--no-chrome", "--max-budget-usd", "0.01", NATIVE_PROMPT,
)
GRANT_SHA256 = "e39fbc491d447cc239e26b837c2d8185c21de9944c39ff79c1538333edbdc06b"
GRANT_REVIEW_SHA256 = "d4a02c8ae663128c1bb883c71ab44f298119b22c1e38658308844826c71e4059"
REGISTRY_SHA256 = "c1b1a816a2ee42f08d6e135b495a60e65a3a081f4b94b39bf60aed3cf4c8ba82"
REGISTRY_REVIEW_SHA256 = "55cbcc07837e27607ee88e3a3d82aa59f63575444c24a257cc4ecefdb560e7cb"
SCOPE_SHA256 = "d2f4d61436a8884d5a46ec3d1ae163aa0d1c17344a85010395f832c49ea3f267"
BINARY_REF = "shared/job_runtime/tests/fixtures/r6_one_off_claude_live_integration_v1/fake_claude.py"
BINARY_DESCRIPTOR = {"bytes": 1197, "mode": 448,
    "sha256": "441ec85d14760889d4ece3c297abd5f62b6fea8cd0aba11fc25f5e02ff925607",
    "uid": 501}
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SECRET = re.compile(r"(?i)(sk-ant-|api[_-]?key|auth(?:orization|_token)|bearer\s|password|secret(?:_value)?)")


class ContractError(ValueError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ContractError(code)


def exact(value: Any, keys: Iterable[str], code: str) -> Mapping[str, Any]:
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def strict(value: Any, depth: int = 0) -> None:
    require(depth <= 32, "JSON_DEPTH")
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        require(-(2**53)+1 <= value <= (2**53)-1, "JSON_INTEGER")
        return
    if type(value) is float:
        require(math.isfinite(value), "JSON_FLOAT")
        return
    if type(value) is list:
        for item in value:
            strict(item, depth + 1)
        return
    require(type(value) is dict and all(type(key) is str for key in value), "JSON_TYPE")
    for item in value.values():
        strict(item, depth + 1)


def canonical_bytes(value: Any) -> bytes:
    strict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: Any, code: str) -> str:
    require(type(value) is str and _SHA.fullmatch(value) is not None, code)
    return value


def safe_public(value: Any) -> None:
    raw = canonical_bytes(value).decode("ascii")
    require(_SECRET.search(raw) is None, "PUBLIC_SECRET")
    require("/users/" not in raw.lower() and ".job-runtime" not in raw.lower(),
            "PUBLIC_PRIVATE_DATA")


def validate_descriptor(value: Any, executable: bool = False) -> Mapping[str, Any]:
    item = exact(value, {"bytes", "mode", "sha256", "uid"}, "DESCRIPTOR_SHAPE")
    require(type(item["bytes"]) is int and item["bytes"] > 0 and
            type(item["mode"]) is int and type(item["uid"]) is int, "DESCRIPTOR_TYPE")
    digest(item["sha256"], "DESCRIPTOR_SHA")
    if executable:
        require(item["mode"] & 0o111 != 0, "BINARY_NOT_EXECUTABLE")
    return item


def validate_grant(value: Any) -> Mapping[str, Any]:
    keys = {"version", "cell_id", "grant_id", "issuer", "binary_ref", "binary", "argv",
        "native_prompt", "model", "effort", "credential_ref", "timeout_seconds",
        "max_requests", "max_upstream", "request_retries", "status_calls", "replay",
        "not_before", "expires_at", "post_run_receipt_required"}
    item = exact(value, keys, "GRANT_SHAPE")
    require(item["version"] == 2 and
            item["cell_id"] == "cell/provider-free-main-authority-v4" and
            item["grant_id"] == "grant/provider-free-main-authority-v4" and
            item["issuer"] == "main-session/integration-owner-v4", "GRANT_ID")
    validate_descriptor(item["binary"], True)
    require(item["binary"] == BINARY_DESCRIPTOR and item["binary_ref"] == BINARY_REF,
            "GRANT_BINARY_IDENTITY")
    require(tuple(item["argv"]) == SAFE_ARGV and item["native_prompt"] == NATIVE_PROMPT and
            item["model"] == MODEL and item["effort"] == EFFORT, "GRANT_COMMAND")
    require(item["credential_ref"] == "profile://current/opaque-main-authority-v4",
            "GRANT_CREDENTIAL_REF")
    require(item["timeout_seconds"] == 5 and item["max_requests"] == 1 and
            item["max_upstream"] == 1 and item["request_retries"] == 0 and
            item["status_calls"] == 0 and item["replay"] is False and
            item["post_run_receipt_required"] is False, "GRANT_LIMITS")
    require(type(item["not_before"]) is str and type(item["expires_at"]) is str,
            "GRANT_TIME_TYPE")
    return item


def parse_aware(value: Any, code: str) -> datetime:
    require(type(value) is str, code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ContractError(code) from None
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, code)
    return parsed.astimezone(timezone.utc)


def validate_window(grant: Mapping[str, Any], now: datetime) -> None:
    require(isinstance(now, datetime) and now.tzinfo is not None and
            now.utcoffset() is not None, "TRUSTED_CLOCK_INVALID")
    start = parse_aware(grant["not_before"], "GRANT_NOT_BEFORE_MALFORMED")
    end = parse_aware(grant["expires_at"], "GRANT_EXPIRES_MALFORMED")
    require(start < end, "GRANT_WINDOW_INVALID")
    require(start <= now.astimezone(timezone.utc) < end, "GRANT_STALE_OR_NOT_YET_VALID")


def validate_review(value: Any, grant_sha: str, issuer: str) -> Mapping[str, Any]:
    item = exact(value, {"version", "review_id", "reviewer", "independent",
                         "grant_sha256", "decision", "scope"}, "REVIEW_SHAPE")
    require(item == {"decision": "APPROVE", "grant_sha256": grant_sha,
        "independent": True,
        "review_id": "review/r6-o1-claude-live-integration-v4-provider-free-claude-20261111",
        "reviewer": "independent/claude-v4-provider-free-review",
        "scope": "ONE_CELL_ONE_SHOT", "version": 2} and item["reviewer"] != issuer,
        "REVIEW_INVALID")
    return item


def validate_registry(value: Any, cell: str, grant_sha: str,
                      review_sha: str) -> Mapping[str, Any]:
    item = exact(value, {"version", "registry_id", "authority", "entries"},
                 "REGISTRY_SHAPE")
    require(item["version"] == 2 and
            item["registry_id"] == "registry/provider-free-main-authority-v4" and
            item["authority"] == "external/main-session-integration-owner-registry-v4",
            "REGISTRY_AUTHORITY")
    require(item["entries"] == [{"cell_id": cell, "grant_sha256": grant_sha,
        "review_sha256": review_sha, "state": "ACTIVE"}], "REGISTRY_BINDING")
    return item


def _identity_complete(item: Mapping[str, Any]) -> None:
    require(item["engine"]["provider"] in (None, PROVIDER), "ENGINE_PROVIDER")
    process = item["process"]
    require(process["provider"] == PROVIDER and process["model"] == MODEL and
            process["binary_ref"] == BINARY_REF and
            process["binary_descriptor"] == BINARY_DESCRIPTOR and
            process["argv"] == list(SAFE_ARGV), "PROCESS_IDENTITY")
    ferry = item["ferry"]
    require(ferry["provider"] == PROVIDER and ferry["transport"] == FERRY and
            ferry["host"] == FERRY_HOST and ferry["path"] == FERRY_PATH and
            ferry["model"] == MODEL, "FERRY_IDENTITY")


def validate_seal(value: Any) -> Mapping[str, Any]:
    keys = {"version", "status", "code", "countable", "cell_id", "model", "effort",
        "engine", "authority", "process", "ferry", "custody", "terminal", "cleanup",
        "publication", "unknown_fence", "state_authority", "effects"}
    item = exact(value, keys, "SEAL_SHAPE")
    require(item["version"] == 6 and item["status"] in ("PASS", "STOP", "UNKNOWN") and
            type(item["code"]) is str and item["countable"] is False and
            item["model"] == MODEL and item["effort"] == EFFORT, "SEAL_HEADER")
    exact(item["engine"], {"provider", "job_id", "slot_id", "attempt_id", "operation_id",
        "prompt_binding_sha256", "readback_digest", "status"}, "ENGINE_SHAPE")
    authority = exact(item["authority"], {"grant_sha256", "grant_review_sha256",
        "registry_sha256", "registry_review_sha256", "scope_sha256", "clock_id",
        "validated_before_effect", "post_receipt_required_pregrant"}, "AUTHORITY_SHAPE")
    require(authority["validated_before_effect"] is True and
            authority["post_receipt_required_pregrant"] is False and
            authority["clock_id"] == CLOCK_ID, "AUTHORITY_PHASE")
    process = exact(item["process"], {"provider", "model", "binary_ref", "binary_descriptor",
        "argv", "argv_sha256", "starts", "exit_code", "timed_out", "binary_sha256",
        "private_copy_sha256", "private_copy_device", "private_copy_inode",
        "private_copy_mode", "private_copy_uid", "process_start_token_sha256",
        "child_start_token_sha256", "shell", "process_group", "descriptors_closed",
        "pid_gone", "child_pid", "child_pid_gone", "cleanup_probe_after_parent_exit",
        "process_group_gone", "descendants_reaped", "cleanup_exception"}, "PROCESS_SHAPE")
    ferry = exact(item["ferry"], {"provider", "transport", "host", "path", "model", "admissions",
        "upstream_attempts", "second_rejections", "listener_closed", "status_calls",
        "request_fingerprint_sha256", "cleanup_exception"}, "FERRY_SHAPE")
    for key in ("argv_sha256", "binary_sha256", "private_copy_sha256",
                "process_start_token_sha256", "child_start_token_sha256"):
        digest(process[key], "PROCESS_DIGEST")
    require(all(type(process[key]) is int and process[key] >= 0 for key in
                ("starts", "private_copy_device", "private_copy_inode",
                 "private_copy_mode", "private_copy_uid", "child_pid")),
            "PROCESS_INTEGER")
    digest(ferry["request_fingerprint_sha256"], "FERRY_FINGERPRINT")
    require(all(type(ferry[key]) is int and ferry[key] >= 0 for key in
                ("admissions", "upstream_attempts", "second_rejections", "status_calls")),
            "FERRY_INTEGER")
    exact(item["custody"], {"stdout_bytes", "stdout_sha256", "stderr_bytes", "stderr_sha256",
        "owner_private", "raw_public"}, "CUSTODY_SHAPE")
    exact(item["terminal"], {"recognized", "exactly_one", "state", "parser"},
          "TERMINAL_SHAPE")
    exact(item["cleanup"], {"process_group_reaped", "verified_copy_removed",
        "listener_closed", "descriptors_closed", "exception_count"}, "CLEANUP_SHAPE")
    publication = exact(item["publication"], {"sanitized", "atomic", "file_fsynced",
        "directory_fsynced", "final_reopened_nofollow", "readback_verified", "ordering",
        "public_sha256"}, "PUBLICATION_SHAPE")
    unknown = exact(item["unknown_fence"], {"durable", "durability", "retry", "replay",
        "status_calls"}, "UNKNOWN_SHAPE")
    require(unknown["retry"] is False and unknown["replay"] is False and
            unknown["status_calls"] == 0 and unknown["durability"] in
            ("NOT_APPLICABLE", "DURABLE", "NON_DURABLE"), "UNKNOWN_POLICY")
    state_authority = exact(item["state_authority"], {"protocol", "generation_sha256",
        "state", "precedence", "source_pinned"}, "STATE_AUTHORITY_SHAPE")
    require(state_authority["protocol"] == STATE_PROTOCOL and
            state_authority["state"] in ("ABSENT", "UNKNOWN", "PASS", "POISONED") and
            state_authority["precedence"] == "AUTHORITY_BEFORE_PROJECTIONS" and
            state_authority["source_pinned"] is True,
            "STATE_AUTHORITY_POLICY")
    digest(state_authority["generation_sha256"], "STATE_AUTHORITY_GENERATION")
    require(item["effects"] == {"provider": 0, "non_loopback_network": 0, "account": 0,
        "login": 0, "private_live_root": 0, "email": 0, "host": 0, "persistent": 0,
        "business": 0, "scheduler": 0, "r5": 0}, "EFFECTS")
    _identity_complete(item)
    if item["cell_id"] is not None:
        require(authority == {"grant_sha256": GRANT_SHA256,
            "grant_review_sha256": GRANT_REVIEW_SHA256,
            "registry_sha256": REGISTRY_SHA256,
            "registry_review_sha256": REGISTRY_REVIEW_SHA256,
            "scope_sha256": SCOPE_SHA256, "clock_id": CLOCK_ID,
            "validated_before_effect": True, "post_receipt_required_pregrant": False},
            "AUTHORITY_IDENTITY")
    require(publication["sanitized"] is True, "PUBLICATION_SANITIZED")
    digest(publication["public_sha256"], "PUBLICATION_SHA")
    unpublished = {"sanitized": True, "atomic": False, "file_fsynced": False,
        "directory_fsynced": False, "final_reopened_nofollow": False,
        "readback_verified": False, "ordering": "NONE", "public_sha256": "0" * 64}
    committed = (publication["atomic"] is True and
        publication["file_fsynced"] is True and
        publication["directory_fsynced"] is True and
        publication["final_reopened_nofollow"] is True and
        publication["readback_verified"] is True and
        publication["ordering"] == PUBLICATION_ORDERING and
        publication["public_sha256"] != "0" * 64)
    not_applicable = {"durable": False, "durability": "NOT_APPLICABLE",
        "retry": False, "replay": False, "status_calls": 0}
    nondurable = {"durable": False, "durability": "NON_DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    durable = {"durable": True, "durability": "DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    if item["status"] == "PASS":
        require(item["code"] == "EXACT_CLAUDE_HOST_TERMINAL_FERRY_ENGINE_EXIT_VERIFIED" and
            item["engine"]["provider"] == PROVIDER and
            item["engine"]["status"] == "succeeded" and process["starts"] == 1 and
            process["exit_code"] == 0 and process["timed_out"] is False and
            process["descriptors_closed"] is True and process["pid_gone"] is True and
            process["descendants_reaped"] is True and
            process["process_group_gone"] is True and
            process["child_pid_gone"] is True and
            process["cleanup_probe_after_parent_exit"] is True and
            process["cleanup_exception"] is False and
            item["terminal"] == {"recognized": True, "exactly_one": True,
                "state": "exact", "parser": "claude-stream-json-v1"} and
            item["cleanup"] == {"process_group_reaped": True,
                "verified_copy_removed": True, "listener_closed": True,
                "descriptors_closed": True, "exception_count": 0} and
            item["ferry"]["admissions"] == item["ferry"]["upstream_attempts"] == 1 and
            item["ferry"]["second_rejections"] == 0 and
            item["ferry"]["listener_closed"] is True and
            item["ferry"]["cleanup_exception"] is False and
            item["custody"]["owner_private"] is True and
            item["custody"]["raw_public"] is False and committed and
            unknown == not_applicable and state_authority["state"] == "PASS" and
            state_authority["generation_sha256"] != "0" * 64, "PASS_CONFLICT")
    elif item["status"] == "UNKNOWN":
        if unknown == durable:
            require((committed or publication == unpublished) and
                    not item["code"].endswith("_NON_DURABLE") and
                    state_authority["state"] in ("UNKNOWN", "POISONED") and
                    state_authority["generation_sha256"] != "0" * 64,
                    "UNKNOWN_DURABLE_CONFLICT")
        else:
            require(unknown == nondurable and publication == unpublished and
                    item["code"].endswith("_NON_DURABLE") and
                    state_authority["state"] == "ABSENT",
                    "UNKNOWN_NON_DURABLE_CONFLICT")
    else:
        require(unknown == not_applicable and publication == unpublished and
                state_authority["state"] == "ABSENT",
                "STOP_CONFLICT")
    safe_public(item)
    return item


def blank_seal(code: str = "EXTERNAL_AUTHORITY_REQUIRED") -> dict:
    return {"version": 6, "status": "STOP", "code": code, "countable": False,
        "cell_id": None, "model": MODEL, "effort": EFFORT,
        "engine": {"provider": None, "job_id": None, "slot_id": None, "attempt_id": None,
            "operation_id": None, "prompt_binding_sha256": None, "readback_digest": None,
            "status": None},
        "authority": {"grant_sha256": "0"*64, "grant_review_sha256": "0"*64,
            "registry_sha256": "0"*64, "registry_review_sha256": "0"*64,
            "scope_sha256": "0"*64, "clock_id": CLOCK_ID,
            "validated_before_effect": True, "post_receipt_required_pregrant": False},
        "process": {"provider": PROVIDER, "model": MODEL, "binary_ref": BINARY_REF,
            "binary_descriptor": dict(BINARY_DESCRIPTOR), "argv": list(SAFE_ARGV),
            "argv_sha256": sha256_bytes(canonical_bytes(list(SAFE_ARGV))), "starts": 0,
            "exit_code": None, "timed_out": False, "binary_sha256": "0"*64,
            "private_copy_sha256": "0"*64, "private_copy_device": 0,
            "private_copy_inode": 0, "private_copy_mode": 0,
            "private_copy_uid": 0, "process_start_token_sha256": "0"*64,
            "child_start_token_sha256": "0"*64, "shell": False,
            "process_group": True, "descriptors_closed": True, "pid_gone": True,
            "child_pid": 0,
            "child_pid_gone": True, "cleanup_probe_after_parent_exit": True,
            "process_group_gone": True, "descendants_reaped": True,
            "cleanup_exception": False},
        "ferry": {"provider": PROVIDER, "transport": FERRY, "host": FERRY_HOST,
            "path": FERRY_PATH, "model": MODEL, "admissions": 0, "upstream_attempts": 0,
            "second_rejections": 0, "listener_closed": True, "status_calls": 0,
            "request_fingerprint_sha256": "0"*64, "cleanup_exception": False},
        "custody": {"stdout_bytes": 0, "stdout_sha256": "0"*64, "stderr_bytes": 0,
            "stderr_sha256": "0"*64, "owner_private": True, "raw_public": False},
        "terminal": {"recognized": False, "exactly_one": False, "state": "absent",
            "parser": "claude-stream-json-v1"},
        "cleanup": {"process_group_reaped": True, "verified_copy_removed": True,
            "listener_closed": True, "descriptors_closed": True, "exception_count": 0},
        "publication": {"sanitized": True, "atomic": False, "file_fsynced": False,
            "directory_fsynced": False, "final_reopened_nofollow": False,
            "readback_verified": False, "ordering": "NONE", "public_sha256": "0"*64},
        "unknown_fence": {"durable": False, "durability": "NOT_APPLICABLE",
            "retry": False, "replay": False, "status_calls": 0},
        "state_authority": {"protocol": STATE_PROTOCOL,
            "generation_sha256": "0"*64, "state": "ABSENT",
            "precedence": "AUTHORITY_BEFORE_PROJECTIONS", "source_pinned": True},
        "effects": {"provider": 0, "non_loopback_network": 0, "account": 0,
            "login": 0, "private_live_root": 0, "email": 0, "host": 0,
            "persistent": 0, "business": 0, "scheduler": 0, "r5": 0}}
