"""Codex-facing fixed calculation request; the host owns worker isolation."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import time

from .runner import ROOT, STATE, state_path


def request(change, attempt, scheduled_at):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',change) or not re.fullmatch('[0-9a-f-]{36}',attempt):
        raise ValueError('CALCULATION_REQUEST_ID_INVALID')
    if datetime.fromisoformat(scheduled_at).tzinfo is None:raise ValueError('SCHEDULE_TIME_INVALID')
    folder=STATE/'bridge'/attempt
    for path in [folder,*folder.parents]:
        if path==ROOT:break
        if path.is_symlink():raise ValueError('CALCULATION_BRIDGE_SYMLINK')
    ready=folder/'ready.json'
    if not ready.is_file() or ready.is_symlink() or ready.stat().st_size>2048:
        raise ValueError('CALCULATION_BRIDGE_NOT_PREPARED')
    value=json.loads(ready.read_text())
    if value.get('change_id')!=change or value.get('attempt_id')!=attempt or value.get('scheduled_at')!=scheduled_at:
        raise ValueError('CALCULATION_BRIDGE_CONTEXT_MISMATCH')
    if set(value)!={'change_id','attempt_id','scheduled_at','candidate_sha256'}:
        raise ValueError('CALCULATION_BRIDGE_FIELDS_INVALID')
    if not re.fullmatch('[0-9a-f]{64}',value['candidate_sha256']):raise ValueError('CALCULATION_PIN_INVALID')
    path=state_path(STATE/'client'/attempt/'request.json')
    if not path.parent.is_dir():raise ValueError('CALCULATION_INBOX_NOT_PREPARED')
    try:
        fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    except FileExistsError:
        if path.is_symlink() or path.stat().st_size>2048 or json.loads(path.read_text())!=value:
            raise ValueError('CALCULATION_REQUEST_CONFLICT')
    else:
        with os.fdopen(fd,'w') as stream:
            json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
    deadline=time.monotonic()+800
    response=folder/'response.json'
    while not response.exists():
        if time.monotonic()>deadline:raise TimeoutError('CALCULATION_RESPONSE_TIMEOUT')
        time.sleep(.3)
    if response.is_symlink() or response.stat().st_size>8192:raise ValueError('CALCULATION_RESPONSE_INVALID')
    result=json.loads(response.read_text())
    if result.get('status')=='completed':
        expected=STATE/'runs'/('scheduled-'+attempt)
        if Path(result['report_directory']).resolve()!=expected.resolve():
            raise ValueError('CALCULATION_RESULT_PATH_MISMATCH')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--change-id',required=True)
    p.add_argument('--attempt-id',required=True);p.add_argument('--scheduled-at',required=True)
    a=p.parse_args();result=request(a.change_id,a.attempt_id,a.scheduled_at)
    print(json.dumps(result));raise SystemExit(0 if result.get('status')=='completed' else 2)
