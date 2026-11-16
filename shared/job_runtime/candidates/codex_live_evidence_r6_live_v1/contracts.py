"""Strict provider-free contracts, held-file custody, and durable synthetic authority."""
from __future__ import annotations
import hashlib,json,math,os,re,stat
from datetime import datetime,timezone
from pathlib import Path
from typing import Any,Dict,Iterable,Mapping,Optional,Tuple
PACKAGE="codex_live_evidence_r6_live_v1"
DESIGN_SHA256="e025e5c9c1437577cade2613cd478990d87828c967dce31b36d532c672dde4f4"
REVIEW_SHA256="a36b5a49b5a0ed26df5524b127f4b6f930f401b8a192cf82127361564ac28f20"
PLACEHOLDER="REQUIRED_AT_GRANT_SEAL"
LIMITS={"inference_invocation_max":1,"gateway_admission_max":1,"upstream_attempt_max":1,"max_attempts":1,"concurrency":1,"max_workers":1,"request_retries":0,"stream_retries":0,"gateway_retries":0,"second_admission_rejected":True,"countable_observation":False,"replay_authorized":False}
IDENTITY_FIELDS=("execution_id","job_id","slot_id","attempt_id","operation_id","native_prompt_identity","engine_identity","provider_process_start_identity","request_id","request_local_gateway_id","request_local_gateway_fingerprint","request_fingerprint")
STATE_WRITERS={"user_grant_authority":frozenset(("exact_live_authorization_scope","expected_account_fingerprint","credential_reference","selected_model","hard_usd_cap","cost_authority","not_before","deadline")),"Engine":frozenset(("job","slot","attempt","operation","native_prompt_identity","engine_identity","status transition","prompt binding hash")),"process_custodian":frozenset(("held binary identity","process start identity","raw stdout custody","raw stderr custody","process terminal","resource inventory")),"request_local_gateway":frozenset(("request admission","upstream attempt count","request fingerprint","second admission rejection")),"translator":frozenset(("grammar receipt","raw input hashes","sanitized capture","sanitized diagnostic code")),"reconciler":frozenset(("artifact-only reconciliation receipt",)),"cleanup_custodian":frozenset(("cleanup receipt","residual resource inventory")),"evidence_publisher":frozenset(("owner-private manifest","sanitized allowlisted projection","atomic publication receipt")),"evaluation":frozenset(("countability decision",))}
LEGAL_TRANSITIONS=frozenset((("NEW","PREFLIGHT"),("PREFLIGHT","STOP"),("PREFLIGHT","ADMITTED"),("ADMITTED","PASS"),("ADMITTED","UNKNOWN"),("UNKNOWN","UNKNOWN_UNRESOLVED"),("UNKNOWN","RECONCILED_FROM_EXISTING_ARTIFACTS")))
class ContractError(ValueError):pass
class DuplicateAdmissionCriticalStop(ContractError):pass
_LIVE_AUTH_MARKER=object()
class LiveAuthorization:
    __slots__=("grant_seal_sha256","explicit_user_authorization_receipt_sha256","one_use_nonce","provenance_sha256")
    def __init__(self,grant_seal_sha256:str,receipt_sha256:str,nonce:str,provenance_sha256:str,_marker:Any=None)->None:
        if _marker is not _LIVE_AUTH_MARKER:raise ContractError("R6_TRUSTED_VERIFIER_REQUIRED")
        if not is_sha(grant_seal_sha256) or not is_sha(receipt_sha256) or not is_sha(provenance_sha256) or not isinstance(nonce,str) or not nonce:raise ContractError("R6_LIVE_AUTHORIZATION_INVALID")
        self.grant_seal_sha256=grant_seal_sha256;self.explicit_user_authorization_receipt_sha256=receipt_sha256;self.one_use_nonce=nonce;self.provenance_sha256=provenance_sha256
    @classmethod
    def _issue(cls,grant_sha:str,receipt_sha:str,nonce:str,provenance_sha:str,marker:Any)->"LiveAuthorization":return cls(grant_sha,receipt_sha,nonce,provenance_sha,marker)
def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def is_sha(v:Any)->bool:return isinstance(v,str) and len(v)==64 and all(c in "0123456789abcdef" for c in v)
def canonical_bytes(v:Any)->bytes:
    def walk(x:Any)->None:
        if isinstance(x,float) and not math.isfinite(x):raise ContractError("R6_NONFINITE")
        if isinstance(x,dict):
            for k,y in x.items():
                if not isinstance(k,str):raise ContractError("R6_NON_STRING_KEY")
                walk(y)
        elif isinstance(x,list):
            for y in x:walk(y)
    walk(v)
    try:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
    except (TypeError,ValueError) as e:raise ContractError("R6_CANONICAL_INVALID") from e
def strict_json_bytes(data:bytes)->Any:
    def pairs(items:Any)->Dict[str,Any]:
        out={}
        for k,v in items:
            if k in out:raise ContractError("R6_DUPLICATE_KEY")
            out[k]=v
        return out
    try:return json.loads(data.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(ContractError("R6_NONFINITE")))
    except ContractError:raise
    except Exception as e:raise ContractError("R6_JSON_INVALID") from e
def exact_keys(v:Any,required:Iterable[str],code:str)->None:
    if type(v) is not dict or set(v)!=set(required):raise ContractError(code)
def require_string(v:Any,code:str,allow_empty:bool=False)->str:
    if type(v) is not str or (not allow_empty and not v):raise ContractError(code)
    return v
def require_bool(v:Any,code:str)->bool:
    if type(v) is not bool:raise ContractError(code)
    return v
def require_int(v:Any,code:str,minimum:int=0)->int:
    if type(v) is not int or v<minimum:raise ContractError(code)
    return v
def require_number(v:Any,code:str)->float:
    if type(v) not in (int,float) or isinstance(v,bool) or not math.isfinite(float(v)):raise ContractError(code)
    return float(v)
def parse_time(v:Any)->datetime:
    require_string(v,"R6_TIME_INVALID")
    try:return datetime.fromisoformat(v.replace("Z","+00:00")).astimezone(timezone.utc)
    except Exception as e:raise ContractError("R6_TIME_INVALID") from e
_SECRET_VALUE=re.compile(r"(?i)(bearer\s+|password\s*[:=]|api[_-]?key\s*[:=]|access[_-]?token\s*[:=]|secret\s*[:=]|sk-[a-z0-9]{8,}|-----begin [a-z ]*private key-----)")
_PRIVATE_KEYS={"credential_value","credential_bytes","token","tokens","auth_header","authorization_header","decrypted_value","password","api_key","access_token","secret","secrets"}
_PUBLIC_RAW_KEYS={"raw_stdout","raw_stderr","raw_catalog","prompt_text","provider_response","provider_request","environment_values","observed_opaque_account_fingerprint"}
def scan_forbidden(v:Any,public:bool=False)->None:
    def walk(x:Any)->None:
        if type(x) is dict:
            for k,y in x.items():
                low=str(k).lower().replace(" ","_")
                if low in _PRIVATE_KEYS or (public and (low in _PUBLIC_RAW_KEYS or low.endswith("_private_path") or low=="private_path")):raise ContractError("R6_SECRET_OR_RAW_FORBIDDEN")
                walk(y)
        elif type(x) is list:
            for y in x:walk(y)
        elif isinstance(x,bytes):
            text=x.decode("utf-8","ignore")
            if _SECRET_VALUE.search(text):raise ContractError("R6_SECRET_VALUE_FORBIDDEN")
        elif type(x) is str:
            if _SECRET_VALUE.search(x) or (public and (x.startswith("/") or "../" in x)):raise ContractError("R6_SECRET_VALUE_FORBIDDEN")
    walk(v)
def enforce_authority(owner:str,writes:Iterable[str],transition:Optional[Tuple[str,str]]=None)->None:
    fields=set(writes)
    if owner not in STATE_WRITERS or not fields or not fields.issubset(STATE_WRITERS[owner]):raise ContractError("R6_SINGLE_WRITER_VIOLATION")
    if transition is not None and (owner!="Engine" or transition not in LEGAL_TRANSITIONS):raise ContractError("R6_ILLEGAL_TRANSITION")
def validate_outcome(v:Mapping[str,Any])->None:
    if type(v) is not dict:raise ContractError("R6_OUTCOME_INVALID")
    outcome=v.get("terminal_outcome")
    if outcome not in ("PASS","STOP","UNKNOWN") or v.get("countable_observation") is not False:raise ContractError("R6_OUTCOME_INVALID")
    a=v.get("admission_count");u=v.get("upstream_attempt_count");i=v.get("inference_invocation_count")
    if outcome=="PASS" and (a,u,i,v.get("cleanup_complete"))!=(1,1,1,True):raise ContractError("R6_PASS_INVALID")
    if outcome=="STOP" and (a,u,i,v.get("submission"))!=(0,0,0,"DEFINITELY_NOT_SUBMITTED"):raise ContractError("R6_STOP_INVALID")
    if outcome=="UNKNOWN" and (a!=1 or v.get("retry") is not False or v.get("replay") is not False or v.get("provider_status_calls")!=0 or v.get("durable_owner_private_evidence") is not True):raise ContractError("R6_UNKNOWN_INVALID")
def _flags(directory:bool=False)->int:
    value=os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
    if directory:value|=getattr(os,"O_DIRECTORY",0)
    else:value|=getattr(os,"O_NONBLOCK",0)
    return value
class HeldArtifactSet:
    """Descriptor-relative no-follow traversal rooted at one trusted directory."""
    def __init__(self,root:Path,owner_uid:int)->None:
        self.root=Path(root);self.owner_uid=owner_uid;self._fds=[]
        if not self.root.is_absolute():raise ContractError("R6_ROOT_NOT_ABSOLUTE")
        try:self.root_fd=os.open(str(self.root),_flags(True))
        except OSError as e:raise ContractError("R6_ROOT_OPEN_FAILED") from e
        self._fds.append(self.root_fd);st=os.fstat(self.root_fd)
        if st.st_uid!=owner_uid or stat.S_IMODE(st.st_mode)!=0o700 or not stat.S_ISDIR(st.st_mode):self.close();raise ContractError("R6_CUSTODY_ROOT_IDENTITY")
        self.root_identity={"device":st.st_dev,"inode":st.st_ino,"owner_uid":st.st_uid,"mode":stat.S_IMODE(st.st_mode)}
    def _parts(self,path:Any)->Tuple[str,...]:
        p=Path(require_string(path,"R6_ARTIFACT_PATH"))
        if not p.is_absolute():raise ContractError("R6_PATH_NOT_ABSOLUTE")
        try:rel=p.relative_to(self.root)
        except ValueError as e:raise ContractError("R6_PATH_OUTSIDE_ROOT") from e
        parts=rel.parts
        if not parts or any(x in ("",".","..") for x in parts):raise ContractError("R6_PATH_COMPONENT_INVALID")
        return tuple(parts)
    def open_exact(self,binding:Mapping[str,Any],label:str)->Dict[str,Any]:
        exact_keys(binding,("path","bytes","sha256") if set(binding)=={"path","bytes","sha256"} else ("path","bytes","sha256","device","inode","owner_uid","mode"),"R6_ARTIFACT_BINDING_CLOSED")
        parts=self._parts(binding["path"]);parent=os.dup(self.root_fd);self._fds.append(parent)
        try:
            for part in parts[:-1]:
                nxt=os.open(part,_flags(True),dir_fd=parent);self._fds.append(nxt);parent=nxt
            fd=os.open(parts[-1],_flags(False),dir_fd=parent);self._fds.append(fd);st=os.fstat(fd)
        except OSError as e:raise ContractError("R6_NOFOLLOW_OPEN_FAILED") from e
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=self.owner_uid:raise ContractError("R6_ARTIFACT_IDENTITY")
        expected=(require_int(binding["bytes"],"R6_ARTIFACT_BYTES"),require_string(binding["sha256"],"R6_ARTIFACT_SHA"))
        chunks=[];os.lseek(fd,0,os.SEEK_SET)
        while True:
            chunk=os.read(fd,65536)
            if not chunk:break
            chunks.append(chunk)
        data=b"".join(chunks);actual=(len(data),sha256_bytes(data))
        if expected!=actual:raise ContractError("R6_ARTIFACT_DRIFT")
        if "device" in binding and (binding["device"],binding["inode"],binding["owner_uid"],binding["mode"])!=(st.st_dev,st.st_ino,st.st_uid,stat.S_IMODE(st.st_mode)):raise ContractError("R6_ARTIFACT_IDENTITY")
        return {"label":label,"fd":fd,"data":data,"bytes":len(data),"sha256":actual[1],"device":st.st_dev,"inode":st.st_ino,"owner_uid":st.st_uid,"mode":stat.S_IMODE(st.st_mode)}
    def close(self)->None:
        for fd in reversed(self._fds):
            try:os.close(fd)
            except OSError:pass
        self._fds=[]
    def __enter__(self)->"HeldArtifactSet":return self
    def __exit__(self,*_:Any)->None:self.close()
def atomic_bytes(path:Path,data:bytes,mode:int=0o600)->None:
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True);name=path.name;tmp="."+name+".tmp-"+sha256_bytes(data)[:12];parent=os.open(str(path.parent),_flags(True));fd=-1
    try:
        fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),mode,dir_fd=parent)
        view=memoryview(data)
        while view:view=view[os.write(fd,view):]
        os.fsync(fd);os.close(fd);fd=-1;os.rename(tmp,name,src_dir_fd=parent,dst_dir_fd=parent);os.fsync(parent)
    except Exception:
        if fd>=0:os.close(fd)
        try:os.unlink(tmp,dir_fd=parent)
        except OSError:pass
        raise
    finally:os.close(parent)
class DurableAuthorityStore:
    """One filesystem authority for nonce, operation, and admission CAS."""
    def __init__(self,root:Path)->None:
        self.root=Path(root)/".r6-authority";self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
        if stat.S_IMODE(self.root.stat().st_mode)!=0o700:raise ContractError("R6_AUTHORITY_STORE_MODE")
    @staticmethod
    def operation_key(identity:Mapping[str,Any])->str:return sha256_bytes((str(identity["operation_id"])+"\0"+str(identity["request_fingerprint"])).encode())
    def _create(self,prefix:str,key:str,payload:Mapping[str,Any])->None:
        path=self.root/(prefix+"-"+key+".json");data=canonical_bytes(dict(payload));parent=os.open(str(self.root),_flags(True));fd=-1
        try:
            fd=os.open(path.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),0o600,dir_fd=parent);os.write(fd,data);os.fsync(fd);os.close(fd);fd=-1;os.fsync(parent)
        except FileExistsError as e:raise DuplicateAdmissionCriticalStop("R6_AUTHORITY_ALREADY_CONSUMED") from e
        finally:
            if fd>=0:os.close(fd)
            os.close(parent)
    def reserve_and_burn(self,nonce:str,identity:Mapping[str,Any])->str:
        op=self.operation_key(identity);nonce_key=sha256_bytes(nonce.encode());self._create("nonce",nonce_key,{"state":"BURNED","operation_key":op,"nonce_sha256":nonce_key})
        try:self._create("operation",op,{"state":"BURNED","operation_key":op,"nonce_sha256":nonce_key})
        except Exception:
            try:(self.root/("nonce-"+nonce_key+".json")).unlink()
            except OSError:pass
            raise
        return op
    def admit(self,operation_key:str,receipt:Mapping[str,Any])->None:self._create("admission",operation_key,receipt)
    def is_admitted(self,operation_key:str)->bool:return (self.root/("admission-"+operation_key+".json")).is_file()
