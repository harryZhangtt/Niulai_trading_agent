"""Thin scheduler operator CLI; owns no provider, business, or SQLite behavior."""
import argparse,json,os,platform,subprocess
from pathlib import Path
from . import allocation,setup

class OperatorError(ValueError):pass

def _config(root):return root/'.job-runtime/config/runtime.json'
def _emit(value):print(json.dumps(value,sort_keys=True,separators=(',',':')))
def _bool(value):
    if value not in ('true','false'):raise argparse.ArgumentTypeError('expected true|false')
    return value=='true'
def _job(path):
    value=json.loads(Path(path).read_text())
    if type(value) is not dict:raise OperatorError('JOB_FILE_INVALID')
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',required=True);commands=p.add_subparsers(dest='command',required=True)
    init=commands.add_parser('init');init.add_argument('--schema-version',type=int,choices=[1,2],default=2);init.add_argument('--provider',choices=['claude-host','codex-cli'],default='claude-host');init.add_argument('--provider-bin');init.add_argument('--model');init.add_argument('--host',choices=['session','skip'],default='skip');init.add_argument('--allow-external-host-root',action='store_true');init.add_argument('--host-root')
    commands.add_parser('doctor')
    schedule=commands.add_parser('schedule');subs=schedule.add_subparsers(dest='schedule_command',required=True);subs.add_parser('validate');listing=subs.add_parser('list');listing.add_argument('--job-id');add=subs.add_parser('add');add.add_argument('--allocation',required=True);add.add_argument('--job-file',required=True);enable=subs.add_parser('set-enabled');enable.add_argument('--job-id',required=True);enable.add_argument('--enabled',type=_bool,required=True)
    host=commands.add_parser('host');host.add_argument('action',choices=['status','reload','stop-session']);host.add_argument('--service-label')
    a=p.parse_args();os.umask(0o077);root=Path(a.workspace).resolve(strict=True)
    try:
        if a.command=='init':
            model=a.model or ('claude-opus-5-5' if a.provider=='claude-host' else 'gpt-6.1-sol')
            result=setup.prepare(root,schema_version=a.schema_version,provider=a.provider,provider_bin=a.provider_bin,model=model)
            session={'requested':a.host,'state':'unchanged'}
            if a.host=='session':
                if platform.system()!='Darwin':raise OperatorError('HOST_SESSION_UNSUPPORTED')
                if not a.allow_external_host_root:raise OperatorError('HOST_EXTERNAL_ROOT_AUTHORIZATION_REQUIRED')
                from .host_deploy import materialize
                deployed=materialize(root,external_root=a.host_root)
                session={'requested':'session','state':'prepared','service_label':deployed['service_label'],'workspace_id':deployed['workspace_id'],'credentials_required':not deployed['credentials_copied']}
            result={**result,'session_service':session}
        elif a.command=='doctor':
            result={**setup.inspect(root),'host_supported':platform.system()=='Darwin'}
        elif a.command=='schedule':
            config=_config(root)
            if a.schedule_command=='validate':result=allocation.validate_all(root,config)
            elif a.schedule_command=='list':
                jobs=allocation.list_jobs(root,config);jobs=[{'id':j['id'],'enabled':j['enabled'],'schedule':j['schedule'],'model_profile':j['model_profile']} for j in jobs if not a.job_id or j['id']==a.job_id];result={'schema_version':1,'status':'ok','jobs':jobs}
            elif a.schedule_command=='add':result=allocation.add_job(root,config,root/a.allocation,_job(a.job_file))
            else:result=allocation.set_enabled(root,config,a.job_id,a.enabled)
        else:
            from . import host as host_module
            action={'status':'status','reload':'reload','stop-session':'uninstall-session'}[a.action]
            command=[str(root/'.job-runtime/.venv/bin/python'),'-B','-m','shared.job_runtime.host',action,'--workspace',str(root),'--config',str(_config(root))]
            if a.service_label:command+=['--service-label',a.service_label]
            value=subprocess.run(command,capture_output=True,text=True,timeout=30)
            if value.returncode:raise OperatorError('HOST_OPERATION_FAILED')
            result=json.loads(value.stdout)
        _emit(result);return 0
    except Exception as error:
        code=str(error) if str(error).isupper() and len(str(error))<96 else 'OPERATOR_FAILED';_emit({'status':'failed','code':code});return 2
if __name__=='__main__':raise SystemExit(main())
