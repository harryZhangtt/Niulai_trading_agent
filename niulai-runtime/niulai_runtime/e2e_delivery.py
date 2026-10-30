"""One explicitly authorized scheduled test email; separate from production slots."""
import argparse,json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from .config import load_config,assert_recipient,ConfigError
from .scheduler import admit
from .delivery import Outbox,DeliveryError,assert_content_parity
from .replay import from_raw,private_file

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['compose','prepare','claim','accepted','unknown','verify','status'])
    for n in ('workspace','config','request-id','payload'):p.add_argument('--'+n,required=True)
    p.add_argument('--attempt-id');p.add_argument('--message-id');p.add_argument('--readback');a=p.parse_args();os.umask(0o077)
    root=Path(a.workspace).resolve(strict=True);config=load_config(a.config,root)
    if config.mode!='manual_test' or config.production_enabled:raise DeliveryError('TEST_POLICY_REQUIRED')
    admission=admit(config,datetime.now(timezone.utc),None,config.scheduler_owner,manual_request_id=a.request_id)
    if not admission.allowed:raise DeliveryError(admission.reason)
    path=private_file(a.payload,root);key=admission.delivery_key
    if a.action=='compose':
        from .e2e_guard import compose
        if path.exists():raise DeliveryError('FRESH_PAYLOAD_REQUIRED')
        payload=compose(root,path.parent,config.recipient,a.request_id)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(payload,stream,ensure_ascii=False)
        print(json.dumps({'status':'composed','payload_saved':True}));return
    payload=json.loads(path.read_text())
    if a.action in ('prepare','claim','verify'):
        from .e2e_guard import validate
        validate(root,path.parent,payload,config.recipient,a.request_id)
    outbox=Outbox(config.state_root/'databases/outbox.sqlite',root)
    if a.action in ('prepare','claim'):
        profile=json.load(sys.stdin);assert_recipient(config,profile.get('email'),payload.get('to'))
        if a.action=='prepare':
            row=outbox.prepare(key,payload,recipient=config.recipient,profile_email=profile['email'])
            print(json.dumps({'status':row['status'],'digest':row['digest']}))
        else:print(json.dumps(outbox.claim(key,a.attempt_id),ensure_ascii=False))
    elif a.action=='accepted':print(json.dumps(outbox.accepted(key,a.attempt_id,a.message_id)))
    elif a.action=='unknown':print(json.dumps(outbox.unknown(key,a.attempt_id)))
    elif a.action=='verify':
        row=outbox.get(key)
        if not row or row['status']!='accepted' or row['message_id']!=a.message_id:raise DeliveryError('ACCEPTED_RECEIPT_REQUIRED')
        actual=from_raw(private_file(a.readback,root).read_text(),config.recipient)
        fp=assert_content_parity(payload,actual,config.recipient,config.recipient)
        print(json.dumps(outbox.reconcile_accepted(key,message_id=a.message_id,verified_digest=fp['digest'])))
    else:print(json.dumps(outbox.get(key)))

if __name__=='__main__':
    try:main()
    except Exception as e:
        code=str(e) if isinstance(e,(ConfigError,DeliveryError)) else 'TEST_DELIVERY_FAILED'
        print(json.dumps({'status':'failed','error':code}));raise SystemExit(2)
