"""Provider-free injected two-cell runner; no provider, network, tools, or publication."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Dict, Mapping
from .bundle import BundleError, RawDecisionStore
from .contracts import (CELL_ORDER, DISPOSITIONS, DQ_CHECKS, FROZEN_INPUTS, LIMITS, MODEL_ID,
                        canonical_bytes, sha256_bytes, sha256_json, validate_bundle, validate_result)

OutcomeFactory = Callable[[Mapping[str, Any]], Mapping[str, Any]]

def default_run(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    return {"status": "DENIED_NO_INJECTED_PROVIDER_FREE_OUTCOME", "countable": False,
            "effects": {"provider": 0, "network": 0, "publication": 0, "tools": 0, "web": 0, "subagents": 0}}

def _checks(enabled: bool, supplied: Any) -> list:
    if not enabled:
        return [{"name": n, "status": "NOT_RUN_TREATMENT_DISABLED", "code": "NOT_RUN_TREATMENT_DISABLED"} for n in DQ_CHECKS]
    if type(supplied) is not list:
        return [{"name": n, "status": "UNKNOWN", "code": "CHECK_RESULT_MISSING"} for n in DQ_CHECKS]
    return [dict(item) for item in supplied]

def run_pair(outcome_factory: OutcomeFactory, bundle_root: Path, *, fault_cell: str = "") -> Dict[str, Any]:
    cells = []
    for index, cell_id in enumerate(CELL_ORDER):
        enabled = index == 1
        plan = {"version": 1, "cell_id": cell_id, "order_index": index, "model": MODEL_ID,
                "dq_enabled": enabled, "inputs": deepcopy(FROZEN_INPUTS), "limits": deepcopy(LIMITS)}
        plan_sha = sha256_json(plan); outcome = dict(outcome_factory(deepcopy(plan)))
        terminal = outcome.get("terminal_state", "MISSING"); raw = outcome.get("raw", b"")
        if type(raw) is not bytes: raw = b""
        checks = _checks(enabled, outcome.get("dq_checks")); attempt_count = outcome.get("attempt_count", 0 if terminal == "STOP" else 1)
        errors = []
        echo_sha = sha256_json(outcome.get("plan_echo", {}))
        if echo_sha != plan_sha: errors.append("PLAN_ECHO_DRIFT")
        if terminal == "STOP" and attempt_count != 0: errors.append("STOP_NOT_ZERO_ATTEMPT")
        elif terminal != "STOP" and attempt_count != 1: errors.append("ATTEMPT_COUNT_INVALID")
        if enabled and any(c.get("status") != "PASS" for c in checks): errors.append("DQ_NOT_ALL_PASS")
        raw_ref = {"name": "model-terminal.raw", "sha256": sha256_bytes(raw), "bytes": len(raw), "owner_private": True, "public": False}
        cell = {"version": 1, "plan": plan, "plan_sha256": plan_sha, "plan_echo_sha256": echo_sha,
                "attempt_id": outcome.get("attempt_id", "attempt-" + cell_id), "terminal_state": terminal,
                "attempt_count": attempt_count, "retry_count": outcome.get("retry_count", 0),
                "replay_count": outcome.get("replay_count", 0), "status_query_count": outcome.get("status_query_count", 0),
                "tool_count": outcome.get("tool_count", 0), "web_count": outcome.get("web_count", 0),
                "subagent_count": outcome.get("subagent_count", 0), "fallback_count": outcome.get("fallback_count", 0),
                "raw_ref": raw_ref, "raw_committed_before_decision": True, "dq_checks": checks,
                "disposition": DISPOSITIONS.get(terminal, "RETAIN_MISSING_NO_PUBLICATION"), "denominator_included": True,
                "publication": {"status": "SUPPRESSED_PROVIDER_FREE", "attempts": 0, "unknown_fenced": terminal == "UNKNOWN"},
                "validity_errors": sorted(errors)}
        base = {"version": 1, "cell": deepcopy(cell), "raw_body_ascii": raw.decode("ascii"), "raw_sha256": raw_ref["sha256"]}
        base["decision_sha256"] = sha256_json(base); base["bundle_sha256"] = sha256_json(base); validate_bundle(base)
        store = RawDecisionStore(Path(bundle_root)/cell_id, "after_raw" if fault_cell == cell_id else None)
        receipt = store.commit(raw, base)
        cell["bundle_receipt"] = {"raw": receipt.raw_path.name, "bundle": receipt.bundle_path.name,
                                  "raw_sha256": receipt.raw_sha256, "bundle_file_sha256": receipt.bundle_sha256,
                                  "recovered": receipt.recovered}
        cell.pop("bundle_receipt")
        cells.append(cell)
    symmetry = [{k: v for k, v in c["plan"].items() if k not in ("cell_id", "order_index", "dq_enabled")} for c in cells]
    result = {"version": 1, "scope": "PROVIDER_FREE_FIXTURE", "model": MODEL_ID, "cell_order": list(CELL_ORDER),
              "cells": cells, "denominator_count": 2, "status": "FIXTURE_ONLY_PENDING_INDEPENDENT_REVIEW",
              "countable": False, "publication_attempts": 0, "symmetry_sha256": sha256_json(symmetry)}
    validate_result(result); return result

__all__ = ["default_run", "run_pair"]
