"""Niulai allocation adapter. Generic scheduling infrastructure never imports it."""
from pathlib import Path
import json
import os
import subprocess
import re


def prepare_readiness(options, workspace, context):
    # Business admission remains with Niulai. The current allocation is a
    # read-only readiness job until delivery ownership is cut over separately.
    if set(options) != {'policy','actor','python'}:
        return {'status':'failed','code':'NIULAI_ALLOCATION_INVALID'}
    root=Path(workspace).resolve();python=(root/options['python']).absolute()
    if not python.is_file() or '..' in Path(options['python']).parts or not python.is_relative_to(root/'.niulai-state') or not python.resolve().is_relative_to(root/'.niulai-state'):
        return {'status':'failed','code':'NIULAI_JOB_PYTHON_UNAVAILABLE'}
    env={k:os.environ[k] for k in ('PATH','HOME','USER','LANG','SSL_CERT_FILE','SSL_CERT_DIR') if k in os.environ}
    env.update(PYTHONPATH=str(root/'niulai-runtime'),PYTHONDONTWRITEBYTECODE='1',TMPDIR=str(root/'.niulai-state/tmp'))
    cp=subprocess.run([str(python),'-m','niulai_runtime.wake','--workspace',str(root),
                       '--config',str(root/options['policy']),'--actor',options['actor']],
                      cwd=root,env=env,capture_output=True,text=True,timeout=30)
    if cp.returncode:return {'status':'failed','code':'NIULAI_ADMISSION_FAILED'}
    result=json.loads(cp.stdout)
    if not result['admission']['allowed']:
        return {'status':'succeeded','code':'NIULAI_BUSINESS_GATE_SKIPPED','receipt':{'admission':result}}
    return {'niulai_admission':result,'email_enabled':False,'purpose':'scheduled_readiness'}


def prepare_e2e(options,workspace,context):
    from .config import load_config
    if set(options)!={'delivery_policy','request_id','session'} or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',options['request_id']):
        return {'status':'failed','code':'E2E_ALLOCATION_INVALID'}
    root=Path(workspace).resolve();policy=load_config(root/options['delivery_policy'],root)
    if policy.mode!='manual_test' or policy.production_enabled:return {'status':'failed','code':'E2E_TEST_POLICY_REQUIRED'}
    return {'workspace':str(root),'purpose':'authorized_one_time_full_scheduled_e2e',
            'request_id':options['request_id'],'session':options['session'],'recipient':policy.recipient,
            'delivery_policy':str(root/options['delivery_policy']),
            'output_directory':str(root/'.niulai-state/e2e'/options['request_id']),
            'tiger_policy':str(root/'.niulai-state/config/tiger.json')}


def verify_e2e(options,workspace,context,result):
    from datetime import datetime
    from .config import load_config
    from .scheduler import admit
    from .delivery import Outbox
    from .e2e_guard import validate
    from .delivery import assert_content_parity
    from .replay import from_raw
    root=Path(workspace).resolve();policy=load_config(root/options['delivery_policy'],root)
    scheduled=datetime.fromisoformat(context['scheduled_at'])
    admission=admit(policy,scheduled,None,policy.scheduler_owner,manual_request_id=options['request_id'])
    row=Outbox(policy.state_root/'databases/outbox.sqlite',root).get(admission.delivery_key)
    transport=result.get('receipt',{});final=transport.get('final',{})
    tools=transport.get('tool_names',[])
    if not all(any(suffix in name.replace('__','.') for name in tools) for suffix in ('gmail.send_email','gmail.read_email','sites.get_site')):
        return {'verified':False}
    summary_only=(transport.get('summary_parse_failure',{}).get('category')=='format' and transport.get('turn_completed') is True and transport.get('exit_code')==0 and not transport.get('tool_failures'))
    if not row or row['status']!='accepted' or not row['verified_at']:
        return {'verified':False}
    if not summary_only and row['message_id']!=(final.get('message_id') or final.get('email_message_id')):return {'verified':False}
    out=root/'.niulai-state/e2e'/options['request_id'];payload=json.loads((out/'email_payload.json').read_text())
    fp=validate(root,out,payload,policy.recipient,options['request_id'])
    readback=out/'gmail_readback.b64'
    if readback.is_symlink() or not readback.is_file():return {'verified':False}
    assert_content_parity(payload,from_raw(readback.read_text(),policy.recipient),policy.recipient,policy.recipient)
    totals=json.loads((out/'holdings/daily.json').read_text())['accounts'][0]['position_totals']
    fetched=datetime.fromisoformat(totals['snapshot_query_at'].replace('Z','+00:00'))
    if fetched<scheduled or fp['digest']!=row['digest']:return {'verified':False}
    return {'verified':True,'message_id':row['message_id'],'verified_at':row['verified_at'],'payload_digest':fp['digest'],'fresh_holdings_after_schedule':True}
