"""macOS launchd lifecycle. Generated state stays in the workspace."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import stat
import subprocess
import sys

from .config import load, inside
from .service import atomic

LABEL='com.local.trading-agent.job-runtime'
WATCH=LABEL+'.watchdog'
MAX_STATE_BYTES=1024*1024


def label_scope(service_label=None):
    """Return explicit lifecycle identities; omitted preserves production bytes."""
    if service_label is None:
        return LABEL, WATCH
    if (type(service_label) is not str or service_label == LABEL or
            service_label.endswith('.watchdog') or len(service_label.encode('utf-8')) > 240 or
            re.fullmatch(r'[a-z][a-z0-9-]{0,62}(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+', service_label) is None or
            len((service_label+'.watchdog.plist').encode('utf-8')) > 255):
        raise ValueError('HOST_SERVICE_LABEL_INVALID')
    return service_label, service_label+'.watchdog'


def _open_parent_nofollow(path):
    """Return a parent dirfd while holding every no-follow ancestor descriptor."""
    path = Path(path)
    components = path.parts[1:] if path.is_absolute() else path.parts
    descriptors = [os.open(path.anchor if path.is_absolute() else '.',
                           os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))]
    try:
        root_info=os.fstat(descriptors[0])
        if (not stat.S_ISDIR(root_info.st_mode) or root_info.st_uid not in (0,os.getuid()) or
                root_info.st_mode & (stat.S_IWGRP|stat.S_IWOTH)):
            raise OSError('untrusted state directory')
        if not components or components[-1] in ('', '.', '..'):
            raise OSError('invalid state path')
        for component in components[:-1]:
            if component in ('', '.', '..'):
                raise OSError('invalid state path component')
            descriptors.append(os.open(
                component, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) |
                getattr(os, 'O_NOFOLLOW', 0), dir_fd=descriptors[-1]))
            info=os.fstat(descriptors[-1])
            if (info.st_uid not in (0,os.getuid()) or
                    info.st_mode & (stat.S_IWGRP|stat.S_IWOTH)):
                raise OSError('untrusted state directory')
        return descriptors[-1], components[-1], descriptors
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _open_component_nofollow(path):
    parent, leaf, descriptors = _open_parent_nofollow(path)
    try:
        result = os.open(leaf, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                         getattr(os, 'O_NONBLOCK', 0), dir_fd=parent)
        return result, descriptors
    except BaseException:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        raise


def _read_state_json(path, maximum=MAX_STATE_BYTES):
    """Read one private owner-owned regular state file without following links."""
    descriptor=None
    parents=[]
    try:
        descriptor,parents=_open_component_nofollow(path)
        before=os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid!=os.getuid() or
                stat.S_IMODE(before.st_mode)&0o077 or not 0<before.st_size<=maximum):
            raise ValueError('HOST_STATE_FILE_INVALID')
        chunks=[];remaining=before.st_size
        while remaining:
            chunk=os.read(descriptor,min(65536,remaining))
            if not chunk:raise ValueError('HOST_STATE_FILE_INVALID')
            chunks.append(chunk);remaining-=len(chunk)
        after=os.fstat(descriptor)
        if ((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)):
            raise ValueError('HOST_STATE_FILE_CHANGED')
        value=json.loads(b''.join(chunks))
        if not isinstance(value,dict):raise ValueError('HOST_STATE_FILE_INVALID')
        return value
    except (OSError,UnicodeError,json.JSONDecodeError):
        raise ValueError('HOST_STATE_FILE_INVALID') from None
    finally:
        if descriptor is not None:os.close(descriptor)
        for held in reversed(parents):os.close(held)


def _atomic_bytes(path, data):
    """Publish bytes relative to one held no-follow directory."""
    parent = None
    descriptors = []
    temporary = None
    try:
        parent, target, descriptors = _open_parent_nofollow(path)
        for _ in range(32):
            temporary = '.host-' + secrets.token_hex(12)
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                                     getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=parent)
                break
            except FileExistsError:
                continue
        else:
            raise OSError('host temporary unavailable')
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target, src_dir_fd=parent, dst_dir_fd=parent)
        temporary = None
        os.fsync(parent)
    finally:
        if temporary is not None and parent is not None:
            try:os.unlink(temporary, dir_fd=parent)
            except OSError:pass
        for held in reversed(descriptors):os.close(held)


def _state_timestamp_age(path,key,now):
    """Return (age, invalid); existing malformed/future data is immediately stale."""
    if not path.exists() and not path.is_symlink():return None,False
    try:
        parsed=datetime.fromisoformat(_read_state_json(path)[key])
        if parsed.tzinfo is None or parsed.utcoffset() is None or parsed>now:
            return None,True
        return (now-parsed).total_seconds(),False
    except (ValueError,KeyError,TypeError):
        return None,True


def generate(workspace, config_path, service_label=None):
    root=Path(workspace).resolve(strict=True);config,_=load(config_path,root)
    service_label,watch_label=label_scope(service_label)
    state=root/'.job-runtime';folder=inside(state/'launchd',root,True);folder.mkdir(mode=0o700,exist_ok=True)
    python=str(Path(config.get('python_bin',root/'.job-runtime/.venv/bin/python')).resolve())
    inside(python,root,True)
    if not Path(python).is_file():raise ValueError('RUNTIME_PYTHON_MISSING')
    env={'PYTHONPATH':str(root),'PYTHONDONTWRITEBYTECODE':'1','TMPDIR':str(state/'tmp'),
         'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(Path.home())}
    for key in ('SSL_CERT_FILE','SSL_CERT_DIR','HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY'):
        if os.environ.get(key):env[key]=os.environ[key]
    common={'WorkingDirectory':str(root),'EnvironmentVariables':env,'ProcessType':'Background','Umask':0o077}
    daemon_args=['/usr/bin/caffeinate','-i',python,'-B','-m','shared.job_runtime.launcher',
                 '--workspace',str(root),'--config',str(Path(config_path).resolve())]
    watch_args=[python,'-m','shared.job_runtime.host','watchdog',
                '--workspace',str(root),'--config',str(Path(config_path).resolve())]
    if service_label != LABEL:
        daemon_args += ['--service-label',service_label]
        watch_args += ['--service-label',service_label]
    service_log = 'service' if service_label == LABEL else service_label
    watch_log = 'watchdog' if watch_label == WATCH else watch_label
    daemon={**common,'Label':service_label,'ProgramArguments':daemon_args,
            'KeepAlive':True,'RunAtLoad':True,'ThrottleInterval':15,'ExitTimeOut':15,
            'StandardOutPath':str(state/('logs/'+service_log+'.stdout.log')),'StandardErrorPath':str(state/('logs/'+service_log+'.stderr.log'))}
    watch={**common,'Label':watch_label,'ProgramArguments':watch_args,
           'StartInterval':60,'RunAtLoad':True,'StandardOutPath':str(state/('logs/'+watch_log+'.stdout.log')),
           'StandardErrorPath':str(state/('logs/'+watch_log+'.stderr.log'))}
    paths=[]
    for value in (daemon,watch):
        p=inside(folder/(value['Label']+'.plist'),root,True)
        _atomic_bytes(p,plistlib.dumps(value));paths.append(p)
    return paths


def command(args):
    return subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=15)


def install(workspace,config_path,persistent=False,service_label=None):
    paths=generate(workspace,config_path,service_label);domain='gui/'+str(os.getuid())
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


def watchdog(workspace,config_path,service_label=None):
    service_label,_watch_label=label_scope(service_label)
    root=Path(workspace).resolve(strict=True);config,jobs=load(config_path,root);state=root/'.job-runtime'
    now=datetime.now(timezone.utc);target='gui/'+str(os.getuid())+'/'+service_label
    value={'checked_at':now.isoformat(),'daemon_registered':command(['print',target]).returncode==0,'actions':[]}
    heartbeat,heartbeat_invalid=_state_timestamp_age(state/'heartbeat.json','at',now)
    tick,tick_invalid=_state_timestamp_age(state/'status.json','last_tick',now)
    value.update(heartbeat_age_seconds=heartbeat,tick_age_seconds=tick,
                 heartbeat_invalid=heartbeat_invalid,tick_invalid=tick_invalid)
    timeout=max(p['timeout_seconds'] for p in config['model_profiles'].values())
    # Conservative bound also covers profiles serialized on one auth cache.
    batch_bound=max(timeout,sum(config['model_profiles'][j['model_profile']]['timeout_seconds'] for j in jobs if j['enabled']))
    missing_path=state/'watchdog-missing-since.json'
    missing_age=0
    if heartbeat is None or tick is None:
        if not missing_path.exists() and not missing_path.is_symlink():
            atomic(missing_path,{'at':now.isoformat()})
        missing_value,missing_invalid=_state_timestamp_age(missing_path,'at',now)
        missing_age=missing_value or 0
    else:
        missing_invalid=False
        if missing_path.exists() or missing_path.is_symlink():missing_path.unlink()
    stale=(heartbeat_invalid or tick_invalid or missing_invalid or
           (heartbeat is not None and heartbeat>config['stale_seconds']) or
           (tick is not None and tick>batch_bound+config['stale_seconds']) or
           missing_age>config['stale_seconds'])
    if not value['daemon_registered']:
        p=state/'launchd'/(service_label+'.plist')
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
    p.add_argument('--workspace',required=True);p.add_argument('--config',required=True);p.add_argument('--service-label');a=p.parse_args();os.umask(0o077)
    service_label,watch_label=label_scope(a.service_label)
    try:
        if a.action=='generate':value={'paths':[str(x) for x in generate(a.workspace,a.config,a.service_label)]}
        elif a.action.startswith('install-'):value=install(a.workspace,a.config,a.action=='install-persistent',a.service_label)
        elif a.action=='watchdog':value=watchdog(a.workspace,a.config,a.service_label)
        elif a.action=='reload':
            result=command(['kill','SIGHUP','gui/'+str(os.getuid())+'/'+service_label])
            value={'reload_signal_accepted':result.returncode==0}
        elif a.action=='uninstall-session':
            for label in (watch_label,service_label):command(['bootout','gui/'+str(os.getuid())+'/'+label])
            value={'session_services_unloaded':True,'persistent_links_removed':False}
        else:
            root=Path(a.workspace).resolve();value={'registered':{label:command(['print','gui/'+str(os.getuid())+'/'+label]).returncode==0 for label in (service_label,watch_label)}}
            state_errors={}
            for name in ('heartbeat','status','watchdog','service-generation','reload-status'):
                f=root/'.job-runtime'/(name+'.json')
                if not f.exists() and not f.is_symlink():
                    value[name]=None
                    continue
                try:value[name]=_read_state_json(f)
                except ValueError:
                    value[name]=None;state_errors[name]='HOST_STATE_FILE_INVALID'
            if state_errors:value['state_errors']=state_errors
        print(json.dumps(value));return 0
    except Exception:
        print(json.dumps({'status':'failed','code':'HOST_OPERATION_FAILED'}));return 2


if __name__=='__main__':raise SystemExit(main())
