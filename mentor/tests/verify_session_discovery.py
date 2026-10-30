"""Inspect a fresh local Codex runtime without a model call or hook-trust bypass."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import time

from mentor.session_init import ROOT, SKILLS


def verify():
    state = ROOT / 'mentor/runtime/init-verification'
    home, temporary = state / 'codex-home', state / 'tmp'
    for directory in (home, temporary):
        directory.mkdir(parents=True, exist_ok=True)
    # Trust only the project layer in this isolated test home. Hook trust stays unset.
    (home / 'config.toml').write_text(
        '[projects.' + json.dumps(str(ROOT)) + ']\ntrust_level = "trusted"\n')
    env = {**os.environ, 'CODEX_HOME': str(home), 'TMPDIR': str(temporary),
           'PYTHONDONTWRITEBYTECODE': '1'}
    with (state / 'app-server.stderr').open('w') as err:
        process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'],
                                   cwd=ROOT, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=err, text=True, bufsize=1)

        def request(identifier, method, params):
            process.stdin.write(json.dumps({'id': identifier, 'method': method, 'params': params}) + '\n')
            process.stdin.flush()
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + 20
            try:
                while time.monotonic() < deadline:
                    if not selector.select(max(0, deadline - time.monotonic())):
                        break
                    line = process.stdout.readline()
                    if not line:
                        raise RuntimeError('Codex app-server exited')
                    result = json.loads(line)
                    if result.get('id') == identifier:
                        if 'error' in result:
                            raise RuntimeError('Codex rejected ' + method)
                        return result['result']
                raise TimeoutError(method)
            finally:
                selector.close()

        try:
            request(1, 'initialize', {'clientInfo': {'name': 'mentor-local-verifier', 'version': '1.0'}})
            process.stdin.write('{"method":"initialized"}\n')
            process.stdin.flush()
            cwds = [str(ROOT), str(ROOT / 'mentor'), str(ROOT / 'shared/market_data_mcp')]
            skills = request(2, 'skills/list', {'cwds': cwds, 'forceReload': True})
            hooks = request(3, 'hooks/list', {'cwds': cwds})
            summary = []
            assert len(skills['data']) == len(hooks['data']) == len(cwds)
            for entry, hook_entry in zip(skills['data'], hooks['data']):
                assert not entry['errors'] and not hook_entry['errors']
                found = {s['name']: s for s in entry['skills'] if s['name'] in SKILLS}
                assert set(found) == set(SKILLS)
                for name, skill in found.items():
                    assert skill['enabled'] and Path(skill['path']).resolve() == ROOT / 'mentor/skills' / name / 'SKILL.md'
                configured = [h for h in hook_entry['hooks']
                              if h['sourcePath'] == str(ROOT / '.codex/hooks.json') and
                              h.get('statusMessage') == 'Loading mentor policy and router']
                assert len(configured) == 1 and configured[0]['eventName'] == 'sessionStart'
                assert configured[0]['timeoutSec'] == 3
                summary.append({'cwd': str(Path(entry['cwd']).relative_to(ROOT)),
                                'skills': sorted(found), 'hook_trust': configured[0]['trustStatus']})
            report = {'catalog_verification': 'pass', 'model_called': False,
                      'hook_execution_verified': False, 'directories': summary}
            (state / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            process.stdin.close()
            process.stdout.close()


if __name__ == '__main__':
    verify()
