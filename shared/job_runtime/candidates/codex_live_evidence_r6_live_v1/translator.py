"""Closed raw-to-sanitized translator with recursive secret-value rejection."""
from typing import Any,Dict,Mapping
from .contracts import ContractError,exact_keys,scan_forbidden,sha256_bytes
def translate(raw:Mapping[str,Any])->Dict[str,Any]:
    exact_keys(raw,("terminal","stdout","stderr","request_bytes"),"R6_TRANSLATOR_INPUT_CLOSED")
    if raw["terminal"] not in ("PASS","UNKNOWN") or type(raw["stdout"]) is not bytes or type(raw["stderr"]) is not bytes or type(raw["request_bytes"]) is not int:raise ContractError("R6_TRANSLATOR_INPUT_INVALID")
    scan_forbidden(raw)
    out={"terminal":raw["terminal"],"stdout_sha256":sha256_bytes(raw["stdout"]),"stdout_bytes":len(raw["stdout"]),"stderr_sha256":sha256_bytes(raw["stderr"]),"stderr_bytes":len(raw["stderr"]),"parser_sha256":"0"*64};scan_forbidden(out,public=True);return out
