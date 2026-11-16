"""Artifact-only durable UNKNOWN persistence and reconstruction."""
from pathlib import Path
from typing import Any,Dict,Mapping
from .contracts import ContractError,atomic_bytes,canonical_bytes,scan_forbidden,strict_json_bytes
def persist_unknown(path:Path,evidence:Mapping[str,Any])->Dict[str,Any]:
    if evidence.get("terminal_outcome")!="UNKNOWN":raise ContractError("R6_UNKNOWN_REQUIRED")
    scan_forbidden(evidence);data=canonical_bytes(dict(evidence));atomic_bytes(path,data)
    return {"atomic":True,"bytes":len(data),"dispatch_count":0,"provider_status_calls":0,"retry":False,"replay":False,"original_evidence_mutated":False}
def reconstruct_unknown(path:Path)->Dict[str,Any]:
    value=strict_json_bytes(path.read_bytes())
    if value.get("terminal_outcome")!="UNKNOWN" or value.get("retry") is not False or value.get("replay") is not False:raise ContractError("R6_UNKNOWN_INVALID")
    return value
