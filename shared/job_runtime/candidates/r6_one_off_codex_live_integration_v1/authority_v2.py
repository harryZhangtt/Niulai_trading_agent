"""Source-pinned noncaller authority for the disabled v2 integration."""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib,json,os,stat
from pathlib import Path
from typing import Any,Dict,Iterable,Mapping,Sequence,Tuple
from .contracts import ContractError,canonical_bytes,require,sha256_bytes
ROOT=Path(__file__).resolve().parents[4]
REGISTRY=("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-integration-owner-registry-v2.json",614,"277fc5b4e9df2d3fae478cd5dc53b6970e31a423bf7a868991f34dd2d615fcf1")
GRANT=("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-v2.json",2467,"75ae5830b2eb93f4b757349203da2f464f80b018ef8bb098fff22dd02c6431a2")
REVIEW=("tuning/architecture/r6_one_off_codex_live_integration_v1/fixed-pre-dispatch-grant-review-v2.json",536,"ce6448ac04d4c0c4b0a302c2f8211eb1021479694d467b1eea11787b30bcb94a")
_MARKER=object()
def _exact(v:Any,keys:Iterable[str],code:str)->Mapping[str,Any]:require(type(v) is dict and set(v)==set(keys),code);return v
def _strict(raw:bytes)->Any:
 def pairs(items:Sequence[Tuple[str,Any]])->Dict[str,Any]:
  out={}
  for k,v in items:
   require(k not in out,"AUTH_DUPLICATE_KEY");out[k]=v
  return out
 try:return json.loads(raw.decode('utf-8','strict'),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in()).throw(ContractError('AUTH_NONFINITE')))
 except ContractError:raise
 except Exception as exc:raise ContractError('AUTH_MALFORMED') from exc
def _read(ref:Tuple[str,int,str])->bytes:
 path=ROOT/ref[0];flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)
 try:fd=os.open(path,flags)
 except OSError as exc:raise ContractError('AUTH_REF_OPEN') from exc
 try:
  info=os.fstat(fd);require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and not(info.st_mode&0o022),'AUTH_REF_IDENTITY');chunks=[]
  while True:
   b=os.read(fd,1024*1024)
   if not b:break
   chunks.append(b)
 finally:os.close(fd)
 raw=b''.join(chunks);require((len(raw),sha256_bytes(raw))==ref[1:],'AUTH_REF_DRIFT');return raw
def _ref(ref:Tuple[str,int,str])->Dict[str,Any]:return {'path':ref[0],'bytes':ref[1],'sha256':ref[2]}
def _instant(v:Any)->datetime:
 require(type(v) is str and (v.endswith('Z') or '+' in v[10:]),'AUTH_TIMEZONE_REQUIRED')
 try:d=datetime.fromisoformat(v.replace('Z','+00:00'))
 except ValueError as exc:raise ContractError('AUTH_TIME_MALFORMED') from exc
 require(d.tzinfo is not None and d.utcoffset() is not None,'AUTH_TIMEZONE_REQUIRED');return d.astimezone(timezone.utc)
def validate_fixed_grant(value:Any,observed:datetime)->Mapping[str,Any]:
 require(isinstance(observed,datetime) and observed.tzinfo is not None and observed.utcoffset() is not None,'OBSERVED_UTC_REQUIRED');observed=observed.astimezone(timezone.utc)
 keys=('version','kind','issuer_role','self_minted','enabled','authority_id','cell_id','treatment','binary','argv','config','prompt','source','profile','budget','window','limits','effects');g=_exact(value,keys,'AUTH_GRANT_SHAPE')
 require(g['version']==2 and g['kind']=='R6_CODEX_PRE_DISPATCH_CELL_GRANT' and g['issuer_role']=='external_integration_owner' and g['self_minted'] is False and g['enabled'] is True and g['authority_id']=='r6-codex-integration-owner-v2','AUTH_GRANT_OWNER')
 require(g['cell_id'] in ('R6DQ-7F2C91A4','R6DQ-1B8E43D7','R6DQ-C4A7095E','R6DQ-92D6F0B3'),'AUTH_CELL')
 require(g['treatment']=={'provider':'codex_cli','release':'0.167.0','model':'gpt-6.1-sol','effort':'low'},'AUTH_TREATMENT')
 binary=_exact(g['binary'],('path','bytes','sha256','mode','official_release_binary_sha256'),'AUTH_BINARY');require(binary['mode']=='0755' and binary['official_release_binary_sha256']=='030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc','AUTH_BINARY')
 require(type(g['argv']) is list and len(g['argv'])==11 and g['argv']==[binary['path'],'exec','--model','gpt-6.1-sol','-c','model_reasoning_effort="low"','-c','model_provider="r6_codex_one_shot"','--json','--skip-git-repo-check','-'],'AUTH_ARGV')
 expected_provider={'id':'r6_codex_one_shot','base_url':'http://127.0.0.1:<ephemeral>/backend-api/codex','wire_api':'responses','official_endpoint':'https://chatgpt.com/backend-api/codex/responses','requires_openai_auth':True,'supports_websockets':False,'request_retries':0,'stream_retries':0}
 require(g['config']=={'model_provider':expected_provider,'model':'gpt-6.1-sol','effort':'low'},'AUTH_CONFIG')
 require(g['prompt']=={'bytes':526,'sha256':'3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b','transport':'native_stdin_exact_once','source_ref':'mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json'},'AUTH_PROMPT')
 require(g['source']=={'cutoff_at':'2026-11-09T00:00:00Z','cutoff_sha256':'32f28a6cea0b1053321a52782abe40d6fd8a2d58b95bb954f90794ec5b733072','allowed':['SEC EDGAR official','Microsoft Investor Relations official']},'AUTH_SOURCE')
 profile=_exact(g['profile'],('selector','credential_reference','credential_reference_sha256','auth_material'),'AUTH_PROFILE');require(profile['selector']=='current CLI profile' and profile['auth_material']=='transient_memory_only' and profile['credential_reference']=='opaque://codex/current-profile' and profile['credential_reference_sha256']==sha256_bytes(profile['credential_reference'].encode()),'AUTH_PROFILE')
 require(g['budget']=={'currency':'USD','hard_cap':'0.01'},'AUTH_BUDGET');start,end=_instant(g['window']['not_before']),_instant(g['window']['deadline']);require(set(g['window'])=={'not_before','deadline'} and start<end and start<=observed<=end,'AUTH_WINDOW_EXPIRED')
 require(g['limits']=={'admissions':1,'inferences':1,'provider_forwards':1,'attempts':1,'concurrency':1,'request_retries':0,'stream_retries':0,'gateway_retries':0,'replay':False,'status_calls':0,'process_timeout_seconds':8},'AUTH_LIMITS')
 require(g['effects']=={'default':'DENY','provider_free_fixture':True,'publication':'sanitized_only','business':False,'email':False,'non_loopback':False},'AUTH_EFFECTS');return g
class FixedAuthority:
 __slots__=('grant','grant_sha256','review_sha256')
 def __init__(self,grant:Mapping[str,Any],gsha:str,rsha:str,marker:object)->None:
  require(marker is _MARKER,'AUTH_NONCALLER_REQUIRED');self.grant=grant;self.grant_sha256=gsha;self.review_sha256=rsha
def load_fixed_authority()->FixedAuthority:
 observed=datetime.now(timezone.utc);registry=_strict(_read(REGISTRY));grant_raw=_read(GRANT);review_raw=_read(REVIEW);grant=validate_fixed_grant(_strict(grant_raw),observed)
 _exact(registry,('version','kind','owner','caller_may_mint','caller_may_select_authority','grant','review','activation','effects'),'AUTH_REGISTRY_SHAPE');require(registry=={'version':2,'kind':'R6_CODEX_INTEGRATION_OWNER_TRUST_ROOT','owner':'independent_integration_owner','caller_may_mint':False,'caller_may_select_authority':False,'grant':_ref(GRANT),'review':_ref(REVIEW),'activation':False,'effects':'provider_free_only'},'AUTH_REGISTRY')
 review=_strict(review_raw);_exact(review,('version','kind','reviewer_role','verdict','subject','checks'),'AUTH_REVIEW_SHAPE');require(review['version']==2 and review['kind']=='R6_CODEX_PRE_DISPATCH_CELL_GRANT_REVIEW' and review['reviewer_role']=='independent_reviewer' and review['verdict']=='CLEAN_PROVIDER_FREE_INTEGRATION' and review['subject']==_ref(GRANT) and all(v is True for v in review['checks'].values()),'AUTH_REVIEW')
 return FixedAuthority(grant,sha256_bytes(grant_raw),sha256_bytes(review_raw),_MARKER)
__all__=['FixedAuthority','load_fixed_authority','validate_fixed_grant']
