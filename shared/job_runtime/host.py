"""macOS launchd lifecycle. Generated state stays in the workspace."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from .config import load, inside
from .service import atomic

LABEL='com.local.trading-agent.job-runtime'
WATCH=LABEL+'.watchdog'


def generate(workspace, config_path):
    root=Path(workspace).resolve(strict=True);config,_=load(config_path,root)
    state=root/'.job-runtime';folder=inside(state/'launchd',root,True);folder.mkdir(mode=0o700,exist_ok=True)
    python=str(Path(config.get('python_bin',root/'.job-runtime/.venv/bin/python')).resolve())
    inside(python,root,True)
    if not Path(python).is_file():raise ValueError('RUNTIME_PYTHON_MISSING')
    env={'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(state/'tmp'),
         'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(Path.home())}
    for key in ('SSL_CERT_FILE','SSL_CERT_DIR','HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY'):
        if os.environ.get(key):env[key]=os.environ[key]
    common={'WorkingDirectory':str(root),'EnvironmentVariables':env,'ProcessType':'Background','Umask':0o077}
    daemon={**common,'Label':LABEL,'ProgramArguments':['/usr/bin/caffeinate','-i',python,'-m','shared.job_runtime.service',
              '--workspace',str(root),'--config',str(Path(config_path).resolve())],
            'KeepAlive':True,'RunAtLoad':True,'ThrottleInterval':15,'ExitTimeOut':15,
            'StandardOutPath':str(state/'logs/service.stdout.log'),'StandardErrorPath':str(state/'logs/service.stderr.log')}
    watch={**common,'Label':WATCH,'ProgramArguments':[python,'-m','shared.job_runtime.host','watchdog',
             '--workspace',str(root),'--config',str(Path(config_path).resolve())],
           'StartInterval':60,'RunAtLoad':True,'StandardOutPath':str(state/'logs/watchdog.stdout.log'),
           'StandardErrorPath':str(state/'logs/watchdog.stderr.log')}
    paths=[]
    for value in (daemon,watch):
        p=inside(folder/(value['Label']+'.plist'),root,True)
        p.write_bytes(plistlib.dumps(value));p.chmod(0o600);paths.append(p)
    return paths


def command(args):
    return subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=15)


def install(workspace,config_path,persistent=False):
    paths=generate(workspace,config_path);domain='gui/'+str(os.getuid())
    if persistent:
        # This is an explicit optional filesystem exception. The caller must
        # obtain user authorization before creating links outside the workspace.
        folder=Path.home()/'Library/LaunchAgents'
        if not folder.is_dir():raise ValueError('LAUNCHAGENTS_DIRECTORY_MISSING')
        for p in paths:
            link=folder/p.name
            if link.is_symlink() and link.resolve()==p:continue
            if link.exists() or link.is_symlink():raise ValueError('LAUNCHAGENT_NAME_CONFLICT')
            link.symlink_to(p)
    for p in paths:
        label=p.stem
        if command(['print',domain+'/'+label]).returncode==0:continue
        result=command(['bootstrap',domain,str(p)])
        if result.returncode:raise ValueError('LAUNCHD_BOOTSTRAP_FAILED')
    return {'installed':True,'persistent_login_links':persistent,'domain':domain,'labels':[p.stem for p in paths]}


def watchdog(workspace,config_path):
    root=Path(workspace).resolve(strict=True);config,jobs=load(config_path,root);state=root/'.job-runtime'
    now=datetime.now(timezone.utc);target='gui/'+str(os.getuid())+'/'+LABEL
    value={'checked_at':now.isoformat(),'daemon_registered':command(['print',target]).returncode==0,'actions':[]}
    def age(path,key):
        try:return max(0,(now-datetime.fromisoformat(json.loads(path.read_text())[key])).total_seconds())
        except (OSError,ValueError,KeyError):return None
    heartbeat=age(state/'heartbeat.json','at');tick=age(state/'status.json','last_tick')
    value.update(heartbeat_age_seconds=heartbeat,tick_age_seconds=tick)
    timeout=max(p['timeout_seconds'] for p in config['model_profiles'].values())
    # Conservative bound also covers profiles serialized on one auth cache.
    batch_bound=max(timeout,sum(config['model_profiles'][j['model_profile']]['timeout_seconds'] for j in jobs if j['enabled']))
    missing_path=state/'watchdog-missing-since.json'
    missing_age=0
    if heartbeat is None or tick is None:
        if not missing_path.exists():atomic(missing_path,{'at':now.isoformat()})
        missing_age=age(missing_path,'at') or 0
    elif missing_path.exists():missing_path.unlink()
    stale=(heartbeat is not None and heartbeat>config['stale_seconds']) or (tick is not None and tick>batch_bound+config['stale_seconds']) or missing_age>config['stale_seconds']
    if not value['daemon_registered']:
        p=state/'launchd'/(LABEL+'.plist')
        result=command(['bootstrap','gui/'+str(os.getuid()),str(p)])
        value['actions'].append('DAEMON_BOOTSTRAP_ACCEPTED' if result.returncode==0 else 'DAEMON_BOOTSTRAP_FAILED')
    elif stale:
        # Graceful stop lets the executor terminate its model process group.
        # launchd KeepAlive restarts the service. Unknown runs are NOT replayed.
        result=command(['kill','SIGTERM',target])
        value['actions'].append('STALE_DAEMON_TERM_ACCEPTED' if result.returncode==0 else 'STALE_DAEMON_TERM_FAILED')
    value['healthy']=value['daemon_registered'] and not stale and heartbeat is not None and tick is not None
    atomic(state/'watchdog.json',value)
    return value


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','install-session','install-persistent','reload','watchdog','status','uninstall-session'])
    p.add_argument('--workspace',required=True);p.add_argument('--config',required=True);a=p.parse_args();os.umask(0o077)
    try:
        if a.action=='generate':value={'paths':[str(x) for x in generate(a.workspace,a.config)]}
        elif a.action.startswith('install-'):value=install(a.workspace,a.config,a.action=='install-persistent')
        elif a.action=='watchdog':value=watchdog(a.workspace,a.config)
        elif a.action=='reload':
            result=command(['kill','SIGHUP','gui/'+str(os.getuid())+'/'+LABEL])
            value={'reload_signal_accepted':result.returncode==0}
        elif a.action=='uninstall-session':
            for label in (WATCH,LABEL):command(['bootout','gui/'+str(os.getuid())+'/'+label])
            value={'session_services_unloaded':True,'persistent_links_removed':False}
        else:
            root=Path(a.workspace).resolve();value={'registered':{label:command(['print','gui/'+str(os.getuid())+'/'+label]).returncode==0 for label in (LABEL,WATCH)}}
            for name in ('heartbeat','status','watchdog'):
                f=root/'.job-runtime'/(name+'.json');value[name]=json.loads(f.read_text()) if f.exists() else None
        print(json.dumps(value));return 0
    except Exception:
        print(json.dumps({'status':'failed','code':'HOST_OPERATION_FAILED'}));return 2


if __name__=='__main__':raise SystemExit(main())
