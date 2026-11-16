"""Strict, inert contracts for the additive provider-free R6 candidate."""
from __future__ import annotations
import hashlib,json,math,os,re,stat
from pathlib import Path
from types import MappingProxyType
from typing import Any,Dict,Iterable,Mapping,Optional,Sequence,Tuple
DESIGN_SHA256="8b0db47bc9cc4cb2a7fb63bc0755fddd631e3e2e0193889f5a7f43053d2c6a72"
REVIEW_SHA256="a5da363afb32ab52ce10aaf116855a3977979469184014fab77a718ccba9d069"
CALL_BUDGET=MappingProxyType({"catalog_preflight_count":1,"concurrency":1,"gateway_admission_max":1,"gateway_retries":0,"inference_invocation_max":1,"max_attempts":1,"max_workers":1,"request_retries":0,"stream_retries":0,"upstream_attempt_max":1,"second_admission_rejected":True})
IDENTITY_FIELDS=("execution_id","job_id","slot_id","attempt_id","operation_id","provider_process_start_identity","gateway_id","request_id","request_fingerprint")
PARTICIPANTS=("grant","preflight","prompt_process","gateway","translator","terminal","reconciliation","cleanup","live_evidence")
SHA_RE=re.compile(r"^[0-9a-f]{64}$");TOKEN_RE=re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
FORBIDDEN_PUBLIC_KEYS={"credentials","credential","password","secret","auth_header","authorization","account_identity","raw_catalog","raw_stdout","raw_stderr","raw_provider_text","sensitive_prompt_bytes","nested_provider_errors","access_token","refresh_token"}
FORBIDDEN_PUBLIC_VALUE=re.compile(r"(?i)(?:bearer\s+[a-z0-9._~+/=-]{8,}|sk-[a-z0-9]{8,}|api[_-]?key\s*[:=])")
# Exact public predecessor inventory. Hash-only entries mean predecessor evidence retained only a digest.
HISTORICAL_IDENTITIES=MappingProxyType({
 "R3":MappingProxyType({"execution_id":None,"job_id":"claude-live-smoke-20261109T123642Z","slot_id":"sha256:edbc12c8e6d6754920a7b76d2e25b6c80e118a65047d17a8223e8923bbf6059f","attempt_id":"sha256:c72c078909328d1e8096090c9a4fd3efc5695837ce208d5f89a396d2dce9cc1c","operation_id":None,"provider_process_start_identity":None,"gateway_id":None,"request_id":None,"request_fingerprint":None}),
 "R4":MappingProxyType({"execution_id":None,"job_id":None,"slot_id":"sha256:66ca95b8a8cd1b6471b893a13169249d8a36713e5475665e42352a13dbec2186","attempt_id":"sha256:f8ddc6225b89f25cff3a39ae0cc310ef7348d7fd507783eb597d61ed9c35ae08","operation_id":None,"provider_process_start_identity":None,"gateway_id":None,"request_id":None,"request_fingerprint":None}),
 "R5":MappingProxyType({field:None for field in IDENTITY_FIELDS}),
})
STATE_WRITERS=MappingProxyType({"Engine":frozenset(("job","slot","attempt","operation","status","prompt_binding_hash")),"gateway":frozenset(("request_admission","upstream_attempt_count","request_fingerprint")),"process_custodian":frozenset(("process_start","raw_streams","process_terminal","cleanup")),"translator":frozenset(("grammar_receipt","sanitized_capture")),"reconciler":frozenset(("artifact_only_reconciliation",)),"evaluation":frozenset(("countability_decision",))})
LEGAL_TRANSITIONS=frozenset({("NEW","PREFLIGHT_STOP"),("NEW","ADMITTED"),("ADMITTED","PASS"),("ADMITTED","UNKNOWN"),("UNKNOWN","UNKNOWN_UNRESOLVED"),("UNKNOWN","RECONCILED_FROM_EXISTING_ARTIFACTS")})
class R6ContractError(ValueError):
 def __init__(self,code:str)->None:self.code=code;super().__init__(code)
def _plain(value:Any)->Any:
 if isinstance(value,Mapping):return {k:_plain(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [_plain(v) for v in value]
 return value
def canonical_bytes(value:Any)->bytes:
 try:return json.dumps(_plain(value),sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
 except (TypeError,ValueError,OverflowError):raise R6ContractError("R6_JSON_INVALID") from None
def sha256_bytes(data:bytes)->str:return hashlib.sha256(data).hexdigest()
def strict_json_bytes(data:bytes)->Any:
 def pairs(items:Iterable[Tuple[str,Any]])->Dict[str,Any]:
  value={}
  for key,item in items:
   if key in value:raise R6ContractError("R6_DUPLICATE_KEY")
   value[key]=item
  return value
 try:value=json.loads(data.decode("utf-8"),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(R6ContractError("R6_NONFINITE")))
 except R6ContractError:raise
 except Exception:raise R6ContractError("R6_JSON_INVALID") from None
 reject_nonfinite(value);return value
def reject_nonfinite(value:Any)->None:
 if type(value) is float and not math.isfinite(value):raise R6ContractError("R6_NONFINITE")
 if type(value) is dict:
  for child in value.values():reject_nonfinite(child)
 elif type(value) is list:
  for child in value:reject_nonfinite(child)
def require_exact(value:Any,keys:Iterable[str],code:str)->Mapping[str,Any]:
 if type(value) is not dict or set(value)!=set(keys):raise R6ContractError(code)
 return value
def enforce_authority(owner:str,writes:Iterable[str],transition:Optional[Tuple[str,str]]=None)->None:
 if owner not in STATE_WRITERS or type(writes) not in (set,frozenset,tuple,list):raise R6ContractError("R6_WRITER_INVALID")
 requested=frozenset(writes)
 if not requested or not requested.issubset(STATE_WRITERS[owner]):raise R6ContractError("R6_SINGLE_WRITER_VIOLATION")
 if transition is not None:
  if type(transition) is not tuple or len(transition)!=2 or transition not in LEGAL_TRANSITIONS:raise R6ContractError("R6_TRANSITION_FORBIDDEN")
  if owner!="Engine" or "status" not in requested:raise R6ContractError("R6_TRANSITION_AUTHORITY_VIOLATION")
def _historical_reuse(field:str,item:str)->bool:
 for record in HISTORICAL_IDENTITIES.values():
  prior=record[field]
  if prior is None:continue
  if prior.startswith("sha256:"):
   digest=prior[7:]
   if item==digest or sha256_bytes(item.encode("utf-8"))==digest:return True
  elif item==prior:return True
 return False
def validate_identity(value:Any)->Mapping[str,str]:
 require_exact(value,IDENTITY_FIELDS,"R6_IDENTITY_SHAPE");normalized={}
 for key in IDENTITY_FIELDS:
  item=value[key]
  if type(item) is str and _historical_reuse(key,item):raise R6ContractError("R6_PRIOR_IDENTITY_REUSE")
  if type(item) is not str or TOKEN_RE.fullmatch(item) is None or item!=item.strip():raise R6ContractError("R6_IDENTITY_INVALID")
  normalized[key]=item
 if SHA_RE.fullmatch(normalized["request_fingerprint"]) is None:raise R6ContractError("R6_REQUEST_FINGERPRINT_INVALID")
 return MappingProxyType(normalized)
def assert_same_identity(expected:Mapping[str,str],*receipts:Mapping[str,Any])->None:
 canonical=dict(validate_identity(dict(expected)))
 for receipt in receipts:
  if type(receipt) is not dict or dict(validate_identity(receipt.get("identity")))!=canonical:raise R6ContractError("R6_CROSS_RECEIPT_IDENTITY_MISMATCH")
def identity_receipts(identity:Mapping[str,str])->Mapping[str,Mapping[str,str]]:
 normalized=dict(validate_identity(dict(identity)));return MappingProxyType({name:MappingProxyType(dict(normalized)) for name in PARTICIPANTS})
def scan_public(value:Any,path:str="$")->None:
 if type(value) is dict:
  for key,child in value.items():
   if type(key) is not str or key.lower() in FORBIDDEN_PUBLIC_KEYS or (key.lower().startswith("raw_") and key.lower()!="raw_hashes"):raise R6ContractError("R6_PUBLIC_SECRET_OR_RAW_FIELD")
   scan_public(child,path+"."+key)
 elif type(value) in (list,tuple):
  for index,child in enumerate(value):scan_public(child,"%s[%d]"%(path,index))
 elif type(value) is str and FORBIDDEN_PUBLIC_VALUE.search(value):raise R6ContractError("R6_PUBLIC_SECRET_OR_RAW_VALUE")
 elif type(value) is float and not math.isfinite(value):raise R6ContractError("R6_NONFINITE")
def _freeze(value:Any)->Any:
 if type(value) is dict:return MappingProxyType({k:_freeze(v) for k,v in value.items()})
 if type(value) is list:return tuple(_freeze(v) for v in value)
 return value
def public_projection(value:Mapping[str,Any])->Mapping[str,Any]:scan_public(value);return _freeze(dict(value))
def binding(path:Path,data:bytes,**extra:Any)->Dict[str,Any]:
 info=path.stat();result={"path":str(path),"bytes":len(data),"sha256":sha256_bytes(data),"inode":info.st_ino,"owner":info.st_uid,"mode":stat.S_IMODE(info.st_mode)};result.update(extra);return result
class SecureArtifactSet:
 """Open every path component no-follow and hold all file descriptors through use."""
 def __init__(self,bindings:Mapping[str,Mapping[str,Any]],synthetic_root:Path)->None:
  self.bindings=bindings;self.root=synthetic_root.resolve(strict=True);self._fds={};self._before={};self._closed=False
 def __enter__(self):
  try:
   root_flags=os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
   root_fd=os.open(str(self.root),root_flags)
   try:
    for name,bound in self.bindings.items():self._open_one(name,bound,root_fd)
   finally:os.close(root_fd)
  except BaseException:self.close();raise
  return self
 def _open_one(self,name:str,bound:Mapping[str,Any],root_fd:int)->None:
  base={"path","bytes","sha256","inode","owner","mode"}
  if type(bound) is not dict or not base.issubset(bound) or type(bound["path"]) is not str or type(bound["bytes"]) is not int or bound["bytes"]<0 or type(bound["sha256"]) is not str or SHA_RE.fullmatch(bound["sha256"]) is None:raise R6ContractError("R6_FILE_BINDING_INVALID")
  path=Path(bound["path"])
  if not path.is_absolute():raise R6ContractError("R6_PATH_NOT_ABSOLUTE")
  try:parts=path.absolute().relative_to(self.root.absolute()).parts
  except ValueError:raise R6ContractError("R6_PATH_OUTSIDE_SYNTHETIC_ROOT") from None
  if not parts:raise R6ContractError("R6_FILE_BINDING_INVALID")
  parent=os.dup(root_fd)
  try:
   for part in parts[:-1]:
    nxt=os.open(part,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0),dir_fd=parent);os.close(parent);parent=nxt
   fd=os.open(parts[-1],os.O_RDONLY|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_NONBLOCK",0),dir_fd=parent)
  except OSError:raise R6ContractError("R6_SECURE_READ_FAILED") from None
  finally:os.close(parent)
  info=os.fstat(fd)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)&0o022:
   os.close(fd);raise R6ContractError("R6_FILE_IDENTITY_INVALID")
  if (bound["inode"],bound["owner"],bound["mode"],bound["bytes"])!=(info.st_ino,info.st_uid,stat.S_IMODE(info.st_mode),info.st_size):
   os.close(fd);raise R6ContractError("R6_FILE_IDENTITY_MISMATCH")
  self._fds[name]=fd;self._before[name]=(info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink,info.st_size,info.st_mtime_ns)
 def read_all(self)->Dict[str,bytes]:
  values={}
  for name,fd in self._fds.items():
   os.lseek(fd,0,os.SEEK_SET);chunks=[]
   while True:
    chunk=os.read(fd,65536)
    if not chunk:break
    chunks.append(chunk)
   data=b"".join(chunks);after=os.fstat(fd);bound=self.bindings[name]
   signature=(after.st_dev,after.st_ino,after.st_mode,after.st_uid,after.st_nlink,after.st_size,after.st_mtime_ns)
   try:current=Path(bound["path"]).lstat()
   except OSError:raise R6ContractError("R6_PATH_SUBSTITUTION") from None
   if signature!=self._before[name] or (current.st_dev,current.st_ino)!=(after.st_dev,after.st_ino):raise R6ContractError("R6_PATH_SUBSTITUTION")
   if len(data)!=bound["bytes"] or sha256_bytes(data)!=bound["sha256"]:raise R6ContractError("R6_FILE_DIGEST_MISMATCH")
   values[name]=data
  return values
 def close(self)->None:
  if not self._closed:
   for fd in self._fds.values():
    try:os.close(fd)
    except OSError:pass
   self._closed=True
 def __exit__(self,*_args):self.close()
def secure_read(bound:Mapping[str,Any],synthetic_root:Path,*,executable:bool=False)->bytes:
 with SecureArtifactSet({"artifact":bound},synthetic_root) as opened:return opened.read_all()["artifact"]
def validate_outcome(value:Mapping[str,Any])->None:
 outcome=value.get("terminal_outcome")
 if outcome not in ("PASS","STOP","UNKNOWN") or value.get("countable_observation") is not False:raise R6ContractError("R6_TERMINAL_OUTCOME_INVALID")
 attempts=value.get("upstream_attempt_count")
 if type(attempts) is not int:raise R6ContractError("R6_TERMINAL_OUTCOME_INVALID")
 if outcome=="PASS" and (attempts!=1 or value.get("terminal_complete") is not True or value.get("cleanup_complete") is not True):raise R6ContractError("R6_PASS_INVALID")
 if outcome=="STOP" and (attempts!=0 or value.get("submission")!="DEFINITELY_NOT_SUBMITTED"):raise R6ContractError("R6_STOP_INVALID")
 if outcome=="UNKNOWN" and (attempts!=1 or value.get("admission_count")!=1 or value.get("replay") is not False or value.get("retry") is not False or value.get("provider_status_calls")!=0 or value.get("reconciliation_dispatch") is not False or value.get("durable_after_reconstruction") is not True):raise R6ContractError("R6_UNKNOWN_INVALID")


def _closed(value:Any,keys:Iterable[str],code:str)->None:
 if type(value) is not dict or set(value)!=set(keys):raise R6ContractError(code)
def _identity_receipt(value:Any,identity:Mapping[str,str],code:str)->None:
 if type(value) is not dict or dict(validate_identity(value))!=dict(identity):raise R6ContractError(code)
def validate_live_evidence(value:Any)->None:
 """Validate the final serialized evidence against the closed live-evidence contract."""
 if type(value) is not dict:raise R6ContractError("R6_LIVE_EVIDENCE_SHAPE")
 outcome=value.get("terminal_outcome")
 common={"schema_version","identity","identity_receipts","terminal_outcome","countable_observation","upstream_attempt_count","preflight","live_authority","enabled","provider_calls","network_calls","account_calls","email_calls","private_state_calls"}
 extras={"PASS":{"gateway","translator","cleanup","terminal_complete","cleanup_complete","terminal"},"STOP":{"submission"},"UNKNOWN":{"gateway","translator","cleanup","reconciliation","admission_count","durable_after_reconstruction","provider_status_calls","reconciliation_dispatch","replay","retry"}}
 if outcome not in extras:raise R6ContractError("R6_LIVE_EVIDENCE_OUTCOME")
 _closed(value,common|extras[outcome],"R6_LIVE_EVIDENCE_SHAPE")
 if value["schema_version"]!="live-evidence-v1" or value["countable_observation"] is not False or value["live_authority"] is not False or value["enabled"] is not False or any(type(value[k]) is not int or value[k]!=0 for k in ("provider_calls","network_calls","account_calls","email_calls","private_state_calls")):raise R6ContractError("R6_LIVE_EVIDENCE_CONSTANT")
 identity=validate_identity(value["identity"]);receipts=value["identity_receipts"]
 _closed(receipts,PARTICIPANTS,"R6_IDENTITY_RECEIPTS_SHAPE")
 for receipt in receipts.values():
  if dict(validate_identity(receipt))!=dict(identity):raise R6ContractError("R6_CROSS_RECEIPT_IDENTITY_MISMATCH")
 pre=value["preflight"]
 if type(pre) is not dict or pre.get("decision") not in ("PASS","STOP"):raise R6ContractError("R6_PREFLIGHT_RECEIPT_INVALID")
 pre_keys={"schema_version","identity","decision","reason_code","submission","upstream_attempt_count","countable_observation"}|({"catalog_preflight_count","artifact_set_sha256"} if pre["decision"]=="PASS" else set())
 _closed(pre,pre_keys,"R6_PREFLIGHT_RECEIPT_INVALID");_identity_receipt(pre["identity"],identity,"R6_PREFLIGHT_RECEIPT_INVALID")
 if pre["schema_version"]!="preflight-receipt-v1" or type(pre["reason_code"]) is not str or pre["submission"]!="DEFINITELY_NOT_SUBMITTED" or pre["upstream_attempt_count"]!=0 or pre["countable_observation"] is not False:raise R6ContractError("R6_PREFLIGHT_RECEIPT_INVALID")
 if pre["decision"]=="PASS" and (pre["catalog_preflight_count"]!=1 or SHA_RE.fullmatch(str(pre["artifact_set_sha256"])) is None):raise R6ContractError("R6_PREFLIGHT_RECEIPT_INVALID")
 validate_outcome(value)
 if outcome=="STOP":return
 gateway=value["gateway"];gkeys={"schema_version","identity","request_sha256","request_fingerprint","admission_count","upstream_attempt_count","second_admission_rejected","gateway_retries","countable_observation"};_closed(gateway,gkeys,"R6_GATEWAY_RECEIPT_INVALID");_identity_receipt(gateway["identity"],identity,"R6_GATEWAY_RECEIPT_INVALID")
 if gateway["schema_version"]!="gateway-observer-receipt-v1" or any(SHA_RE.fullmatch(str(gateway[k])) is None for k in ("request_sha256","request_fingerprint")) or (gateway["admission_count"],gateway["upstream_attempt_count"],gateway["second_admission_rejected"],gateway["gateway_retries"],gateway["countable_observation"])!=(1,1,True,0,False):raise R6ContractError("R6_GATEWAY_RECEIPT_INVALID")
 translator=value["translator"];tkeys={"schema_version","identity","parser_path","parser_bytes","parser_sha256","grammar_version","raw_hashes","sanitized_path","sanitized_bytes","sanitized_sha256","sanitized_terminal","countable_observation"};_closed(translator,tkeys,"R6_TRANSLATOR_RECEIPT_INVALID");_identity_receipt(translator["identity"],identity,"R6_TRANSLATOR_RECEIPT_INVALID")
 terminal_data=translator["sanitized_terminal"];_closed(terminal_data,{"terminal_status","process_exit","output_bytes","output_sha256"},"R6_TRANSLATOR_RECEIPT_INVALID")
 if translator["schema_version"]!="translator-receipt-v1" or type(translator["parser_path"]) is not str or type(translator["parser_bytes"]) is not int or translator["parser_bytes"]<1 or SHA_RE.fullmatch(str(translator["parser_sha256"])) is None or translator["grammar_version"]!="r6-synthetic-terminal-1" or type(translator["raw_hashes"]) is not list or not translator["raw_hashes"] or any(SHA_RE.fullmatch(str(x)) is None for x in translator["raw_hashes"]) or type(translator["sanitized_path"]) is not str or type(translator["sanitized_bytes"]) is not int or translator["sanitized_bytes"]<1 or SHA_RE.fullmatch(str(translator["sanitized_sha256"])) is None or translator["countable_observation"] is not False or type(terminal_data["terminal_status"]) is not str or type(terminal_data["process_exit"]) is not int or type(terminal_data["output_bytes"]) is not int or terminal_data["output_bytes"]<0 or SHA_RE.fullmatch(str(terminal_data["output_sha256"])) is None:raise R6ContractError("R6_TRANSLATOR_RECEIPT_INVALID")
 cleanup=value["cleanup"];ckeys={"identity","process_group","listener","socket_path","file_descriptors","temporary_paths","residual_children","unlisted_effects"};_closed(cleanup,ckeys,"R6_CLEANUP_RECEIPT_INVALID");_identity_receipt(cleanup["identity"],identity,"R6_CLEANUP_RECEIPT_INVALID")
 for key in ("process_group","listener","socket_path","file_descriptors","temporary_paths"):
  if cleanup[key]!={"applicable":False,"evidence":"provider_free_no_resource_created"}:raise R6ContractError("R6_CLEANUP_RECEIPT_INVALID")
 if cleanup["residual_children"]!=0 or cleanup["unlisted_effects"]!=0:raise R6ContractError("R6_CLEANUP_RECEIPT_INVALID")
 if outcome=="PASS":
  terminal=value["terminal"];_closed(terminal,{"identity","terminal_status","process_exit","output_bytes","output_sha256"},"R6_TERMINAL_RECEIPT_INVALID");_identity_receipt(terminal["identity"],identity,"R6_TERMINAL_RECEIPT_INVALID")
  if type(terminal["terminal_status"]) is not str or type(terminal["process_exit"]) is not int or type(terminal["output_bytes"]) is not int or terminal["output_bytes"]<0 or SHA_RE.fullmatch(str(terminal["output_sha256"])) is None:raise R6ContractError("R6_TERMINAL_RECEIPT_INVALID")
 else:
  reconciliation=value["reconciliation"];rkeys={"schema_version","identity","outcome","artifact_only","dispatch_count","provider_status_calls","replay","retry","original_evidence_mutated","countable_observation"};_closed(reconciliation,rkeys,"R6_RECONCILIATION_RECEIPT_INVALID");_identity_receipt(reconciliation["identity"],identity,"R6_RECONCILIATION_RECEIPT_INVALID")
  if reconciliation["schema_version"]!="reconciliation-receipt-v1" or reconciliation["outcome"] not in ("UNKNOWN_UNRESOLVED","RECONCILED_FROM_EXISTING_ARTIFACTS") or (reconciliation["artifact_only"],reconciliation["dispatch_count"],reconciliation["provider_status_calls"],reconciliation["replay"],reconciliation["retry"],reconciliation["original_evidence_mutated"],reconciliation["countable_observation"])!=(True,0,0,False,False,False,False):raise R6ContractError("R6_RECONCILIATION_RECEIPT_INVALID")
