"""Strict durable no-replay authority for the disabled TEST_ONLY canary."""
from __future__ import annotations
import hashlib,json,os,re,stat
from pathlib import Path
from shared.job_runtime.provider_contract import ProviderResultV1
from .budget import ARMS,CAMPAIGN,JOBS

class JournalError(ValueError):pass
SHA=re.compile(r'[0-9a-f]{64}\Z')
IDENTITY=re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,255}\Z')
BINDING_FIELDS={'deployment_id','campaign_id','job_id','arm','slot_id','attempt_id','operation_id','profile','model','cap','resource','prompt_sha256'}
CLAIM_FIELDS=BINDING_FIELDS|{'schema_version','record_type','state','nonce','claim_id','binding_sha256'}
RESULT_FIELDS={'version','provider','operation_id','phase','submission','terminal_proof','status','code','failure_kind','http_status','provider_should_retry','retry_after_at','retry_after_source','receipt'}
TERMINAL_FIELDS={'schema_version','record_type','claim_id','nonce','outcome','provider','operation_id','result_sha256','sealed_result','terminal_sha256'}

def _canonical(v):return (json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')
def _plain(value):
 if hasattr(value,'items'):return {k:_plain(v) for k,v in value.items()}
 if isinstance(value,(tuple,list)):return [_plain(v) for v in value]
 return value
def _domain_hash(domain,value):return hashlib.sha256(domain+b'\0'+_canonical(value)).hexdigest()
def _strict(raw):
 if not 1<=len(raw)<=65536:raise JournalError('JOURNAL_SIZE_INVALID')
 def pairs(items):
  out={}
  for k,v in items:
   if k in out:raise JournalError('JOURNAL_DUPLICATE_KEY')
   out[k]=v
  return out
 try:value=json.loads(raw.decode('ascii'),object_pairs_hook=pairs,parse_constant=lambda _:(_ for _ in ()).throw(JournalError('JOURNAL_NONFINITE')))
 except (UnicodeError,json.JSONDecodeError):raise JournalError('JOURNAL_JSON_INVALID') from None
 if type(value) is not dict or _canonical(value)!=raw:raise JournalError('JOURNAL_NONCANONICAL')
 return value
def _validate_binding(binding):
 if type(binding) is not dict or set(binding)!=BINDING_FIELDS:raise JournalError('BINDING_SCHEMA_INVALID')
 if any(type(binding[k]) is not str for k in BINDING_FIELDS):raise JournalError('BINDING_SCHEMA_INVALID')
 if binding['deployment_id']!=CAMPAIGN or binding['campaign_id']!=CAMPAIGN or binding['job_id'] not in JOBS or binding['arm']!=ARMS[binding['job_id']]:raise JournalError('BINDING_SCHEMA_INVALID')
 if binding['profile']!='fable-5-1-dq-disabled' or binding['model']!='claude-fable-5-1' or binding['cap']!='0.02' or binding['resource']!='fable-5-1-dq-v1-shared' or binding['prompt_sha256']!='3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b':raise JournalError('BINDING_SCHEMA_INVALID')
 if any(IDENTITY.fullmatch(binding[k]) is None for k in ('slot_id','attempt_id','operation_id')):raise JournalError('BINDING_SCHEMA_INVALID')
 return dict(binding)
def derive_effect_nonce(binding):return _domain_hash(b'fable-effect-nonce-v1',_validate_binding(dict(binding)))
def _claim_hash(v):return _domain_hash(b'fable-effect-claim-v1',{k:v[k] for k in CLAIM_FIELDS-{'binding_sha256'}})
def _terminal_hash(v):return _domain_hash(b'fable-effect-terminal-v1',{k:v[k] for k in TERMINAL_FIELDS-{'terminal_sha256'}})
def _claim_binding(v):return {k:v[k] for k in BINDING_FIELDS}
def _validate_claim(v,nonce):
 if type(v) is not dict or set(v)!=CLAIM_FIELDS:raise JournalError('CLAIM_SCHEMA_INVALID')
 if type(v['schema_version']) is not int or v['schema_version']!=1 or v['record_type']!='effect_claim' or v['state']!='SUBMISSION_UNKNOWN':raise JournalError('CLAIM_SCHEMA_INVALID')
 binding=_validate_binding(_claim_binding(v));expected=derive_effect_nonce(binding)
 if nonce!=expected or v['nonce']!=expected or SHA.fullmatch(nonce) is None or v['claim_id']!=CAMPAIGN+'/'+v['job_id']+'/'+nonce or v['binding_sha256']!=_claim_hash(v):raise JournalError('CLAIM_SCHEMA_INVALID')
 return v
def _result_mapping(result):
 if type(result) is not ProviderResultV1:raise JournalError('TERMINAL_RESULT_TYPE_INVALID')
 value=_plain(result.to_mapping())
 if type(value) is not dict or set(value)!=RESULT_FIELDS:raise JournalError('TERMINAL_RESULT_SCHEMA_INVALID')
 try:checked=ProviderResultV1(**value)
 except Exception:raise JournalError('TERMINAL_RESULT_SCHEMA_INVALID') from None
 sealed=_plain(checked.to_mapping());raw=json.dumps(sealed,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
 return sealed,hashlib.sha256(raw).hexdigest()
def _validate_terminal(v,nonce,claim):
 if type(v) is not dict or set(v)!=TERMINAL_FIELDS or type(v['schema_version']) is not int or v['schema_version']!=1 or v['record_type']!='effect_terminal':raise JournalError('TERMINAL_SCHEMA_INVALID')
 if any(type(v[k]) is not str for k in TERMINAL_FIELDS-{'schema_version','sealed_result'}):raise JournalError('TERMINAL_SCHEMA_INVALID')
 if v['nonce']!=nonce or v['claim_id']!=claim['claim_id'] or v['outcome'] not in ('VALID','INVALID') or v['provider']!='claude_host' or v['operation_id']!=claim['operation_id'] or SHA.fullmatch(v['result_sha256']) is None:raise JournalError('TERMINAL_SCHEMA_INVALID')
 if type(v['sealed_result']) is not dict or set(v['sealed_result'])!=RESULT_FIELDS:raise JournalError('TERMINAL_SCHEMA_INVALID')
 try:result=ProviderResultV1(**v['sealed_result'])
 except Exception:raise JournalError('TERMINAL_SCHEMA_INVALID') from None
 sealed,digest=_result_mapping(result)
 expected_outcome='VALID' if result.status.value=='succeeded' and result.submission.value=='definitely_submitted' and result.failure_kind.value=='none' else ('INVALID' if result.status.value=='failed' else None)
 if result.provider.value!='claude_host' or result.operation_id!=claim['operation_id'] or result.phase.value!='terminal' or result.terminal_proof.value!='verified' or expected_outcome!=v['outcome'] or sealed!=v['sealed_result'] or digest!=v['result_sha256'] or v['terminal_sha256']!=_terminal_hash(v):raise JournalError('TERMINAL_SCHEMA_INVALID')
 return v
def _read_at(fd,name):
 f=-1
 try:
  f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd);info=os.fstat(f)
  if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1:raise JournalError('JOURNAL_CUSTODY_INVALID')
  raw=b''
  while len(raw)<=65536:
   chunk=os.read(f,65537-len(raw))
   if not chunk:break
   raw+=chunk
  return _strict(raw)
 except OSError:raise JournalError('JOURNAL_CUSTODY_INVALID') from None
 finally:
  if f>=0:os.close(f)
def _write_at(fd,name,value):
 raw=_canonical(value);f=-1
 try:
  f=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=fd);view=memoryview(raw)
  while view:
   n=os.write(f,view)
   if n<=0:raise JournalError('JOURNAL_WRITE_FAILED')
   view=view[n:]
  os.fsync(f)
 except OSError:raise JournalError('JOURNAL_WRITE_FAILED') from None
 finally:
  if f>=0:os.close(f)
 try:os.fsync(fd)
 except OSError:raise JournalError('JOURNAL_WRITE_FAILED') from None
 return hashlib.sha256(raw).hexdigest()
def _validate_dir_fd(fd):
 info=os.fstat(fd)
 if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700 or info.st_nlink<2:raise JournalError('JOURNAL_DIRECTORY_CUSTODY_INVALID')
 return (info.st_dev,info.st_ino)
class EffectClaim:
 def __init__(self,root,binding):
  self.root_fd=self.dir_fd=-1;self.closed=False
  try:
   self.root=Path(root).resolve();self.root_fd=os.open(self.root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);_validate_dir_fd(self.root_fd)
   try:os.mkdir('effect-claims',0o700,dir_fd=self.root_fd)
   except FileExistsError:pass
   self.dir_fd=os.open('effect-claims',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=self.root_fd);_validate_dir_fd(self.dir_fd);self.binding=_validate_binding(dict(binding));self.nonce=derive_effect_nonce(self.binding);self.claim_name='claim-'+self.nonce+'.json';self.terminal_name='terminal-'+self.nonce+'.json';self._admit()
  except Exception:self.close();raise
 def _entries(self):return sorted(os.listdir(self.dir_fd))
 def _scan(self):
  claims={};terminals={}
  for name in self._entries():
   if name.startswith('claim-') and name.endswith('.json'):
    nonce=name[6:-5]
    if SHA.fullmatch(nonce) is None:raise JournalError('JOURNAL_ENTRY_INVALID')
    claim=_validate_claim(_read_at(self.dir_fd,name),nonce)
    if nonce in claims:raise JournalError('JOURNAL_DUPLICATE_CLAIM')
    claims[nonce]=claim
   elif name.startswith('terminal-') and name.endswith('.json'):
    nonce=name[9:-5]
    if SHA.fullmatch(nonce) is None or nonce in terminals:raise JournalError('JOURNAL_ENTRY_INVALID')
    terminals[nonce]=_read_at(self.dir_fd,name)
   else:raise JournalError('JOURNAL_ENTRY_INVALID')
  if set(terminals)-set(claims):raise JournalError('ORPHAN_TERMINAL')
  for nonce,value in terminals.items():terminals[nonce]=_validate_terminal(value,nonce,claims[nonce])
  return claims,terminals
 def _admit(self):
  claims,terminals=self._scan()
  for nonce,claim in claims.items():
   if nonce not in terminals:raise JournalError('UNRESOLVED_EFFECT_CLAIM')
   if claim['job_id']==self.binding['job_id']:raise JournalError('ONE_SHOT_EFFECT_CLAIMED')
  if self.binding['job_id']==JOBS[1] and not any(c['job_id']==JOBS[0] and terminals.get(n,{}).get('outcome')=='VALID' for n,c in claims.items()):raise JournalError('OFF_TERMINAL_NOT_VALID')
  body={**self.binding,'schema_version':1,'record_type':'effect_claim','state':'SUBMISSION_UNKNOWN','nonce':self.nonce};body['claim_id']=CAMPAIGN+'/'+body['job_id']+'/'+self.nonce;body['binding_sha256']=_claim_hash(body);_validate_claim(body,self.nonce);_write_at(self.dir_fd,self.claim_name,body);self.claim=body
 def terminal(self,outcome,result):
  sealed,digest=_result_mapping(result);body={'schema_version':1,'record_type':'effect_terminal','claim_id':self.claim['claim_id'],'nonce':self.nonce,'outcome':outcome,'provider':'claude_host','operation_id':self.claim['operation_id'],'result_sha256':digest,'sealed_result':sealed};body['terminal_sha256']=_terminal_hash(body);_validate_terminal(body,self.nonce,self.claim);_write_at(self.dir_fd,self.terminal_name,body);return body
 def close(self):
  if self.closed:return
  for fd in (self.dir_fd,self.root_fd):
   if fd>=0:
    try:os.close(fd)
    except OSError:pass
  self.dir_fd=self.root_fd=-1;self.closed=True
 def __enter__(self):return self
 def __exit__(self,*_):self.close()
