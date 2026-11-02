"""Observe the installed user skill from independent Git roots; no model turn."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ui.tests.verify_session_discovery import RPC


def main():
    output = ROOT / 'ui/runtime/harry-ui-20261102/discovery'
    output.mkdir(parents=True, exist_ok=True)
    target = Path.home() / '.agents/skills/harry-ui-skill-set/SKILL.md'
    foreign = []
    for name in ('alpha', 'beta'):
        repo = output / 'repositories' / name
        repo.mkdir(parents=True, exist_ok=True)
        if not (repo / '.git').exists():
            subprocess.run(['git', 'init', '-q', str(repo)], check=True, timeout=10)
        foreign.append(repo)
    home, temporary = output / 'codex-home', output / 'tmp'
    for path in (home, temporary):
        path.mkdir(exist_ok=True)
    env = dict(os.environ, CODEX_HOME=str(home), TMPDIR=str(temporary),
               PYTHONDONTWRITEBYTECODE='1', XDG_CACHE_HOME=str(output / 'cache'),
               XDG_CONFIG_HOME=str(output / 'config'), CODEX_SQLITE_HOME=str(output / 'sqlite'))
    report = {'model_called': False, 'global_configuration_modified': False,
              'automatic_hook_execution_claimed': False, 'repositories': []}
    with (output / 'stderr.log').open('w') as errors:
        process = subprocess.Popen(['codex', 'app-server', '--listen', 'stdio://'],
                                   cwd=foreign[0], env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=errors, start_new_session=True)
        rpc = RPC(process)
        try:
            rpc.request(1, 'initialize', {'clientInfo': {'name': 'harry-ui-discovery-check', 'version': '1.0'}})
            process.stdin.write(b'{"method":"initialized"}\n')
            process.stdin.flush()
            result = rpc.request(2, 'skills/list', {'cwds': [str(repo) for repo in foreign] + [str(ROOT)], 'forceReload': True})
            for entry in result['data']:
                matches = [skill for skill in entry['skills'] if skill['name'] == 'harry-ui-skill-set'
                           and Path(skill['path']).resolve() == target]
                if entry['errors'] or len(matches) != 1 or not matches[0]['enabled']:
                    raise RuntimeError('user_skill_discovery_failed')
                internal = [skill for skill in entry['skills'] if Path(skill['path']).is_relative_to(target.parent)
                            and skill['name'] != 'harry-ui-skill-set']
                if internal:
                    raise RuntimeError('internal_experts_exposed_in_discovery')
                report['repositories'].append({'cwd': str(Path(entry['cwd']).relative_to(ROOT)),
                                               'name': matches[0]['name'], 'scope': matches[0].get('scope'),
                                               'enabled': True, 'internal_experts_discovered': 0})
            if len(report['repositories']) != 3:
                raise RuntimeError('missing_discovery_result')
            report['status'] = 'passed'
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
            (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
