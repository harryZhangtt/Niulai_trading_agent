"""Copy-on-write, recoverable authority model for a future separate process."""
from dataclasses import dataclass
from enum import Enum
import copy, hashlib, hmac, secrets, threading
from .canonical import dumps
from .contracts import DESIGN_SHA256, binding as valid_binding, binding_digest, closed, request_envelope, signed_state_payload, state_body
from .errors import AuthorityError, CrashSimulated, PreSendFailure, ProtocolError, UnknownOutcome
from .framing import FrameDecoder, encode_frame
from .journal import SanitizedJournal

class CrashPoint(Enum): NONE="none"; BEFORE_COMMIT="before_commit"; AFTER_COMMIT="after_commit"
class ManualClock:
    def __init__(self,value=1000): self.value=value
    def now(self): return self.value
    def advance(self,seconds): self.value+=seconds
@dataclass(frozen=True)
class CleanupResult:
    generation_revoked: bool
    key_zeroization: str
    runtime_capability_zeroization: str
    registrar_capability_zeroization: str
    socket_cleanup: str="UNOBSERVED_MODEL_ONLY"
    journal_fsync: str="UNOBSERVED_MODEL_ONLY"
    process_termination: str="UNOBSERVED_MODEL_ONLY"

class Authority:
    def __init__(self,owner_uid,capability,registrar_capability=None,generation=1,key=None,clock=None):
        if type(owner_uid) is not int or owner_uid<0: raise ProtocolError("OWNER_UID_INVALID")
        if type(capability) is not bytes or len(capability)<32: raise ProtocolError("CAPABILITY_INVALID")
        if registrar_capability is None: registrar_capability=secrets.token_bytes(32)
        if type(registrar_capability) is not bytes or len(registrar_capability)<32 or hmac.compare_digest(capability,registrar_capability): raise ProtocolError("REGISTRAR_CAPABILITY_INVALID")
        if type(generation) is not int or generation<1: raise ProtocolError("GENERATION_INVALID")
        if key is None: key=secrets.token_bytes(32)
        if type(key) is not bytes or len(key)<32: raise ProtocolError("KEY_INVALID")
        self._owner_uid=owner_uid; self._runtime_capability=bytearray(capability); self._registrar_capability=bytearray(registrar_capability); self._key=bytearray(key)
        self._generation=generation; self._clock=clock or ManualClock(); self._lock=threading.RLock(); self._crashed=False; self._last_wall=0
        self._state={"authorized":{},"bindings":{},"consumed_proofs":{},"consumed_states":{},"proofs":{},"revoked":False,"sessions":{},"states":{}}
        self._journal=SanitizedJournal(self._sign)
    def _sign(self,payload): return hmac.new(bytes(self._key),dumps(payload),hashlib.sha256).hexdigest()
    def _artifact(self,kind,payload):
        env={"design_sha256":DESIGN_SHA256,"generation":self._generation,"kind":kind,"payload":copy.deepcopy(payload)}
        return {"envelope":env,"signature":self._sign(env)}
    def _verify(self,signed,kind):
        closed(signed,("envelope","signature"),"SIGNED_SHAPE"); env=signed["envelope"]
        closed(env,("design_sha256","generation","kind","payload"),"SIGNED_ENVELOPE_SHAPE")
        if env["design_sha256"]!=DESIGN_SHA256: raise AuthorityError("DESIGN_MISMATCH")
        if env["generation"]!=self._generation or env["kind"]!=kind: raise AuthorityError("SIGNED_BINDING_MISMATCH")
        if type(signed["signature"]) is not str or not hmac.compare_digest(signed["signature"],self._sign(env)): raise AuthorityError("SIGNATURE_INVALID")
        return copy.deepcopy(env["payload"])
    def _available(self):
        if self._crashed: raise UnknownOutcome("AUTHORITY_CRASHED_UNKNOWN")
        if self._state["revoked"]: raise AuthorityError("GENERATION_REVOKED")
    def _time(self):
        now=self._clock.now()
        if type(now) is not int: raise AuthorityError("CLOCK_INVALID")
        now=max(now,self._last_wall); self._last_wall=now; return now
    def _handle(self,kind,payload): return kind+":"+hashlib.sha256(dumps({"design_sha256":DESIGN_SHA256,"generation":self._generation,"payload":payload})).hexdigest()
    def _transaction(self,event,session_id,sequence,mutator,crash=CrashPoint.NONE):
        old=copy.deepcopy(self._state); new=copy.deepcopy(old)
        result=mutator(new)
        if crash is CrashPoint.BEFORE_COMMIT:
            self._state=old; self._crashed=True; raise CrashSimulated("CRASH_BEFORE_COMMIT_UNKNOWN")
        self._state=new
        try: self._journal.append_commit(event,self._generation,session_id,sequence,self._time(),new)
        except Exception:
            self._state=old; raise
        if crash is CrashPoint.AFTER_COMMIT:
            self._crashed=True; raise CrashSimulated("CRASH_AFTER_COMMIT_UNKNOWN")
        return result
    def _op(self,op,body,state,session_id,request_sequence):
        if op=="register_expected_binding":
            value=valid_binding(body); digest=binding_digest(value); handle=self._handle("binding",{"digest":digest})
            if handle in state["bindings"]: raise AuthorityError("BINDING_DUPLICATE")
            state["bindings"][handle]={"digest":digest,"identity":value}; return {"authority_id":"authority-process-v1","binding_handle":handle,"binding_digest":digest,"generation":self._generation}
        if op=="observe_pre_forward_502":
            closed(body,("binding_handle","request_ordinal","status","upstream_attempts","upstream_count_delta","submission","retry_after_seconds"),"OBSERVATION_SHAPE")
            binding=state["bindings"].get(body["binding_handle"])
            if binding is None: raise AuthorityError("BINDING_UNKNOWN")
            if type(body["request_ordinal"]) is not int or body["request_ordinal"]<1: raise ProtocolError("ORDINAL_INVALID")
            if type(body["status"]) is not int or type(body["upstream_attempts"]) is not int or type(body["upstream_count_delta"]) is not int or body["status"]!=502 or body["upstream_attempts"]!=0 or body["upstream_count_delta"]!=0 or body["submission"]!="not_submitted": raise AuthorityError("NOT_PREFORWARD_502")
            if type(body["retry_after_seconds"]) is not int or body["retry_after_seconds"]<1: raise ProtocolError("RETRY_AFTER_INVALID")
            payload={"binding_digest":binding["digest"],"binding_handle":body["binding_handle"],"design_sha256":DESIGN_SHA256,"observed_at":self._time(),"request_ordinal":body["request_ordinal"],"request_sequence":request_sequence,"retry_after_seconds":body["retry_after_seconds"],"session_id":session_id,"status":502,"submission":"not_submitted","upstream_attempts":0,"upstream_count_delta":0}
            handle=self._handle("proof",payload); signed=self._artifact("preforward502",payload); state["proofs"][handle]=signed
            return {"proof_handle":handle,"signed_proof":signed}
        if op=="seal_initial_state":
            closed(body,("state",),"SEAL_INITIAL_SHAPE"); st=state_body(body["state"])
            if st["phase"]!="READY" or st["retry_count"]!=0: raise AuthorityError("INITIAL_STATE_PHASE_INVALID")
            self._validate_state_binding(st,state)
            payload=signed_state_payload({"body":st})
            handle=self._handle("state",payload); signed=self._artifact("campaign_state",payload); state["states"][handle]=signed
            return {"state_handle":handle,"signed_state":signed}
        if op=="verify_state":
            closed(body,("state_handle","signed_state","exact_state"),"VERIFY_STATE_SHAPE"); payload=signed_state_payload(body["exact_state"])
            actual=self._verify(body["signed_state"],"campaign_state")
            if actual!=payload or state["states"].get(body["state_handle"])!=body["signed_state"] or self._handle("state",actual)!=body["state_handle"]: raise AuthorityError("STATE_REPLACEMENT")
            return {"valid":True}
        if op=="verify_and_consume_proof":
            closed(body,("proof_handle","signed_proof","exact_expected_bindings"),"VERIFY_PROOF_SHAPE"); proof=self._proof(body,state)
            expected=valid_binding(body["exact_expected_bindings"])
            if proof["binding_digest"]!=binding_digest(expected) or state["bindings"].get(proof["binding_handle"],{}).get("identity")!=expected: raise AuthorityError("PROOF_CROSS_BINDING")
            if body["proof_handle"] in state["consumed_proofs"]: raise AuthorityError("PROOF_ALREADY_CONSUMED")
            state["consumed_proofs"][body["proof_handle"]]=True
            return {"retry_after_seconds":proof["retry_after_seconds"],"verified_observed_at":proof["observed_at"]}
        if op=="transition_retry":
            closed(body,("state_handle","signed_state","proof_handle","signed_proof","exact_expected_bindings","next_state_template"),"TRANSITION_SHAPE")
            if body["state_handle"] in state["consumed_states"] or body["proof_handle"] in state["consumed_proofs"]: raise AuthorityError("TRANSITION_ALREADY_CONSUMED")
            current=self._verify(body["signed_state"],"campaign_state"); current=signed_state_payload(current)
            if state["states"].get(body["state_handle"])!=body["signed_state"]: raise AuthorityError("STATE_REPLACEMENT")
            proof=self._proof(body,state); expected=valid_binding(body["exact_expected_bindings"]); template=state_body(body["next_state_template"])
            digest=binding_digest(expected); self._validate_state_binding(current["body"],state); self._validate_state_binding(template,state)
            if not (current["body"]["binding_handle"]==proof["binding_handle"]==template["binding_handle"] and current["body"]["binding_digest"]==proof["binding_digest"]==template["binding_digest"]==digest): raise AuthorityError("TRANSITION_BINDING_MISMATCH")
            for name in ("run","campaign","job","slot"):
                if template[name]!=current["body"][name]: raise AuthorityError("TRANSITION_IDENTITY_MISMATCH")
            if template["phase"]!="RETRY_WAIT" or template["retry_count"]!=current["body"]["retry_count"]+1: raise AuthorityError("TRANSITION_ILLEGAL")
            next_at=max(self._time(),proof["observed_at"])+proof["retry_after_seconds"]
            payload=signed_state_payload({"body":template,"predecessor_state_handle":body["state_handle"],"consumed_proof_handle":body["proof_handle"],"binding_digest":digest,"next_retry_at":next_at})
            handle=self._handle("state",payload); signed=self._artifact("campaign_state",payload)
            state["consumed_states"][body["state_handle"]]=True; state["consumed_proofs"][body["proof_handle"]]=True; state["states"][handle]=signed
            return {"consumed_predecessor":body["state_handle"],"consumed_proof":body["proof_handle"],"derived_next_retry_at":next_at,"signed_successor":signed,"state_handle":handle}
        if op=="authorize_retry":
            closed(body,("state_handle","signed_state","exact_state"),"AUTHORIZE_SHAPE")
            if body["state_handle"] in state["authorized"]: raise AuthorityError("RETRY_ALREADY_AUTHORIZED")
            payload=signed_state_payload(body["exact_state"]); actual=signed_state_payload(self._verify(body["signed_state"],"campaign_state"))
            if payload!=actual or state["states"].get(body["state_handle"])!=body["signed_state"]: raise AuthorityError("STATE_REPLACEMENT")
            if payload["body"]["phase"]!="RETRY_WAIT" or state["consumed_states"].get(payload["predecessor_state_handle"]) is not True or state["consumed_proofs"].get(payload["consumed_proof_handle"]) is not True or payload["binding_digest"]!=payload["body"]["binding_digest"]: raise AuthorityError("RETRY_PROVENANCE_INVALID")
            self._validate_state_binding(payload["body"],state)
            if self._time()<payload["next_retry_at"]: raise AuthorityError("RETRY_COOLDOWN_ACTIVE")
            state["authorized"][body["state_handle"]]=True; auth=self._artifact("retry_authorization",{"design_sha256":DESIGN_SHA256,"state_handle":body["state_handle"],"authorized_at":self._time()})
            return {"authorization_handle":self._handle("authorization",auth["envelope"]["payload"]),"signed_authorization":auth}
        if op=="revoke_generation":
            closed(body,("generation",),"REVOKE_SHAPE")
            if type(body["generation"]) is not int or body["generation"]!=self._generation: raise AuthorityError("GENERATION_MISMATCH")
            state["revoked"]=True
            return {"generation":self._generation,"revoked":True}
        raise ProtocolError("OP_UNKNOWN")
    def _validate_state_binding(self,body,state):
        binding=state["bindings"].get(body["binding_handle"])
        if binding is None or binding["digest"]!=body["binding_digest"]: raise AuthorityError("STATE_BINDING_MISMATCH")
        identity=binding["identity"]
        for name in ("run","campaign","job","slot","attempt"):
            if body[name]!=identity[name]: raise AuthorityError("STATE_BINDING_IDENTITY_MISMATCH")

    def _proof(self,body,state):
        proof=self._verify(body["signed_proof"],"preforward502")
        if proof.get("design_sha256")!=DESIGN_SHA256 or state["proofs"].get(body["proof_handle"])!=body["signed_proof"] or self._handle("proof",proof)!=body["proof_handle"]: raise AuthorityError("PROOF_REPLACEMENT")
        return proof
    def dispatch(self,request,peer_uid,capability,crash=CrashPoint.NONE):
        with self._lock:
            request_envelope(request); self._available()
            if peer_uid!=self._owner_uid: raise AuthorityError("PEER_UID_MISMATCH")
            expected=bytes(self._registrar_capability if request["role"]=="registrar" else self._runtime_capability)
            if type(capability) is not bytes or not hmac.compare_digest(capability,expected): raise AuthorityError("CAPABILITY_MISMATCH")
            if request["generation"]!=self._generation: raise AuthorityError("GENERATION_MISMATCH")
            registrar_op=request["op"] in ("register_expected_binding","revoke_generation")
            if registrar_op != (request["role"]=="registrar"): raise AuthorityError("ROLE_OPERATION_FORBIDDEN")
            outcome={}
            def mutate(state):
                session=state["sessions"].get(request["session_id"])
                identity={"design_sha256":DESIGN_SHA256,"generation":self._generation,"peer_uid":peer_uid,"role":request["role"]}
                if session is None:
                    if request["sequence"]!=1: raise AuthorityError("SESSION_SEQUENCE_MISMATCH")
                    state["sessions"][request["session_id"]]=dict(identity,next_sequence=2)
                else:
                    if any(session[k]!=v for k,v in identity.items()): raise AuthorityError("SESSION_IDENTITY_MISMATCH")
                    if request["sequence"]!=session["next_sequence"]: raise AuthorityError("SESSION_SEQUENCE_MISMATCH")
                    session["next_sequence"]+=1
                try: outcome["result"]=self._op(request["op"],request["body"],state,request["session_id"],request["sequence"])
                except (AuthorityError,ProtocolError) as exc: outcome["error"]=exc
                return outcome.get("result")
            result=self._transaction(request["op"]+"_processed",request["session_id"],request["sequence"],mutate,crash)
            if "error" in outcome: raise outcome["error"]
            return result
    def signed_error(self,request,code,session_terminal):
        safe=request if type(request) is dict else {}
        payload={"code":code,"design_sha256":DESIGN_SHA256,"generation":self._generation,"op":safe.get("op","invalid"),"sequence":safe.get("sequence",0),"session_id":safe.get("session_id","invalid"),"session_terminal":session_terminal}
        return self._artifact("protocol_error",payload)
    def revoke_and_cleanup(self):
        with self._lock:
            if not self._state["revoked"]:
                self._available()
                self._transaction("generation_revoked","cleanup",0,lambda state: state.__setitem__("revoked",True))
            for buf in (self._key,self._runtime_capability,self._registrar_capability):
                for i in range(len(buf)): buf[i]=0
            return CleanupResult(True,"BEST_EFFORT_ZEROED","BEST_EFFORT_ZEROED","BEST_EFFORT_ZEROED")
    def journal_snapshot(self): return self._journal.snapshot()
    @classmethod
    def from_journal(cls,entries,owner_uid,capability,registrar_capability,generation,key,clock=None):
        recovered=SanitizedJournal.verify(entries,key,generation)
        obj=cls(owner_uid,capability,registrar_capability,generation,key,clock); obj._journal._entries=list(copy.deepcopy(entries))
        if recovered is not None: obj._state=recovered
        if entries: obj._last_wall=entries[-1]["timestamp"]
        return obj

class AuthorityClient:
    _RESULT_FIELDS={"register_expected_binding":("authority_id","binding_handle","binding_digest","generation"),"observe_pre_forward_502":("proof_handle","signed_proof"),"verify_and_consume_proof":("retry_after_seconds","verified_observed_at"),"seal_initial_state":("state_handle","signed_state"),"verify_state":("valid",),"transition_retry":("consumed_predecessor","consumed_proof","derived_next_retry_at","signed_successor","state_handle"),"authorize_retry":("authorization_handle","signed_authorization"),"revoke_generation":("generation","revoked")}
    def __init__(self,exchange,capability,session_id,role="runtime",generation=1):
        if type(generation) is not int or generation<1: raise ProtocolError("CLIENT_GENERATION_INVALID")
        self._exchange=exchange; self._capability=bytearray(capability); self._session_id=session_id; self._role=role; self._generation=generation; self._sequence=0; self._closed=False
    @staticmethod
    def _integer(value,minimum,code):
        if type(value) is not int or value<minimum: raise ProtocolError(code)
    @staticmethod
    def _sha(value,code):
        if type(value) is not str or len(value)!=64 or any(c not in "0123456789abcdef" for c in value): raise ProtocolError(code)
    @staticmethod
    def _handle_value(value,prefix,code):
        if type(value) is not str or not value.startswith(prefix+":") or len(value)!=len(prefix)+65: raise ProtocolError(code)
        AuthorityClient._sha(value[len(prefix)+1:],code)
    def _artifact(self,signed,kind):
        closed(signed,("envelope","signature"),"RESULT_SIGNED_SHAPE"); env=signed["envelope"]; closed(env,("design_sha256","generation","kind","payload"),"RESULT_SIGNED_ENVELOPE_SHAPE"); self._sha(signed["signature"],"RESULT_SIGNATURE_INVALID")
        if env["design_sha256"]!=DESIGN_SHA256 or env["generation"]!=self._generation or env["kind"]!=kind or type(env["payload"]) is not dict: raise ProtocolError("RESULT_SIGNED_BINDING_MISMATCH")
        return env["payload"]
    def _expected_handle(self,kind,payload): return kind+":"+hashlib.sha256(dumps({"design_sha256":DESIGN_SHA256,"generation":self._generation,"payload":payload})).hexdigest()
    def _proof_artifact(self,signed,handle,expected_request=None):
        payload=self._artifact(signed,"preforward502")
        fields=("binding_digest","binding_handle","design_sha256","observed_at","request_ordinal","request_sequence","retry_after_seconds","session_id","status","submission","upstream_attempts","upstream_count_delta")
        closed(payload,fields,"PROOF_PAYLOAD_SHAPE"); self._sha(payload["binding_digest"],"PROOF_DIGEST_INVALID"); self._handle_value(payload["binding_handle"],"binding","PROOF_BINDING_INVALID"); self._integer(payload["observed_at"],0,"PROOF_TIME_INVALID"); self._integer(payload["request_ordinal"],1,"PROOF_ORDINAL_INVALID"); self._integer(payload["request_sequence"],1,"PROOF_SEQUENCE_INVALID"); self._integer(payload["retry_after_seconds"],1,"PROOF_RETRY_INVALID")
        self._integer(payload["status"],0,"PROOF_STATUS_INVALID"); self._integer(payload["upstream_attempts"],0,"PROOF_UPSTREAM_INVALID"); self._integer(payload["upstream_count_delta"],0,"PROOF_DELTA_INVALID")
        if payload["design_sha256"]!=DESIGN_SHA256 or payload["status"]!=502 or payload["submission"]!="not_submitted" or payload["upstream_attempts"]!=0 or payload["upstream_count_delta"]!=0: raise ProtocolError("PROOF_FIXED_CLAIM_INVALID")
        self._handle_value(handle,"proof","PROOF_HANDLE_INVALID")
        if handle!=self._expected_handle("proof",payload): raise ProtocolError("PROOF_HANDLE_RELATION")
        if expected_request is not None:
            if payload["binding_handle"]!=expected_request["binding_handle"] or payload["request_ordinal"]!=expected_request["request_ordinal"] or payload["retry_after_seconds"]!=expected_request["retry_after_seconds"] or any(expected_request[k]!=payload[k] for k in ("status","submission","upstream_attempts","upstream_count_delta")): raise ProtocolError("PROOF_REQUEST_MISMATCH")
        return payload
    def _state_artifact(self,signed,handle,expected=None):
        payload=signed_state_payload(self._artifact(signed,"campaign_state")); self._handle_value(handle,"state","STATE_HANDLE_INVALID")
        if handle!=self._expected_handle("state",payload): raise ProtocolError("STATE_HANDLE_RELATION")
        if expected is not None and payload!=expected: raise ProtocolError("STATE_REQUEST_MISMATCH")
        return payload
    def _validate_result(self,op,result,request):
        fields=self._RESULT_FIELDS.get(op)
        if fields is None: raise ProtocolError("RESPONSE_OP_UNKNOWN")
        closed(result,fields,"RESULT_SHAPE")
        if op=="register_expected_binding":
            digest=binding_digest(request); expected=self._expected_handle("binding",{"digest":digest})
            self._integer(result["generation"],1,"RESULT_GENERATION_INVALID")
            if result["authority_id"]!="authority-process-v1" or result["binding_handle"]!=expected or result["binding_digest"]!=digest or result["generation"]!=self._generation: raise ProtocolError("RESULT_REGISTER_RELATION")
        elif op=="observe_pre_forward_502":
            proof=self._proof_artifact(result["signed_proof"],result["proof_handle"],request)
            if proof["session_id"]!=self._session_id or proof["request_sequence"]!=self._sequence: raise ProtocolError("PROOF_SESSION_MISMATCH")
        elif op=="verify_and_consume_proof":
            proof=self._proof_artifact(request["signed_proof"],request["proof_handle"]); digest=binding_digest(request["exact_expected_bindings"]); expected_handle=self._expected_handle("binding",{"digest":digest})
            if proof["binding_digest"]!=digest or proof["binding_handle"]!=expected_handle: raise ProtocolError("PROOF_EXPECTED_BINDING_MISMATCH")
            self._integer(result["verified_observed_at"],0,"RESULT_TIME_INVALID"); self._integer(result["retry_after_seconds"],1,"RESULT_RETRY_INVALID")
            if result["verified_observed_at"]!=proof["observed_at"] or result["retry_after_seconds"]!=proof["retry_after_seconds"]: raise ProtocolError("RESULT_PROOF_ECHO_MISMATCH")
        elif op=="seal_initial_state":
            self._state_artifact(result["signed_state"],result["state_handle"],{"body":state_body(request["state"])})
        elif op=="verify_state":
            self._state_artifact(request["signed_state"],request["state_handle"],signed_state_payload(request["exact_state"]))
            if result["valid"] is not True: raise ProtocolError("RESULT_VALID_INVALID")
        elif op=="transition_retry":
            current=self._state_artifact(request["signed_state"],request["state_handle"]); proof=self._proof_artifact(request["signed_proof"],request["proof_handle"]); digest=binding_digest(request["exact_expected_bindings"])
            successor=self._state_artifact(result["signed_successor"],result["state_handle"]); self._integer(result["derived_next_retry_at"],0,"RESULT_TIME_INVALID")
            expected_body=state_body(request["next_state_template"]); expected_handle=self._expected_handle("binding",{"digest":digest})
            if current["body"]["binding_digest"]!=digest or current["body"]["binding_handle"]!=expected_handle or proof["binding_digest"]!=digest or proof["binding_handle"]!=expected_handle or expected_body["binding_digest"]!=digest or expected_body["binding_handle"]!=expected_handle: raise ProtocolError("TRANSITION_EXPECTED_BINDING_MISMATCH")
            if result["consumed_predecessor"]!=request["state_handle"] or result["consumed_proof"]!=request["proof_handle"] or successor["body"]!=expected_body or successor["binding_digest"]!=digest or successor["predecessor_state_handle"]!=request["state_handle"] or successor["consumed_proof_handle"]!=request["proof_handle"] or successor["next_retry_at"]!=result["derived_next_retry_at"] or result["derived_next_retry_at"]<proof["observed_at"]+proof["retry_after_seconds"]: raise ProtocolError("RESULT_TRANSITION_RELATION")
        elif op=="authorize_retry":
            self._state_artifact(request["signed_state"],request["state_handle"],signed_state_payload(request["exact_state"])); payload=self._artifact(result["signed_authorization"],"retry_authorization"); closed(payload,("authorized_at","design_sha256","state_handle"),"AUTHORIZATION_PAYLOAD_SHAPE"); self._integer(payload["authorized_at"],0,"AUTHORIZATION_TIME_INVALID"); self._handle_value(result["authorization_handle"],"authorization","AUTHORIZATION_HANDLE_INVALID")
            expected_state=signed_state_payload(request["exact_state"])
            if payload["authorized_at"]<expected_state["next_retry_at"]: raise ProtocolError("AUTHORIZATION_BEFORE_COOLDOWN")
            if payload["design_sha256"]!=DESIGN_SHA256 or payload["state_handle"]!=request["state_handle"] or result["authorization_handle"]!=self._expected_handle("authorization",payload): raise ProtocolError("AUTHORIZATION_RELATION_MISMATCH")
        elif op=="revoke_generation":
            closed(request,("generation",),"REVOKE_REQUEST_SHAPE"); self._integer(request["generation"],1,"REVOKE_GENERATION_INVALID"); self._integer(result["generation"],1,"RESULT_GENERATION_INVALID")
            if request["generation"]!=self._generation or result["generation"]!=self._generation or result["revoked"] is not True: raise ProtocolError("REVOKE_RELATION_MISMATCH")
        return result
    def _process(self,response,op,body):
        closed(response,("design_sha256","generation","ok","op","sequence","session_id","session_terminal","result","signed_error"),"RESPONSE_SHAPE")
        self._integer(response["generation"],1,"RESPONSE_GENERATION_INVALID"); self._integer(response["sequence"],1,"RESPONSE_SEQUENCE_INVALID")
        if response["design_sha256"]!=DESIGN_SHA256 or response["generation"]!=self._generation or response["sequence"]!=self._sequence or response["session_id"]!=self._session_id or response["op"]!=op: raise ProtocolError("RESPONSE_BINDING_MISMATCH")
        if type(response["session_terminal"]) is not bool: raise ProtocolError("RESPONSE_TERMINAL_INVALID")
        if response["ok"] is False:
            if response["result"] is not None: raise ProtocolError("ERROR_RESULT_INVALID")
            signed=response["signed_error"]; payload=self._artifact(signed,"protocol_error"); closed(payload,("code","design_sha256","generation","op","sequence","session_id","session_terminal"),"ERROR_PAYLOAD_SHAPE")
            self._integer(payload["generation"],1,"ERROR_GENERATION_INVALID"); self._integer(payload["sequence"],1,"ERROR_SEQUENCE_INVALID")
            if type(payload["session_terminal"]) is not bool or type(payload["code"]) is not str or payload["design_sha256"]!=DESIGN_SHA256 or payload["generation"]!=self._generation or payload["op"]!=op or payload["sequence"]!=self._sequence or payload["session_id"]!=self._session_id or payload["session_terminal"] is not response["session_terminal"]: raise ProtocolError("ERROR_BINDING_MISMATCH")
            if response["session_terminal"]: self._closed=True
            raise AuthorityError(payload["code"])
        if response["ok"] is not True or response["signed_error"] is not None or response["session_terminal"]: raise ProtocolError("RESPONSE_INVALID")
        return self._validate_result(op,response["result"],body)
    def call(self,op,body):
        if self._closed: raise AuthorityError("CLIENT_SESSION_CLOSED")
        next_sequence=self._sequence+1; request={"body":body,"design_sha256":DESIGN_SHA256,"generation":self._generation,"op":op,"role":self._role,"sequence":next_sequence,"session_id":self._session_id}; frame=encode_frame(request)
        try: response=self._exchange(frame,bytes(self._capability))
        except PreSendFailure:
            raise
        except Exception:
            self._closed=True; raise UnknownOutcome("AUTHORITY_DISCONNECT_UNKNOWN")
        self._sequence=next_sequence
        try: return self._process(response,op,body)
        except AuthorityError as exc:
            if type(exc) is AuthorityError: raise
            self._closed=True; raise UnknownOutcome("AUTHORITY_DISCONNECT_UNKNOWN")
        except Exception:
            self._closed=True; raise UnknownOutcome("AUTHORITY_DISCONNECT_UNKNOWN")
    def close(self):
        self._closed=True
        for i in range(len(self._capability)): self._capability[i]=0

class MemoryServerSession:
    def __init__(self,authority,endpoint): self._authority=authority; self._endpoint=endpoint; self._terminal=set()
    def exchange(self,frame,capability,chunk_size=7):
        self._endpoint._peer.send(frame,chunk_size); decoder=FrameDecoder(); requests=decoder.feed(self._endpoint.receive()); decoder.finish()
        if len(requests)!=1: raise ProtocolError("REQUEST_FRAME_COUNT")
        request=requests[0]; safe=request if type(request) is dict else {}; sid=safe.get("session_id","invalid"); op=safe.get("op","invalid"); seq=safe.get("sequence",0)
        try:
            if sid in self._terminal: raise AuthorityError("SESSION_TERMINAL")
            result=self._authority.dispatch(request,self._endpoint.peer_uid,capability)
            response={"design_sha256":DESIGN_SHA256,"generation":self._authority._generation,"ok":True,"op":op,"result":result,"sequence":seq,"session_id":sid,"session_terminal":False,"signed_error":None}
        except (AuthorityError,ProtocolError) as exc:
            session=self._authority._state["sessions"].get(sid); committed=session is not None and session.get("next_sequence")==seq+1
            terminal=not committed
            if terminal: self._terminal.add(sid)
            signed=self._authority.signed_error(request,exc.code,terminal)
            response={"design_sha256":DESIGN_SHA256,"generation":self._authority._generation,"ok":False,"op":op,"result":None,"sequence":seq,"session_id":sid,"session_terminal":terminal,"signed_error":signed}
        raw=encode_frame(response); out=[]; d=FrameDecoder()
        for i in range(0,len(raw),5): out.extend(d.feed(raw[i:i+5]))
        d.finish(); return out[0]
