"""Strict translator from injected synthetic observations to sanitized receipts."""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Mapping
from .adapter import validate_synthetic_observation
from .contracts import R6ContractError, canonical_bytes, scan_public, sha256_bytes, validate_identity

PARSER_PATH = "shared/job_runtime/candidates/codex_live_evidence_r6_v1/translator.py"
GRAMMAR = "r6-synthetic-terminal-1"

def parser_binding() -> Dict[str, Any]:
    data = Path(__file__).read_bytes()
    return {"path": PARSER_PATH, "bytes": len(data), "sha256": sha256_bytes(data)}

def translate(capture: Mapping[str, Any]) -> Dict[str, Any]:
    if type(capture) is not dict or set(capture) != {"identity","scenario","observation","synthetic"} or capture["synthetic"] is not True:
        raise R6ContractError("R6_CAPTURE_INVALID")
    identity = validate_identity(capture["identity"])
    observation = capture["observation"]
    if type(observation) is not dict: raise R6ContractError("R6_MALFORMED_TERMINAL")
    scenario = capture["scenario"]
    validate_synthetic_observation(scenario, observation)
    if scenario == "missing_terminal" or "terminal_status" not in observation: raise R6ContractError("R6_MISSING_TERMINAL")
    if set(observation) != {"terminal_status","process_exit","output"} or type(observation["terminal_status"]) is not str or type(observation["process_exit"]) is not int or type(observation["output"]) is not str:
        raise R6ContractError("R6_MALFORMED_TERMINAL")
    if scenario == "nominal" and observation["terminal_status"] != "completed": raise R6ContractError("R6_MALFORMED_TERMINAL")
    raw = canonical_bytes(observation)
    sanitized = {"terminal_status":observation["terminal_status"], "process_exit":observation["process_exit"], "output_bytes":len(observation["output"].encode("utf-8")), "output_sha256":sha256_bytes(observation["output"].encode("utf-8"))}
    scan_public(sanitized)
    parser = parser_binding()
    return {"schema_version":"translator-receipt-v1", "identity":dict(identity), "parser_path":PARSER_PATH,
            "parser_bytes":parser["bytes"], "parser_sha256":parser["sha256"], "grammar_version":GRAMMAR, "raw_hashes":[sha256_bytes(raw)],
            "sanitized_path":"synthetic://sanitized/terminal.json", "sanitized_bytes":len(canonical_bytes(sanitized)),
            "sanitized_sha256":sha256_bytes(canonical_bytes(sanitized)), "sanitized_terminal":sanitized,
            "countable_observation":False}
