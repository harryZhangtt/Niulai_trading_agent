"""Duplicate-safe bounded probe parser layered on the fixed v7 boundary."""
import hashlib
from pathlib import Path
import stat
from typing import Any
from factor.docker.local.v4 import launcher as v4
from factor.docker.local.v7 import launcher as v7
PACKAGE=Path(__file__).resolve().parent;PROFILE_PATH=PACKAGE/'runtime-profile-v8.json';EXPECTED_WORKSPACE=Path('/Users/bytedance/Desktop/Trading Agent');CAPABILITY='factor-local-v8-start';MAX_BYTES=65536
EXPECTED={'v7_tree_sha256':'2d9466813177b413e7edee69940dab6f163cb3b25c39708d3e19c0af6231a97a','v7_profile_physical_sha256':'233083d45ceaed20fbbddf7186a1ecdcfe15f265f86a1a1fead54af15979ce2c','v7_profile_canonical_sha256':'df8e9753ccdcae42341aee61644c1a876df3a82fef7d08c42dbd6737b2366c8a'}
class V8ContractError(ValueError):pass
def require(x,c):
 if not x:raise V8ContractError(c)
def load(path):
 try:return v4.loads_strict(Path(path).read_bytes())
 except Exception:raise V8ContractError('V8_JSON') from None
def digest(v):return hashlib.sha256(v4.canonical(v)).hexdigest()
def tree(root):
 h=hashlib.sha256()
 for p in sorted(x for x in root.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix!='.pyc'):
  rel=p.relative_to(root).as_posix();h.update(rel.encode());h.update(b'\0');h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode());h.update(b'\n')
 return h.hexdigest()
def validate_profile(v,w):
 s=load(PACKAGE/'runtime-profile-v8.schema.json')
 try:v4.validate_schema_value(v,{'const':s['const']})
 except Exception:raise V8ContractError('V8_SCHEMA') from None
 w=v4.validate_workspace(w);require(v['status']=='selected-disabled' and v['runnable'] is False and v['apply_allowed'] is False,'V8_FENCE');require(v['predecessors']==EXPECTED,'V8_BINDING');require(tree(w/'factor/docker/local/v7')==EXPECTED['v7_tree_sha256'],'V8_V7_TREE')
 raw=(w/'factor/docker/local/v7/runtime-profile-v7.json').read_bytes();require(hashlib.sha256(raw).hexdigest()==EXPECTED['v7_profile_physical_sha256'] and digest(v4.loads_strict(raw))==EXPECTED['v7_profile_canonical_sha256'],'V8_V7_PROFILE');return v
def _strict(raw:bytes,label:str)->Any:
 require(type(raw) is bytes and 0<len(raw)<=MAX_BYTES,'V8_'+label+'_SIZE')
 try:return v4.loads_strict(raw)
 except v4.V4ContractError as exc:raise V8ContractError('V8_'+label+'_'+str(exc).replace('V4_','')) from None
def _probe(env,host_home,before):
 c=v7._command([v7.v6.COLIMA,'status','factor-mining','--json'],env,'/',30);d=v7._command([v7.v6.DOCKER,'--config',env['DOCKER_CONFIG'],'context','inspect','colima-factor-mining','--format','json'],{'HOME':env['HOME'],'PATH':v7.v6.PATH_VALUE},'/',30);require(c.returncode==0 and d.returncode==0,'V8_PROBE_RC')
 cv=_strict(c.stdout,'COLIMA');dv=_strict(d.stdout,'DOCKER');require(type(cv) is dict and set(cv)=={'profile','status'} and cv=={'profile':'factor-mining','status':'Running'},'V8_COLIMA_STATUS')
 if type(dv) is list:require(len(dv)==1 and type(dv[0]) is dict,'V8_CONTEXT_SHAPE');dv=dv[0]
 require(type(dv) is dict,'V8_CONTEXT_SHAPE');endpoint=dv.get('Endpoints',{}).get('docker',{}).get('Host');require(type(endpoint) is str and endpoint.startswith('unix://'),'V8_ENDPOINT');raw=endpoint[7:];require('..' not in Path(raw).parts,'V8_ENDPOINT_TRAVERSAL');sock=Path(raw);require(sock.is_absolute(),'V8_ENDPOINT_ABSOLUTE')
 try:resolved=sock.resolve(strict=True);home=Path(env['COLIMA_HOME']).resolve(strict=True);resolved.relative_to(home)
 except (OSError,ValueError):raise V8ContractError('V8_ENDPOINT_CONTAINMENT') from None
 require(stat.S_ISSOCK(resolved.stat().st_mode),'V8_ENDPOINT_NOT_SOCKET');after=v7._global(host_home);return {'profile':'factor-mining','running':True,'context':'colima-factor-mining','endpoint':str(resolved),'global_context_before':before,'global_context_after':after}
def _activate_for_test(w,runner,probe,glob,before_spawn=None):return v7._txn(w,runner,probe,glob,before_spawn)
def activate(w,*,apply=False,capability=None,parent_approved=False):
 w=v4.validate_workspace(w);p=validate_profile(load(PROFILE_PATH),w)
 if not apply:return {'status':'selected-disabled','apply_allowed':False,'profile_sha256':digest(p)}
 require(parent_approved is True and capability==CAPABILITY,'V8_UNAUTHORIZED');return v7._txn(w,v7._run_colima,_probe,v7._global)
