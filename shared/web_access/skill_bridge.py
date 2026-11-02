"""Closed public-read host capability for the native slash acceptance slice.

The model can write one request ID; it cannot choose URL, code, browser config,
output root or retry policy. Authoritative source receipts stay outside its
writable client directory. No server, TCP port or long-lived worker is added.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid

from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import ROOT, private_path, require, read as artifact, save, digest
from .egolite import _execute, read
from .policy import Session, load_config

CLIENT=ROOT/'.job-runtime/acceptance/egolite-slash-20261102/client'
HOST=ROOT/'.niulai-state/reports/research-sources/egolite-slash-20261102/host'
URL='https://lite.ego.app/document/en/docs/codex'


def client(operation, *, timeout=90):
    require(str(uuid.UUID(operation))==operation,'SKILL_BRIDGE_OPERATION_INVALID')
    folder=CLIENT/operation
    require(folder.is_dir() and not folder.is_symlink(),'SKILL_BRIDGE_CLIENT_NOT_PREPARED')
    request={'schema_version':1,'action':'egolite.vendor_guide','operation_id':operation}
    path=folder/'request.json'
    if not path.exists():
        # A complete request becomes visible at once and never replaces another.
        pending=folder/('.request-'+str(uuid.uuid4()))
        fd=os.open(pending,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(request,f);f.flush();os.fsync(f.fileno())
        try:os.link(pending,path)
        except FileExistsError:pass
        finally:pending.unlink()
    require(not path.is_symlink() and json.loads(path.read_text())==request,'SKILL_BRIDGE_REQUEST_CONFLICT')
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        response=folder/'response.json'
        if response.exists():
            require(not response.is_symlink() and response.stat().st_size<=16384,'SKILL_BRIDGE_RESPONSE_INVALID')
            value=json.loads(response.read_text());require(value.get('operation_id')==operation,'SKILL_BRIDGE_RESPONSE_BINDING')
            return value
        time.sleep(.1)
    return {'status':'unknown','code':'SKILL_BRIDGE_RESPONSE_PENDING','operation_id':operation}


class Host:
    def __init__(self,operation,*,reader=read,resume=False):
        require(str(uuid.UUID(operation))==operation,'SKILL_BRIDGE_OPERATION_INVALID')
        self.operation=operation;self.reader=reader;self.done=False
        self.client=CLIENT/operation
        if resume:
            require(self.client.is_dir() and not self.client.is_symlink() and not list(self.client.iterdir())
                and not (HOST/operation/'claim.json').exists(),'SKILL_BRIDGE_RESUME_UNSAFE')
        else:self.client.mkdir(parents=True,exist_ok=False,mode=0o700)
        self.out=private_path(HOST/operation,create=True)
        self.config=load_config(ROOT/'.research-sources/web-access/config/egolite-installed.json')
        self.request={'schema_version':1,'action':'egolite.vendor_guide','operation_id':operation}

    def tick(self,remaining_seconds=90):
        if self.done:return
        path=self.client/'request.json'
        if not path.exists():return
        require(not path.is_symlink() and path.stat().st_size<=4096 and json.loads(path.read_text())==self.request,
                'SKILL_BRIDGE_REQUEST_REJECTED')
        claim=self.out/'claim.json'
        # Unknown old claim is held, never interpreted as permission to retry.
        fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:
            json.dump({'request':self.request,'claimed_at':datetime.now(timezone.utc).isoformat(),
                       'config_sha256':digest(self.config)},f);f.flush();os.fsync(f.fileno())
        self.done=True
        started=time.monotonic()
        try:
            require(remaining_seconds>1,'SKILL_BRIDGE_DEADLINE_BEFORE_DISPATCH')
            guide=_execute([self.config['egolite']['executable'],'skill'],'',min(15,remaining_seconds),65536,self.out)
            require(b'[ego-browser:skill] end of guide v2.2.0' in guide,'SKILL_BRIDGE_GUIDE_INVALID')
            decision=Session(self.config).plan(operation='read',url=URL,interactive=True)
            decision['timeout_seconds']=min(decision['timeout_seconds'],remaining_seconds-(time.monotonic()-started))
            require(decision['timeout_seconds']>0,'SKILL_BRIDGE_DEADLINE_BEFORE_DISPATCH')
            result=self.reader(self.config,decision,
                output_directory=self.out)
            result={**result,'guide_sha256':hashlib.sha256(guide).hexdigest()}
        except Exception:
            result={'status':'blocked','code':'SKILL_BRIDGE_HOST_FAILED','effect_state':'unknown'}
        authoritative={**result,'operation_id':self.operation,'request':self.request,'config_sha256':digest(self.config)}
        ref=save(self.out,authoritative)
        atomic(self.out/'result.json',ref)
        atomic(self.client/'response.json',{'operation_id':self.operation,'status':result['status'],'result_ref':ref})

    def verify(self):
        path=self.out/'result.json'
        if not path.exists():return {'verified':False,'code':'SKILL_BRIDGE_RESULT_MISSING'}
        ref=json.loads(path.read_text());r=artifact(ref)
        require(r.get('request')==self.request and r.get('operation_id')==self.operation,'SKILL_BRIDGE_RESULT_BINDING')
        if r.get('status')!='observed':return {'verified':False,'code':'SKILL_BRIDGE_BROWSER_BLOCKED','result_ref':ref}
        o=artifact(r['receipt_ref']);text=artifact(o['snapshot_ref'],json_value=False).decode()
        verified=(o['observed_url']==URL and o['requested_url']==URL and o['cleanup_verified'] is True
            and not o['truncated'] and o['config_sha256']==digest(self.config)
            and all(re.search(p,text,re.I) for p in ('Step 5','complete the task','Troubleshooting')))
        return {'verified':bool(verified),'result_ref':ref,'observation_ref':r['receipt_ref'],
                'task_space':o['task_space'],'code':'SKILL_BRIDGE_SOURCE_VERIFIED' if verified else 'SKILL_BRIDGE_SOURCE_INCOMPLETE'}
