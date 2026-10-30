"""One bounded local CLI/browser round trip, with owned-session/server cleanup."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'ui'
RUNTIME = UI / 'runtime'


def main():
    RUNTIME.mkdir(exist_ok=True)
    env = dict(os.environ, TMPDIR=str(RUNTIME / 'tmp'), CI='1')
    log = (RUNTIME / 'cli-server.log').open('w')
    server = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1',
                               '--port', '4178', '--strictPort'], cwd=UI / 'verification',
                              env=env, stdout=log, stderr=log, start_new_session=True)
    receipts = []

    def cli(*args):
        result = subprocess.run([sys.executable, str(UI / 'tools/run.py'), 'playwright-cli',
                                 '-s=ui-smoke', *args], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=35)
        receipts.append({'command': list(args), 'returncode': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode:
            raise RuntimeError(f'CLI {args[0]} failed: {result.stderr[:300]} {result.stdout[:300]}')
        return result.stdout

    try:
        deadline = time.monotonic() + 10
        while True:
            if server.poll() is not None:
                raise RuntimeError('owned test server exited before readiness')
            try:
                with urlopen('http://127.0.0.1:4178', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('owned test server readiness timeout')
                time.sleep(.1)
        cli('open', 'http://127.0.0.1:4178')
        cli('route', '**/api/entities/*', '--body={"name":"CLI fixture profile"}', '--content-type=application/json')
        cli('reload')
        output = cli('eval', 'document.querySelector("#editor-title").textContent')
        if 'Editing profile A' not in output:
            raise RuntimeError('rendered editor was not observed')
        cli('snapshot', '--filename=' + str(RUNTIME / 'cli-snapshot.yml'))
        cli('close')
        listing = cli('list', '--json')
        (RUNTIME / 'cli-list-after-close.json').write_text(listing)
        print('UI_CLI_SMOKE_OK')
        return 0
    finally:
        # Close only the session created by this smoke check, never other browsers.
        try:
            cli('close')
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        if server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)
            try:
                server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait(timeout=3)
        log.close()
        (RUNTIME / 'cli-smoke-receipts.json').write_text(json.dumps(receipts, indent=2) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
