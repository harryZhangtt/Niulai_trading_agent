"""Read-only reconciliation for the existing Colima factor-mining VM."""
from __future__ import annotations
import hashlib, json, os, stat, subprocess
from pathlib import Path
from typing import Any, Callable
from factor.docker.local.v4 import launcher as v4

WORKSPACE=Path('/Users/bytedance/Desktop/Trading Agent')
COLIMA=Path('/opt/homebrew/bin/colima'); DOCKER=Path('/opt/homebrew/bin/docker')
COLIMA_HOME=WORKSPACE/'.c'; CACHE=WORKSPACE/'factor/runtime/local/colima-cache'
DOCKER_CONFIG=WORKSPACE/'factor/runtime/local/docker-config'; HOME=WORKSPACE/'factor/runtime/local/home'
PATH_VALUE='/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'; MAX=256*1024
class ReconcileError(ValueError): pass
def require(x,c):
 if not x: raise ReconcileError(c)
def strict(raw:bytes)->Any:
 require(type(raw) is bytes and 0<len(raw)<=MAX,'V9_OUTPUT_SIZE')
 try:return v4.loads_strict(raw)
 except Exception:raise ReconcileError('V9_OUTPUT_JSON') from None
def run(argv:list[str],env:dict[str,str],timeout:int=30):
 return subprocess.run(argv,env=env,cwd=WORKSPACE,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=False)
def env()->dict[str,str]:return {'HOME':str(HOME),'PATH':PATH_VALUE,'COLIMA_HOME':str(COLIMA_HOME),'COLIMA_CACHE_HOME':str(CACHE),'COLIMA_PROFILE':'factor-mining','DOCKER_CONFIG':str(DOCKER_CONFIG)}
def global_context(runner=run)->str:
 try:r=runner([str(DOCKER),'context','show'],dict(os.environ),30)
 except Exception:raise ReconcileError('V9_GLOBAL_EXECUTION') from None
 require(r.returncode==0,'V9_GLOBAL_RC')
 try:v=r.stdout.decode('utf-8','strict').strip()
 except (AttributeError,UnicodeError):raise ReconcileError('V9_GLOBAL_VALUE') from None
 require(v and '\n' not in v,'V9_GLOBAL_VALUE');return v
def beneath(path:Path,root:Path,kind:str)->Path:
 require(path.is_absolute() and '..' not in path.parts,'V9_'+kind+'_PATH')
 try:p=path.resolve(strict=True);r=root.resolve(strict=True);p.relative_to(r)
 except (OSError,ValueError):raise ReconcileError('V9_'+kind+'_CONTAINMENT') from None
 return p
def beneath_optional(path:Path,root:Path,kind:str)->Path:
 require(path.is_absolute() and '..' not in path.parts,'V9_'+kind+'_PATH')
 try:
  r=root.resolve(strict=True);cursor=path
  while not cursor.exists():
   require(cursor.parent!=cursor,'V9_'+kind+'_CONTAINMENT');cursor=cursor.parent
  cursor.resolve(strict=True).relative_to(r)
 except (OSError,ValueError):raise ReconcileError('V9_'+kind+'_CONTAINMENT') from None
 return path
def reconcile(runner:Callable=run)->dict[str,Any]:
 before=global_context(runner);e=env()
 try:
  c=runner([str(COLIMA),'status','factor-mining','--json'],e,30)
  d=runner([str(DOCKER),'--config',str(DOCKER_CONFIG),'context','inspect','colima-factor-mining','--format','json'],{'HOME':str(HOME),'PATH':PATH_VALUE},30)
  i=runner([str(DOCKER),'--config',str(DOCKER_CONFIG),'--context','colima-factor-mining','info','--format','{{json .}}'],{'HOME':str(HOME),'PATH':PATH_VALUE},60)
 except Exception:raise ReconcileError('V9_PROBE_EXECUTION') from None
 require(c.returncode==d.returncode==i.returncode==0,'V9_PROBE_RC')
 cv,dv,iv=strict(c.stdout),strict(d.stdout),strict(i.stdout)
 require(type(cv) is dict and cv.get('display_name')=='colima [profile=factor-mining]' and cv.get('driver')=='macOS Virtualization.Framework' and cv.get('arch')=='aarch64' and cv.get('runtime')=='docker' and cv.get('mount_type')=='virtiofs' and type(cv.get('docker_socket')) is str and type(cv.get('containerd_socket')) is str and cv.get('kubernetes') is False and type(cv.get('cpu')) is int and cv.get('cpu')==6 and type(cv.get('memory')) is int and cv.get('memory')==12884901888 and type(cv.get('disk')) is int and cv.get('disk')==42949672960,'V9_COLIMA_STATUS')
 require(type(dv) is list and len(dv)==1 and type(dv[0]) is dict,'V9_CONTEXT_SHAPE');ctx=dv[0]
 require(ctx.get('Name')=='colima-factor-mining','V9_CONTEXT_NAME');endpoint=ctx.get('Endpoints',{}).get('docker',{}).get('Host');require(type(endpoint) is str and endpoint.startswith('unix://'),'V9_ENDPOINT')
 sock=beneath(Path(endpoint[7:]),COLIMA_HOME,'SOCKET');require(stat.S_ISSOCK(sock.stat().st_mode) and cv['docker_socket']==endpoint,'V9_SOCKET_TYPE')
 containerd=beneath(Path(cv['containerd_socket'][7:]) if cv['containerd_socket'].startswith('unix://') else Path(cv['containerd_socket']),COLIMA_HOME,'CONTAINERD');require(stat.S_ISSOCK(containerd.stat().st_mode),'V9_CONTAINERD_TYPE')
 storage=ctx.get('Storage',{});require(type(storage) is dict,'V9_STORAGE_SHAPE');meta=beneath(Path(storage.get('MetadataPath','')),DOCKER_CONFIG,'METADATA');tls=beneath_optional(Path(storage.get('TLSPath','')),DOCKER_CONFIG,'TLS')
 require(type(iv) is dict and iv.get('Name')=='colima-factor-mining' and type(iv.get('NCPU')) is int and iv.get('NCPU')==6 and type(iv.get('MemTotal')) is int and 11*1024**3<=iv.get('MemTotal')<=12*1024**3 and type(iv.get('Containers')) is int and iv.get('Containers')==0 and type(iv.get('Images')) is int and iv.get('Images')==0 and iv.get('PidsLimit') is True and iv.get('MemoryLimit') is True and iv.get('SwapLimit') is True and iv.get('CPUShares') is True and iv.get('CgroupVersion')=='2','V9_ENGINE_INFO')
 after=global_context(runner);require(before==after,'V9_GLOBAL_CONTEXT_DRIFT')
 evidence={'colima':cv,'context':ctx,'engine':{k:iv[k] for k in ('Name','NCPU','MemTotal','Containers','Images','PidsLimit','MemoryLimit','SwapLimit','CPUShares','CgroupVersion')},'global_context':before,'socket':str(sock),'metadata':str(meta)}
 return {'schema_version':1,'status':'reconciled-running','profile':'factor-mining','retry_allowed':False,'evidence_sha256':hashlib.sha256(json.dumps(evidence,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'evidence':evidence}
def main()->int:
 try:print(json.dumps(reconcile(),sort_keys=True,separators=(',',':')));return 0
 except ReconcileError as x:print(json.dumps({'status':'reconcile-failed','code':str(x)},sort_keys=True,separators=(',',':')));return 2
 except Exception:print(json.dumps({'status':'reconcile-failed','code':'V9_INTERNAL_FAILURE'},sort_keys=True,separators=(',',':')));return 2
if __name__=='__main__':raise SystemExit(main())
