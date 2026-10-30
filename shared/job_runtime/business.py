"""Isolated, explicit Gmail/Sites business execution; raw tool data stays in RAM.

Readiness execution remains in model.py with tools disabled. This adapter does
not retry, install/connect plugins, change permissions, or select another model.
"""
from __future__ import annotations
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import time

from .model import ModelError, _classify, _environment, _private_path, _profile, _require, _terminate

GMAIL = 'connector_2128aebfecb84f64a069897515042a44'
SITES = 'connector_20205bf7d4e99a89d7154bb849718324'
BASE = {'codex_bin','model','effort','timeout_seconds','auth_home','max_output_bytes'}
CAPS = {'apps','shell','phase'}
OPTIONAL_CAPS = {'approval_mode'}
SECRET = re.compile(r'(?i)(?:\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|'
                    r'\bbearer\s+[A-Za-z0-9._-]+|\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}|'
                    r'\b(?:access_token|refresh_token|client_secret|siwc_bypass_bearer_token)\b)')


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
    _require(type(profile['shell']) is bool and profile['shell'] == (profile['phase']=='business'),
             'BUSINESS_SHELL_POLICY_MISMATCH')
    approval=profile.get('approval_mode','never')
    _require(approval in ('never','automatic_review') and
             (profile['phase']=='business' or approval=='never'),'BUSINESS_APPROVAL_MODE_INVALID')
    apps=profile['apps']
    _require(isinstance(apps,list) and 1 <= len(apps) <= 2 and len(set(apps))==len(apps)
             and all(x in (GMAIL,SITES) for x in apps), 'BUSINESS_APPS_POLICY_INVALID')
    return {k:v for k,v in profile.items() if k in BASE}


def _stream(process, prompt, timeout, maximum, cancel):
    """Bounded multiplexed pipes; never write prompt, stdout or stderr to disk."""
    streams=selectors.DefaultSelector();out=bytearray();err=bytearray();sent=0;reason=None
    for pipe,kind,event in ((process.stdin,'stdin',selectors.EVENT_WRITE),
                            (process.stdout,'stdout',selectors.EVENT_READ),
                            (process.stderr,'stderr',selectors.EVENT_READ)):
        os.set_blocking(pipe.fileno(),False);streams.register(pipe,event,kind)
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
                    if len(out)+len(err)>maximum:
                        reason='BUSINESS_OUTPUT_LIMIT_EXCEEDED';_terminate(process);break
            if reason:break
        if process.poll() is None:
            remaining=deadline-time.monotonic()
            if remaining<=0:reason='BUSINESS_DEADLINE_EXCEEDED';_terminate(process)
            else:
                try:process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:reason='BUSINESS_DEADLINE_EXCEEDED';_terminate(process)
        return bytes(out),bytes(err),reason
    finally:
        streams.close()
        for pipe in (process.stdin,process.stdout,process.stderr):
            if pipe is not None and not pipe.closed:pipe.close()


def _metadata(raw):
    result={'completed':False,'failed':False,'thread_id':None,'usage':None,
            'observed_model':None,'tool_names':set(),'final':None,'errors':[],'parse_errors':0,
            'tool_failures':[]}
    for line in raw.decode(errors='replace').splitlines():
        if not line.strip():continue
        try:event=json.loads(line)
        except ValueError:result['parse_errors']+=1;continue
        if not isinstance(event,dict):result['parse_errors']+=1;continue
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
    return result


def _error_texts(value, depth=0, error_context=False):
    """Inspect error envelopes only; never examine or return tool arguments."""
    if depth>8:return []
    if isinstance(value,dict):
        flagged=error_context or value.get('isError')is True or value.get('is_error')is True or value.get('status')in ('error','failed')
        result=[]
        for key in ('error','message','content','text','result','structuredContent','data'):
            if key in value:result.extend(_error_texts(value[key],depth+1,flagged or key=='error'))
        return result
    if isinstance(value,list):
        result=[]
        for item in value[:100]:result.extend(_error_texts(item,depth+1,error_context))
        return result
    if isinstance(value,str):
        if error_context:return [value[:16384]]
        if len(value)<=65536 and value.lstrip().startswith(('{','[')):
            try:return _error_texts(json.loads(value),depth+1)
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


def _final(text, phase, workspace):
    if not isinstance(text,str):raise SummaryError('BUSINESS_FINAL_REJECTED',category='format')
    if len(text)>65536:raise SummaryError('BUSINESS_FINAL_REJECTED',category='oversized_output')
    if SECRET.search(text):raise SummaryError('BUSINESS_FINAL_REJECTED',category='sensitive_output')
    try:value=json.loads(text)
    except ValueError:raise SummaryError('BUSINESS_FINAL_JSON_REQUIRED') from None
    if not isinstance(value,dict):raise SummaryError('BUSINESS_FINAL_JSON_REQUIRED')
    if phase=='catalog':
        allowed={'gmail_tool_names','sites_tool_names','catalog_verified','status','code'}
    else:
        allowed={'status','code','message_id','email_message_id','gmail_verified','price_status','holdings_status',
                 'report_directory','report_paths','error_codes','source_dates','delivery_verified'}
    if not set(value)<=allowed:raise SummaryError('BUSINESS_FINAL_FIELDS_REJECTED',category='rejected_fields')
    safe={}
    for key,item in value.items():
        if key in ('gmail_tool_names','sites_tool_names'):
            _summary_require(isinstance(item,list) and len(item)<=100 and all(isinstance(x,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:/-]{0,159}',x) for x in item),key)
        elif key in ('catalog_verified','gmail_verified','delivery_verified'):
            _summary_require(type(item)is bool,key)
        elif key in ('message_id','email_message_id'):
            _summary_require(item is None or isinstance(item,str) and re.fullmatch(r'[0-9a-fA-F]{8,64}',item),key)
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
        safe[key]=item
    return safe


def run_business(profile, prompt, workspace, run_dir, context=None):
    """One isolated invocation. Raw tool arguments/results never leave RAM."""
    receipt={'started_at':datetime.now(timezone.utc).isoformat(),'requested_model':profile.get('model') if isinstance(profile,dict) else None,
             'observed_model':None,'automatic_retry':False,'fallback_used':False}
    process=None;fd=None
    try:
        workspace=Path(workspace).resolve(strict=True);base=_profile_caps(profile)
        binary,home,timeout,maximum=_profile(base,workspace)
        lock=_private_path(home/'runtime.lock',workspace);fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'retryable','code':'MODEL_AUTH_CACHE_BUSY','receipt':receipt}
        _require(isinstance(prompt,str) and 0<len(prompt.encode())<=512*1024,'BUSINESS_PROMPT_INVALID')
        context=context or {};_require(set(context)<={'cancel_event'},'BUSINESS_CONTEXT_INVALID')
        if context.get('cancel_event')is not None and context['cancel_event'].is_set():
            return {'status':'retryable','code':'BUSINESS_CANCELLED_BEFORE_START','receipt':receipt}
        run_dir=_private_path(run_dir,workspace);_require(not run_dir.exists(),'MODEL_RUN_DIRECTORY_EXISTS')
        run_dir=_private_path(run_dir,workspace,directory=True);env=_environment(workspace,home,run_dir)
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
        for app in profile['apps']:overrides['apps.'+app+'.enabled']=True
        if profile['shell']:
            # Business source is read-only; writes are limited to these private
            # state roots. Do not give the model the repository as writable cwd.
            private_state=workspace/'.niulai-state';_require(private_state.is_dir() and not private_state.is_symlink(),'BUSINESS_PRIVATE_STATE_REQUIRED')
            cmd+=['--add-dir',str(private_state)]
            overrides['sandbox_workspace_write.network_access']=True
        for key,value in overrides.items():cmd+=['-c',key+'='+json.dumps(value)]
        cmd+=['-']
        process=subprocess.Popen(cmd,cwd=working,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,start_new_session=True,pass_fds=(fd,))
        raw,errors,reason=_stream(process,prompt.encode(),timeout,maximum,context.get('cancel_event'))
        receipt.update(ended_at=datetime.now(timezone.utc).isoformat(),exit_code=process.returncode,
                       phase=profile['phase'],approval_mode=profile.get('approval_mode','never'),
                       run_directory=str(run_dir.relative_to(workspace)))
        if reason:return {'status':'unknown','code':reason,'receipt':receipt}
        meta=_metadata(raw)
        receipt.update(thread_id=meta['thread_id'],usage=meta['usage'],
                       tool_names=sorted(meta['tool_names']),turn_completed=meta['completed'],
                       tool_failures=meta['tool_failures'])
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
            receipt.update(final=final,final_sha256=hashlib.sha256(json.dumps(final,sort_keys=True).encode()).hexdigest())
            if final.get('status') in ('blocked','failed'):
                return {'status':'failed','code':final.get('code','BUSINESS_JOB_BLOCKED'),'receipt':receipt}
            return {'status':'succeeded','code':'BUSINESS_TURN_COMPLETED','receipt':receipt}
        status,code=_classify(meta['errors']+[errors.decode(errors='replace')],process.returncode)
        return {'status':status,'code':code,'receipt':receipt}
    except ModelError as error:
        return {'status':'failed','code':str(error),'receipt':receipt}
    except Exception:
        if process is not None and process.poll()is None:_terminate(process)
        return {'status':'unknown','code':'BUSINESS_ADAPTER_FAILED','receipt':receipt}
    except BaseException:
        if process is not None:_terminate(process)
        raise
    finally:
        if fd is not None:os.close(fd)
