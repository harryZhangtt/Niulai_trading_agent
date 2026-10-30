"""Verify UI discovery and actual SessionStart events in a local isolated Codex home.

No model turn, copied auth, trust-hash edits, bypass flags or global writes.
"""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from ui.session_init import ROOT, SKILLS


class RPC:
    def __init__(self, process):
        self.process = process
        self.buffer = b''
        self.messages = []
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ)

    def collect(self, seconds):
        if self.selector.select(seconds):
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('local app-server exited')
            self.buffer += chunk
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                self.messages.append(json.loads(line))

    def request(self, identifier, method, params):
        self.process.stdin.write((json.dumps({'id': identifier, 'method': method, 'params': params}) + '\n').encode())
        self.process.stdin.flush()
        deadline = time.monotonic() + 20
        while True:
            for message in self.messages:
                if message.get('id') == identifier:
                    if 'error' in message:
                        raise RuntimeError('local app-server rejected ' + method)
                    return message['result']
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            self.collect(remaining)


def verify(record):
    if not record or not record.replace('-', '').isalnum():
        raise ValueError('record must be a plain alphanumeric run name')
    state = ROOT / 'ui/runtime/init-verification'
    home, temporary = state / 'codex-home', state / 'tmp'
    for path in (home, temporary):
        path.mkdir(parents=True, exist_ok=True)
    config = home / 'config.toml'
    if not config.exists():
        config.write_text('[projects.' + json.dumps(str(ROOT)) + ']\ntrust_level = "trusted"\n')
    env = {**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(temporary), 'PYTHONDONTWRITEBYTECODE': '1'}
    report = {'model_called': False, 'hook_execution_verified': False,
              'hook_trust_modified_by_verifier': False, 'record': record}
    target = state / (record + '.json')
    if target.exists():
        raise ValueError('refusing to overwrite an earlier runtime verification')
    with (state / (record + '.stderr')).open('w') as error:
        process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'], cwd=ROOT,
                                   env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=error, start_new_session=True)
        rpc = RPC(process)
        try:
            rpc.request(1, 'initialize', {'clientInfo': {'name': 'ui-local-verifier', 'version': '1.0'}})
            process.stdin.write(b'{"method":"initialized"}\n')
            process.stdin.flush()
            cwds = [str(ROOT), str(ROOT / 'ui'), str(ROOT / 'ui/verification')]
            skills = rpc.request(2, 'skills/list', {'cwds': cwds, 'forceReload': True})
            hooks = rpc.request(3, 'hooks/list', {'cwds': cwds})
            summary = []
            for entry, hook_entry in zip(skills['data'], hooks['data']):
                if entry['errors'] or hook_entry['errors']:
                    raise RuntimeError('local discovery returned errors')
                found = {s['name']: s for s in entry['skills']
                         if s['name'] in SKILLS and Path(s['path']).resolve() ==
                         ROOT / 'ui/skills' / s['name'] / 'SKILL.md'}
                if set(found) != set(SKILLS) or not all(s['enabled'] for s in found.values()):
                    raise RuntimeError('canonical UI discovery incomplete')
                configured = [h for h in hook_entry['hooks']
                              if h['sourcePath'] == str(ROOT / '.codex/hooks.json') and
                              h.get('statusMessage') == 'Loading UI policy and router']
                if len(configured) != 1 or configured[0]['eventName'] != 'sessionStart':
                    raise RuntimeError('UI SessionStart definition not found')
                summary.append({'cwd': str(Path(entry['cwd']).relative_to(ROOT)),
                                'skills': sorted(found), 'hook_trust': configured[0]['trustStatus']})
            if len(summary) != len(cwds):
                raise RuntimeError('missing discovery directory')
            report.update(catalog_verification='pass', directories=summary)
            session = rpc.request(4, 'thread/start', {'cwd': str(ROOT), 'ephemeral': True,
                                                  'approvalPolicy': 'never', 'sandbox': 'read-only',
                                                  'sessionStartSource': 'startup'})
            report['thread_created'] = bool(session.get('thread', {}).get('id'))
            # Synchronous lifecycle output should arrive before thread/start returns.
            completed = [m for m in rpc.messages if m.get('method') == 'hook/completed']
            report['hook_events'] = [m['params']['run'] for m in completed
                                    if m.get('params', {}).get('run', {}).get('statusMessage') ==
                                    'Loading UI policy and router']
            report['hook_execution_verified'] = any(
                run.get('status') == 'completed' and 'UI_INIT_OK' in json.dumps(run.get('entries', []))
                for run in report['hook_events'])
            report['initialization_status'] = ('UI_INIT_OK' if report['hook_execution_verified'] else
                                                'unverified: no successful actual UI SessionStart output')
        except Exception as exc:
            report['verification_error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            rpc.selector.close()
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=2)
            process.stdin.close()
            process.stdout.close()
            target.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--record', required=True)
    verify(parser.parse_args().record)
