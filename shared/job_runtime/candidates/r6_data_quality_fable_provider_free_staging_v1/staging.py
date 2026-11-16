"""Disabled schema-2 Fable data-quality canary staging."""
from __future__ import annotations
import hashlib,json,os,sqlite3,stat
from pathlib import Path
from typing import Any
from shared.job_runtime.config import load
from shared.job_runtime.engine import Engine
from shared.job_runtime.host_deploy import materialize
from shared.job_runtime.service import publish_prompt_jobs, resource_jobs
from .budget import CampaignBudgetLedger
from .deployment_package.fable_canary_budget.dispatch import campaign_dispatcher

DEPLOYMENT_ID="fable-5-1-dq-v1"
MODEL="claude-fable-5-1"
PROFILE="fable-5-1-dq-disabled"
JOBS=("fable-5-1-dq-off","fable-5-1-dq-on")
RESOURCE="fable-5-1-dq-v1-shared"
PROMPT_SHA256="3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
PROMPT_BYTES=526
SOURCE_PROMPT=Path(__file__).with_name("prompt.txt")

class StagingError(ValueError): pass

def _canonical(value: Any) -> bytes:
    return (json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False)+"\n").encode("ascii")
def _write(path: Path, raw: bytes, mode: int=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.parent.chmod(0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,"wb") as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
def _prompt() -> bytes:
    raw=SOURCE_PROMPT.read_bytes()
    if len(raw)!=PROMPT_BYTES or hashlib.sha256(raw).hexdigest()!=PROMPT_SHA256:raise StagingError("PROMPT_CUSTODY_INVALID")
    return raw

def _read_private_json(path:Path):
    info=os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or not 0<info.st_size<=1048576:raise StagingError("PRIVATE_DESCRIPTOR_INVALID")
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);before=os.fstat(fd)
    try:raw=b''.join(iter(lambda:os.read(fd,65536),b''))
    finally:os.close(fd)
    after=os.lstat(path)
    if (before.st_dev,before.st_ino,before.st_size)!=(after.st_dev,after.st_ino,after.st_size):raise StagingError("PRIVATE_DESCRIPTOR_INVALID")
    try:return json.loads(raw),raw
    except json.JSONDecodeError:raise StagingError("PRIVATE_DESCRIPTOR_INVALID") from None
def _current_closure():
    path=Path(__file__).resolve().parents[4]/"tuning/architecture/r6_data_quality_fable_provider_free_staging_v1/source-closure-v1.json"
    raw=path.read_bytes();return {"path":"tuning/architecture/r6_data_quality_fable_provider_free_staging_v1/source-closure-v1.json","bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
def _file_inventory(root:Path,relatives):
    rows=[]
    for relative in relatives:
        raw=(root/relative).read_bytes();rows.append({"path":relative,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    return rows
def build_candidate(root: Path, scheduled_at: str) -> dict:
    """Create a new private disposable source workspace; never alter active state."""
    root=Path(root).absolute()
    if root.exists():raise StagingError("CANDIDATE_ROOT_EXISTS")
    root.mkdir(parents=True,mode=0o700);root.chmod(0o700);root=root.resolve()
    state=root/".job-runtime";auth=state/"config/fable-auth-home";auth.mkdir(parents=True,mode=0o700)
    for prompt_path in (state/"config/prompts/fable-dq-off.txt",state/"config/prompts/fable-dq-on.txt"):_write(prompt_path,_prompt())
    _write(state/".venv/bin/python",b"#!/bin/sh\nexit 126\n",0o700)
    jobs=[]
    for job_id,arm in zip(JOBS,("OFF","ON")):
        replay={"version":1,"effect":"none","automatic_phases":["not_started"],"slot_operation_scope":f"{DEPLOYMENT_ID}/{arm.lower()}","reconciliation_adapter":None}
        jobs.append({"id":job_id,"enabled":False,"schedule":{"kind":"once","at":scheduled_at,"grace_seconds":240},"model_profile":PROFILE,"prompt_file":f".job-runtime/config/prompts/fable-dq-{arm.lower()}.txt","replay_contract":replay})
    allocation={"schema_version":2,"jobs":jobs}
    config={"schema_version":2,"tick_seconds":5,"heartbeat_seconds":10,"stale_seconds":60,"max_workers":1,"retry":{"version":2,"max_attempts":1,"base_delay_seconds":1,"max_delay_seconds":1,"deadline_seconds":240},"model_profiles":{PROFILE:{"provider":"claude_host","model":MODEL,"effort":"low","timeout_seconds":300,"auth_home":str(auth),"max_budget_usd":0.02,"circuit":{"failure_threshold":1,"open_seconds":60,"probe_seconds":10}}},"allocation_files":[".job-runtime/config/fable-dq-allocation.json"],"source_paths":[]}
    _write(state/"config/fable-dq-allocation.json",_canonical(allocation));_write(state/"config/runtime.json",_canonical(config))
    ledger_path=state/"acceptance/fable-5-1-dq-v1/campaign-budget.sqlite";CampaignBudgetLedger(ledger_path)
    identity=hashlib.sha256(str(root).encode()).hexdigest()[:16];host_label=f"com.local.trading-agent.job-runtime.{identity}"
    closure=_current_closure()
    manifest={"schema_version":1,"status":"REVIEW_PENDING","activation":False,"deployment_id":DEPLOYMENT_ID,"source_closure":closure,"candidate_root":str(root),"model":MODEL,"prompt":{"sha256":PROMPT_SHA256,"bytes":PROMPT_BYTES,"paths":[".job-runtime/config/prompts/fable-dq-off.txt",".job-runtime/config/prompts/fable-dq-on.txt"]},"jobs":[{"id":JOBS[0],"arm":"OFF","enabled":False},{"id":JOBS[1],"arm":"ON","enabled":False}],"execution":{"max_workers":1,"resource_key":RESOURCE,"shared_resource":True},"limits":{"attempts":1,"retries":0,"fallbacks":0,"status_queries":0},"replay_effect":"none","budget":{"currency":"USD","per_arm_max":"0.02","aggregate_max":"0.04","user_approved":True,"ledger_path":".job-runtime/acceptance/fable-5-1-dq-v1/campaign-budget.sqlite"},"effects":{"provider":0,"network":0,"email":0,"business":0,"ixic":0},"host":{"installed":False,"jobs_enabled":False,"service_label":host_label,"watchdog_label":host_label+".watchdog","pointer":".job-runtime/setup/host-deployment.json"}}
    _write(state/"config/staging-manifest.json",_canonical(manifest))
    for directory in [state,*[p for p in state.rglob("*") if p.is_dir()]]:directory.chmod(0o700)
    loaded,jobs_loaded=load(root/".job-runtime/config/runtime.json",root)
    if loaded["max_workers"]!=1 or len(jobs_loaded)!=2 or any(j["enabled"] for j in jobs_loaded):raise StagingError("CANDIDATE_VALIDATION_FAILED")
    return manifest

def load_candidate(root: Path):
    root=Path(root).resolve()
    for name in ("fable-dq-off.txt","fable-dq-on.txt"):
        raw=(root/".job-runtime/config/prompts"/name).read_bytes()
        if len(raw)!=PROMPT_BYTES or hashlib.sha256(raw).hexdigest()!=PROMPT_SHA256:raise StagingError("PROMPT_CUSTODY_INVALID")
    return load(root/".job-runtime/config/runtime.json",root)

def engine_projection(root: Path):
    root=Path(root).resolve();config,captured=load_candidate(root)
    jobs=resource_jobs(config,publish_prompt_jobs(root,captured,DEPLOYMENT_ID))
    for job in jobs:job["_resource_key"]=RESOURCE
    return config,jobs

def open_disabled_engine(root: Path, dispatcher):
    root=Path(root).resolve();config,jobs=engine_projection(root)
    return Engine(root/".job-runtime/runs",jobs,config["retry"],dispatcher,workspace_root=root,max_workers=1)

def materialize_disposable(root: Path, external_root: Path) -> dict:
    """Materialize a reviewed TEST_ONLY package and ledger into disposable roots."""
    root=Path(root).resolve();candidate_external=Path(external_root).absolute();external_root=candidate_external.parent.resolve(strict=True)/candidate_external.name;load_candidate(root)
    if external_root.exists():_validate_existing_pointer(root,external_root)
    materialize(root,external_root=external_root);deployed=external_root/"workspace";package=_deploy_reviewed_package(deployed);authority_deps=_deploy_authority_dependencies(deployed);host=_reseal_host_receipt(root,external_root);ledger=_copy_ledger(root,deployed)
    if not deployed.is_dir() or any(p.is_symlink() for p in deployed.rglob("*")):raise StagingError("PHYSICAL_CLOSURE_INVALID")
    if host["persistent_links"] or host["credentials_copied"]:raise StagingError("HOST_RECEIPT_INVALID")
    source_rel=[".job-runtime/config/runtime.json",".job-runtime/config/fable-dq-allocation.json",".job-runtime/config/prompts/fable-dq-off.txt",".job-runtime/config/prompts/fable-dq-on.txt",".job-runtime/config/staging-manifest.json"]
    deployed_rel=[".job-runtime/config/runtime.json",".job-runtime/config/fable-dq-allocation.json",".job-runtime/config/prompts/fable-dq-off.txt",".job-runtime/config/prompts/fable-dq-on.txt","shared/job_runtime/fable_canary_budget/__init__.py","shared/job_runtime/fable_canary_budget/budget.py","shared/job_runtime/fable_canary_budget/dispatch.py","shared/job_runtime/fable_canary_budget/journal.py"]
    return {"host_receipt":host,"ledger":ledger.__dict__,"package":package,"authority_dependencies":authority_deps,"source_inventory":_file_inventory(root,source_rel),"deployment_inventory":_file_inventory(deployed,deployed_rel),"source_closure":_current_closure(),"source_root":str(root),"deployment_root":str(external_root)}

def _verify_current_closure(expected):
    descriptor=_current_closure()
    if descriptor!=expected:raise StagingError("SOURCE_CLOSURE_DRIFT")
    path=Path(__file__).resolve().parents[4]/descriptor["path"];value=json.loads(path.read_text());repo=Path(__file__).resolve().parents[4]
    for row in value["members"]:
        raw=(repo/row["path"]).read_bytes()
        if len(raw)!=row["bytes"] or hashlib.sha256(raw).hexdigest()!=row["sha256"]:raise StagingError("SOURCE_CLOSURE_DRIFT")
def rollback_disposable(root:Path,external_root:Path,*,source_parent:Path,deployment_parent:Path,expected:dict)->None:
    try:root=Path(root).resolve(strict=True);external_root=Path(external_root).resolve(strict=True)
    except OSError:raise StagingError("ROLLBACK_ROOT_INVALID") from None
    try:source_parent=Path(source_parent).resolve(strict=True);deployment_parent=Path(deployment_parent).resolve(strict=True)
    except OSError:raise StagingError("ROLLBACK_ROOT_INVALID") from None
    if root.parent.resolve(strict=True)!=source_parent or external_root.parent.resolve(strict=True)!=deployment_parent or not root.exists() or not external_root.exists():raise StagingError("ROLLBACK_ROOT_INVALID")
    if root.is_symlink() or external_root.is_symlink():raise StagingError("ROLLBACK_SYMLINK_REJECTED")
    _verify_current_closure(expected.get("source_closure"))
    manifest,_=_read_private_json(root/".job-runtime/config/staging-manifest.json")
    if manifest.get("activation") is not False or manifest.get("deployment_id")!=DEPLOYMENT_ID:raise StagingError("ROLLBACK_ACTIVE_OR_MISMATCH")
    _,jobs=load_candidate(root)
    if any(job["enabled"] for job in jobs):raise StagingError("ROLLBACK_ACTIVE_OR_MISMATCH")
    current=materialize_disposable(root,external_root);current_host=current["host_receipt"]
    if expected!=current:raise StagingError("ROLLBACK_RECEIPT_MISMATCH")
    try:pointer,_=_read_private_json(root/".job-runtime/setup/host-deployment.json");_,receipt_raw=_read_private_json(external_root/"deployment-receipt.json")
    except (OSError,StagingError):raise StagingError("ROLLBACK_POINTER_MISMATCH") from None
    if pointer!={"schema_version":1,"workspace_id":current_host["workspace_id"],"receipt_sha256":hashlib.sha256(receipt_raw).hexdigest(),"service_label":current_host["service_label"]}:raise StagingError("ROLLBACK_POINTER_MISMATCH")
    _validate_owned_tree(external_root);_validate_owned_tree(root)
    token=hashlib.sha256(_canonical({"source":str(root),"deployment":str(external_root),"receipt":expected})).hexdigest()[:16];source_staged="."+root.name+".rollback-"+token;deployment_staged="."+external_root.name+".rollback-"+token;journal_path=deployment_parent/(".fable-rollback-"+token+".json")
    plan=["journal","rename_deployment","rename_source","commit"]
    for phase in plan:_rollback_hook(phase)
    journal={"schema_version":1,"status":"prepared","source":{"original":root.name,"staged":source_staged},"deployment":{"original":external_root.name,"staged":deployment_staged},"receipt_sha256":hashlib.sha256(_canonical(expected)).hexdigest()};_write(journal_path,_canonical(journal))
    source_fd=os.open(source_parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);deployment_fd=os.open(deployment_parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    deployment_renamed=source_renamed=False;os.fsync(source_fd);os.fsync(deployment_fd)
    try:
        os.rename(external_root.name,deployment_staged,src_dir_fd=deployment_fd,dst_dir_fd=deployment_fd);deployment_renamed=True
        os.rename(root.name,source_staged,src_dir_fd=source_fd,dst_dir_fd=source_fd);source_renamed=True
        journal['status']='RETIRED_COMMITTED';journal['source']['inventory']=expected['source_inventory'];journal['deployment']['inventory']=expected['deployment_inventory'];_atomic_replace(journal_path,journal);os.fsync(source_fd);os.fsync(deployment_fd);deployment_renamed=False;source_renamed=False
    except Exception:
        if source_renamed:
            try:os.rename(source_staged,root.name,src_dir_fd=source_fd,dst_dir_fd=source_fd)
            except OSError:pass
        if deployment_renamed:
            try:os.rename(deployment_staged,external_root.name,src_dir_fd=deployment_fd,dst_dir_fd=deployment_fd)
            except OSError:pass
        raise
    finally:os.close(source_fd);os.close(deployment_fd)

def _deploy_authority_dependencies(deployed_root:Path):
    repo=Path(__file__).resolve().parents[4];source=repo/"shared/research_sources";target=deployed_root/"shared/research_sources";rows=[]
    for path in sorted(source.rglob("*")):
        if path.is_symlink():raise StagingError("AUTHORITY_DEPENDENCY_SYMLINK")
        if not path.is_file() or path.suffix not in (".py",".json"):continue
        relative=path.relative_to(source);destination=target/relative;raw=path.read_bytes()
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes()!=raw:raise StagingError("AUTHORITY_DEPENDENCY_DRIFT")
        else:_write(destination,raw)
        destination.chmod(0o600);rows.append({"path":"shared/research_sources/"+relative.as_posix(),"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    return rows
PACKAGE_FILES=("__init__.py","budget.py","dispatch.py","journal.py")
def _deploy_reviewed_package(deployed_root:Path):
    source=Path(__file__).parent/"deployment_package/fable_canary_budget";target=deployed_root/"shared/job_runtime/fable_canary_budget";target.mkdir(mode=0o700,parents=True,exist_ok=True);rows=[]
    for name in PACKAGE_FILES:
        raw=(source/name).read_bytes();destination=target/name
        if destination.exists():
            if destination.is_symlink() or destination.read_bytes()!=raw:raise StagingError("DEPLOYED_PACKAGE_DRIFT")
        else:_write(destination,raw)
        destination.chmod(0o600);rows.append({"path":"shared/job_runtime/fable_canary_budget/"+name,"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()})
    return rows
def _shared_inventory(root:Path):
    rows=[]
    for path in sorted((root/"shared").rglob("*")):
        if path.is_symlink():raise StagingError("PHYSICAL_CLOSURE_INVALID")
        if path.is_file():
            raw=path.read_bytes();rows.append({"path":path.relative_to(root/"shared").as_posix(),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)})
    return rows
def _atomic_replace(path:Path,value):
    raw=_canonical(value);temp=path.with_name(path.name+".candidate-tmp");_write(temp,raw);os.replace(temp,path);path.chmod(0o600);return raw
def _reseal_host_receipt(source_root:Path,external_root:Path):
    receipt_path=external_root/"deployment-receipt.json";receipt,_=_read_private_json(receipt_path);rows=_shared_inventory(external_root/"workspace");receipt["source_files"]=len(rows);receipt["source_sha256"]=hashlib.sha256(_canonical(rows)).hexdigest();raw=_atomic_replace(receipt_path,receipt)
    pointer={"schema_version":1,"workspace_id":receipt["workspace_id"],"receipt_sha256":hashlib.sha256(raw).hexdigest(),"service_label":receipt["service_label"]};_atomic_replace(source_root/".job-runtime/setup/host-deployment.json",pointer);return receipt
def _validate_existing_pointer(source_root:Path,external_root:Path):
    try:receipt,receipt_raw=_read_private_json(external_root/"deployment-receipt.json");pointer,_=_read_private_json(source_root/".job-runtime/setup/host-deployment.json")
    except (OSError,json.JSONDecodeError,StagingError):raise StagingError("HOST_POINTER_INVALID") from None
    expected={"schema_version":1,"workspace_id":receipt.get("workspace_id"),"receipt_sha256":hashlib.sha256(receipt_raw).hexdigest(),"service_label":receipt.get("service_label")}
    if pointer!=expected:raise StagingError("HOST_POINTER_INVALID")
def recover_rollback(source_parent:Path,deployment_parent:Path,journal_path:Path):
    source_parent=Path(source_parent).resolve(strict=True);deployment_parent=Path(deployment_parent).resolve(strict=True);journal,_=_read_private_json(Path(journal_path));source=journal['source'];deployment=journal['deployment'];sfd=os.open(source_parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);dfd=os.open(deployment_parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        so=(source_parent/source['original']).exists();ss=(source_parent/source['staged']).exists();do=(deployment_parent/deployment['original']).exists();ds=(deployment_parent/deployment['staged']).exists()
        if journal['status']=='RETIRED_COMMITTED':
            if not (ss and ds and not so and not do):raise StagingError('ROLLBACK_COMMITTED_STATE_INVALID')
            return 'RETIRED_COMMITTED'
        if journal['status'] not in ('prepared','staged'):raise StagingError('ROLLBACK_JOURNAL_INVALID')
        if ss and not so:os.rename(source['staged'],source['original'],src_dir_fd=sfd,dst_dir_fd=sfd)
        if ds and not do:os.rename(deployment['staged'],deployment['original'],src_dir_fd=dfd,dst_dir_fd=dfd)
        os.fsync(sfd);os.fsync(dfd);journal['status']='RECOVERED';_atomic_replace(Path(journal_path),journal);return 'RECOVERED'
    finally:os.close(sfd);os.close(dfd)
def _copy_ledger(source_root:Path,deployed_root:Path):
    source_dir=source_root/".job-runtime/acceptance/fable-5-1-dq-v1";source=CampaignBudgetLedger(source_dir/"campaign-budget.sqlite",approved_root=source_dir,create=False)
    target_dir=deployed_root/".job-runtime/acceptance/fable-5-1-dq-v1";target_dir.mkdir(parents=True,exist_ok=True,mode=0o700);target_dir.chmod(0o700);target=target_dir/"campaign-budget.sqlite"
    if not target.exists():
        with sqlite3.connect(source.path) as src,sqlite3.connect(target) as dst:src.backup(dst);dst.execute("PRAGMA synchronous=FULL")
        target.chmod(0o600)
    deployed=CampaignBudgetLedger(target,approved_root=target_dir,create=False)
    if source.snapshot()!=deployed.snapshot():raise StagingError("LEDGER_COPY_MISMATCH")
    return deployed.descriptor()

def _validate_owned_tree(root:Path):
    info=os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid!=os.getuid():raise StagingError("ROLLBACK_ROOT_INVALID")
    with os.scandir(root) as entries:
        for entry in entries:
            info=os.lstat(entry.path)
            if stat.S_ISLNK(info.st_mode):raise StagingError("ROLLBACK_SYMLINK_REJECTED")
            if stat.S_ISDIR(info.st_mode):_validate_owned_tree(Path(entry.path))
            elif not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid():raise StagingError("ROLLBACK_ENTRY_INVALID")

def _safe_tree_remove(root:Path):
    info=os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid!=os.getuid():raise StagingError("ROLLBACK_ROOT_INVALID")
    with os.scandir(root) as entries:
        paths=[Path(entry.path) for entry in entries]
    for path in paths:
        entry_info=os.lstat(path)
        if stat.S_ISLNK(entry_info.st_mode):raise StagingError("ROLLBACK_SYMLINK_REJECTED")
        if stat.S_ISDIR(entry_info.st_mode):_safe_tree_remove(path)
        elif stat.S_ISREG(entry_info.st_mode) and entry_info.st_uid==os.getuid():path.unlink()
        else:raise StagingError("ROLLBACK_ENTRY_INVALID")
    root.rmdir()

_ROLLBACK_TEST_HOOK=None
def _rollback_hook(phase):
    if _ROLLBACK_TEST_HOOK is not None:_ROLLBACK_TEST_HOOK(phase)
def _plan_tree(root:Path,prefix:str):
    rows=[]
    with os.scandir(root) as entries:
        for entry in sorted(entries,key=lambda x:x.name):
            info=os.lstat(entry.path)
            if stat.S_ISLNK(info.st_mode):raise StagingError("ROLLBACK_SYMLINK_REJECTED")
            if stat.S_ISDIR(info.st_mode):rows.extend(_plan_tree(Path(entry.path),prefix+"/"+entry.name))
            elif stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid():rows.append(prefix+"/"+entry.name)
            else:raise StagingError("ROLLBACK_ENTRY_INVALID")
    rows.append(prefix);return rows
def _remove_at(parent_fd:int,name:str):
    child_fd=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent_fd)
    try:
        with os.scandir(child_fd) as entries:names=sorted(entry.name for entry in entries)
        for child in names:
            info=os.stat(child,dir_fd=child_fd,follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):raise StagingError("ROLLBACK_SYMLINK_REJECTED")
            if stat.S_ISDIR(info.st_mode):_remove_at(child_fd,child)
            elif stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid():os.unlink(child,dir_fd=child_fd)
            else:raise StagingError("ROLLBACK_ENTRY_INVALID")
    finally:os.close(child_fd)
    os.rmdir(name,dir_fd=parent_fd)

# Version-2 strict rollback authority.  These definitions intentionally replace the
# provisional path-based implementation above while preserving its public API.
_LEGACY_MATERIALIZE_DISPOSABLE=materialize_disposable
_ROLLBACK_STATES=('PREPARED','DEPLOYMENT_STAGED','BOTH_STAGED','RETIRED_COMMITTED','RECOVERED')
_ROLLBACK_JOURNAL_FIELDS={'schema_version','record_type','state','token','binding','source','deployment','receipt_sha256','journal_sha256'}
_ROLLBACK_BINDING_FIELDS={'schema_version','deployment_id','workspace_id','source_basename','deployment_basename','source_inventory_sha256','deployment_inventory_sha256','source_closure_sha256','host_receipt_sha256','service_label','watchdog_label'}
_ROLLBACK_SIDE_FIELDS={'parent','original','staged','inventory'}
_ROLLBACK_PARENT_FIELDS={'dev','ino','uid','mode'}
_ROLLBACK_ROW_FIELDS={'path','kind','mode','uid','nlink','bytes','sha256'}
_HEX64=re.compile(r'[0-9a-f]{64}\Z') if 're' in globals() else __import__('re').compile(r'[0-9a-f]{64}\Z')
_TOKEN_RE=__import__('re').compile(r'[0-9a-f]{32}\Z')

def _reject_nonfinite(_):raise StagingError('ROLLBACK_JOURNAL_INVALID')
def _strict_json(raw:bytes,maximum=1048576):
    if not 1<=len(raw)<=maximum:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise StagingError('ROLLBACK_JOURNAL_INVALID')
            value[key]=item
        return value
    try:value=json.loads(raw.decode('ascii'),object_pairs_hook=pairs,parse_constant=_reject_nonfinite)
    except (UnicodeError,json.JSONDecodeError,StagingError):raise StagingError('ROLLBACK_JOURNAL_INVALID') from None
    if type(value) is not dict or _canonical(value)!=raw:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    return value

def _basename(value):
    if type(value) is not str or not value or value in ('.','..') or '/' in value or '\x00' in value or Path(value).name!=value:raise StagingError('ROLLBACK_ROOT_INVALID')
    return value

def _fd_identity(fd):
    info=os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():raise StagingError('ROLLBACK_ROOT_INVALID')
    return {'dev':info.st_dev,'ino':info.st_ino,'uid':info.st_uid,'mode':stat.S_IMODE(info.st_mode)}

_HELD_PARENT_ANCESTORS={}
def _open_parent(path):
    absolute=Path(path).absolute()
    if not absolute.is_absolute():raise StagingError('ROLLBACK_ROOT_INVALID')
    held=[]
    try:
        current=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);held.append(current)
        for part in absolute.parts[1:]:
            child=os.open(_basename(part),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=current);held.append(child);current=child
        fd=held[-1];identity=_fd_identity(fd)
        if identity['mode']&0o022:raise StagingError('ROLLBACK_ROOT_INVALID')
        held.pop();_HELD_PARENT_ANCESTORS[fd]=held;return fd
    except (OSError,StagingError):
        for item in reversed(held):
            try:os.close(item)
            except OSError:pass
        raise StagingError('ROLLBACK_ROOT_INVALID') from None

def _close_parent(fd):
    try:os.close(fd)
    finally:
        for item in reversed(_HELD_PARENT_ANCESTORS.pop(fd,[])):
            try:os.close(item)
            except OSError:pass

def _open_dir_at(parent_fd,name):
    try:fd=os.open(_basename(name),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent_fd);_fd_identity(fd);return fd
    except OSError:raise StagingError('ROLLBACK_ROOT_INVALID') from None

def _read_file_at(fd,name,maximum=1048576,private=True):
    child=-1
    try:
        child=os.open(_basename(name),os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd);before=os.fstat(child)
        if not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or (private and stat.S_IMODE(before.st_mode)!=0o600) or stat.S_IMODE(before.st_mode)&0o022 or before.st_nlink!=1 or not 0<before.st_size<=maximum:raise StagingError('PRIVATE_DESCRIPTOR_INVALID')
        raw=b''
        while len(raw)<=maximum:
            chunk=os.read(child,min(65536,maximum+1-len(raw)))
            if not chunk:break
            raw+=chunk
        after=os.fstat(child)
        if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise StagingError('PRIVATE_DESCRIPTOR_INVALID')
        return raw
    except OSError:raise StagingError('PRIVATE_DESCRIPTOR_INVALID') from None
    finally:
        if child>=0:os.close(child)

def _read_relative(root_fd,relative,maximum=1048576,private=True):
    parts=Path(relative).parts
    if not parts or any(p in ('','.','..') for p in parts):raise StagingError('PRIVATE_DESCRIPTOR_INVALID')
    held=[];current=root_fd
    try:
        for part in parts[:-1]:
            child=_open_dir_at(current,part);held.append(child);current=child
        return _read_file_at(current,parts[-1],maximum,private)
    finally:
        for fd in reversed(held):os.close(fd)

def _read_relative_json(root_fd,relative):
    raw=_read_relative(root_fd,relative)
    try:return _strict_json(raw),raw
    except StagingError:raise StagingError('PRIVATE_DESCRIPTOR_INVALID') from None

def _inventory_fd(root_fd):
    rows=[]
    def walk(fd,prefix):
        info=os.fstat(fd);rows.append({'path':prefix or '.','kind':'directory','mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'nlink':info.st_nlink,'bytes':0,'sha256':None})
        for name in sorted(os.listdir(fd)):
            if name in ('.','..'):raise StagingError('ROLLBACK_ENTRY_INVALID')
            try:entry=os.stat(name,dir_fd=fd,follow_symlinks=False)
            except OSError:raise StagingError('ROLLBACK_ENTRY_INVALID') from None
            rel=name if not prefix else prefix+'/'+name
            if stat.S_ISLNK(entry.st_mode):raise StagingError('ROLLBACK_SYMLINK_REJECTED')
            if entry.st_uid!=os.getuid():raise StagingError('ROLLBACK_ENTRY_INVALID')
            if stat.S_ISDIR(entry.st_mode):
                child=_open_dir_at(fd,name)
                try:walk(child,rel)
                finally:os.close(child)
            elif stat.S_ISREG(entry.st_mode):
                child=-1
                try:
                    child=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd);held=os.fstat(child);raw=b''
                    while True:
                        chunk=os.read(child,65536)
                        if not chunk:break
                        raw+=chunk
                    after=os.fstat(child)
                    if (held.st_dev,held.st_ino,held.st_size,held.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or held.st_nlink!=1:raise StagingError('ROLLBACK_ENTRY_INVALID')
                    rows.append({'path':rel,'kind':'file','mode':stat.S_IMODE(held.st_mode),'uid':held.st_uid,'nlink':held.st_nlink,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
                finally:
                    if child>=0:os.close(child)
            else:raise StagingError('ROLLBACK_ENTRY_INVALID')
    walk(root_fd,'');return rows

def _inventory_path(root):
    fd=_open_parent(root)
    try:return _inventory_fd(fd)
    finally:_close_parent(fd)

def _inventory_hash(rows):return hashlib.sha256(_canonical(rows)).hexdigest()
def _host_receipt_hash(external_fd):return hashlib.sha256(_read_relative(external_fd,'deployment-receipt.json')).hexdigest()
def _rollback_binding(receipt,source_name,deployment_name):
    host=receipt['host_receipt'];return {'schema_version':1,'deployment_id':DEPLOYMENT_ID,'workspace_id':host['workspace_id'],'source_basename':_basename(source_name),'deployment_basename':_basename(deployment_name),'source_inventory_sha256':_inventory_hash(receipt['source_inventory']),'deployment_inventory_sha256':_inventory_hash(receipt['deployment_inventory']),'source_closure_sha256':receipt['source_closure']['sha256'],'host_receipt_sha256':receipt['host_receipt_sha256'],'service_label':host['service_label'],'watchdog_label':host['watchdog_label']}
def _rollback_token(binding):return hashlib.sha256(b'fable-rollback-token-v2\x00'+_canonical(binding)).hexdigest()[:32]
def _binding_hash(binding):return hashlib.sha256(b'fable-rollback-binding-v2\x00'+_canonical(binding)).hexdigest()
def _stage_name(original,token):return '.'+_basename(original)+'.rollback-'+token
def _journal_name(token):return '.fable-rollback-'+token+'.json'
def _journal_temp_name(token):return _journal_name(token)+'.tmp'

def materialize_disposable(root:Path,external_root:Path)->dict:
    receipt=_LEGACY_MATERIALIZE_DISPOSABLE(root,external_root);root=Path(root).resolve();external_root=Path(external_root).resolve()
    receipt['source_inventory']=_inventory_path(root);receipt['deployment_inventory']=_inventory_path(external_root);receipt['host_receipt_sha256']=hashlib.sha256((external_root/'deployment-receipt.json').read_bytes()).hexdigest()
    binding=_rollback_binding(receipt,root.name,external_root.name);receipt['rollback_binding']={'value':binding,'nonce':_rollback_token(binding),'binding_sha256':_binding_hash(binding)}
    return receipt

def _validate_receipt(expected,source_name,deployment_name,source_rows,deployment_rows,host_hash):
    fields={'host_receipt','ledger','package','authority_dependencies','source_inventory','deployment_inventory','source_closure','source_root','deployment_root','host_receipt_sha256','rollback_binding'}
    if type(expected) is not dict or set(expected)!=fields or expected['source_inventory']!=source_rows or expected['deployment_inventory']!=deployment_rows or expected['host_receipt_sha256']!=host_hash:raise StagingError('ROLLBACK_RECEIPT_MISMATCH')
    wrapped=expected['rollback_binding']
    if type(wrapped) is not dict or set(wrapped)!= {'value','nonce','binding_sha256'}:raise StagingError('ROLLBACK_RECEIPT_MISMATCH')
    binding=wrapped['value'];computed=_rollback_binding(expected,source_name,deployment_name)
    if binding!=computed or wrapped['nonce']!=_rollback_token(computed) or wrapped['binding_sha256']!=_binding_hash(computed):raise StagingError('ROLLBACK_RECEIPT_MISMATCH')
    return binding,wrapped['nonce']

def _validate_binding_v2(value):
    if type(value) is not dict or set(value)!=_ROLLBACK_BINDING_FIELDS or type(value['schema_version']) is not int or value['schema_version']!=1:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    strings=_ROLLBACK_BINDING_FIELDS-{'schema_version'}
    if any(type(value[k]) is not str for k in strings) or value['deployment_id']!=DEPLOYMENT_ID or _HEX64.fullmatch(value['source_inventory_sha256']) is None or _HEX64.fullmatch(value['deployment_inventory_sha256']) is None or _HEX64.fullmatch(value['source_closure_sha256']) is None or _HEX64.fullmatch(value['host_receipt_sha256']) is None:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    _basename(value['source_basename']);_basename(value['deployment_basename']);return value

def _validate_inventory(rows):
    if type(rows) is not list or not rows:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    seen=set()
    for row in rows:
        if type(row) is not dict or set(row)!=_ROLLBACK_ROW_FIELDS or type(row['path']) is not str or type(row['kind']) is not str or row['kind'] not in ('file','directory') or type(row['mode']) is not int or type(row['uid']) is not int or type(row['nlink']) is not int or type(row['bytes']) is not int:raise StagingError('ROLLBACK_JOURNAL_INVALID')
        if row['path'] in seen:raise StagingError('ROLLBACK_JOURNAL_INVALID')
        seen.add(row['path'])
        if row['kind']=='file':
            if _HEX64.fullmatch(row['sha256'] or '') is None or row['bytes']<0:raise StagingError('ROLLBACK_JOURNAL_INVALID')
        elif row['sha256'] is not None or row['bytes']!=0:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    if rows[0]['path']!='.':raise StagingError('ROLLBACK_JOURNAL_INVALID')
    return rows

def _journal_hash(value):return hashlib.sha256(b'fable-rollback-journal-v2\x00'+_canonical({k:value[k] for k in _ROLLBACK_JOURNAL_FIELDS-{'journal_sha256'}})).hexdigest()
def _validate_journal(value,token,parent_identities=None):
    if type(value) is not dict or set(value)!=_ROLLBACK_JOURNAL_FIELDS or type(value['schema_version']) is not int or value['schema_version']!=2 or value['record_type']!='fable_rollback' or value['state'] not in _ROLLBACK_STATES or value['token']!=token or _TOKEN_RE.fullmatch(token) is None:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    binding=_validate_binding_v2(value['binding'])
    if token!=_rollback_token(binding) or value['receipt_sha256']!=_binding_hash(binding) or value['journal_sha256']!=_journal_hash(value):raise StagingError('ROLLBACK_JOURNAL_INVALID')
    for key in ('source','deployment'):
        side=value[key]
        if type(side) is not dict or set(side)!=_ROLLBACK_SIDE_FIELDS or type(side['parent']) is not dict or set(side['parent'])!=_ROLLBACK_PARENT_FIELDS or any(type(side['parent'][k]) is not int for k in _ROLLBACK_PARENT_FIELDS):raise StagingError('ROLLBACK_JOURNAL_INVALID')
        expected_original=binding[key+'_basename'];expected_staged=_stage_name(expected_original,token)
        if side['original']!=expected_original or side['staged']!=expected_staged:raise StagingError('ROLLBACK_JOURNAL_INVALID')
        _validate_inventory(side['inventory'])
        if _inventory_hash(side['inventory'])!=binding[key+'_inventory_sha256']:raise StagingError('ROLLBACK_JOURNAL_INVALID')
        if parent_identities and side['parent']!=parent_identities[key]:raise StagingError('ROLLBACK_PARENT_MISMATCH')
    return value

def _fault(phase):
    if _ROLLBACK_TEST_HOOK is not None:_ROLLBACK_TEST_HOOK(phase)
def _fsync(fd,label):
    _fault('before_fsync_'+label);os.fsync(fd);_fault('after_fsync_'+label)
def _write_raw_at(fd,name,raw,exclusive=True):
    flags=os.O_WRONLY|os.O_CREAT|os.O_NOFOLLOW|os.O_CLOEXEC|(os.O_EXCL if exclusive else os.O_TRUNC)
    child=os.open(name,flags,0o600,dir_fd=fd)
    try:
        view=memoryview(raw)
        while view:
            _fault('before_write');written=os.write(child,view);_fault('after_write')
            if written<=0:raise StagingError('ROLLBACK_WRITE_FAILED')
            view=view[written:]
        _fsync(child,'journal_file')
    finally:os.close(child)
def _persist_journal(parent_fd,value,create=False):
    value=dict(value);value['journal_sha256']=_journal_hash(value);raw=_canonical(value);name=_journal_name(value['token'])
    temp=_journal_temp_name(value['token'])
    try:os.unlink(temp,dir_fd=parent_fd)
    except FileNotFoundError:pass
    if create:
        _fault('journal');_fault('before_create_journal');_write_raw_at(parent_fd,temp,raw,True);_fault('before_create_replace');os.rename(temp,name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd);_fault('after_create_replace');_fsync(parent_fd,'journal_parent');_fault('after_create_journal')
    else:
        _fault('before_replace_write');_write_raw_at(parent_fd,temp,raw,True);_fault('before_replace');os.replace(temp,name,src_dir_fd=parent_fd,dst_dir_fd=parent_fd);_fault('after_replace');_fsync(parent_fd,'journal_parent');_fault('after_replace_fsync')
    return value

def _read_journal_at(parent_fd,name):
    raw=_read_file_at(parent_fd,name);return _strict_json(raw)
def _exists_dir(parent_fd,name):
    try:info=os.stat(name,dir_fd=parent_fd,follow_symlinks=False)
    except FileNotFoundError:return False
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid!=os.getuid():raise StagingError('ROLLBACK_NAMESPACE_INVALID')
    return True

def _scan_token_namespace(source_fd,deployment_fd,journal):
    token=journal['token'];allowed_source={journal['source']['original'],journal['source']['staged']};allowed_deployment={journal['deployment']['original'],journal['deployment']['staged'],_journal_name(token),_journal_temp_name(token)}
    if (os.fstat(source_fd).st_dev,os.fstat(source_fd).st_ino)==(os.fstat(deployment_fd).st_dev,os.fstat(deployment_fd).st_ino):
        allowed=allowed_source|allowed_deployment
        for name in os.listdir(source_fd):
            if token in name and name not in allowed:raise StagingError('ROLLBACK_NAMESPACE_COLLISION')
    else:
        for fd,allowed in ((source_fd,allowed_source),(deployment_fd,allowed_deployment)):
            for name in os.listdir(fd):
                if token in name and name not in allowed:raise StagingError('ROLLBACK_NAMESPACE_COLLISION')

def _namespace(source_fd,deployment_fd,journal):
    return (_exists_dir(source_fd,journal['source']['original']),_exists_dir(source_fd,journal['source']['staged']),_exists_dir(deployment_fd,journal['deployment']['original']),_exists_dir(deployment_fd,journal['deployment']['staged']))
def _verify_named_inventory(parent_fd,name,expected):
    child=_open_dir_at(parent_fd,name)
    try:actual=_inventory_fd(child)
    finally:os.close(child)
    if actual!=expected:raise StagingError('ROLLBACK_INVENTORY_DRIFT')

def _restore_precommit(source_fd,deployment_fd,journal):
    state=journal['state'];ns=_namespace(source_fd,deployment_fd,journal)
    legal={'PREPARED':{(True,False,True,False),(True,False,False,True),(False,True,False,True)},'DEPLOYMENT_STAGED':{(True,False,False,True),(False,True,False,True)},'BOTH_STAGED':{(False,True,False,True)},'RECOVERED':{(True,False,True,False)}}
    if state not in legal or ns not in legal[state]:raise StagingError('ROLLBACK_NAMESPACE_INVALID')
    so,ss,do,ds=ns
    if ss:
        _verify_named_inventory(source_fd,journal['source']['staged'],journal['source']['inventory']);_fault('before_restore_source');os.rename(journal['source']['staged'],journal['source']['original'],src_dir_fd=source_fd,dst_dir_fd=source_fd);_fault('after_restore_source');_fsync(source_fd,'source_parent_restore')
    else:_verify_named_inventory(source_fd,journal['source']['original'],journal['source']['inventory'])
    if ds:
        _verify_named_inventory(deployment_fd,journal['deployment']['staged'],journal['deployment']['inventory']);_fault('before_restore_deployment');os.rename(journal['deployment']['staged'],journal['deployment']['original'],src_dir_fd=deployment_fd,dst_dir_fd=deployment_fd);_fault('after_restore_deployment');_fsync(deployment_fd,'deployment_parent_restore')
    else:_verify_named_inventory(deployment_fd,journal['deployment']['original'],journal['deployment']['inventory'])
    if _namespace(source_fd,deployment_fd,journal)!=(True,False,True,False):raise StagingError('ROLLBACK_RESTORE_FAILED')
    if state!='RECOVERED':journal=dict(journal);journal['state']='RECOVERED';journal=_persist_journal(deployment_fd,journal)
    return journal

def _verify_closure_descriptor(expected):
    if type(expected) is not dict or set(expected)!={'path','bytes','sha256'} or type(expected['path']) is not str or type(expected['bytes']) is not int or _HEX64.fullmatch(expected['sha256'] or '') is None:raise StagingError('SOURCE_CLOSURE_DRIFT')
    repo=Path(__file__).resolve().parents[4];repo_fd=_open_parent(repo)
    try:
        raw=_read_relative(repo_fd,expected['path'],private=False)
        if len(raw)!=expected['bytes'] or hashlib.sha256(raw).hexdigest()!=expected['sha256']:raise StagingError('SOURCE_CLOSURE_DRIFT')
        value=_strict_json(raw)
        if type(value) is not dict or type(value.get('members')) is not list:raise StagingError('SOURCE_CLOSURE_DRIFT')
        for row in value['members']:
            member=_read_relative(repo_fd,row['path'],max(1048576,row['bytes']+1),private=False)
            if len(member)!=row['bytes'] or hashlib.sha256(member).hexdigest()!=row['sha256']:raise StagingError('SOURCE_CLOSURE_DRIFT')
    finally:_close_parent(repo_fd)

def rollback_disposable(root:Path,external_root:Path,*,source_parent:Path,deployment_parent:Path,expected:dict)->None:
    source_parent=Path(source_parent).absolute();deployment_parent=Path(deployment_parent).absolute();root=Path(root).absolute();external_root=Path(external_root).absolute()
    if root.parent!=source_parent or external_root.parent!=deployment_parent:raise StagingError('ROLLBACK_ROOT_INVALID')
    source_name=_basename(root.name);deployment_name=_basename(external_root.name);sfd=_open_parent(source_parent);dfd=_open_parent(deployment_parent);source_root_fd=deployment_root_fd=-1;journal=None
    try:
        source_root_fd=_open_dir_at(sfd,source_name);deployment_root_fd=_open_dir_at(dfd,deployment_name);source_rows=_inventory_fd(source_root_fd);deployment_rows=_inventory_fd(deployment_root_fd);host_hash=_host_receipt_hash(deployment_root_fd);binding,token=_validate_receipt(expected,source_name,deployment_name,source_rows,deployment_rows,host_hash);_verify_closure_descriptor(expected['source_closure'])
        manifest,_=_read_relative_json(source_root_fd,'.job-runtime/config/staging-manifest.json');allocation,_=_read_relative_json(source_root_fd,'.job-runtime/config/fable-dq-allocation.json');pointer,_=_read_relative_json(source_root_fd,'.job-runtime/setup/host-deployment.json');host,host_raw=_read_relative_json(deployment_root_fd,'deployment-receipt.json')
        if manifest.get('activation') is not False or any(job.get('enabled') is not False for job in allocation.get('jobs',[])) or host.get('workspace_id')!=binding['workspace_id'] or host.get('service_label')!=binding['service_label'] or host.get('watchdog_label')!=binding['watchdog_label'] or pointer!={'schema_version':1,'workspace_id':binding['workspace_id'],'receipt_sha256':hashlib.sha256(host_raw).hexdigest(),'service_label':binding['service_label']}:raise StagingError('ROLLBACK_ACTIVE_OR_MISMATCH')
        parent_ids={'source':_fd_identity(sfd),'deployment':_fd_identity(dfd)};journal={'schema_version':2,'record_type':'fable_rollback','state':'PREPARED','token':token,'binding':binding,'source':{'parent':parent_ids['source'],'original':source_name,'staged':_stage_name(source_name,token),'inventory':source_rows},'deployment':{'parent':parent_ids['deployment'],'original':deployment_name,'staged':_stage_name(deployment_name,token),'inventory':deployment_rows},'receipt_sha256':_binding_hash(binding),'journal_sha256':''};_validate_journal(_persist_journal(dfd,journal,create=True),token,parent_ids);journal=_read_journal_at(dfd,_journal_name(token));_validate_journal(journal,token,parent_ids);_scan_token_namespace(sfd,dfd,journal)
        os.close(source_root_fd);source_root_fd=-1;os.close(deployment_root_fd);deployment_root_fd=-1
        _fault('rename_deployment');_fault('before_rename_deployment');os.rename(deployment_name,journal['deployment']['staged'],src_dir_fd=dfd,dst_dir_fd=dfd);_fault('after_rename_deployment');_fsync(dfd,'deployment_parent_stage');journal=dict(journal);journal['state']='DEPLOYMENT_STAGED';journal=_persist_journal(dfd,journal)
        _fault('before_rename_source');os.rename(source_name,journal['source']['staged'],src_dir_fd=sfd,dst_dir_fd=sfd);_fault('after_rename_source');_fsync(sfd,'source_parent_stage');journal=dict(journal);journal['state']='BOTH_STAGED';journal=_persist_journal(dfd,journal)
        _verify_named_inventory(sfd,journal['source']['staged'],source_rows);_verify_named_inventory(dfd,journal['deployment']['staged'],deployment_rows);_fault('commit');journal=dict(journal);journal['state']='RETIRED_COMMITTED';journal=_persist_journal(dfd,journal);_validate_journal(journal,token,parent_ids)
    except BaseException:
        if journal is not None and journal.get('state')!='RETIRED_COMMITTED':
            try:
                disk=_read_journal_at(dfd,_journal_name(journal['token']));disk=_validate_journal(disk,journal['token'],{'source':_fd_identity(sfd),'deployment':_fd_identity(dfd)})
                if disk['state']!='RETIRED_COMMITTED':_restore_precommit(sfd,dfd,disk)
            except Exception:pass
        raise
    finally:
        for fd in (source_root_fd,deployment_root_fd):
            if fd>=0:os.close(fd)
        for fd in (sfd,dfd):
            if fd>=0:_close_parent(fd)

def recover_rollback(source_parent:Path,deployment_parent:Path,journal_path:Path):
    source_parent=Path(source_parent).absolute();deployment_parent=Path(deployment_parent).absolute();journal_path=Path(journal_path).absolute()
    if journal_path.parent!=deployment_parent:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    name=_basename(journal_path.name);match=__import__('re').fullmatch(r'\.fable-rollback-([0-9a-f]{32})\.json',name)
    if not match:raise StagingError('ROLLBACK_JOURNAL_INVALID')
    token=match.group(1);sfd=_open_parent(source_parent);dfd=_open_parent(deployment_parent)
    try:
        journal=_validate_journal(_read_journal_at(dfd,name),token,{'source':_fd_identity(sfd),'deployment':_fd_identity(dfd)});_scan_token_namespace(sfd,dfd,journal);temp=_journal_temp_name(token)
        try:
            temp_value=_strict_json(_read_file_at(dfd,temp));_validate_journal(temp_value,token,{'source':_fd_identity(sfd),'deployment':_fd_identity(dfd)});os.unlink(temp,dir_fd=dfd);_fsync(dfd,'journal_temp_cleanup')
        except StagingError:
            try:os.stat(temp,dir_fd=dfd,follow_symlinks=False)
            except FileNotFoundError:pass
            else:raise
        if journal['state']=='RETIRED_COMMITTED':
            if _namespace(sfd,dfd,journal)!=(False,True,False,True):raise StagingError('ROLLBACK_COMMITTED_STATE_INVALID')
            _verify_named_inventory(sfd,journal['source']['staged'],journal['source']['inventory']);_verify_named_inventory(dfd,journal['deployment']['staged'],journal['deployment']['inventory']);return 'RETIRED_COMMITTED'
        journal=_restore_precommit(sfd,dfd,journal);return 'RECOVERED'
    finally:_close_parent(sfd);_close_parent(dfd)
