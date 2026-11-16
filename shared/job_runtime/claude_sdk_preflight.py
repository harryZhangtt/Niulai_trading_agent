"""Offline-only Claude Agent SDK pin and option-surface preflight."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import io
import os
import stat
import json
from pathlib import Path
import sys

from .claude_bridge import CLAUDE_MODEL_CAPABILITIES

EXPECTED_DISTRIBUTION = "claude-agent-sdk"
EXPECTED_VERSION = "0.2.179"
MINIMUM_PYTHON = (3, 10)
ASSISTANT_FIELDS = frozenset({"model", "error"})
RESULT_FIELDS = frozenset({
    "model_usage", "usage", "total_cost_usd", "stop_reason", "api_error_status",
    "terminal_reason", "subtype", "is_error", "result", "session_id",
})
MODEL_USAGE_REQUIRED_KEYS = frozenset({
    "inputTokens", "outputTokens", "cacheReadInputTokens",
    "cacheCreationInputTokens", "webSearchRequests", "costUSD",
    "contextWindow", "maxOutputTokens",
})
MODEL_USAGE_OPTIONAL_KEYS = frozenset({"canonicalModel", "provider"})



def _tree_hash(distribution) -> str | None:
    files = distribution.files
    if files is None:
        return None
    rows = []
    for item in sorted(files, key=str):
        path = distribution.locate_file(item)
        if path.is_file():
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                return None
            rows.append((str(item), digest))
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()


def _record_digests(distribution) -> tuple[str | None, str | None]:
    """Hash exact RECORD bytes and importlib's normalized text representation.

    The raw digest is authoritative.  The text digest is compatibility evidence
    for historical receipts that used ``Distribution.read_text("RECORD")``.
    The final directory entry is opened relative to a no-follow directory
    descriptor, and its identity is checked before, during, and after reading.
    """
    files = distribution.files
    if files is None:
        return None, None
    record_items = [item for item in files if Path(str(item)).name == "RECORD"
                    and Path(str(item)).parent.name.endswith(".dist-info")]
    if len(record_items) != 1:
        return None, None
    record_path = Path(distribution.locate_file(record_items[0]))
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(record_path.parent, directory_flags)
    file_fd = -1
    try:
        before = os.stat(record_path.name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            return None, None
        file_fd = os.open(record_path.name, file_flags, dir_fd=directory_fd)
        opened = os.fstat(file_fd)
        identity = (before.st_dev, before.st_ino, before.st_mode, before.st_size)
        if identity != (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size):
            return None, None
        chunks = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_open = os.fstat(file_fd)
        after_path = os.stat(record_path.name, dir_fd=directory_fd, follow_symlinks=False)
        if identity != (after_open.st_dev, after_open.st_ino, after_open.st_mode, after_open.st_size):
            return None, None
        if identity != (after_path.st_dev, after_path.st_ino, after_path.st_mode, after_path.st_size):
            return None, None
        raw = b"".join(chunks)
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        os.close(directory_fd)
    raw_sha256 = hashlib.sha256(raw).hexdigest()
    try:
        with io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", newline=None) as stream:
            normalized = stream.read().encode("utf-8")
    except UnicodeError:
        return raw_sha256, None
    return raw_sha256, hashlib.sha256(normalized).hexdigest()


def _declared_fields(value) -> set[str]:
    fields = getattr(value, "__dataclass_fields__", None)
    if isinstance(fields, dict):
        return set(fields)
    annotations = getattr(value, "__annotations__", None)
    return set(annotations) if isinstance(annotations, dict) else set()


def _typed_dict_shape(value):
    annotations = _declared_fields(value)
    required = set(getattr(value, "__required_keys__", ()))
    optional = set(getattr(value, "__optional_keys__", ()))
    return annotations, required, optional


def inspect_environment(requirements_path: Path, lock_path: Path | None = None) -> dict:
    requirements_path = Path(requirements_path)
    lock_path = Path(lock_path) if lock_path else requirements_path.with_name(
        "claude-requirements.lock.json")
    declared = requirements_path.read_text().strip() if requirements_path.is_file() else None
    try:
        lock = json.loads(lock_path.read_text())
    except (OSError, json.JSONDecodeError):
        lock = {}
    blockers = []
    if declared != f"{EXPECTED_DISTRIBUTION}=={EXPECTED_VERSION}":
        blockers.append("CLAUDE_SDK_PIN_INVALID")
    if sys.version_info < MINIMUM_PYTHON:
        blockers.append("CLAUDE_SDK_PYTHON_UNSUPPORTED")
    expected_tree = lock.get("expected_distribution_tree_sha256")
    expected_record_raw = lock.get("expected_record_raw_bytes_sha256")
    expected_record_text = lock.get("expected_record_importlib_text_utf8_sha256")
    if not isinstance(expected_tree, str) or len(expected_tree) != 64:
        blockers.append("CLAUDE_SDK_REVIEWED_TREE_DIGEST_MISSING")
    if not isinstance(expected_record_raw, str) or len(expected_record_raw) != 64:
        blockers.append("CLAUDE_SDK_REVIEWED_RECORD_RAW_BYTES_DIGEST_MISSING")
    if not isinstance(expected_record_text, str) or len(expected_record_text) != 64:
        blockers.append("CLAUDE_SDK_REVIEWED_RECORD_IMPORTLIB_TEXT_DIGEST_MISSING")
    installed = None
    package_tree_sha256 = None
    record_raw_bytes_sha256 = None
    record_importlib_text_utf8_sha256 = None
    option_parameters = None
    query_parameters = None
    assistant_fields = None
    result_fields = None
    model_usage_keys = None
    model_usage_required_keys = None
    model_usage_optional_keys = None
    try:
        distribution = importlib.metadata.distribution(EXPECTED_DISTRIBUTION)
        installed = distribution.version
        package_tree_sha256 = _tree_hash(distribution)
        (record_raw_bytes_sha256,
         record_importlib_text_utf8_sha256) = _record_digests(distribution)
    except importlib.metadata.PackageNotFoundError:
        blockers.append("CLAUDE_SDK_MISSING")
    if installed is not None and installed != EXPECTED_VERSION:
        blockers.append("CLAUDE_SDK_VERSION_MISMATCH")
    if installed == EXPECTED_VERSION:
        if package_tree_sha256 != expected_tree:
            blockers.append("CLAUDE_SDK_TREE_DIGEST_MISMATCH")
        if record_raw_bytes_sha256 != expected_record_raw:
            blockers.append("CLAUDE_SDK_RECORD_RAW_BYTES_DIGEST_MISMATCH")
        if record_importlib_text_utf8_sha256 != expected_record_text:
            blockers.append("CLAUDE_SDK_RECORD_IMPORTLIB_TEXT_DIGEST_MISMATCH")
        try:
            from claude_agent_sdk import (
                AssistantMessage, ClaudeAgentOptions, ResultMessage, query)
            try:
                from claude_agent_sdk.types import ModelUsage
            except ImportError:
                from claude_agent_sdk import ModelUsage
            option_signature = inspect.signature(ClaudeAgentOptions)
            query_signature = inspect.signature(query)
            option_parameters = tuple(option_signature.parameters)
            query_parameters = tuple(query_signature.parameters)
            assistant_fields = tuple(sorted(_declared_fields(AssistantMessage)))
            result_fields = tuple(sorted(_declared_fields(ResultMessage)))
            (model_usage_annotations, model_usage_required,
             model_usage_optional) = _typed_dict_shape(ModelUsage)
            model_usage_keys = tuple(sorted(model_usage_annotations))
            model_usage_required_keys = tuple(sorted(model_usage_required))
            model_usage_optional_keys = tuple(sorted(model_usage_optional))
            required = set(CLAUDE_MODEL_CAPABILITIES["claude-fable-5-1"][
                "required_option_fields"])
            has_kwargs = any(item.kind is inspect.Parameter.VAR_KEYWORD
                             for item in option_signature.parameters.values())
            if not has_kwargs and not required <= set(option_signature.parameters):
                blockers.append("CLAUDE_SDK_OPTION_SURFACE_MISMATCH")
            if not {"prompt", "options"} <= set(query_signature.parameters):
                blockers.append("CLAUDE_SDK_QUERY_SURFACE_MISMATCH")
            if not ASSISTANT_FIELDS <= set(assistant_fields):
                blockers.append("CLAUDE_SDK_ASSISTANT_SURFACE_MISMATCH")
            if not RESULT_FIELDS <= set(result_fields):
                blockers.append("CLAUDE_SDK_RESULT_SURFACE_MISMATCH")
            if (model_usage_annotations != (MODEL_USAGE_REQUIRED_KEYS | MODEL_USAGE_OPTIONAL_KEYS)
                    or model_usage_required != MODEL_USAGE_REQUIRED_KEYS
                    or model_usage_optional != MODEL_USAGE_OPTIONAL_KEYS):
                blockers.append("CLAUDE_SDK_MODEL_USAGE_SURFACE_MISMATCH")
        except (ImportError, AttributeError, TypeError, ValueError):
            blockers.append("CLAUDE_SDK_IMPORT_SURFACE_INVALID")
    return {
        "schema_version": 3,
        "status": "READY_OFFLINE" if not blockers else "BLOCKED_OFFLINE",
        "blockers": sorted(set(blockers)),
        "network_used": False, "install_performed": False,
        "declared_requirement": declared, "installed_version": installed,
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "minimum_python": "3.10", "target_runtime_python": "3.12",
        "package_tree_sha256": package_tree_sha256,
        "record_raw_bytes_sha256": record_raw_bytes_sha256,
        "record_importlib_text_utf8_sha256": record_importlib_text_utf8_sha256,
        "expected_distribution_tree_sha256": expected_tree,
        "expected_record_raw_bytes_sha256": expected_record_raw,
        "expected_record_importlib_text_utf8_sha256": expected_record_text,
        "option_parameters": option_parameters, "query_parameters": query_parameters,
        "assistant_fields": assistant_fields, "result_fields": result_fields,
        "model_usage_keys": model_usage_keys,
        "model_usage_required_keys": model_usage_required_keys,
        "model_usage_optional_keys": model_usage_optional_keys,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements", required=True)
    args = parser.parse_args(argv)
    result = inspect_environment(Path(args.requirements))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "READY_OFFLINE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
