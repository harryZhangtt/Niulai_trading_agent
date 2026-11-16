"""Closed contracts for the disabled Codex one-shot real-integration boundary."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, math, os, re, stat
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Sequence, Tuple

MODEL="gpt-6.1-sol"; RELEASE="0.167.0"; EFFORT="low"; PROVIDER_ID="r6_codex_one_shot"
ROUTE="/backend-api/codex/responses"; OFFICIAL_HOST="chatgpt.com"; USD_CAP="0.01"
PROMPT_SHA256="3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"; PROMPT_BYTES=526
SOURCE_CUTOFF="2026-11-09T00:00:00Z"; SOURCE_CUTOFF_SHA256="32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072"
CELL_IDS=frozenset(("R6DQ-7F2C91A4","R6DQ-1B8E43D7","R6DQ-C4A7095E","R6DQ-92D6F0B3"))
PREDECESSORS=(
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-driver-provider-free-strengthened-v3-producer-verification.json",10889,"41ea7176c458de79de4d5f34eecc1f7cc45bb437d06701caec4fb49e723f9472"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-driver-provider-free-strengthened-v3-independent-review.json",15298,"601268263ce979bdf62ca1c096e031e914a436b3be6ed89c98916b587b0551d3"),
("tuning/architecture/r6_one_off_codex_adapter_v1/producer-verification-v4-final.json",10809,"cc608750c4b06a502195a28f1e13308ba7702803482a78fe1c7ba25894b50644"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-live-adapter-provider-free-v4-independent-review.json",11239,"e02ab04cfa2ea891b4830f03d20563c6493f694d3f88e2524a3cee86d7efd214"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v7-producer-verification.json",10079,"11cf2f102fc953acfb8468edcad77dda94195c846eac886ac5b9855a167308b5"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-o1-codex-catalog-provider-free-successor-v7-independent-review.json",15664,"7f84134641537c5264853e5ca0b193a064a2d5710cba34f504cb772941e211fd"),
("tuning/architecture/r6_one_off_codex_catalog_v1/source-research-v8.json",2840,"2ca78dceef8353c2fa56d655e7a294b7b6ad4152b9897dd353467b22651c1353"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-producer-verification-v6.json",9973,"2242c2caac942821e697308ed70df95472523ad0011b09584c4f83137cbe89a6"),
("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-attempt-envelope-v1-successor-v6-independent-review.json",6657,"0fde238ba360411bd4b75d202f1cd378615b50283b01dc965d798135e7c4b867"),
)
_SHA=re.compile(r"^[0-9a-f]{64}$"); _ID=re.compile(r"^[a-z0-9][a-z0-9._/-]{7,191}$")
class ContractError(ValueError): pass
def require(ok:bool,code:str)->None:
 if not ok: raise ContractError(code)
def canonical_bytes(v:Any)->bytes:return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
def sha256_bytes(v:bytes)->str:return hashlib.sha256(v).hexdigest()
def strict_json(raw:bytes)->Any:
 def pairs(items:Sequence[Tuple[str,Any]])->Dict[str,Any]:
  out={}
  for k,v in items:
   if k in out:raise ContractError("DUPLICATE_JSON_KEY")
   out[k]=v
  return out
 try:return json.loads(raw.decode("utf-8","strict"),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in()).throw(ContractError("NONFINITE_JSON")))
 except ContractError:raise
 except Exception as exc:raise ContractError("MALFORMED_JSON") from exc
def exact(v:Any,keys:Iterable[str],code:str)->Mapping[str,Any]:require(type(v) is dict and set(v)==set(keys),code);return v
def ref(path:Path,root:Path)->Dict[str,Any]:
 raw=path.read_bytes();return {"path":path.relative_to(root).as_posix(),"bytes":len(raw),"sha256":sha256_bytes(raw)}
def read_ref(value:Any,root:Path,code:str)->bytes:
 item=exact(value,("path","bytes","sha256"),code+"_SHAPE");p=Path(item["path"]);require(type(item["path"]) is str and not p.is_absolute() and ".." not in p.parts,code+"_PATH");target=root/p
 try:fd=os.open(target,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0))
 except OSError as exc:raise ContractError(code+"_OPEN") from exc
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode),code+"_REGULAR");chunks=[]
  while True:
   chunk=os.read(fd,1024*1024)
   if not chunk:break
   chunks.append(chunk)
 finally:os.close(fd)
 raw=b"".join(chunks);require(type(item["bytes"]) is int and len(raw)==item["bytes"] and _SHA.fullmatch(item["sha256"] or "") and sha256_bytes(raw)==item["sha256"],code+"_DRIFT");return raw
def verify_predecessors(root:Path)->None:
 for path,size,digest in PREDECESSORS:read_ref({"path":path,"bytes":size,"sha256":digest},root,"PREDECESSOR")
def _instant(v:Any)->datetime:
 require(type(v) is str,"WINDOW_TIME")
 try:d=datetime.fromisoformat(v.replace("Z","+00:00"))
 except ValueError as exc:raise ContractError("WINDOW_TIME") from exc
 require(d.tzinfo is not None,"WINDOW_TIME");return d.astimezone(timezone.utc)
def validate_pregrant(value:Any)->Mapping[str,Any]:
 g=exact(value,("version","kind","issuer_role","self_minted","enabled","cell_id","treatment","binary","argv","config","prompt","source","budget","window","limits","profile","effects"),"GRANT_SHAPE")
 require(g["version"]==1 and g["kind"]=="R6_CODEX_PRE_DISPATCH_CELL_GRANT" and g["issuer_role"]=="external_authority" and g["self_minted"] is False and g["enabled"] is True,"GRANT_AUTHORITY")
 require(g["cell_id"] in CELL_IDS,"GRANT_CELL");require(g["treatment"]=={"provider":"codex_cli","release":RELEASE,"model":MODEL,"effort":EFFORT},"GRANT_TREATMENT")
 binary=exact(g["binary"],("path","bytes","sha256","mode"),"GRANT_BINARY");require(type(binary["path"]) is str and type(binary["bytes"]) is int and binary["bytes"]>0 and _SHA.fullmatch(binary["sha256"] or "") and binary["mode"]=="0755","GRANT_BINARY")
 require(type(g["argv"]) is list and len(g["argv"])>=11 and g["argv"][0]==binary["path"] and g["argv"][1:4]==["exec","--model",MODEL] and g["argv"][-1]=="-","GRANT_ARGV")
 cfg=exact(g["config"],("model_provider_id","base_url","wire_api","official_endpoint","requires_openai_auth","reasoning_effort","request_retries","stream_retries"),"GRANT_CONFIG")
 require(cfg=={"model_provider_id":PROVIDER_ID,"base_url":"http://127.0.0.1:<ephemeral>/backend-api/codex","wire_api":"responses","official_endpoint":"https://chatgpt.com/backend-api/codex/responses","requires_openai_auth":True,"reasoning_effort":EFFORT,"request_retries":0,"stream_retries":0},"GRANT_CONFIG")
 require(g["prompt"]=={"bytes":PROMPT_BYTES,"sha256":PROMPT_SHA256,"transport":"native_stdin_exact_once"},"GRANT_PROMPT")
 require(g["source"]=={"cutoff_at":SOURCE_CUTOFF,"cutoff_sha256":SOURCE_CUTOFF_SHA256},"GRANT_SOURCE")
 require(g["budget"]=={"currency":"USD","hard_cap":"0.01"},"GRANT_BUDGET")
 start,end=_instant(g["window"]["not_before"]),_instant(g["window"]["deadline"]);require(set(g["window"])=={"not_before","deadline"} and (end-start).total_seconds()==1800,"GRANT_WINDOW")
 require(g["limits"]=={"admissions":1,"inferences":1,"provider_forwards":1,"attempts":1,"concurrency":1,"request_retries":0,"stream_retries":0,"gateway_retries":0,"replay":False,"status_calls":0},"GRANT_LIMITS")
 require(g["profile"]=={"selector":"current CLI profile","auth":"opaque_transient_memory_only"},"GRANT_PROFILE")
 require(g["effects"]=={"default":"DENY","publication":"sanitized_only","business":False,"email":False},"GRANT_EFFECTS");return g
def load_pregrant(grant_ref:Mapping[str,Any],review_ref:Mapping[str,Any],root:Path,now:datetime)->Tuple[Mapping[str,Any],str,str]:
 grant_raw=read_ref(grant_ref,root,"PREGRANT");review_raw=read_ref(review_ref,root,"PREGRANT_REVIEW");g=validate_pregrant(strict_json(grant_raw));r=exact(strict_json(review_raw),("version","kind","reviewer_role","verdict","subject","checks"),"REVIEW_SHAPE")
 require(r["version"]==1 and r["kind"]=="R6_CODEX_PRE_DISPATCH_CELL_GRANT_REVIEW" and r["reviewer_role"]=="independent_reviewer" and r["verdict"]=="CLEAN" and r["subject"]==dict(grant_ref),"REVIEW_AUTHORITY")
 require(r["checks"]=={"cell":True,"treatment":True,"binary":True,"argv":True,"config":True,"prompt":True,"source":True,"budget_window":True,"limits":True},"REVIEW_CHECKS")
 require(_instant(g["window"]["not_before"])<=now.astimezone(timezone.utc)<=_instant(g["window"]["deadline"]),"GRANT_NOT_CURRENT");return g,sha256_bytes(grant_raw),sha256_bytes(review_raw)
def validate_driver_binding(grant:Mapping[str,Any],config:Mapping[str,Any],prompt:bytes)->None:
 b=grant["binary"];require(config["binary"]["path"]==b["path"] and config["binary"]["bytes"]==b["bytes"] and config["binary"]["sha256"]==b["sha256"],"BINARY_GRANT_MISMATCH");require(config["model"]==MODEL and config["effort"]==EFFORT,"TREATMENT_GRANT_MISMATCH");require(len(prompt)==PROMPT_BYTES and sha256_bytes(prompt)==PROMPT_SHA256,"PROMPT_GRANT_MISMATCH")
def post_run_seal(result:Any,grant_sha:str,review_sha:str,p0:Mapping[str,Any])->Dict[str,Any]:
 receipts={k:sha256_bytes(canonical_bytes(v)) for k,v in result.receipts.items()};seal={"version":1,"kind":"R6_CODEX_POST_RUN_EXECUTION_SEAL","authority":"EVIDENCE_ONLY_NOT_DISPATCH_AUTHORITY","pregrant_sha256":grant_sha,"pregrant_review_sha256":review_sha,"outcome":result.outcome,"code":result.code,"gateway_receipt_sha256":receipts.get("gateway","0"*64),"process_receipt_sha256":receipts.get("process","0"*64),"terminal_receipt_sha256":receipts.get("terminal","0"*64),"custody_receipt_sha256":receipts.get("custody_cleanup","0"*64),"publication_receipt_sha256":sha256_bytes(canonical_bytes(result.publication or {})),"engine_readback_sha256":receipts.get("engine_readback","0"*64),"p0_envelope_sha256":sha256_bytes(canonical_bytes(p0)),"counts":dict(result.counters),"fence":{"retry":False,"replay":False,"status_calls":0,"reconciliation":False},"countable_observation":False}
 validate_post_seal(seal);return seal
def validate_post_seal(v:Any)->Mapping[str,Any]:
 keys=("version","kind","authority","pregrant_sha256","pregrant_review_sha256","outcome","code","gateway_receipt_sha256","process_receipt_sha256","terminal_receipt_sha256","custody_receipt_sha256","publication_receipt_sha256","engine_readback_sha256","p0_envelope_sha256","counts","fence","countable_observation");s=exact(v,keys,"SEAL_SHAPE");require(s["version"]==1 and s["kind"]=="R6_CODEX_POST_RUN_EXECUTION_SEAL" and s["authority"]=="EVIDENCE_ONLY_NOT_DISPATCH_AUTHORITY" and s["outcome"] in ("PASS","STOP","UNKNOWN") and s["countable_observation"] is False,"SEAL_CONSTANT")
 for k in keys:
  if k.endswith("sha256"):require(_SHA.fullmatch(s[k] or "") is not None,"SEAL_DIGEST")
 require(s["fence"]=={"retry":False,"replay":False,"status_calls":0,"reconciliation":False},"SEAL_FENCE");return s
