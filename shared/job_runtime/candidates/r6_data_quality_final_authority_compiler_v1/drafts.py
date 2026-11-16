"""Closed validators for non-authorizing future grant Drafts.

These functions validate data only.  They do not mint, sign, review, write,
activate, adopt, or return a live grant.
"""
from __future__ import annotations
from typing import Any, Mapping
from .compiler import ContractError, STATUS, _require

_ORDER = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
_COMMON_PROMPT = {"path": "mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json", "bytes": 526, "sha256": "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b", "transport": "native_stdin_exact_once"}
_TOOL = {"version": "tool-policy-v7", "clean_review_sha256": "10a073d131cee84e9e7d439b9e19b015c323d68d991919ad5ff6e3daf980e150", "bytedcli_allowed": False}
_WINDOW = {"not_before": "2026-11-11T00:00:00Z", "deadline": "2026-11-12T00:00:00Z", "block_seconds": 1800}
_LIMITS = {"concurrency": 1, "requests": 1, "retries": 0, "replays": 0, "status_queries": 0}
_CELLS = {
    "R6DQ-7F2C91A4": {"order": 0, "provider": "CLAUDE", "addon": "CONDITION-X", "addon_state": "OFF", "model": "claude-opus-5-5", "effort": "low", "provider_identity": {"boundary": "claude-v8", "provider": "claude_host", "transport": "claude_ferry", "binary_sha256": "abc9feeeca8091d51b623291e044cf0528c2f6b74e0c1d6ef671d52c73f7cd3c"}, "offset": 450},
    "R6DQ-1B8E43D7": {"order": 1, "provider": "CODEX", "addon": "CONDITION-Y", "addon_state": "ON", "model": "gpt-6.1-sol", "effort": "low", "provider_identity": {"boundary": "codex-v6", "provider": "codex_cli", "adapter": "CodexAttemptAdapterV9", "schema": "stage-b-execution-v3", "publication_driver": "AtomicPublisher.publish", "binary_sha256": "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc"}, "offset": 900},
    "R6DQ-C4A7095E": {"order": 2, "provider": "CLAUDE", "addon": "CONDITION-Y", "addon_state": "ON", "model": "claude-opus-5-5", "effort": "low", "provider_identity": {"boundary": "claude-v8", "provider": "claude_host", "transport": "claude_ferry", "binary_sha256": "abc9feeeca8091d51b623291e044cf0528c2f6b74e0c1d6ef671d52c73f7cd3c"}, "offset": 1350},
    "R6DQ-92D6F0B3": {"order": 3, "provider": "CODEX", "addon": "CONDITION-X", "addon_state": "OFF", "model": "gpt-6.1-sol", "effort": "low", "provider_identity": {"boundary": "codex-v6", "provider": "codex_cli", "adapter": "CodexAttemptAdapterV9", "schema": "stage-b-execution-v3", "publication_driver": "AtomicPublisher.publish", "binary_sha256": "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc"}, "offset": 1800},
}


def _closed(value: Any, fields: set[str], code: str) -> Mapping[str, Any]:
    _require(type(value) is dict and set(value) == fields, code)
    return value


def validate_cell_draft(value: Any) -> Mapping[str, Any]:
    value = _closed(value, {"artifact_kind", "status", "activation", "authority_effect", "self_minted", "cell_id", "order_index", "provider", "addon", "model", "budget", "window", "prompt", "tool_policy", "p0", "limits", "countable"}, "CELL_DRAFT_SHAPE")
    _require(value["artifact_kind"] == "NON_AUTHORIZING_CELL_GRANT_DRAFT" and value["status"] == STATUS, "CELL_DRAFT_STATUS")
    _require(value["activation"] is False and value["authority_effect"] == "NONE" and value["self_minted"] is False and value["countable"] is False, "CELL_DRAFT_MUST_NOT_AUTHORIZE")
    cell_id = value["cell_id"]
    _require(cell_id in _CELLS, "CELL_ID")
    expected = _CELLS[cell_id]
    _require(value["order_index"] == expected["order"], "CELL_ORDER_DRIFT")
    _require(value["provider"] == {"port": expected["provider"], **expected["provider_identity"]}, "CELL_PROVIDER_DRIFT")
    _require(value["addon"] == {"label": expected["addon"], "state": expected["addon_state"]}, "CELL_ADDON_DRIFT")
    _require(value["model"] == {"id": expected["model"], "effort": expected["effort"]}, "CELL_MODEL_DRIFT")
    _require(value["budget"] == {"currency": "USD", "hard_cap": "0.01"}, "CELL_BUDGET_DRIFT")
    _require(value["window"] == {**_WINDOW, "admission_offset_seconds": expected["offset"]}, "CELL_WINDOW_DRIFT")
    _require(value["prompt"] == _COMMON_PROMPT, "CELL_PROMPT_DRIFT")
    _require(value["tool_policy"] == _TOOL, "CELL_TOOL_POLICY_DRIFT")
    _require(value["p0"] == {"version": "P0-v10", "clean_pin_required": True}, "CELL_P0_DRIFT")
    _require(value["limits"] == _LIMITS, "CELL_LIMIT_DRIFT")
    return value


def validate_block_draft(value: Any) -> Mapping[str, Any]:
    value = _closed(value, {"artifact_kind", "status", "activation", "authority_effect", "self_minted", "block_id", "cell_order", "cells", "limits", "countability", "partial_block", "bytedcli_allowed"}, "BLOCK_DRAFT_SHAPE")
    _require(value["artifact_kind"] == "NON_AUTHORIZING_BLOCK_GRANT_DRAFT" and value["status"] == STATUS, "BLOCK_DRAFT_STATUS")
    _require(value["activation"] is False and value["authority_effect"] == "NONE" and value["self_minted"] is False, "BLOCK_DRAFT_MUST_NOT_AUTHORIZE")
    _require(value["block_id"] == "R6-DQ-FINAL-FOUR-CELL-BLOCK-V1", "BLOCK_ID")
    _require(tuple(value["cell_order"]) == _ORDER, "BLOCK_ORDER_DRIFT")
    _require(type(value["cells"]) is list and len(value["cells"]) == 4, "PARTIAL_BLOCK_FORBIDDEN")
    for expected_id, cell in zip(_ORDER, value["cells"]):
        validate_cell_draft(cell)
        _require(cell["cell_id"] == expected_id, "BLOCK_CELL_SWAP")
    _require(value["limits"] == {"concurrency": 1, "requests_per_cell": 1, "total_requests": 4, "retries": 0, "replays": 0, "status_queries": 0}, "BLOCK_LIMIT_DRIFT")
    _require(value["countability"] == "ALL_FOUR_OR_NONE" and value["partial_block"] is False, "BLOCK_COUNTABILITY")
    _require(value["bytedcli_allowed"] is False, "BYTEDCLI_FORBIDDEN")
    return value


__all__ = ["validate_block_draft", "validate_cell_draft"]
