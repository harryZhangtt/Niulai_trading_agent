"""Isolated, explicit Gmail/Sites business execution; raw tool data stays in RAM.

Readiness execution remains in model.py with tools disabled. This adapter does
not retry, install/connect plugins, change permissions, or select another model.
"""
from __future__ import annotations
from datetime import datetime, timezone
from collections.abc import Mapping
import base64
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import time

from .model import ModelError, _classify, _environment, _private_path, _profile, _require, _terminate

# Exact-source execution injects the digest of the held bytes it compiled.
# Ordinary imports intentionally expose no attested source identity.
IMPLEMENTATION_SHA256 = globals().get('_EXECUTED_SOURCE_SHA256')

GMAIL = 'connector_2128aebfecb84f64a069897515042a44'
SITES = 'connector_20205bf7d4e99a89d7154bb849718324'
BASE = {'codex_bin','model','effort','timeout_seconds','auth_home','max_output_bytes'}
CAPS = {'apps','shell','phase'}
OPTIONAL_CAPS = {'approval_mode','writable_roots'}
SECRET = re.compile(r'(?i)(?:\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|'
                    r'\bbearer\s+[A-Za-z0-9._-]+|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}|'
                    r'\b(?:access_token|refresh_token|client_secret|siwc_bypass_bearer_token)\b)')
GMAIL_ID = re.compile(r'[0-9a-fA-F]{8,64}')
EVENT_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{7,127}')
SHA256 = re.compile(r'[0-9a-f]{64}')
GMAIL_EVIDENCE = frozenset({'message_id','email_thread_id','send_event_id','read_event_id',
                            'recipient_sha256','subject_sha256','body_sha256','html_sha256',
                            'attachments_sha256','delivery_payload_sha256','sender_identity_sha256',
                            'raw_readback_sha256','readback_verified_at'})
GMAIL_CLAIM_COMMON = frozenset({'schema_version','job_id','slot_id','attempt_id','host','run','candidate',
                                'mode','delivery_payload_sha256','recipient_sha256','subject_sha256',
                                'sender_identity_sha256','profile_identity_sha256','payload_sha256'})


class SummaryError(ModelError):
    """Field names/codes are fixed by this module; rejected values stay in RAM."""
    def __init__(self, code, field=None, category='format'):
        super().__init__(code)
        self.field=field
        self.category=category


def _summary_require(condition, field, category='format'):
    if not condition:
        raise SummaryError('BUSINESS_FINAL_'+field.upper()+'_INVALID',field,category)


def _profile_caps(profile):
    _require(type(profile) is dict and CAPS <= profile.keys() and profile.keys() <= BASE | CAPS | OPTIONAL_CAPS,
             'BUSINESS_PROFILE_INVALID')
    _require(profile['phase'] in ('catalog','business'), 'BUSINESS_PHASE_INVALID')
    _require(type(profile['shell']) is bool and
             (profile['phase']=='business' or profile['shell'] is False),
             'BUSINESS_SHELL_POLICY_MISMATCH')
    approval=profile.get('approval_mode','never')
    _require(approval in ('never','automatic_review') and
             (profile['phase']=='business' or approval=='never'),'BUSINESS_APPROVAL_MODE_INVALID')
    _require('writable_roots' not in profile or profile['shell'],
             'BUSINESS_WRITABLE_ROOTS_INVALID')
    apps=profile['apps']
    _require(isinstance(apps,list) and 1 <= len(apps) <= 2 and len(set(apps))==len(apps)
             and all(x in (GMAIL,SITES) for x in apps), 'BUSINESS_APPS_POLICY_INVALID')
    return {k:v for k,v in profile.items() if k in BASE}


def _writable_roots(profile, workspace, auth_home):
    """Validate central-profile grants; job input/context cannot expand them."""
    if not profile['shell']:return []
    if 'writable_roots' in profile:
        roots=profile['writable_roots']
    else:
        # Preserve the existing Niulai profile's default capability. An explicit
        # list replaces this grant; it never silently adds Niulai state back.
        state=workspace/'.niulai-state'
        _require(state.is_dir() and not state.is_symlink(),'BUSINESS_PRIVATE_STATE_REQUIRED')
        roots=['.niulai-state']
    _require(isinstance(roots,list) and len(roots)<=8 and all(isinstance(x,str) for x in roots)
             and len(set(roots))==len(roots),'BUSINESS_WRITABLE_ROOTS_INVALID')
    resolved=[]
    for relative in roots:
        path=Path(relative)
        _require(bool(relative) and not path.is_absolute() and '..' not in path.parts
                 and bool(path.parts) and path.parts[0] in ('.job-runtime','.niulai-state'),
                 'BUSINESS_WRITABLE_ROOT_REJECTED')
        candidate=workspace/path
        allowed=workspace/path.parts[0]
        _require(candidate.resolve().is_relative_to(allowed.resolve()),'BUSINESS_WRITABLE_ROOT_REJECTED')
        for ancestor in [candidate,*candidate.parents]:
            if ancestor==workspace:break
            _require(not ancestor.is_symlink(),'BUSINESS_WRITABLE_ROOT_SYMLINK')
        _require(candidate.is_dir(),'BUSINESS_WRITABLE_ROOT_MISSING')
        _require(candidate.stat().st_uid==os.getuid(),'BUSINESS_WRITABLE_ROOT_OWNER')
        candidate=candidate.resolve()
        auth=Path(auth_home).resolve()
        _require(not candidate.is_relative_to(auth) and not auth.is_relative_to(candidate),
                 'BUSINESS_WRITABLE_AUTH_OVERLAP')
        _require(candidate not in resolved,'BUSINESS_WRITABLE_ROOTS_INVALID')
        resolved.append(candidate)
    return resolved


class _ObservedOutput(bytes):
    """RAM-only JSONL completion times captured by the pipe reader."""
    def __new__(cls, raw, observations):
        value=super().__new__(cls,raw);value.observations=observations;return value


def _stream(process, prompt, timeout, maximum, cancel):
    """Bounded multiplexed pipes; never write prompt, stdout or stderr to disk."""
    streams=selectors.DefaultSelector();out=bytearray();err=bytearray();sent=0;reason=None
    for pipe,kind,event in ((process.stdin,'stdin',selectors.EVENT_WRITE),
                            (process.stdout,'stdout',selectors.EVENT_READ),
                            (process.stderr,'stderr',selectors.EVENT_READ)):
        os.set_blocking(pipe.fileno(),False);streams.register(pipe,event,kind)
    observations=[];line_end=0
    deadline=time.monotonic()+timeout
    try:
        while streams.get_map():
            if time.monotonic()>=deadline:reason='BUSINESS_DEADLINE_EXCEEDED'
            elif cancel is not None and cancel.is_set():reason='BUSINESS_CANCELLED'
            if reason:
                _terminate(process);break
            for key,_ in streams.select(.05):
                if key.data=='stdin':
                    try:sent+=os.write(key.fileobj.fileno(),prompt[sent:sent+65536])
                    except BrokenPipeError:sent=len(prompt)
                    if sent==len(prompt):
                        streams.unregister(key.fileobj);key.fileobj.close()
                else:
                    try:chunk=os.read(key.fileobj.fileno(),65536)
                    except BlockingIOError:continue
                    if not chunk:
                        streams.unregister(key.fileobj);key.fileobj.close();continue
                    target=out if key.data=='stdout' else err
                    target.extend(chunk)
                    if key.data=='stdout':
                        observed=datetime.now(timezone.utc).isoformat()
                        while True:
                            boundary=out.find(b'\n',line_end)
                            if boundary<0:break
                            observations.append(observed);line_end=boundary+1
                    if len(out)+len(err)>maximum:
                        reason='BUSINESS_OUTPUT_LIMIT_EXCEEDED';_terminate(process);break
            if reason:break
        if process.poll() is None:
            remaining=deadline-time.monotonic()
            if remaining<=0:reason='BUSINESS_DEADLINE_EXCEEDED';_terminate(process)
            else:
                try:process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:reason='BUSINESS_DEADLINE_EXCEEDED';_terminate(process)
        return _ObservedOutput(bytes(out),observations),bytes(err),reason
    finally:
        streams.close()
        for pipe in (process.stdin,process.stdout,process.stderr):
            if pipe is not None and not pipe.closed:pipe.close()


def _metadata(raw, started=None, ended=None):
    gmail=_GmailObservation(started,ended)
    result={'completed':False,'failed':False,'thread_id':None,'usage':None,
            'observed_model':None,'tool_names':set(),'final':None,'errors':[],'parse_errors':0,
            'tool_failures':[]}
    for index,line in enumerate(raw.decode(errors='replace').splitlines()):
        if not line.strip():continue
        try:event=_json(line)
        except ValueError:result['parse_errors']+=1;gmail.bad=True;continue
        if not isinstance(event,dict):result['parse_errors']+=1;gmail.bad=True;continue
        observations=getattr(raw,'observations',())
        gmail.observe(event,observations[index] if index<len(observations) else None)
        kind=event.get('type')
        if kind=='thread.started':
            observed=event.get('thread_id')
            if isinstance(observed,str) and re.fullmatch(r'[A-Za-z0-9_-]{8,128}',observed):result['thread_id']=observed
        if isinstance(event.get('model'),str):result['observed_model']=event['model']
        if kind=='turn.completed':
            result['completed']=True;usage=event.get('usage')
            if isinstance(usage,dict):
                result['usage']={k:v for k,v in usage.items() if k in ('input_tokens','cached_input_tokens','output_tokens') and type(v)is int and v>=0}
        if kind in ('error','turn.failed'):
            result['failed']=True;e=event.get('error')
            message=e.get('message') if isinstance(e,dict) else event.get('message')
            if isinstance(message,str):result['errors'].append(message)
        item=event.get('item')
        if isinstance(item,dict):
            if kind=='item.completed' and item.get('type')=='agent_message' and isinstance(item.get('text'),str):
                result['final']=item['text']
            if item.get('type') in ('mcp_tool_call','tool_call','function_call','command_execution'):
                name=item.get('tool') or item.get('name') or item.get('type')
                if isinstance(name,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]{0,159}',name) and not SECRET.search(name):
                    result['tool_names'].add(name)
                    failures=[]
                    if item.get('error') is not None:
                        failures.extend(_error_texts({'isError':True,'error':item['error']}))
                    failures.extend(_error_texts(item.get('result')))
                    for message in failures:
                        code=_approval_failure(message)
                        if code:
                            row={'tool':name,'code':code,'dispatch_status':'rejected_before_dispatch'}
                            if row not in result['tool_failures']:result['tool_failures'].append(row)
    result['gmail_observation']=gmail.finish()
    return result


# Frozen host bridge v3: Codex 0.166 content/structured_content envelopes.
# No camelCase alias, model-authored evidence, replay or delivery authority.


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:raise ValueError('duplicate')
        value[key] = item
    return value


def _json(value):
    return json.loads(value, object_pairs_hook=_unique)


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


def _mailbox(value):
    if not isinstance(value,str):raise ValueError
    addresses=getaddresses([value])
    if len(addresses)!=1 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",addresses[0][1]):raise ValueError
    return addresses[0][1].lower()


def _validate_gmail_claim(claim, *, job_id=None, context=None):
    """Validate and detach an exact pre-send claim; optionally bind scheduler IDs."""
    if not isinstance(claim,Mapping):return None
    claim=dict(claim)
    raw=GMAIL_CLAIM_COMMON|({'body_sha256'} if claim.get('mode')=='text' else {'html_sha256','attachments_sha256'} if claim.get('mode')=='raw' else set())
    if set(claim)!=raw or type(claim.get('schema_version')) is not int or claim['schema_version']!=1:return None
    ids=('job_id','slot_id','attempt_id','host','run','candidate')
    if any(not isinstance(claim[k],str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,255}',claim[k]) or SECRET.search(claim[k]) for k in ids):return None
    hashes=set(claim)-set(ids)-{'schema_version','mode'}
    if any(not isinstance(claim[k],str) or not SHA256.fullmatch(claim[k]) for k in hashes):return None
    if _digest(_canonical({k:v for k,v in claim.items() if k!='payload_sha256'}))!=claim['payload_sha256']:return None
    if claim['sender_identity_sha256']!=claim['profile_identity_sha256']:return None
    if job_id is not None and claim['job_id']!=job_id:return None
    if context is not None and any(claim[k]!=context.get(k) for k in ('slot_id','attempt_id')):return None
    return json.loads(_canonical(claim))


def _encoded(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}',value):raise ValueError
    data=base64.b64decode(value+'='*(-len(value)%4),altchars=b'-_',validate=True)
    if value not in (base64.urlsafe_b64encode(data).decode(),base64.urlsafe_b64encode(data).decode().rstrip('=')):raise ValueError
    return data


def _result(value):
    if type(value)is not dict or not value or not set(value)<={'content','structured_content'}:raise ValueError
    variants=[]
    if 'structured_content' in value:
        data=value['structured_content']
        variants.append(_json(data) if isinstance(data,str) else data)
    if 'content' in value:
        content=value['content']
        if type(content)is not list or len(content)!=1 or type(content[0])is not dict or set(content[0])!={'type','text'} or content[0]['type']!='text':raise ValueError
        variants.append(_json(content[0]['text']))
    if any(type(v)is not dict or v!=variants[0] for v in variants):raise ValueError
    return variants[0]


def _gmail_claim_path(workspace, claim, namespace):
    key = _digest(_canonical([claim[k] for k in ('job_id','slot_id','attempt_id')]))
    directory = _private_path(Path(workspace)/'.job-runtime'/'gmail-claims'/namespace,
                              Path(workspace), directory=True)
    return _private_path(directory/(key+'.json'), Path(workspace))


def _check_gmail_claim(workspace,claim,namespace):
    path=_gmail_claim_path(workspace,claim,namespace)
    if not path.exists():return None
    try:
        previous=_json(path.read_text())
        digest=previous.get('payload_sha256') if isinstance(previous,dict) else previous
    except (OSError,ValueError):digest=None
    return ('RUNTIME_GMAIL_CLAIM_REPLAY' if digest==claim['payload_sha256']
            else 'RUNTIME_GMAIL_CLAIM_CONFLICT')


def _claim_phase(workspace,claim,phase):
    path=_gmail_claim_path(workspace,claim,'business')
    temporary=path.with_suffix('.phase-'+str(os.getpid()))
    try:
        with open(temporary,'x') as stream:
            os.chmod(temporary,0o600)
            stream.write(_canonical({'payload_sha256':claim['payload_sha256'],'phase':phase}))
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _consume_gmail_claim(workspace, claim, namespace):
    """Reserve durably before launch. Existing reservations fence crash ambiguity."""
    path=_gmail_claim_path(workspace,claim,namespace)
    try:fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    except FileExistsError:return _check_gmail_claim(workspace,claim,namespace)
    try:
        with os.fdopen(fd,'w') as stream:
            stream.write(_canonical({'payload_sha256':claim['payload_sha256'],'phase':'reserved'}))
            stream.flush();os.fsync(stream.fileno())
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return None


def _mime_payload(payload, encoded):
    """Reopen exact raw MIME and compare canonical maintained payload components."""
    raw=_encoded(encoded)
    message=BytesParser(policy=policy.default).parsebytes(raw)
    if message.defects or message.get_all('Cc') or message.get_all('Bcc'):raise ValueError
    if type(payload)is dict and set(payload)=={'to','subject','body'}:
        if message.is_multipart() or message.get_content_type()!='text/plain' or message.get_filename() or message.get_content_disposition() not in (None,'inline'):raise ValueError
        if any(len(message.get_all(k,[]))!=1 for k in ('To','From','Subject')):raise ValueError
        recipient=_mailbox(payload['to']);sender=_mailbox(str(message['From']))
        if _mailbox(str(message['To']))!=recipient or str(message['Subject'])!=payload['subject']:raise ValueError
        body=message.get_content()
        if body!=payload['body']:raise ValueError
        canonical={'sender':sender,'recipient':recipient,'subject':payload['subject'],'body':body}
        return dict(recipient_sha256=_digest(recipient),subject_sha256=_digest(payload['subject']),
                    sender_identity_sha256=_digest(sender),body_sha256=_digest(body),
                    delivery_payload_sha256=_digest(_canonical(canonical)),
                    raw_readback_sha256=hashlib.sha256(raw).hexdigest())
    if message.get_content_type()!='multipart/mixed':raise ValueError
    for header in ('To','From','Subject'):
        if len(message.get_all(header,[]))!=1:raise ValueError
    if type(payload)is not dict or not {'to','subject','payload'}<=payload.keys() or not set(payload)<={'to','subject','payload','from_address'}:raise ValueError
    recipient=_mailbox(payload['to']);sender=_mailbox(payload.get('from_address',str(message['From'])))
    if _mailbox(str(message['To']))!=recipient or _mailbox(str(message['From']))!=sender or str(message['Subject'])!=payload['subject']:raise ValueError
    tree=payload['payload']
    if type(tree)is not dict or set(tree)!={'mime_type','parts'} or tree['mime_type']!='multipart/mixed':raise ValueError
    expected=tree['parts'];actual=list(message.iter_parts())
    if type(expected)is not list or len(expected)!=3 or len(actual)!=3:raise ValueError
    html=[];attachments=[]
    for part,source in zip(actual,expected):
        if type(source)is not dict or not set(source)<={'mime_type','charset','content_disposition','filename','body'}:raise ValueError
        mime=source.get('mime_type');body=source.get('body')
        if type(body)is not dict:raise ValueError
        if set(body)=={'content'}:data=body['content'].encode(source.get('charset') or 'utf-8')
        elif set(body)=={'base64_url_content'}:data=_encoded(body['base64_url_content'])
        else:raise ValueError
        if part.is_multipart() or part.get_content_type()!=mime or part.get('Content-ID') or part.get_payload(decode=True)!=data or part.defects:raise ValueError
        if mime=='text/html':
            if part.get_filename() or part.get_content_disposition() not in (None,'inline') or source.get('filename') or source.get('content_disposition') not in (None,'inline'):raise ValueError
            html.append(data)
        elif mime=='application/pdf':
            name=source.get('filename')
            if part.get_filename()!=name or not name or source.get('content_disposition')!='attachment' or part.get_content_disposition()!='attachment':raise ValueError
            if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:raise ValueError
            attachments.append({'filename':name,'sha256':hashlib.sha256(data).hexdigest()})
        else:raise ValueError
    if len(html)!=1 or len(attachments)!=2 or len({x['filename'] for x in attachments})!=2:raise ValueError
    html_sha=hashlib.sha256(html[0]).hexdigest()
    canonical={'sender':sender,'recipient':recipient,'subject':payload['subject'],'html_sha256':html_sha,'attachments':attachments}
    return dict(recipient_sha256=_digest(recipient),subject_sha256=_digest(payload['subject']),
                sender_identity_sha256=_digest(sender),html_sha256=html_sha,
                attachments_sha256=_digest(_canonical(attachments)),
                delivery_payload_sha256=_digest(_canonical(canonical)),
                raw_readback_sha256=hashlib.sha256(raw).hexdigest())


class _GmailObservation:
    """Bounded first-pass collector. Retains at most one payload until readback.

    Arguments/results are transient; finish returns IDs, hashes, times and names.
    Times come from the first pipe read, never from parsing or model output.
    """
    def __init__(self, started=None, ended=None):
        self.started=started;self.ended=ended;self.bad=False;self.thread=None;self.completed=False;self.mode=None
        self.profile=None;self.payload=None;self.draft=None;self.draft_message=None;self.send=None
        self.draft_thread=None;self.draft_read=False;self.evidence=None;self.names=set();self.ids=set();self.agent_messages=0

    def observe(self,event,observed=None):
        if self.bad:return
        try:self._observe(event,observed)
        except (ValueError,TypeError,KeyError,AttributeError,UnicodeError,LookupError):
            self.bad=True;self.payload=None;self.evidence=None

    def _observe(self,event,observed):
        if self.completed:raise ValueError
        if event.get('type') in ('error','turn.failed'):raise ValueError
        if self.agent_messages and event.get('type')!='turn.completed':raise ValueError
        if event.get('type')=='turn.completed':
            if self.thread is None or self.agent_messages!=1:raise ValueError
            self.completed=True;return
        if event.get('type')=='thread.started':
            if self.completed:raise ValueError
            if self.thread is not None:raise ValueError
            self.thread=event.get('thread_id')
            if not isinstance(self.thread,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',self.thread):raise ValueError
        if event.get('type')!='item.completed':return
        item=event.get('item',{})
        if type(item)is not dict:raise ValueError
        if item.get('type')=='agent_message':
            self.agent_messages+=1
            if self.agent_messages!=1 or self.thread is None:raise ValueError
            return
        if item.get('type')!='mcp_tool_call':
            if (item.get('status') in ('failed','unknown','in_progress') or item.get('error') is not None
                    or _error_texts(item.get('result'))):raise ValueError
            other=item.get('tool') or item.get('name')
            if isinstance(other,str) and 'gmail' in other.lower():raise ValueError
            return
        name=item.get('tool')
        if not isinstance(name,str):raise ValueError
        short=name.removeprefix('mcp__codex_apps__')
        auxiliary=short in ('gmail_get_profile','sites_get_site','metadata_search')
        roles={'gmail_create_draft':'draft','gmail_send_draft':'send_draft',
               'gmail_send_email':'send','gmail_read_email':'read'}
        if short not in roles and not auxiliary:raise ValueError
        if self.thread is None or self.completed:raise ValueError
        role=roles.get(short,'auxiliary');self.names.add(name)
        if item.get('status')!='completed' or item.get('error') is not None:raise ValueError
        eid=item.get('id')
        if not isinstance(eid,str) or not EVENT_ID.fullmatch(eid) or SECRET.search(eid) or eid in self.ids:raise ValueError
        if len(self.ids)>=32:raise ValueError
        self.ids.add(eid)
        if not _aware_timestamp(observed):raise ValueError
        when=datetime.fromisoformat(observed.replace('Z','+00:00'))
        for bound,sign in ((self.started,1),(self.ended,-1)):
            if bound is not None:
                if not _aware_timestamp(bound):raise ValueError
                delta=(when-datetime.fromisoformat(bound.replace('Z','+00:00'))).total_seconds()
                if sign*delta < 0:raise ValueError
        args=item.get('arguments');args=_json(args) if isinstance(args,str) else args
        if type(args)is not dict:raise ValueError
        data=_result(item.get('result'))
        if len(json.dumps(data))>1024*1024 or _error_texts(data) or ('error' in data and data['error'] is not None) or data.get('isError') is True or data.get('is_error') is True or data.get('status') in ('error','failed','unknown','pending','in_progress'):raise ValueError
        if role=='auxiliary':
            if short=='gmail_get_profile':
                if self.profile is not None or self.payload is not None or self.send is not None or args:raise ValueError
                mailbox=data.get('emailAddress',data.get('email'))
                normalized=_mailbox(mailbox)
                if 'emailAddress' in data and 'email' in data and _mailbox(data['email'])!=normalized:raise ValueError
                self.profile=_digest(normalized)
            return
        if self.profile is None:raise ValueError
        for k in ('id','threadId'):
            if isinstance(data.get(k),str):data[k]=data[k].lower()
        if isinstance(args.get('message_id'),str):args['message_id']=args['message_id'].lower()
        if role=='draft':
            if 'payload' not in args:raise ValueError
            if self.payload is not None or self.send is not None:raise ValueError
            if set(data)!={'id','message'} or type(data['message'])is not dict:raise ValueError
            self.draft=data['id'];self.draft_message=data['message'].get('id');self.draft_thread=data['message'].get('threadId')
            if isinstance(self.draft_message,str):self.draft_message=self.draft_message.lower()
            if isinstance(self.draft_thread,str):self.draft_thread=self.draft_thread.lower()
            if not set(data['message'])<={'id','threadId','labelIds'} or any(not isinstance(v,str) or not GMAIL_ID.fullmatch(v) for v in (self.draft_message,self.draft_thread)):raise ValueError
            if not isinstance(self.draft,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',self.draft):raise ValueError
            self.mode='raw';self.payload=args;return
        if role in ('send','send_draft'):
            if self.send is not None:raise ValueError
            if role=='send_draft':
                if args!={'draft_id':self.draft} or not self.draft_read:raise ValueError
            else:
                if self.payload is not None:raise ValueError
                self.mode='text' if set(args)=={'to','subject','body'} else 'raw'
                self.payload=args
            if not {'id','threadId'}<=data.keys() or not set(data)<={'id','threadId','labelIds'}:raise ValueError
            if any(not isinstance(data[k],str) or not GMAIL_ID.fullmatch(data[k]) for k in ('id','threadId')):raise ValueError
            self.send=(eid,data['id'],data['threadId'],when);return
        if set(args)!={'message_id','format'} or args['format']!='raw':raise ValueError
        if not {'id','threadId','raw'}<=data.keys() or not set(data)<={'id','threadId','raw','labelIds'}:raise ValueError
        if args['message_id']!=data['id']:raise ValueError
        hashes=_mime_payload(self.payload,data['raw'])
        if self.send is None:
            if self.draft is None or self.draft_read or data['id']!=self.draft_message or data['threadId']!=self.draft_thread:raise ValueError
            self.draft_read=True;return
        sid,mid,tid,sent=self.send
        if self.draft_thread is not None and tid!=self.draft_thread:raise ValueError
        if self.evidence is not None or data['id']!=mid or data['threadId']!=tid or when<sent:raise ValueError
        self.evidence=dict(message_id=mid,email_thread_id=tid,send_event_id=sid,read_event_id=eid,
                           readback_verified_at=when.isoformat(),**hashes)
        self.payload=None

    def finish(self):
        if self.bad or self.thread is None or not self.completed or self.evidence is None:return None
        if self.profile is None or self.profile!=self.evidence['sender_identity_sha256']:return None
        self.evidence['profile_identity_sha256']=self.profile
        return self.evidence,sorted(self.names),self.mode


def _gmail_host_observation(raw, started=None, ended=None):
    return _metadata(raw,started,ended)['gmail_observation']


def _gmail_host_evidence(raw):
    observation=_gmail_host_observation(raw)
    return observation[0] if observation else None


def _gmail_receipt(observation, final, claim=None, workspace=None):
    """Strict variants; payload_sha256 binds every other claim field.

    The caller owns pre-dispatch provenance and current execution binding.
    """
    receipt={'final_evidence_trust':'untrusted_model_output'}
    if observation is not None:
        evidence,names,mode=observation
        receipt.update(gmail_operational_evidence=evidence,gmail_tool_names=names)
    checked_claim=_validate_gmail_claim(claim)
    if checked_claim is None:return receipt
    receipt['gmail_claim']=checked_claim
    if observation is None:return receipt
    components={'recipient_sha256','subject_sha256','sender_identity_sha256','profile_identity_sha256','delivery_payload_sha256'}
    components|={'body_sha256'} if checked_claim['mode']=='text' else {'html_sha256','attachments_sha256'}
    if mode!=checked_claim['mode'] or any(evidence.get(k)!=checked_claim[k] for k in components):return receipt
    try:
        if workspace is None:return receipt
        checked=_final(json.dumps(final),'business',Path(workspace).resolve())
    except (SummaryError,TypeError,ValueError):return receipt
    if checked.get('status') in ('failed','blocked'):return receipt
    if any(k in checked and checked[k]!=evidence[k] for k in GMAIL_EVIDENCE):return receipt
    receipt['final_evidence_trust']='trusted_operational_host_evidence'
    return receipt


def _error_texts(value, depth=0, error_context=False):
    """Inspect error envelopes only; never examine or return tool arguments."""
    if depth>8:return []
    if isinstance(value,dict):
        flagged=error_context or value.get('isError')is True or value.get('is_error')is True or value.get('status')in ('error','failed')
        result=[]
        for key in ('error','message','content','text','result','structuredContent','structured_content','data'):
            if key in value:result.extend(_error_texts(value[key],depth+1,flagged or key=='error'))
        return result
    if isinstance(value,list):
        result=[]
        for item in value[:100]:result.extend(_error_texts(item,depth+1,error_context))
        return result
    if isinstance(value,str):
        if error_context:return [value[:16384]]
        if len(value)<=65536 and value.lstrip().startswith(('{','[')):
            try:return _error_texts(_json(value),depth+1)
            except ValueError:pass
    return []


def _approval_failure(message):
    text=message.lower()
    never=bool(re.search(r'approval[_ -]?policy.{0,60}\bnever\b',text))
    requires=bool(re.search(r'(?:requires?|required|needs?|request|cannot|can.t).{0,70}approval',text))
    if never and requires:return 'TOOL_APPROVAL_REQUIRED_POLICY_NEVER'
    if re.search(r'(?:automatic approval review|automatic reviewer|auto[_ -]?review).{0,100}(?:denied|rejected)',text):
        return 'TOOL_AUTOMATIC_REVIEW_DENIED'
    return None


def _aware_timestamp(value):
    if not isinstance(value,str) or not 20 <= len(value) <= 40:return False
    try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError:return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _validate_gmail_evidence(value):
    """Validate sanitized self-reported fields; trust is established outside model output."""
    present={key for key in GMAIL_EVIDENCE if value.get(key) is not None}
    for key in ('message_id','email_thread_id'):
        if key in present:_summary_require(isinstance(value[key],str) and GMAIL_ID.fullmatch(value[key]),key)
    for key in ('send_event_id','read_event_id'):
        if key in present:
            _summary_require(isinstance(value[key],str) and EVENT_ID.fullmatch(value[key]) and
                             value[key].lower() not in ('unknown','ambiguous','unavailable','none','null'),key)
    if {'send_event_id','read_event_id'} <= present:
        _summary_require(value['send_event_id']!=value['read_event_id'],'send_read_event_ids')
    _summary_require(('send_event_id' in present)==('read_event_id' in present),'send_read_event_ids')
    for key in ('recipient_sha256','subject_sha256','body_sha256','raw_readback_sha256'):
        if key in present:_summary_require(isinstance(value[key],str) and SHA256.fullmatch(value[key]),key)
    if 'readback_verified_at' in present:_summary_require(_aware_timestamp(value['readback_verified_at']),'readback_verified_at')
    if value.get('email_message_id') is not None and value.get('message_id') is not None:
        _summary_require(value['email_message_id'].lower()==value['message_id'],'email_message_id')
    # Partial sanitized evidence is retained for an independent host bridge, but
    # neither its presence nor a model-authored verification flag establishes trust.
    return present


def _final(text, phase, workspace):
    if not isinstance(text,str):raise SummaryError('BUSINESS_FINAL_REJECTED',category='format')
    if len(text)>65536:raise SummaryError('BUSINESS_FINAL_REJECTED',category='oversized_output')
    if SECRET.search(text):raise SummaryError('BUSINESS_FINAL_REJECTED',category='sensitive_output')
    try:value=_json(text)
    except ValueError:raise SummaryError('BUSINESS_FINAL_JSON_REQUIRED') from None
    if not isinstance(value,dict):raise SummaryError('BUSINESS_FINAL_JSON_REQUIRED')
    if phase=='catalog':
        allowed={'gmail_tool_names','sites_tool_names','catalog_verified','status','code'}
    else:
        allowed={'status','code','message_id','email_message_id','email_thread_id','send_event_id',
                 'read_event_id','recipient_sha256','subject_sha256','body_sha256',
                 'raw_readback_sha256','readback_verified_at','gmail_verified','price_status',
                 'holdings_status','report_directory','report_paths','error_codes','source_dates',
                 'delivery_verified'}
    if not set(value)<=allowed:raise SummaryError('BUSINESS_FINAL_FIELDS_REJECTED',category='rejected_fields')
    safe={}
    for key,item in value.items():
        if key in ('gmail_tool_names','sites_tool_names'):
            _summary_require(isinstance(item,list) and len(item)<=100 and all(isinstance(x,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]{0,159}',x) for x in item),key)
        elif key in ('catalog_verified','gmail_verified','delivery_verified'):
            _summary_require(type(item)is bool,key)
        elif key in ('message_id','email_message_id'):
            _summary_require(item is None or isinstance(item,str) and re.fullmatch(r'[0-9a-fA-F]{8,64}',item),key)
        elif key in ('email_thread_id','send_event_id','read_event_id','recipient_sha256','subject_sha256',
                     'body_sha256','raw_readback_sha256','readback_verified_at'):
            pass # Cross-field and exact-format checks run after all fields are bounded.
        elif key in ('report_directory','report_paths'):
            items=item if isinstance(item,list) else [item]
            _summary_require(len(items)<=10,key)
            for entry in items:
                _summary_require(isinstance(entry,str),key)
                p=Path(entry);p=p if p.is_absolute() else workspace/p
                _summary_require(p.resolve().is_relative_to(workspace/'.niulai-state') or p.resolve().is_relative_to(workspace/'.job-runtime'),key,'boundary_violation')
        elif key=='source_dates':
            _summary_require(isinstance(item,list) and len(item)<=10 and all(isinstance(x,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in item),key)
        elif key=='error_codes':
            _summary_require(isinstance(item,list) and len(item)<=30 and all(isinstance(x,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',x) for x in item),key)
        elif key=='code':
            _summary_require(isinstance(item,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,95}',item),key)
        else:
            _summary_require(item in ('ok','completed','sent','verified','partial','failed','blocked',
                             'unavailable','catalog','succeeded','ready','skipped','evaluated',
                             'not_collected','rendered','rendered_partial','collected','historical',
                             'source_missing'),key)
        if key in ('message_id','email_message_id','email_thread_id') and isinstance(item,str):item=item.lower()
        safe[key]=item
    if phase=='business':_validate_gmail_evidence(safe)
    return safe


def run_business(profile, prompt, workspace, run_dir, context=None):
    """One isolated invocation. Raw tool arguments/results never leave RAM."""
    receipt={'started_at':datetime.now(timezone.utc).isoformat(),'requested_model':profile.get('model') if isinstance(profile,dict) else None,
             'observed_model':None,'automatic_retry':False,'fallback_used':False}
    process=None;fd=None;claim_reserved=False;claim=None;run_created=False
    try:
        workspace=Path(workspace).resolve(strict=True);base=_profile_caps(profile)
        binary,home,timeout,maximum=_profile(base,workspace)
        writable_roots=_writable_roots(profile,workspace,home)
        lock=_private_path(home/'runtime.lock',workspace);fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'retryable','code':'MODEL_AUTH_CACHE_BUSY','receipt':receipt}
        _require(isinstance(prompt,str) and 0<len(prompt.encode())<=512*1024,'BUSINESS_PROMPT_INVALID')
        context=context or {};_require(set(context)<={'cancel_event','gmail_claim','commit_dispatch','verify_dispatch'},'BUSINESS_CONTEXT_INVALID')
        claim=_validate_gmail_claim(context.get('gmail_claim'))
        if GMAIL in profile['apps'] and profile['phase']=='business':
            _require(claim is not None,'BUSINESS_GMAIL_CLAIM_REQUIRED')
        if claim is not None:
            receipt.update(gmail_claim=claim,final_evidence_trust='untrusted_model_output')
            code=_check_gmail_claim(workspace,claim,'business')
            if code:return {'status':'unknown','code':code,'receipt':receipt}
        if context.get('cancel_event')is not None and context['cancel_event'].is_set():
            return {'status':'retryable','code':'BUSINESS_CANCELLED_BEFORE_START','receipt':receipt}
        run_dir=_private_path(run_dir,workspace);_require(not run_dir.exists(),'MODEL_RUN_DIRECTORY_EXISTS')
        run_dir=_private_path(run_dir,workspace,directory=True);run_created=True;env=_environment(workspace,home,run_dir)
        env['RUST_LOG']='off'
        working=run_dir/'work';working.mkdir(mode=0o700)
        automatic=profile.get('approval_mode','never')=='automatic_review'
        cmd=[str(binary),'exec','--ignore-user-config','--ephemeral','--strict-config','--json','--color','never',
             '--cd',str(working),
             '--skip-git-repo-check','--model',profile['model']]
        if automatic:cmd+=['--approve-for-me']
        else:cmd+=['--sandbox','workspace-write' if profile['shell'] else 'read-only']
        overrides={'model_reasoning_effort':profile['effort'],'web_search':'disabled',
                   'features.shell_tool':profile['shell'],'features.shell_snapshot':False,'features.apps':True,
                   'apps._default.enabled':False,'mcp_servers':{},'cli_auth_credentials_store':'file',
                   'sqlite_home':env['CODEX_SQLITE_HOME'],'history.persistence':'none','check_for_update_on_startup':False}
        if automatic:overrides['approvals_reviewer']='auto_review'
        else:overrides['approval_policy']='never'
        for app in profile['apps']:
            overrides['apps.'+app+'.enabled']=(app!=GMAIL or claim is not None)
        if profile['shell']:
            # Business source is read-only; writes are limited to these private
            # state roots. Do not give the model the repository as writable cwd.
            for root in writable_roots:cmd+=['--add-dir',str(root)]
            overrides['sandbox_workspace_write.network_access']=True
        for key,value in overrides.items():cmd+=['-c',key+'='+json.dumps(value)]
        cmd+=['-']
        if context.get('verify_dispatch') is not None:context['verify_dispatch']()
        if context.get('cancel_event') is not None and context['cancel_event'].is_set():
            return {'status':'retryable','code':'BUSINESS_CANCELLED_BEFORE_START','receipt':receipt}
        if claim is not None:
            code=_consume_gmail_claim(workspace,claim,'business')
            if code:return {'status':'unknown','code':code,'receipt':receipt}
            claim_reserved=True
            receipt['dispatch_phase']='reserved'
        process=subprocess.Popen(cmd,cwd=working,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,start_new_session=True,pass_fds=(fd,))
        receipt['dispatch_phase']='exposed'
        if claim is not None:_claim_phase(workspace,claim,'exposed')
        if context.get('commit_dispatch') is not None:context['commit_dispatch']()
        if claim is not None:_claim_phase(workspace,claim,'committed')
        raw,errors,reason=_stream(process,prompt.encode(),timeout,maximum,context.get('cancel_event'))
        receipt.update(ended_at=datetime.now(timezone.utc).isoformat(),exit_code=process.returncode,
                       phase=profile['phase'],approval_mode=profile.get('approval_mode','never'),
                       writable_roots=[str(x.relative_to(workspace)) for x in writable_roots],
                       run_directory=str(run_dir.relative_to(workspace)))
        if reason:return {'status':'unknown','code':reason,'receipt':receipt}
        meta=_metadata(raw,receipt['started_at'],receipt['ended_at'])
        receipt.update(thread_id=meta['thread_id'],usage=meta['usage'],
                       tool_names=sorted(meta['tool_names']),turn_completed=meta['completed'],
                       tool_failures=meta['tool_failures'])
        if profile['phase']=='business':
            receipt.update(_gmail_receipt(meta['gmail_observation'],None,context.get('gmail_claim'),workspace))
            receipt['model_final_evidence_trust']='untrusted_model_output'
        if meta['observed_model']is not None and meta['observed_model']!=profile['model']:
            return {'status':'failed','code':'MODEL_IDENTITY_MISMATCH','receipt':receipt}
        receipt['observed_model']=meta['observed_model']
        if meta['tool_failures']:
            return {'status':'failed','code':meta['tool_failures'][0]['code'],'receipt':receipt}
        if profile['phase']=='catalog' and any(re.search(r'(?i)(?:gmail|sites)[_/.]',x) for x in meta['tool_names']):
            return {'status':'failed','code':'CATALOG_CONNECTOR_CALL_REJECTED','receipt':receipt}
        if process.returncode==0 and meta['completed'] and not meta['failed'] and not meta['parse_errors']:
            try:final=_final(meta['final'],profile['phase'],workspace)
            except SummaryError as error:
                receipt['summary_parse_failure']={'code':str(error),'field':error.field,'category':error.category}
                return {'status':'failed','code':str(error),'receipt':receipt}
            receipt.update(final=final,final_sha256=hashlib.sha256(json.dumps(final,sort_keys=True).encode()).hexdigest(),
                           final_evidence_trust='untrusted_model_output',model_final_evidence_trust='untrusted_model_output')
            if profile['phase']=='business':
                receipt.update(_gmail_receipt(meta['gmail_observation'],final,context.get('gmail_claim'),workspace))
                gmail_asserted=(meta['gmail_observation'] is not None or 'gmail_claim' in context or
                                 final.get('status')=='sent' or final.get('gmail_verified') is True or
                                 final.get('delivery_verified') is True)
                if gmail_asserted and receipt['final_evidence_trust']!='trusted_operational_host_evidence':
                    return {'status':'failed' if 'gmail_claim' in context else 'unknown','code':'BUSINESS_GMAIL_EVIDENCE_UNVERIFIED','receipt':receipt}
            if final.get('status') in ('blocked','failed'):
                return {'status':'failed','code':final.get('code','BUSINESS_JOB_BLOCKED'),'receipt':receipt}
            return {'status':'succeeded','code':'BUSINESS_TURN_COMPLETED','receipt':receipt}
        status,code=_classify(meta['errors']+[errors.decode(errors='replace')],process.returncode)
        return {'status':status,'code':code,'receipt':receipt}
    except ModelError as error:
        return {'status':'failed','code':str(error),'receipt':receipt}
    except Exception:
        if process is not None and process.poll()is None:_terminate(process)
        return {'status':'unknown' if process is not None else 'retryable','code':'BUSINESS_ADAPTER_FAILED','receipt':receipt}
    except BaseException:
        if process is not None:_terminate(process)
        raise
    finally:
        if claim_reserved and process is None:
            path=_gmail_claim_path(workspace,claim,'business')
            path.unlink()
            directory_fd=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
        if process is None and run_created:shutil.rmtree(run_dir)
        if process is not None:
            for pipe in (process.stdin,process.stdout,process.stderr):
                if pipe is not None:pipe.close()
        if fd is not None:os.close(fd)
