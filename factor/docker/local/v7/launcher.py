"""Strict fixed Colima activation boundary v7."""
import fcntl,hashlib,json,os
from pathlib import Path
import selectors,signal,socket,stat,subprocess,time
from types import SimpleNamespace
from typing import Any,Callable
from factor.docker.local.v4 import launcher as v4
from factor.docker.local.v6 import launcher as v6
PACKAGE=Path(__file__).resolve().parent;PROFILE_PATH=PACKAGE/'runtime-profile-v7.json';EXPECTED_WORKSPACE=Path('/Users/bytedance/Desktop/Trading Agent');CAPABILITY='factor-local-v7-start';MAX_OUTPUT=65536
EXPECTED={'v6_tree_sha256':'89c934d199e1f58b2bfb5555ff69de3492bd9d3cddb65a97fd894918dccb60c0','v6_profile_physical_sha256':'69f798bbb7d2e14d4dae30fbc14daa223cadfd9ddac718d731cbcdc8341608bf','v6_profile_canonical_sha256':'051ad335925083a3325f02e8edbe023d35552dc88058c89253350123a18ab7c7','v5_tree_sha256':'990d35326ac4624b8d736f2475e96da0de01fac5b100f03973aea7ef94f2bd74','v4_profile_canonical_sha256':'5be9d1827441ba81c8d30beac9ee1090a2866320141940b526997bcf7e8a6407','v2_receipt_canonical_sha256':'c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327','v2_profile_canonical_sha256':'40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d'}
class V7ContractError(ValueError):pass
class ActivationTimeout(Exception):pass
def require(x,c):
 if not x:raise V7ContractError(c)
def load(path):
 try:return v4.loads_strict(Path(path).read_bytes())
 except Exception:raise V7ContractError('V7_JSON') from None
def digest(v):return hashlib.sha256(v4.canonical(v)).hexdigest()
def tree(root):
 h=hashlib.sha256()
 for p in sorted(x for x in root.rglob('*') if x.is_file() and '__pycache__' not in x.parts and x.suffix!='.pyc'):
  rel=p.relative_to(root).as_posix();h.update(rel.encode());h.update(b'\0');h.update(hashlib.sha256(p.read_bytes()).hexdigest().encode());h.update(b'\n')
 return h.hexdigest()
def validate_profile(v,w):
 s=load(PACKAGE/'runtime-profile-v7.schema.json')
 try:v4.validate_schema_value(v,{'const':s['const']})
 except Exception:raise V7ContractError('V7_SCHEMA') from None
 w=v4.validate_workspace(w);require(v['status']=='selected-disabled' and v['runnable'] is False and v['apply_allowed'] is False,'V7_FENCE');require(v['predecessors']==EXPECTED,'V7_BINDING')
 require(tree(w/'factor/docker/local/v6')==EXPECTED['v6_tree_sha256'],'V7_V6_TREE')
 raw=(w/'factor/docker/local/v6/runtime-profile-v6.json').read_bytes();require(hashlib.sha256(raw).hexdigest()==EXPECTED['v6_profile_physical_sha256'] and digest(v4.loads_strict(raw))==EXPECTED['v6_profile_canonical_sha256'],'V7_V6_PROFILE')
 require(tree(w/'factor/docker/local/v5')==EXPECTED['v5_tree_sha256'],'V7_V5_TREE')
 require(digest(load(w/'factor/docker/local/v4/runtime-profile-v4.json'))==EXPECTED['v4_profile_canonical_sha256'],'V7_V4')
 require(digest(load(w/'factor/docker/local/v2/installation-receipt.json'))==EXPECTED['v2_receipt_canonical_sha256'] and digest(load(w/'factor/docker/local/v2/runtime-profile-v2.json'))==EXPECTED['v2_profile_canonical_sha256'],'V7_V2')
 return v
def _command(argv,env,cwd,timeout):
 p=subprocess.Popen(argv,env=env,cwd=cwd,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 sel=selectors.DefaultSelector();buffers={p.stdout:bytearray(),p.stderr:bytearray()};deadline=time.monotonic()+timeout
 try:
  for stream in buffers:os.set_blocking(stream.fileno(),False);sel.register(stream,selectors.EVENT_READ)
  while sel.get_map():
   if time.monotonic()>=deadline:
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    p.wait(timeout=5);raise V7ContractError('V7_PROBE_TIMEOUT')
   for key,_ in sel.select(min(.1,max(0,deadline-time.monotonic()))):
    chunk=os.read(key.fileobj.fileno(),4096)
    if not chunk:sel.unregister(key.fileobj);continue
    buffers[key.fileobj].extend(chunk)
    if len(buffers[key.fileobj])>MAX_OUTPUT:
     try:os.killpg(p.pid,signal.SIGKILL)
     except ProcessLookupError:pass
     p.wait(timeout=5);raise V7ContractError('V7_OUTPUT_BOUND')
  rc=p.wait(timeout=5);return SimpleNamespace(returncode=rc,stdout=bytes(buffers[p.stdout]),stderr=bytes(buffers[p.stderr]))
 finally:
  sel.close()
  for stream in buffers:
   if stream is not None:stream.close()
def _run_colima(argv,env,workspace,timeout,grace):
 p=subprocess.Popen(argv,env=env,cwd=workspace,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 try:return {'returncode':p.wait(timeout=timeout),'timed_out':False}
 except subprocess.TimeoutExpired:
  try:os.killpg(p.pid,signal.SIGTERM)
  except ProcessLookupError:pass
  try:p.wait(timeout=grace)
  except subprocess.TimeoutExpired:pass
  try:os.killpg(p.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  try:p.wait(timeout=grace)
  except subprocess.TimeoutExpired:raise ActivationTimeout('leader-unreaped')
  return {'returncode':None,'timed_out':True}
def _global(home):
 r=_command([v6.DOCKER,'context','show'],{'HOME':home,'PATH':v6.PATH_VALUE},'/',15);require(r.returncode==0,'V7_GLOBAL_RC');value=r.stdout.decode('utf-8','strict').strip();require(value and '\n' not in value,'V7_GLOBAL_VALUE');return value
def _probe(env,host_home,before):
 c=_command([v6.COLIMA,'status','factor-mining','--json'],env,'/',30);d=_command([v6.DOCKER,'--config',env['DOCKER_CONFIG'],'context','inspect','colima-factor-mining','--format','json'],{'HOME':env['HOME'],'PATH':v6.PATH_VALUE},'/',30);require(c.returncode==0 and d.returncode==0,'V7_PROBE_RC')
 try:cv=json.loads(c.stdout);dv=json.loads(d.stdout)
 except (json.JSONDecodeError,UnicodeError):raise V7ContractError('V7_PROBE_JSON') from None
 require(type(cv) is dict and set(cv)=={'profile','status'} and cv=={'profile':'factor-mining','status':'Running'},'V7_COLIMA_STATUS')
 if type(dv) is list:require(len(dv)==1 and type(dv[0]) is dict,'V7_CONTEXT_SHAPE');dv=dv[0]
 require(type(dv) is dict,'V7_CONTEXT_SHAPE');endpoint=dv.get('Endpoints',{}).get('docker',{}).get('Host');require(type(endpoint) is str and endpoint.startswith('unix://'),'V7_ENDPOINT')
 raw=endpoint[7:];require('..' not in Path(raw).parts,'V7_ENDPOINT_TRAVERSAL');sock=Path(raw);require(sock.is_absolute(),'V7_ENDPOINT_ABSOLUTE')
 try:resolved=sock.resolve(strict=True);home=Path(env['COLIMA_HOME']).resolve(strict=True);resolved.relative_to(home)
 except (OSError,ValueError):raise V7ContractError('V7_ENDPOINT_CONTAINMENT') from None
 require(stat.S_ISSOCK(resolved.stat().st_mode),'V7_ENDPOINT_NOT_SOCKET');after=_global(host_home)
 return {'profile':'factor-mining','running':True,'context':'colima-factor-mining','endpoint':str(resolved),'global_context_before':before,'global_context_after':after}
def _valid(s,env):
 return type(s) is dict and s.get('profile')=='factor-mining' and s.get('running') is True and s.get('context')=='colima-factor-mining' and s.get('global_context_before')==s.get('global_context_after') and type(s.get('global_context_before')) is str
def _txn(w,runner,probe,glob,before_spawn=None):
 w=v4.validate_workspace(w);p=validate_profile(load(PROFILE_PATH),w);created=[];roots={};lock=-1;lid=None;wfd=os.open(w,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);wm=os.fstat(wfd);wid=(wm.st_dev,wm.st_ino);host=os.path.expanduser('~')
 try:
  before=glob(host);lock,lid=v6._open_lock(wfd);roots,ids=v6._roots(wfd,w,created)
  if before_spawn:before_spawn(w)
  v6._revalidate(w,wfd,wid,roots,ids)
  try:result=runner(v6.START_ARGV,v6._env(w),w,600,10)
  except ActivationTimeout:return v6._receipt('unknown','V6_TIMEOUT_UNKNOWN',created,created,False,True,None)
  if result['timed_out']:return v6._receipt('unknown','V6_TIMEOUT_UNKNOWN',created,created,False,True,None)
  try:s=probe(v6._env(w),host,before)
  except Exception:s=None
  if result['returncode']==0 and _valid(s,v6._env(w)):return v6._receipt('success','V6_STARTED_RECONCILED',created,created,False,False,0)
  if type(s) is dict and s.get('running') is False:
   clean=v6._cleanup(created);return v6._receipt('failed','V6_FAILED_NO_VM',created,[] if clean else created,clean,False,result['returncode'])
  return v6._receipt('unknown','V6_STATUS_UNKNOWN',created,created,False,False,result['returncode'])
 except (Exception,):
  clean=v6._cleanup(created);return v6._receipt('failed','V6_PRESPAWN_FAILED',created,[] if clean else created,clean,False,None)
 finally:
  for fd in roots.values():os.close(fd)
  if lock>=0:fcntl.flock(lock,fcntl.LOCK_UN);os.close(lock)
  os.close(wfd)
  if lid:
   try:
    lp=w/v6.LOCK_RELATIVE;lm=lp.lstat()
    if stat.S_ISREG(lm.st_mode) and (lm.st_dev,lm.st_ino)==lid:lp.unlink()
   except OSError:pass
def _activate_for_test(w,runner,probe,glob,before_spawn=None):return _txn(w,runner,probe,glob,before_spawn)
def activate(w,*,apply=False,capability=None,parent_approved=False):
 w=v4.validate_workspace(w);p=validate_profile(load(PROFILE_PATH),w)
 if not apply:return {'status':'selected-disabled','apply_allowed':False,'profile_sha256':digest(p)}
 require(parent_approved is True and capability=='factor-local-v7-start','V7_UNAUTHORIZED');return _txn(w,_run_colima,_probe,_global)
