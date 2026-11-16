"""Owner-private atomic allocation transactions; never opens scheduler SQLite."""
from __future__ import annotations
import fcntl,hashlib,json,os,secrets,stat
from pathlib import Path
from .config import inside,read_json,load_projection
from .engine import validate_job
from .provider_contract import ReplayEffect

class AllocationError(ValueError):pass

def _canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()
def _sha(raw):return hashlib.sha256(raw).hexdigest()
def _structural(job,version):
    if type(job) is not dict:raise AllocationError('JOB_INVALID')
    candidate=dict(job)
    if version==1:
        candidate.setdefault('replay_safe',False)
    else:
        required={'id','enabled','schedule','model_profile','prompt_file','replay_contract'}
        if set(candidate)!=required or type(candidate['replay_contract']) is not dict:raise AllocationError('JOB_KEYS_INVALID')
        candidate['replay_safe']=candidate['replay_contract'].get('effect')==ReplayEffect.NONE.value
        candidate.pop('replay_contract')
    try:validate_job(candidate)
    except Exception as error:raise AllocationError(str(error) if str(error).isupper() else 'JOB_INVALID') from None

def _documents(workspace,config_path):
    root=Path(workspace).resolve(strict=True);config_path=inside(config_path,root,True);config=read_json(config_path);docs=[]
    for relative in config['allocation_files']:
        path=inside(root/relative,root,True);value=read_json(path);docs.append((path,value))
    return root,config_path,config,docs

def validate_all(workspace,config_path):
    root,_,config,docs=_documents(workspace,config_path);seen=set();count=0
    for _path,doc in docs:
        if set(doc)!={'schema_version','jobs'} or doc['schema_version']!=config['schema_version'] or type(doc['jobs']) is not list:raise AllocationError('ALLOCATION_SCHEMA_INVALID')
        for job in doc['jobs']:
            _structural(job,config['schema_version'])
            if job.get('model_profile') not in config['model_profiles']:raise AllocationError('MODEL_PROFILE_NOT_FOUND')
            if job['id'] in seen:raise AllocationError('DUPLICATE_JOB_ID')
            seen.add(job['id']);count+=1
    load_projection(config_path,root)
    return {'schema_version':1,'status':'valid','jobs':count,'runtime_schema':config['schema_version']}

def list_jobs(workspace,config_path):
    _root,_path,_config,docs=_documents(workspace,config_path)
    return [dict(job) for _path,doc in docs for job in doc['jobs']]

def _lock(root):
    path=root/'.job-runtime/config/allocation.lock'
    if path.is_symlink():raise AllocationError('ALLOCATION_LOCK_INVALID')
    fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);fcntl.flock(fd,fcntl.LOCK_EX);return fd

def _target(root,config,allocation_path):
    path=inside(allocation_path,root,True)
    allowed={inside(root/relative,root,True) for relative in config['allocation_files']}
    if path not in allowed:raise AllocationError('ALLOCATION_NOT_REGISTERED')
    info=os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)&0o077:raise AllocationError('ALLOCATION_FILE_INVALID')
    return path

def _publish(path,expected,document):
    raw=_canonical(document);parent=path.parent;dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);tmp=None
    try:
        if _sha(path.read_bytes())!=expected:raise AllocationError('ALLOCATION_CONFLICT')
        for _ in range(32):
            tmp='.allocation-'+secrets.token_hex(12)
            try:fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=dirfd);break
            except FileExistsError:continue
        else:raise AllocationError('ALLOCATION_TEMP_UNAVAILABLE')
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        if _sha(path.read_bytes())!=expected:raise AllocationError('ALLOCATION_CONFLICT')
        os.replace(tmp,path.name,src_dir_fd=dirfd,dst_dir_fd=dirfd);tmp=None;os.fsync(dirfd)
    finally:
        if tmp is not None:
            try:os.unlink(tmp,dir_fd=dirfd)
            except OSError:pass
        os.close(dirfd)
    return _sha(raw),len(raw)

def add_job(workspace,config_path,allocation_path,job):
    root=Path(workspace).resolve(strict=True);fd=_lock(root)
    try:
        root,_,config,docs=_documents(root,config_path)
        path=_target(root,config,allocation_path);raw=path.read_bytes();doc=json.loads(raw);candidate=dict(job);candidate['enabled']=False
        if any(existing['id']==candidate.get('id') for _path,current in docs for existing in current['jobs']):raise AllocationError('DUPLICATE_JOB_ID')
        _structural(candidate,config['schema_version']);doc['jobs'].append(candidate)
        # Validate the complete candidate set before replacing bytes.
        for current in doc['jobs']:_structural(current,config['schema_version'])
        new,size=_publish(path,_sha(raw),doc)
        return {'schema_version':1,'status':'updated','old_sha256':_sha(raw),'new_sha256':new,'bytes':size,'changed_ids':[candidate['id']],'reload_required':True}
    finally:os.close(fd)

def set_enabled(workspace,config_path,job_id,enabled):
    if type(enabled) is not bool:raise AllocationError('ENABLED_INVALID')
    root=Path(workspace).resolve(strict=True);fd=_lock(root)
    try:
        root,_,config,docs=_documents(root,config_path)
        matches=[(path,doc,index) for path,doc in docs for index,job in enumerate(doc['jobs']) if job.get('id')==job_id]
        if len(matches)!=1:raise AllocationError('JOB_NOT_FOUND' if not matches else 'DUPLICATE_JOB_ID')
        path,doc,index=matches[0];path=_target(root,config,path);raw=path.read_bytes();doc['jobs'][index]={**doc['jobs'][index],'enabled':enabled}
        for current in doc['jobs']:_structural(current,config['schema_version'])
        new,size=_publish(path,_sha(raw),doc)
        return {'schema_version':1,'status':'updated','old_sha256':_sha(raw),'new_sha256':new,'bytes':size,'changed_ids':[job_id],'reload_required':True}
    finally:os.close(fd)
