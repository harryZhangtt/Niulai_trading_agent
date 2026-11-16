"""Fixed one-shot Colima activation with post-spawn reconciliation.

The public API has no runner/probe injection. Tests use the private
``_activate_for_test`` seam and never invoke Colima or Docker.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import time
from typing import Any, Callable

from factor.docker.local.v4 import launcher as v4
from factor.docker.local.v5 import launcher as v5

PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "runtime-profile-v6.json"
EXPECTED_WORKSPACE = Path("/Users/bytedance/Desktop/Trading Agent")
CAPABILITY = "factor-local-v6-start"
LOCK_RELATIVE = Path(".factor-colima-activation.lock")
PATH_VALUE = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
ROOTS = {
    "COLIMA_HOME": Path(".c"),
    "COLIMA_CACHE_HOME": Path("factor/runtime/local/colima-cache"),
    "DOCKER_CONFIG": Path("factor/runtime/local/docker-config"),
    "HOME": Path("factor/runtime/local/home"),
}
COLIMA = "/opt/homebrew/bin/colima"
DOCKER = "/opt/homebrew/bin/docker"
START_ARGV = [COLIMA, "start", "factor-mining", "--activate=false", "--runtime", "docker",
              "--vm-type", "vz", "--cpus", "6", "--memory", "12", "--disk", "40",
              "--root-disk", "20", "--mount", "none", "--ssh-config=false",
              "--kubernetes=false", "--template=false", "--save-config=true"]
EXPECTED = {
    "v5_tree_sha256": "990d35326ac4624b8d736f2475e96da0de01fac5b100f03973aea7ef94f2bd74",
    "v5_profile_physical_sha256": "71be56773a21df8d54538863fcbd4a5b28f0ebf3690c8e5fef74d39aa042870f",
    "v5_profile_canonical_sha256": "17b973020fec9cca079cf0e562237c9e1823540dc4f224db0cff1a637609a444",
    "v4_profile_physical_sha256": "705c78e004d206c98c4d30de38384e3d75b72c2525efecc1cd7c7cbac3667ac3",
    "v4_profile_canonical_sha256": "5be9d1827441ba81c8d30beac9ee1090a2866320141940b526997bcf7e8a6407",
    "v2_receipt_physical_sha256": "cf552b48d3511ae0116d0554d3035e911aa6425fceebd7a8c8f8a4fc93164908",
    "v2_receipt_canonical_sha256": "c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327",
    "v2_profile_physical_sha256": "81d42def01f98ec29b4f12fb5cb587114c0b28bc1705598e8a04570ecfbc7d3f",
    "v2_profile_canonical_sha256": "40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d",
}

class V6ContractError(ValueError):
    pass

def require(value: bool, code: str) -> None:
    if not value: raise V6ContractError(code)

def load_json(path: Path) -> Any:
    try: return v4.loads_strict(path.read_bytes())
    except (OSError, v4.V4ContractError): raise V6ContractError("V6_JSON_INVALID") from None

def digest(value: Any) -> str:
    return hashlib.sha256(v4.canonical(value)).hexdigest()

def _tree(root: Path) -> str:
    h=hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc"):
        rel=path.relative_to(root).as_posix(); h.update(rel.encode()); h.update(b"\0")
        h.update(hashlib.sha256(path.read_bytes()).hexdigest().encode()); h.update(b"\n")
    return h.hexdigest()

def validate_profile(value: Any, workspace: Path) -> dict[str, Any]:
    schema=load_json(PACKAGE/"runtime-profile-v6.schema.json")
    try: v4.validate_schema_value(value,{"const":schema["const"]})
    except v4.V4ContractError as exc: raise V6ContractError(str(exc).replace("V4_","V6_")) from None
    workspace=v4.validate_workspace(workspace)
    require(value["status"]=="selected-disabled" and value["runnable"] is False and value["apply_allowed"] is False,"V6_FENCE")
    require(value["predecessors"]==EXPECTED,"V6_PREDECESSOR_DECLARATION")
    require(_tree(workspace/"factor/docker/local/v5")==EXPECTED["v5_tree_sha256"],"V6_V5_TREE_DRIFT")
    bindings=[
      ("factor/docker/local/v5/runtime-profile-v5.json","v5_profile_physical_sha256","v5_profile_canonical_sha256"),
      ("factor/docker/local/v4/runtime-profile-v4.json","v4_profile_physical_sha256","v4_profile_canonical_sha256"),
      ("factor/docker/local/v2/installation-receipt.json","v2_receipt_physical_sha256","v2_receipt_canonical_sha256"),
      ("factor/docker/local/v2/runtime-profile-v2.json","v2_profile_physical_sha256","v2_profile_canonical_sha256")]
    for rel,pk,ck in bindings:
        raw=(workspace/rel).read_bytes(); require(hashlib.sha256(raw).hexdigest()==EXPECTED[pk],"V6_PREDECESSOR_PHYSICAL_DRIFT")
        require(digest(v4.loads_strict(raw))==EXPECTED[ck],"V6_PREDECESSOR_CANONICAL_DRIFT")
    return value

def _env(workspace: Path) -> dict[str,str]:
    result={key:str(workspace/rel) for key,rel in ROOTS.items()}
    result["COLIMA_PROFILE"]="factor-mining"; result["PATH"]=PATH_VALUE
    return result

def _open_lock(workspace_fd:int)->tuple[int,tuple[int,int]]:
    try: fd=os.open(str(LOCK_RELATIVE),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600,dir_fd=workspace_fd)
    except OSError: raise V6ContractError("V6_LOCK_UNAVAILABLE") from None
    meta=os.fstat(fd)
    try:
        require(stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_uid==os.geteuid(),"V6_LOCK_METADATA")
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError: os.close(fd); raise V6ContractError("V6_LOCK_CONTENDED") from None
    except Exception: os.close(fd); raise
    return fd,(meta.st_dev,meta.st_ino)
def _roots(workspace_fd:int,workspace:Path,created:list[Path])->tuple[dict[str,int],dict[str,tuple[int,int]]]:
    fds={}; ids={}
    try:
      for name,rel in ROOTS.items():
        fd=os.dup(workspace_fd); current=workspace
        for index,part in enumerate(rel.parts):
          final=index==len(rel.parts)-1; current=current/part; made=False
          try:
            entry=os.stat(part,dir_fd=fd,follow_symlinks=False); require(not stat.S_ISLNK(entry.st_mode),"V6_ROOT_SYMLINK")
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
          except FileNotFoundError:
            try: os.mkdir(part,0o700,dir_fd=fd); made=True; created.append(current); nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            except OSError: raise V6ContractError("V6_ROOT_CREATE_RACE") from None
          except OSError: raise V6ContractError("V6_ROOT_OPEN_RACE") from None
          os.close(fd); fd=nxt; meta=os.fstat(fd)
          require(stat.S_ISDIR(meta.st_mode) and meta.st_uid==os.geteuid(),"V6_ROOT_OWNER_TYPE")
          if made: require(stat.S_IMODE(meta.st_mode)==0o700,"V6_ROOT_MODE")
          if final:
            require(stat.S_IMODE(meta.st_mode)==0o700 and os.listdir(fd)==[],"V6_ROOT_NOT_EMPTY")
            fds[name]=fd;ids[name]=(meta.st_dev,meta.st_ino)
        require(name in fds,"V6_ROOT_MISSING")
      require(len(str(workspace/".c"/v4.SOCKET_SUFFIX).encode())<v4.UNIX_PATH_MAX,"V6_SOCKET_LONG")
      return fds,ids
    except Exception:
      for fd in fds.values(): os.close(fd)
      raise
def _revalidate(workspace:Path,workspace_fd:int,workspace_id:tuple[int,int],fds:dict[str,int],ids:dict[str,tuple[int,int]])->None:
    resolved=workspace.resolve(strict=True); meta=workspace.lstat(); held=os.fstat(workspace_fd)
    require(resolved==workspace and not stat.S_ISLNK(meta.st_mode) and (meta.st_dev,meta.st_ino)==workspace_id==(held.st_dev,held.st_ino),"V6_WORKSPACE_IDENTITY_DRIFT")
    for name,rel in ROOTS.items():
      fd=os.dup(workspace_fd)
      try:
       for part in rel.parts:
        ent=os.stat(part,dir_fd=fd,follow_symlinks=False);require(not stat.S_ISLNK(ent.st_mode),"V6_PRESPAWN_SYMLINK")
        nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
       live=os.fstat(fd);heldroot=os.fstat(fds[name]);require((live.st_dev,live.st_ino)==ids[name]==(heldroot.st_dev,heldroot.st_ino),"V6_ROOT_IDENTITY_DRIFT")
       require(live.st_uid==os.geteuid() and stat.S_IMODE(live.st_mode)==0o700 and os.listdir(fd)==[],"V6_ROOT_METADATA_DRIFT")
      except OSError: raise V6ContractError("V6_PRESPAWN_RACE") from None
      finally: os.close(fd)
def _cleanup(created:list[Path])->bool:
    ok=True
    for p in sorted(created,key=lambda x:len(x.parts),reverse=True):
      try:p.rmdir()
      except FileNotFoundError:pass
      except OSError:ok=False
    return ok

def _run_command(argv:list[str],env:dict[str,str],workspace_fd:int,timeout:int,grace:int):
    process=subprocess.Popen(argv,env=env,cwd=f"/dev/fd/{workspace_fd}",pass_fds=(workspace_fd,),shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    try:return {"returncode":process.wait(timeout=timeout),"timed_out":False}
    except subprocess.TimeoutExpired:
      try:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=grace)
      except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
      return {"returncode":None,"timed_out":True}
def _capture_global(home:str)->str:
    env={"HOME":home,"PATH":PATH_VALUE}
    result=subprocess.run([DOCKER,"context","show"],env=env,cwd="/",shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=15,check=False)
    require(result.returncode==0,"V6_GLOBAL_CONTEXT_UNAVAILABLE"); value=result.stdout.strip();require(value and "\n" not in value,"V6_GLOBAL_CONTEXT_INVALID");return value
def _probe(env:dict[str,str],host_home:str,before:str)->dict[str,Any]:
    colima=subprocess.run([COLIMA,"status","factor-mining","--json"],env=env,cwd="/",shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=30,check=False)
    context=subprocess.run([DOCKER,"--config",env["DOCKER_CONFIG"],"context","inspect","colima-factor-mining","--format","json"],env={"HOME":env["HOME"],"PATH":PATH_VALUE},cwd="/",shell=False,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,timeout=30,check=False)
    after=_capture_global(host_home)
    try:cvalue=json.loads(colima.stdout);dvalue=json.loads(context.stdout)
    except (json.JSONDecodeError,UnicodeError):raise V6ContractError("V6_STATUS_JSON_INVALID") from None
    require(type(cvalue) is dict and type(dvalue) in (dict,list),"V6_STATUS_SHAPE")
    if type(dvalue) is list: require(len(dvalue)==1 and type(dvalue[0]) is dict,"V6_CONTEXT_SHAPE");dvalue=dvalue[0]
    endpoint=dvalue.get("Endpoints",{}).get("docker",{}).get("Host")
    require(type(endpoint) is str and endpoint.startswith("unix://"),"V6_CONTEXT_ENDPOINT")
    socket=Path(endpoint[7:]);root=Path(env["COLIMA_HOME"])
    try:socket.relative_to(root)
    except ValueError:raise V6ContractError("V6_CONTEXT_OUTSIDE_COLIMA_HOME") from None
    running=cvalue.get("status") in ("Running","running") and cvalue.get("profile","factor-mining")=="factor-mining"
    return {"profile":"factor-mining","running":running,"context":"colima-factor-mining","endpoint":endpoint,"global_context_before":before,"global_context_after":after}
def _valid_status(value:Any,env:dict[str,str])->bool:
    if type(value) is not dict or set(value)!={"profile","running","context","endpoint","global_context_before","global_context_after"}:return False
    try:Path(value["endpoint"][7:]).relative_to(Path(env["COLIMA_HOME"]))
    except (TypeError,ValueError):return False
    return value["profile"]=="factor-mining" and value["running"] is True and value["context"]=="colima-factor-mining" and value["global_context_before"]==value["global_context_after"] and type(value["global_context_before"]) is str
def _receipt(status:str,code:str,created:list[Path],retained:list[Path],cleanup:bool,timed_out:bool,returncode:int|None)->dict[str,Any]:
    return {"schema_version":1,"kind":"factor_local_colima_activation_v6_receipt","status":status,"code":code,"created_roots":[str(p) for p in created],"retained_roots":[str(p) for p in retained],"cleanup_complete":cleanup,"timed_out":timed_out,"returncode":returncode,"retry_allowed":False,"diagnostic":"sanitized"}

def _transaction(workspace:Path,runner:Callable,probe:Callable,global_context:Callable,before_spawn:Callable|None=None)->dict[str,Any]:
    workspace=v4.validate_workspace(workspace);profile=validate_profile(load_json(PROFILE_PATH),workspace);created=[];roots={};lock_fd=-1;lock_id=None
    workspace_fd=os.open(workspace,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);wm=os.fstat(workspace_fd);wid=(wm.st_dev,wm.st_ino);host_home=os.path.expanduser("~")
    try:
      before=global_context(host_home);lock_fd,lock_id=_open_lock(workspace_fd);roots,ids=_roots(workspace_fd,workspace,created)
      if before_spawn:before_spawn(workspace)
      _revalidate(workspace,workspace_fd,wid,roots,ids)
      lm=os.stat(str(LOCK_RELATIVE),dir_fd=workspace_fd,follow_symlinks=False);require((lm.st_dev,lm.st_ino)==lock_id,"V6_LOCK_DRIFT")
      env=_env(workspace);result=runner(START_ARGV,env,workspace_fd,profile["execution"]["timeout_seconds"],profile["execution"]["terminate_grace_seconds"])
      if result["timed_out"]:return _receipt("unknown","V6_TIMEOUT_UNKNOWN",created,created,False,True,None)
      try:status=probe(env,host_home,before)
      except Exception:status=None
      if result["returncode"]==0 and _valid_status(status,env):return _receipt("success","V6_STARTED_RECONCILED",created,created,False,False,0)
      if type(status) is dict and status.get("running") is False:
       clean=_cleanup(created);return _receipt("failed","V6_FAILED_NO_VM",created,[] if clean else created,clean,False,result["returncode"])
      return _receipt("unknown","V6_STATUS_UNKNOWN",created,created,False,False,result["returncode"])
    except (V6ContractError,OSError):
      clean=_cleanup(created);return _receipt("failed","V6_PRESPAWN_FAILED",created,[] if clean else created,clean,False,None)
    finally:
      for fd in roots.values():os.close(fd)
      if lock_fd>=0:fcntl.flock(lock_fd,fcntl.LOCK_UN);os.close(lock_fd)
      os.close(workspace_fd)
      if lock_id:
       try:
        p=workspace/LOCK_RELATIVE;m=p.lstat()
        if stat.S_ISREG(m.st_mode) and (m.st_dev,m.st_ino)==lock_id:p.unlink()
       except OSError:pass

def _activate_for_test(workspace:Path,*,runner:Callable,probe:Callable,global_context:Callable,before_spawn:Callable|None=None)->dict[str,Any]:
    """Private injected seam; not exported by CLI or public API."""
    return _transaction(workspace,runner,probe,global_context,before_spawn)
def activate(workspace:Path,*,apply:bool=False,capability:str|None=None,parent_approved:bool=False)->dict[str,Any]:
    workspace=v4.validate_workspace(workspace);profile=validate_profile(load_json(PROFILE_PATH),workspace)
    if not apply:return {"status":"selected-disabled","apply_allowed":False,"profile_sha256":digest(profile),"argv":START_ARGV,"environment":_env(workspace)}
    require(type(parent_approved) is bool and parent_approved is True and capability==CAPABILITY,"V6_UNAUTHORIZED")
    return _transaction(workspace,_run_command,_probe,_capture_global)


def main(argv=None)->int:
    parser=argparse.ArgumentParser(description="Run fixed local Colima v6 activation boundary")
    parser.add_argument("--workspace",type=Path,default=EXPECTED_WORKSPACE)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--capability")
    parser.add_argument("--parent-approved",action="store_true")
    args=parser.parse_args(argv)
    try:result=activate(args.workspace,apply=args.apply,capability=args.capability,parent_approved=args.parent_approved)
    except (V6ContractError,v4.V4ContractError,OSError):
        print(json.dumps({"status":"failed","code":"V6_ACTIVATION_REJECTED","diagnostic":"sanitized"},sort_keys=True));return 2
    print(json.dumps(result,sort_keys=True));return 0 if result["status"] in {"selected-disabled","success"} else 2


if __name__=="__main__":raise SystemExit(main())
