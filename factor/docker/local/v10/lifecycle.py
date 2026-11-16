"""Host-owned, receipt-first health-only Docker lifecycle."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any, Callable
from factor.docker.local.v4 import launcher as v4

ROOT=Path(__file__).resolve().parents[4]; PACKAGE=Path(__file__).resolve().parent
PROFILE_PATH=PACKAGE/'runtime-profile-v10.json'; CONTEXT_PATH=PACKAGE/'build-context.json'
DOCKER=Path('/opt/homebrew/bin/docker'); DOCKER_CONFIG=ROOT/'factor/runtime/local/docker-config'
CAPABILITY='factor-local-health-v10-run'; IMAGE_ID=re.compile(r'sha256:[a-f0-9]{64}\Z')
class LifecycleError(ValueError):pass
def require(x,c):
 if not x:raise LifecycleError(c)
def load(path):
 try:return v4.loads_strict(Path(path).read_bytes())
 except Exception:raise LifecycleError('V10_JSON') from None
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(canonical(v)).hexdigest()
def validate_profile(v):
 schema=load(PACKAGE/'runtime-profile-v10.schema.json');require(type(schema) is dict and schema.get('const')==v,'V10_PROFILE_SCHEMA')
 require(v['status']=='selected-disabled' and v['runnable'] is False and v['apply_allowed'] is False,'V10_FENCE')
 context=load(CONTEXT_PATH);require(v['image']['build_context']=='build-context.json','V10_CONTEXT_REF')
 for name,want in context['files'].items():require(hashlib.sha256((PACKAGE/name).read_bytes()).hexdigest()==want,'V10_CONTEXT_DRIFT')
 require(v['container']['mounts']==[] and v['container']['secrets']==[] and v['container']['docker_socket'] is False and v['container']['network']=='none','V10_ISOLATION')
 return v
def base():return [str(DOCKER),'--config',str(DOCKER_CONFIG),'--context','colima-factor-mining']
def commands(profile,image_id=None):
 p=profile;b=base();pkg=str(PACKAGE)
 pull=b+['pull','--platform','linux/arm64',p['image']['pull_reference']]
 build=b+['build','--pull=false','--platform','linux/arm64','--file',str(PACKAGE/'health.Dockerfile'),'--tag',p['image']['tag'],pkg]
 inspect=b+['image','inspect',p['image']['tag'],'--format','{{.Id}}']
 result={'pull':pull,'build':build,'inspect-image':inspect}
 if image_id:
  c=p['container']; create=b+['create','--name',c['name'],'--network','none','--read-only','--user',c['user'],'--cap-drop','ALL','--security-opt','no-new-privileges=true','--pids-limit',str(c['pids_limit']),'--cpus',c['cpus'],'--memory',c['memory'],'--memory-swap',c['memory_swap'],'--restart','no','--log-driver','local','--log-opt','max-size=10m','--log-opt','max-file=3','--label','local.factor.kind=health','--label','local.factor.profile=v10']
  for item in c['tmpfs']:create+=['--tmpfs',item]
  create+=[image_id,'health'];result.update({'create':create,'inspect-container':b+['container','inspect',c['name']],'start':b+['start',c['name']],'wait':b+['wait',c['name']],'logs':b+['logs','--timestamps',c['name']],'inspect-terminal':b+['container','inspect',c['name']],'remove':b+['rm',c['name']]})
 return result
def _run(argv,timeout=120):return subprocess.run(argv,env={'HOME':str(ROOT/'factor/runtime/local/home'),'PATH':'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin','DOCKER_CONFIG':str(DOCKER_CONFIG)},cwd=ROOT,shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=False)
def _write_receipt(path,value):
 require(path.is_absolute() and path.parent.resolve()==(ROOT/'factor/runtime/local').resolve(),'V10_RECEIPT_PATH')
 raw=(json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode();fd,tmp=tempfile.mkstemp(prefix='.health-',dir=path.parent)
 try:
  os.fchmod(fd,0o600);os.write(fd,raw);os.fsync(fd);os.close(fd);os.replace(tmp,path)
 finally:
  try:os.close(fd)
  except OSError:pass
  try:os.unlink(tmp)
  except OSError:pass
def _execute(runner:Callable,receipt_path:Path):
 p=validate_profile(load(PROFILE_PATH));cmd=commands(p);created=False;image_id=None;records=[];status='failed';code='V10_PRECREATE_FAILED'
 try:
  for step in ('pull','build','inspect-image'):
   r=runner(cmd[step],300);records.append({'step':step,'returncode':r.returncode});require(r.returncode==0,'V10_'+step.upper().replace('-','_'))
   if step=='inspect-image':image_id=r.stdout.decode('ascii','strict').strip();require(IMAGE_ID.fullmatch(image_id),'V10_IMAGE_ID')
  cmd=commands(p,image_id);r=runner(cmd['create'],60);records.append({'step':'create','returncode':r.returncode});require(r.returncode==0,'V10_CREATE');created=True
  for step in ('inspect-container','start','wait','logs','inspect-terminal'):
   r=runner(cmd[step],180);records.append({'step':step,'returncode':r.returncode})
   if r.returncode!=0:raise LifecycleError('V10_POSTCREATE_UNKNOWN')
   if step=='wait':require(r.stdout.decode('ascii','strict').strip()=='0','V10_HEALTH_EXIT')
  status='success';code='V10_HEALTH_VERIFIED'
 except (subprocess.TimeoutExpired,UnicodeError,OSError):
  if created:status='unknown';code='V10_POSTCREATE_UNKNOWN'
 except LifecycleError as exc:
  if created and str(exc)!='V10_HEALTH_EXIT':status='unknown';code='V10_POSTCREATE_UNKNOWN'
  else:code=str(exc)
 receipt={'schema_version':1,'kind':'factor_local_health_receipt','status':status,'code':code,'retry_allowed':False,'created':created,'image_id':image_id,'records':records,'profile_sha256':digest(p)}
 _write_receipt(receipt_path,receipt)
 if created and status in ('success','failed'):
  rr=runner(cmd['remove'],60);receipt['remove_returncode']=rr.returncode;_write_receipt(receipt_path,receipt)
 return receipt
def execute(*,apply=False,capability=None,parent_approved=False,receipt_path=None):
 p=validate_profile(load(PROFILE_PATH))
 if not apply:return {'status':'selected-disabled','apply_allowed':False,'profile_sha256':digest(p),'commands':commands(p)}
 require(capability==CAPABILITY and parent_approved is True and isinstance(receipt_path,Path),'V10_UNAUTHORIZED')
 return _execute(_run,receipt_path)
def _execute_for_test(runner,receipt_path):return _execute(runner,receipt_path)
