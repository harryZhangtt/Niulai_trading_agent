#!/usr/bin/env python3
"""Local installation, credentials and authentication. Never changes global config."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
from urllib.request import Request, urlopen
from auth.credential_store import save_credentials

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
STATE = ROOT / '.market-data-mcp'
SCHWAB_VERSION = 'v0.2.3'


def environment():
    for directory in [STATE, STATE / 'tmp', STATE / 'runtime', STATE / 'schwab', STATE / 'tradingview']:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    env = dict(os.environ)
    credentials = STATE / 'credentials.json'
    if credentials.exists():
        data = json.loads(credentials.read_text())
        for key in ['SCHWAB_APP_KEY', 'SCHWAB_APP_SECRET', 'SCHWAB_CALLBACK_URL']:
            if data.get(key):
                env.setdefault(key, data[key])
    env.update({
        'MCP_REMOTE_CONFIG_DIR': str(STATE / 'tradingview'),
        'SCHWAB_TOKEN_FILE': str(STATE / 'schwab/token.json'),
        'SCHWAB_ALLOW_TRADING': 'false',
        'SCHWAB_ALLOW_MARKET_ORDERS': 'false',
        'TMPDIR': str(STATE / 'tmp'),
    })
    return env


def install_schwab():
    systems = {'Darwin': 'darwin', 'Linux': 'linux'}
    arches = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64', 'AMD64': 'amd64'}
    system, arch = systems.get(platform.system()), arches.get(platform.machine())
    if not system or not arch:
        raise SystemExit('Unsupported Schwab binary platform; see the pinned upstream README.')
    name = 'schwab-{}-{}.tar.gz'.format(system, arch)
    base = 'https://github.com/itsmostafa/schwab-mcp/releases/download/{}/'.format(SCHWAB_VERSION)
    for filename in [name, 'SHA256SUMS.txt']:
        with urlopen(Request(base + filename, headers={'User-Agent': 'TradingAgent-MCP/1.0'}), timeout=30) as response:
            (STATE / 'runtime' / filename).write_bytes(response.read())
    expected = next(line.split()[0] for line in (STATE / 'runtime/SHA256SUMS.txt').read_text().splitlines()
                    if line.endswith(name))
    archive = STATE / 'runtime' / name
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit('Schwab release checksum mismatch; installation refused.')
    target = STATE / 'bin'
    target.mkdir(exist_ok=True, mode=0o700)
    with tarfile.open(archive) as package:
        for member in package.getmembers():
            if member.isfile() and Path(member.name).name in ['schwab', 'LICENSE']:
                output = target / ('schwab' if Path(member.name).name == 'schwab' else 'SCHWAB-LICENSE')
                output.write_bytes(package.extractfile(member).read())
    (target / 'schwab').chmod(0o700)
    print(json.dumps({'version': SCHWAB_VERSION, 'sha256': actual, 'checksum_verified': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['serve', 'auth', 'credentials', 'install-schwab', 'print-config'])
    parser.add_argument('provider', nargs='?', choices=['tradingview', 'schwab', 'finnhub', 'marketdata', 'alpaca', 'massive'])
    args = parser.parse_args()
    env = environment()
    if args.action == 'print-config':
        template = (SOURCE / 'codex.disabled.example.toml').read_text()
        print(template.replace('/ABSOLUTE/WORKSPACE', str(ROOT)))
        return
    if args.action == 'install-schwab':
        install_schwab()
        return
    if args.provider is None:
        parser.error('provider is required for this action')
    if args.action == 'credentials':
        if not sys.stdin.isatty():
            raise SystemExit('Run credentials in an interactive local terminal for hidden input.')
        if args.provider in ['finnhub', 'marketdata', 'alpaca', 'massive']:
            data = {'api_key': getpass.getpass('{} API key (hidden): '.format(args.provider)).strip()}
            if args.provider == 'alpaca':
                data['api_secret'] = getpass.getpass('Alpaca API secret (hidden): ').strip()
            save_credentials(STATE / 'credentials' / (args.provider + '.json'), data)
            print('Saved {} credentials atomically in ignored owner-only workspace state.'.format(args.provider))
            return
        if args.provider != 'schwab':
            parser.error('TradingView uses OAuth; run auth tradingview')
        data = {
            'SCHWAB_APP_KEY': getpass.getpass('Schwab App Key (hidden): ').strip(),
            'SCHWAB_APP_SECRET': getpass.getpass('Schwab App Secret (hidden): ').strip(),
            'SCHWAB_CALLBACK_URL': input('Registered callback [https://127.0.0.1:8182/callback]: ').strip()
                or 'https://127.0.0.1:8182/callback',
        }
        if not data['SCHWAB_APP_KEY'] or not data['SCHWAB_APP_SECRET']:
            raise SystemExit('Both credentials are required; nothing saved.')
        location = STATE / 'credentials.json'
        fd = os.open(location, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(data, output)
        location.chmod(0o600)
        print('Saved credentials inside the ignored workspace state directory.')
        return
    node = shutil.which('node')
    if not node:
        raise SystemExit('Node.js >=22 is required.')
    if args.action == 'serve':
        command = [node, str(SOURCE / 'server.mjs'), args.provider]
    elif args.provider in ['marketdata', 'alpaca', 'massive']:
        urls = {'marketdata': 'https://www.marketdata.app/signup/',
                'alpaca': 'https://app.alpaca.markets/', 'massive': 'https://massive.com/dashboard/'}
        raise SystemExit('Use a free account at {} then run locally:\n'
                         'python3 shared/market_data_mcp/manage.py credentials {}\n'
                         'Do not paste keys into chat. This adapter never purchases a plan.'.format(urls[args.provider], args.provider))
    elif args.provider == 'finnhub':
        raise SystemExit('This local adapter reads the workspace API key. Run credentials finnhub to replace it.\n'
                         'Hosted Finnhub MCP uses separate OAuth: https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html')
    elif args.provider == 'tradingview':
        command = [node, str(SOURCE / 'node_modules/mcp-remote/dist/client.js'),
                   'https://mcp.tradingview.com/mcp', '18273', '--host', '127.0.0.1',
                   '--transport', 'http-only', '--auth-timeout', '600',
                   '--connect-timeout', '15', '--headers-timeout', '25']
    else:
        if not env.get('SCHWAB_APP_KEY') or not env.get('SCHWAB_APP_SECRET'):
            raise SystemExit('First obtain a Ready For Use app at https://developer.schwab.com/ then run\n'
                             'python3 shared/market_data_mcp/manage.py credentials schwab')
        command = [str(STATE / 'bin/schwab'), 'login']
    os.chdir(ROOT)
    os.execvpe(command[0], command, env)


if __name__ == '__main__':
    main()
