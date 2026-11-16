"""Exact source-pinned provider adapters; identity is derived, never caller supplied."""
from __future__ import annotations
import hashlib,json,os,stat
from pathlib import Path
from typing import Any,Dict,Mapping,Optional
from .artifacts import validate_bundle_owner_artifacts
from .bundle import read_attempt_bundle
from .contracts import CELL_BINDINGS,ContractError,PROVIDER_BINDINGS,canonical_bytes,require,strict_json_loads
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.contracts import safe_public as claude_safe_public,validate_evidence as validate_claude_evidence
from shared.job_runtime.candidates.r6_one_off_claude_live_driver_v1.publication import PublicationTrace,publish_owner as claude_publish_owner,publish_public as claude_publish_public
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.custody import FixtureCustody as CodexFixtureCustody
from shared.job_runtime.candidates.r6_one_off_codex_live_driver_v1.publication import AtomicPublisher as CodexAtomicPublisher,validate_public as validate_codex_public
_REPO=Path(__file__).resolve().parents[4]
_MANIFEST=('shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/provider-contracts-v9.json',1998,'1a668419ab622aca992f1792aa730bc29e247322ba554eae6892e20ade51d423')
_READ=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
class AdapterContractError(ContractError):pass
def _read_exact(relative:str,size:int,digest:str)->bytes:
 p=_REPO/relative;fd=-1
 try:
  fd=os.open(p,_READ);meta=os.fstat(fd)
  if not stat.S_ISREG(meta.st_mode) or meta.st_uid!=os.getuid():raise AdapterContractError('PROVIDER_SOURCE_UNSAFE')
  chunks=[]
  while True:
   part=os.read(fd,65536)
   if not part:break
   chunks.append(part)
  raw=b''.join(chunks)
 except OSError:raise AdapterContractError('PROVIDER_SOURCE_OPEN_FAILED') from None
 finally:
  if fd>=0:os.close(fd)
 if (len(raw),hashlib.sha256(raw).hexdigest())!=(size,digest):raise AdapterContractError('PROVIDER_SOURCE_DRIFT')
 return raw
def _manifest()->Mapping[str,Any]:
 raw=_read_exact(*_MANIFEST);value=strict_json_loads(raw.decode('ascii'),'PROVIDER_MANIFEST_JSON')
 require(type(value)is dict and set(value)=={'version','activation','authority','providers'} and value['version']=='r6-data-quality-provider-contracts-v9' and value['activation'] is False and value['authority']=='NONE','PROVIDER_MANIFEST_SHAPE')
 require(type(value['providers'])is dict and set(value['providers'])=={'ARM-A','ARM-B'},'PROVIDER_MANIFEST_PROVIDERS')
 return value
def _contract(label:str)->Mapping[str,Any]:
 value=_manifest()['providers'][label];expected=PROVIDER_BINDINGS[label]
 require(type(value)is dict and set(value)=={'adapter_type','blind_provider_label','provider_schema','publication_driver','sources','research_material_source','research_material_profile_sha256'},'PROVIDER_CONTRACT_SHAPE')
 for key in ('adapter_type','blind_provider_label','provider_schema','publication_driver'):require(value[key]==expected[key],'PROVIDER_CONTRACT_VALUE')
 identity=hashlib.sha256(canonical_bytes(value)).hexdigest();require(identity==expected['publication_driver_identity_sha256'],'PROVIDER_DRIVER_IDENTITY')
 require(type(value['sources'])is list and value['sources'],'PROVIDER_SOURCES')
 for row in value['sources']:
  require(type(row)is dict and set(row)=={'path','bytes','sha256'},'PROVIDER_SOURCE_ROW');_read_exact(row['path'],row['bytes'],row['sha256'])
 material=value['research_material_source'];require(type(material)is dict and set(material)=={'path','bytes','sha256'},'PROVIDER_MATERIAL_SOURCE');_read_exact(material['path'],material['bytes'],material['sha256']);require(type(value['research_material_profile_sha256'])is str and len(value['research_material_profile_sha256'])==64,'PROVIDER_MATERIAL_PROFILE')
 return dict(expected)
def _material_profile(value:Mapping[str,Any])->str:
 normalized=strict_json_loads(canonical_bytes(dict(value)).decode('ascii'),'PROVIDER_MATERIAL_JSON')
 require(type(normalized)is dict and set(normalized)=={'sanitized_output','factual_evidence','source_inventory','citation_inventory'},'PROVIDER_MATERIAL_SHAPE')
 for name,body in normalized.items():
  require(type(body)is dict,'PROVIDER_MATERIAL_BODY')
  for key in ('binding','provider_terminal','raw_sha256','publication_artifact_sha256'):body.pop(key,None)
  if name=='sanitized_output':body.pop('answer',None);body.pop('complete',None)
  if name=='source_inventory':
   for source in body.get('sources',[]):source.pop('source_cutoff_sha256',None)
 return hashlib.sha256(canonical_bytes(normalized)).hexdigest()
def _validate_material(label:str,value:Mapping[str,Any])->None:
 contract=_manifest()['providers'][label];require(_material_profile(value)==contract['research_material_profile_sha256'],'PROVIDER_RESEARCH_MATERIAL_MISMATCH')
class PrimitiveAdapter:
 __slots__=()
 def __new__(cls,*args:Any,**kwargs:Any):
  if cls is PrimitiveAdapter:raise AdapterContractError('ARBITRARY_PROVIDER_ADAPTER_FORBIDDEN')
  return super().__new__(cls)
class ClaudeAttemptAdapterV9(PrimitiveAdapter):
 __slots__=('owner_root','public_root','trace','capture_digest_fault','owner_tamper_on_publish')
 def __init__(self,owner_root:Path,public_root:Path,trace:Optional[Any]=None,capture_digest_fault:bool=False,owner_tamper_on_publish:bool=False)->None:
  self.owner_root=Path(owner_root);self.public_root=Path(public_root);self.owner_root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(self.owner_root,0o700);self.trace=trace or PublicationTrace();self.capture_digest_fault=capture_digest_fault;self.owner_tamper_on_publish=owner_tamper_on_publish
 def validate_publication(self,value:Mapping[str,Any])->None:
  artifact=dict(value);validate_claude_evidence(artifact);claude_safe_public(artifact)
 def validate_research_material(self,value:Mapping[str,Any])->None:_validate_material('ARM-A',value)
 def capture(self,name:str,raw:bytes)->Mapping[str,Any]:
  final=claude_publish_owner(self.owner_root/name,{'provider-terminal.raw':raw},self.trace);digest=hashlib.sha256(raw).hexdigest();return {'name':name+'/'+final+'/provider-terminal.raw','bytes':len(raw),'sha256':'0'*64 if self.capture_digest_fault else digest,'owner_private':True,'public':False}
 def publish_committed(self,name:str,path:Path,digest:str)->Mapping[str,Any]:
  artifact=_artifact(self,name,path,digest)
  return {'provider_receipt':claude_publish_public(self.public_root/name,artifact,self.trace),'provider_schema':'claude-evidence-v1'}
class CodexAttemptAdapterV9(PrimitiveAdapter):
 __slots__=('owner_root','public_root','publisher','custody','capture_digest_fault','owner_tamper_on_publish')
 def __init__(self,owner_root:Path,public_root:Path,publication_fault:Optional[str]=None,capture_digest_fault:bool=False,owner_tamper_on_publish:bool=False)->None:
  self.owner_root=Path(owner_root);self.public_root=Path(public_root);self.owner_root.mkdir(mode=0o700,parents=True,exist_ok=True);self.public_root.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(self.owner_root,0o700);os.chmod(self.public_root,0o700);self.publisher=CodexAtomicPublisher(self.public_root,fault=publication_fault);self.custody={};self.capture_digest_fault=capture_digest_fault;self.owner_tamper_on_publish=owner_tamper_on_publish
 def validate_publication(self,value:Mapping[str,Any])->None:validate_codex_public(dict(value))
 def validate_research_material(self,value:Mapping[str,Any])->None:_validate_material('ARM-B',value)
 def capture(self,name:str,raw:bytes)->Mapping[str,Any]:
  item=CodexFixtureCustody(self.owner_root,name);self.custody[name]=item;desc=dict(item.write_private('provider-terminal.raw',raw));desc['name']=name+'/provider-terminal.raw'
  if self.capture_digest_fault:desc['sha256']='0'*64
  return desc
 def publish_committed(self,name:str,path:Path,digest:str)->Mapping[str,Any]:
  artifact=_artifact(self,name,path,digest);return self.publisher.publish(name+'-stage-b-execution-v3',artifact)
def provider_identity_for_adapter(adapter:Any,cell_id:str)->Mapping[str,Any]:
 require(cell_id in CELL_BINDINGS,'CELL_ID_INVALID');label=CELL_BINDINGS[cell_id][0];expected_type=ClaudeAttemptAdapterV9 if label=='ARM-A' else CodexAttemptAdapterV9
 require(type(adapter)is expected_type,'PROVIDER_ADAPTER_TYPE_MISMATCH');contract=_contract(label);require(contract['adapter_type']==type(adapter).__name__,'PROVIDER_ADAPTER_TYPE_IDENTITY');return contract
def _artifact(adapter:Any,name:str,path:Path,digest:str)->Dict[str,Any]:
 identity=provider_identity_for_adapter(adapter,read_attempt_bundle(path,digest)['key']['cell_id']);bundle=read_attempt_bundle(path,digest);validate_bundle_owner_artifacts(adapter.owner_root,bundle)
 require(name==bundle['key_digest'],'BUNDLE_PUBLICATION_NAME_MISMATCH');require(bundle['provider_identity']==identity,'BUNDLE_PROVIDER_IDENTITY_INVALID');ref=bundle['publication_artifact_ref'];require(ref['provider_schema']==identity['provider_schema'] and ref['publication_driver_identity_sha256']==identity['publication_driver_identity_sha256'] and ref['provider_validated'] is True,'BUNDLE_PROVIDER_ARTIFACT_INVALID')
 if adapter.owner_tamper_on_publish:
  target=adapter.owner_root/bundle['research_evidence']['sanitized_output']['ref']['relative_ref'];target.write_bytes(b'{}');os.chmod(target,0o600);validate_bundle_owner_artifacts(adapter.owner_root,bundle)
 value=strict_json_loads(bundle['provider_publication_artifact_body'],'BUNDLE_PROVIDER_ARTIFACT_JSON');adapter.validate_publication(value);return dict(value)
def claude_adapter(owner_root:Path,public_root:Path,trace:Any=None,*,capture_digest_fault:bool=False,owner_tamper_on_publish:bool=False)->ClaudeAttemptAdapterV9:return ClaudeAttemptAdapterV9(owner_root,public_root,trace,capture_digest_fault,owner_tamper_on_publish)
def codex_adapter(owner_root:Path,public_root:Path,publication_fault:Optional[str]=None,*,capture_digest_fault:bool=False,owner_tamper_on_publish:bool=False)->CodexAttemptAdapterV9:return CodexAttemptAdapterV9(owner_root,public_root,publication_fault,capture_digest_fault,owner_tamper_on_publish)
__all__=['AdapterContractError','PrimitiveAdapter','ClaudeAttemptAdapterV9','CodexAttemptAdapterV9','claude_adapter','codex_adapter','provider_identity_for_adapter']
