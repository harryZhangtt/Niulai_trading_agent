"""Freeze two matched implementation packets. Does not call a model or grader."""
import hashlib
import json
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

import tiktoken

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path(__file__).resolve().parent
RUN = ROOT / 'tuning/runtime/ui-implementation-quality-v1'

HELPER = '''"""Public local typecheck/build/server helper; no hidden quality cases."""
import argparse,json,os,signal,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('action',choices=['typecheck','build','serve']);a=p.parse_args()
worker=Path(__file__).resolve().parents[1];settings=json.loads((worker/'tools/environment.json').read_text())
tools=Path(settings['tool_root']);output=worker/'runtime'/('check-'+a.action+'-'+str(time.time_ns()))
output.mkdir(parents=True);temporary=worker/'runtime/tmp';temporary.mkdir(parents=True,exist_ok=True)
env={**os.environ,'UI_TOOL_ROOT':str(tools),'BENCH_APP':str(worker/'app'),'BENCH_OUTPUT':str(output),
     'BENCH_PORT':str(settings['port']),'PLAYWRIGHT_BROWSERS_PATH':settings['browsers'],
     'TMPDIR':str(temporary),'XDG_CACHE_HOME':str(worker/'runtime/cache'),'CI':'1','PYTHONDONTWRITEBYTECODE':'1'}
if a.action=='typecheck':command=['node',str(worker/'tools/typecheck.cjs')]
else:
    command=['node',str(tools/'node_modules/vite/bin/vite.js')]
    if a.action=='build':command+=['build']
    command+=['--config',str(worker/'tools/vite.config.mjs')]
print(json.dumps({'command':command,'output':str(output),'port':settings['port']}),flush=True)
process=subprocess.Popen(command,cwd=worker,env=env,start_new_session=True)
try:code=process.wait(timeout=600 if a.action=='serve' else 180)
except (subprocess.TimeoutExpired,KeyboardInterrupt):
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait(timeout=3)
    code=124
raise SystemExit(code)
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    manifest_path = RUN / 'manifest.json'
    if manifest_path.exists():
        raise ValueError('Refusing to overwrite frozen implementation packets')
    author = json.loads((RUN / 'author/freeze.json').read_text())
    for relative, expected in author['source_sha256'].items():
        if digest(SOURCE / relative) != expected:
            raise ValueError('Author source changed: ' + relative)
    enc = tiktoken.get_encoding('o200k_base')
    common = (ROOT / 'mentor/skills/development-discipline/SKILL.md').read_text()
    public_task = (SOURCE / 'task.md').read_text()
    arms = ['general', 'routed']
    random.Random(103064).shuffle(arms)
    jobs = []
    for index, arm in enumerate(arms, 1):
        worker = RUN / ('repair-' + str(index))
        worker.mkdir(exist_ok=False)
        shutil.copytree(SOURCE / 'seed', worker / 'app')
        (worker / 'tools').mkdir()
        for name in ('typecheck.cjs', 'vite.config.mjs'):
            shutil.copy2(SOURCE / 'tests' / name, worker / 'tools' / name)
        (worker / 'tools/check.py').write_text(HELPER)
        settings = {'tool_root': str(ROOT / 'ui/verification'),
                    'browsers': str(ROOT / 'ui/runtime/browsers'), 'port': 5210 + index}
        (worker / 'tools/environment.json').write_text(json.dumps(settings, indent=2) + '\n')
        (worker / 'runtime').mkdir()
        guide = ''
        if arm == 'routed':
            shutil.copytree(ROOT / 'ui/skills', worker / 'skills',
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            guide = '\nUI POLICY:\n' + (ROOT / 'ui/AGENTS.md').read_text()
            guide += '\nUI ROUTER:\n' + (ROOT / 'ui/ROUTING.md').read_text()
        contract = '''Implement the supplied existing-app hardening request autonomously.
This is a controlled local development evaluation; the guidance supplied here is
the task-specific condition. No production runtime or external effects are allowed.
Current host SessionStart execution is unverified; the source guidance below is
provided directly as fallback, not claimed as actual hook output. Do not edit or
trust hooks, access private state, browse, install packages or discover other files.
Work only inside this worker directory, except reading/executing the explicitly
declared shared local locked tool graph and browser binaries in tools/environment.json.
No other worker, hidden grader, reference implementation or benchmark source access.
Restrictions are instructions, not an OS sandbox. Do not delegate or change model.
Budget: up to twelve minutes implementation work; no hidden test feedback/retries.

Before editing code, inspect the app and write inspection.json as {issues:[
{description,location,mechanism,planned_check}]}; use concrete observed code paths,
not merely a generic checklist. Then implement only the public editable src/ surface.
Keep supplied immutable vendor, entrypoints, tools and package metadata unchanged.
Use python3 tools/check.py typecheck, build or serve for local verification. The
serve action uses your assigned localhost port; stop your owned server afterwards.
You may create self-authored check scripts and outputs under runtime/. The local
Playwright API is available from the locked tool graph. No hidden tests are supplied.
Save actual verification evidence, not claimed execution without results.
Write result.json with changes, checks, limitations. Preserve failed attempts.
Finish with a concise receipt. Do not inspect files outside the declared scope.
'''
        if arm == 'routed':
            contract += '''Before reading any UI skill bodies, choose the minimal packages
using only the router and write route.json as {skills:[package names],reason:...}.
Then read selected local skills/references and record relative paths actually
consulted in resources.json as {paths:[...]}. Reuse loaded text. The package
commands are guidance: in this controlled packet use the supplied local tools,
not canonical app files or shared browser sessions. Do not load all packages.
'''
        else:
            contract += 'This condition has common engineering guidance only; no UI skill bodies are supplied.\n'
        packet = contract + '\nCOMMON DEVELOPMENT GUIDANCE:\n' + common + guide + '\nPUBLIC TASK:\n' + public_task
        (worker / 'packet.txt').write_text(packet)
        protected = {}
        for path in worker.rglob('*'):
            if path.is_file() and not ('app/src' in str(path.relative_to(worker)) and path.name != 'main.tsx'):
                protected[str(path.relative_to(worker))] = digest(path)
        jobs.append({'id': worker.name, 'arm': arm, 'port': settings['port'],
                     'packet_tokens_proxy': len(enc.encode(packet)), 'protected_sha256': protected,
                     'output': 'result.json', 'inspection': 'inspection.json'})
    sources = {str((SOURCE / name).relative_to(ROOT)): value for name, value in author['source_sha256'].items()}
    for path in [SOURCE / 'protocol.md', SOURCE / 'prepare.py', ROOT / 'ui/AGENTS.md',
                 ROOT / 'ui/ROUTING.md', ROOT / 'mentor/skills/development-discipline/SKILL.md',
                 ROOT / 'ui/verification/package-lock.json']:
        sources[str(path.relative_to(ROOT))] = digest(path)
    manifest = {'experiment': 'ui-implementation-quality-v1',
                'frozen_at': datetime.now(timezone.utc).isoformat(), 'jobs': jobs,
                'model_policy': 'same inherited model/settings; no override',
                'source_sha256': sources, 'provider_usage': None,
                'isolation': 'instruction-only file boundaries; shared locked local tools'}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'jobs': [{'id': j['id'], 'arm': j['arm'], 'packet_tokens_proxy': j['packet_tokens_proxy']} for j in jobs]}, indent=2))


if __name__ == '__main__':
    main()
