"""Host-authored public-only probe executed after native skill selection.

One durable operation key, one guide check and one bounded source read. An
existing claim never permits another browser attempt, including after a crash.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from shared.research_sources.artifacts import ROOT, private_path, read as artifact, save, require
from shared.job_runtime.service import atomic
from .egolite import _execute, read
from .policy import Session, load_config

DIRECTORY=ROOT/'.niulai-state/reports/research-sources/egolite-slash-20261102'
URL='https://lite.ego.app/document/en/docs/codex'


def probe(operation):
    require(str(uuid.UUID(operation))==operation,'SKILL_PROBE_OPERATION_INVALID')
    out=private_path(DIRECTORY/operation,create=True)
    claim=out/'claim.json'
    fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:
        json.dump({'operation':operation,'status':'started','started_at':datetime.now(timezone.utc).isoformat()},f)
        f.flush();os.fsync(f.fileno())
    config=load_config(ROOT/'.research-sources/web-access/config/egolite-installed.json')
    guide=_execute([config['egolite']['executable'],'skill'],'',15,65536,out)
    require(b'[ego-browser:skill] end of guide v2.2.0' in guide,'SKILL_PROBE_GUIDE_INCOMPLETE')
    result=read(config,Session(config).plan(operation='read',url=URL,interactive=True),output_directory=out)
    observation=artifact(result['receipt_ref'])
    check={'operation':operation,'status':result['status'],'observation_ref':result['receipt_ref'],
        'guide_sha256':hashlib.sha256(guide).hexdigest(),'finished_at':datetime.now(timezone.utc).isoformat()}
    ref=save(out,check)
    atomic(out/'result.json',ref)
    return {'status':result['status'],'result_ref':ref}


def main():
    p=argparse.ArgumentParser();p.add_argument('--operation',required=True);args=p.parse_args()
    try:r=probe(args.operation)
    except PermissionError:r={'status':'blocked','code':'SKILL_PROBE_PERMISSION_DENIED'}
    except FileExistsError:r={'status':'blocked','code':'SKILL_PROBE_ALREADY_CLAIMED'}
    except Exception:r={'status':'blocked','code':'SKILL_PROBE_FAILED'}
    print(json.dumps(r));return 0 if r['status']=='observed' else 2


if __name__=='__main__':raise SystemExit(main())
