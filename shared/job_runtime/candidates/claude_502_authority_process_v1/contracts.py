"""Closed protocol contracts bound to the frozen design digest."""
import re
from .canonical import dumps
from .errors import ProtocolError
import hashlib

DESIGN_SHA256 = "74599835c69be8598cb4a4b9d5a3a7fee1d19e43195405bda608fe5befbb13a3"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
BINDING_FIELDS = ("run","campaign","job","slot","attempt","operation","request","prompt","gateway","process","source","config","evidence")
STATE_FIELDS = ("version","run","campaign","job","slot","attempt","phase","retry_count","binding_handle","binding_digest")
OPS = frozenset(("register_expected_binding","observe_pre_forward_502","verify_and_consume_proof","seal_initial_state","verify_state","transition_retry","authorize_retry","revoke_generation"))


def closed(value, fields, code):
    if type(value) is not dict or set(value) != set(fields): raise ProtocolError(code)

def identifier(value, code="ID_INVALID"):
    if type(value) is not str or _ID.fullmatch(value) is None: raise ProtocolError(code)
    return value

def sha(value, code="SHA_INVALID"):
    if type(value) is not str or _SHA.fullmatch(value) is None: raise ProtocolError(code)
    return value

def binding(value):
    closed(value,BINDING_FIELDS,"BINDING_SHAPE")
    out={}
    for name in BINDING_FIELDS:
        out[name]=sha(value[name],"BINDING_HASH_INVALID") if name in ("prompt","source","config","evidence") else identifier(value[name],"BINDING_ID_INVALID")
    return out

def binding_digest(value): return hashlib.sha256(dumps(binding(value))).hexdigest()

def state_body(value):
    closed(value,STATE_FIELDS,"STATE_SHAPE")
    if type(value["version"]) is not int or value["version"] != 1: raise ProtocolError("STATE_VERSION_INVALID")
    if type(value["retry_count"]) is not int or value["retry_count"] < 0: raise ProtocolError("STATE_RETRY_INVALID")
    if value["phase"] not in ("READY","RETRY_WAIT","AUTHORIZED","UNKNOWN","REVOKED"): raise ProtocolError("STATE_PHASE_INVALID")
    for name in ("run","campaign","job","slot","attempt"): identifier(value[name],"STATE_ID_INVALID")
    identifier(value["binding_handle"],"STATE_BINDING_HANDLE_INVALID"); sha(value["binding_digest"],"STATE_BINDING_DIGEST_INVALID")
    return dict(value)

def signed_state_payload(value):
    if type(value) is not dict or "body" not in value: raise ProtocolError("SIGNED_STATE_PAYLOAD_SHAPE")
    body=state_body(value["body"])
    if body["phase"]=="READY":
        closed(value,("body",),"INITIAL_STATE_PAYLOAD_SHAPE")
    elif body["phase"]=="RETRY_WAIT":
        closed(value,("body","predecessor_state_handle","consumed_proof_handle","binding_digest","next_retry_at"),"RETRY_STATE_PAYLOAD_SHAPE")
        identifier(value["predecessor_state_handle"],"STATE_PREDECESSOR_INVALID")
        identifier(value["consumed_proof_handle"],"STATE_PROOF_INVALID")
        sha(value["binding_digest"],"STATE_BINDING_DIGEST_INVALID")
        if type(value["next_retry_at"]) is not int or value["next_retry_at"]<0: raise ProtocolError("STATE_TIMING_INVALID")
    else: raise ProtocolError("SIGNED_STATE_PHASE_FORBIDDEN")
    return dict(value)

def request_envelope(value):
    closed(value,("design_sha256","generation","session_id","role","sequence","op","body"),"REQUEST_SHAPE")
    if value["design_sha256"] != DESIGN_SHA256: raise ProtocolError("DESIGN_MISMATCH")
    if type(value["generation"]) is not int or value["generation"] < 1: raise ProtocolError("GENERATION_INVALID")
    identifier(value["session_id"],"SESSION_ID_INVALID")
    if value["role"] not in ("runtime","registrar"): raise ProtocolError("ROLE_INVALID")
    if type(value["sequence"]) is not int or value["sequence"] < 1: raise ProtocolError("SEQUENCE_INVALID")
    if value["op"] not in OPS: raise ProtocolError("OP_UNKNOWN")
    if type(value["body"]) is not dict: raise ProtocolError("BODY_TYPE")
    return value
