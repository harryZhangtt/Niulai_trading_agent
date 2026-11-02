"""Checkpointed adapter around the preserved financial parser/classifier.

Each raw response remains in SQLite. Recovery reuses valid observations at the
original cutoff and is explicitly retrospective; it never backdates a live run.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import time
import types
from urllib.request import Request, urlopen

from .daily_work import private, atomic, require, sha
from .e2e_prepare import stage, clone_database, live_digest, remove_copied_replay_cache


def module(path, name):
    value = types.ModuleType(name); value.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), value.__dict__)
    return value


def prepare(root, out, meta, *, fault=False, offline=False):
    root = Path(root).resolve(); out = private(root, out, True)
    if (out / 'branch.json').exists():
        old = json.loads((out / 'branch.json').read_text())
        if not old['pending'] or old['blocked']:
            return old
    code = out / 'code'
    if not code.exists():
        stage(root, code)
    # Imports point to staged copies, never write caches into migration source.
    sys.path.insert(0, str(code))
    try:
        watch = module(code / 'price_watch.py', '_daily_watch')
        renderer = module(code / 'price_summary_view.py', '_daily_view')
    finally:
        sys.path.remove(str(code))
    inputs = Path(meta['inputs']); workflow = json.loads((inputs / 'workflow.json').read_text())
    definitions = json.loads((inputs / 'alerts.json').read_text())['alerts']
    watch.validate_config(workflow); watch.validate_rules(definitions)
    for name, expected in meta['input_sha256'].items():
        require(sha((inputs / name).read_bytes()) == expected, 'DAILY_INPUT_CHANGED')
    database = (private(root, root / '.niulai-state/databases/daily-prices.sqlite')
                if meta['purpose'] == 'production' else out / 'observations.sqlite')
    if not database.exists():
        clone_database(inputs / 'alerts.sqlite', database)
        with sqlite3.connect(database) as db:
            remove_copied_replay_cache(db)
    cutoff = watch.instant(meta['price_asof']); market = watch.session(cutoff)
    require(market is not None, 'DAILY_PRICE_SESSION_REQUIRED')
    deadline = time.monotonic() + 180

    def bounded_text(url):
        if time.monotonic() >= deadline:
            raise TimeoutError('SOURCE_DEADLINE')
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0 NiulaiCodex/1'}),
                     timeout=min(8, max(0.1, deadline - time.monotonic()))) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            require(len(raw) <= 4 * 1024 * 1024, 'PRICE_RESPONSE_TOO_LARGE')
            return raw.decode()

    watch.request_text = bounded_text
    with sqlite3.connect(database) as db:
        watch.setup(db); baseline = live_digest(db)
        db.execute('CREATE TABLE IF NOT EXISTS daily_sources(scope TEXT,ticker TEXT,payload TEXT NOT NULL,PRIMARY KEY(scope,ticker))')
        saved = {r[0]: json.loads(r[1]) for r in db.execute('SELECT ticker,payload FROM daily_sources WHERE scope=?', (meta['scope'],))}
    def fetch(symbol, market, asof, earliest):
        old = saved.get(symbol)
        if old and not old.get('error'):
            return old
        if offline:
            value = {'ticker': symbol, 'error': 'SOURCE_DEADLINE_BRANCH_UNAVAILABLE', 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        elif fault:
            value = {'ticker': symbol, 'error': 'SYNTHETIC_SOURCE_FAILURE', 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        elif time.monotonic() >= deadline:
            value = {'ticker': symbol, 'error': 'SOURCE_DEADLINE', 'retrieved_at': datetime.now(timezone.utc).isoformat()}
        else:
            value = watch.fetch(symbol, market, asof, earliest)
        # One independent connection per worker; source is durable before return.
        with sqlite3.connect(database, timeout=20) as db:
            db.execute('INSERT OR REPLACE INTO daily_sources VALUES(?,?,?)', (meta['scope'], symbol, json.dumps(value)))
        return value
    watch.fetch_safe = fetch
    prior = json.loads((out / 'price_result.json').read_text()) if (out / 'price_result.json').exists() else None
    mode = 'live' if meta['purpose'] == 'production' and not prior and not offline else 'replay'
    with sqlite3.connect(database) as db:
        priors = [json.loads(r[0]) for r in db.execute('SELECT payload FROM price_runs')]
        priors = [r for r in priors if r.get('status') in ('completed', 'partial') and r.get('mode') == 'live'
                  and not r.get('retrospective') and watch.instant(r['as_of']) < cutoff]
        previous = max(priors, key=lambda r: watch.instant(r['as_of'])) if priors else None
        result = prior if prior and prior.get('status') == 'completed' else watch.run(workflow, definitions, db, cutoff, 'existing_summary', mode)
        mode = result.get('mode')
        require(result.get('status') in ('completed', 'partial'), 'DAILY_PRICE_FINALIZATION_REQUIRED')
        if mode == 'replay':
            require(live_digest(db) == baseline, 'DAILY_REPLAY_CHANGED_LIVE_SIGNALS')
    # A retry at a fixed historical cutoff must never create a new crossing.
    view = renderer.build(result, prior=previous, definitions=definitions, historical=mode != 'live')
    atomic(out / 'prior.json', previous)
    atomic(out / 'price_result.json', result); atomic(out / 'price_view.json', view)
    (out / 'price_message.txt').write_text('Complete rule scope and quote-only scope are retained in the structured report.\n'
        'Recovery/historical evaluation is retrospective; no new crossing is inferred.\n')
    from .e2e_prepare import run_stage
    temp = private(root, out / 'tmp', True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(temp), XDG_CACHE_HOME=str(temp))
    run_stage([sys.executable, str(code / 'render_price_pdf.py'), str(out / 'price_view.json'), str(out / 'price.pdf')],
              env=env, cwd=out, timeout=90, log=out / 'render.log')
    values = list(saved.values())
    with sqlite3.connect(database) as db:
        values = [json.loads(r[0]) for r in db.execute('SELECT payload FROM daily_sources WHERE scope=?', (meta['scope'],))]
    errors = [str(v.get('error', '')) for v in values if v.get('error')]
    if fault:
        errors.append('SYNTHETIC_SOURCE_FAILURE')
    blocked = any(any(s in e.lower() for s in ('403', 'forbidden', 'approval', 'unauthorized', '401')) for e in errors)
    transient = any(any(s in e.lower() for s in ('timeout', 'timed out', 'deadline', '408', '425', '429', '500',
        '502', '503', '504', 'connection', 'urlerror', 'urlopen', 'network', 'name resolution', 'nodename',
        'temporar', 'synthetic_source')) for e in errors)
    receipt = {'status': result['status'], 'coverage': result['coverage'], 'blocked': blocked,
        'pending': transient, 'mode': mode, 'as_of': result['as_of'], 'session': result['session'],
        'raw_sources': len(values), 'synthetic_fault': fault,
        'result_sha256': sha((out / 'price_result.json').read_bytes())}
    atomic(out / 'branch.json', receipt)
    return receipt
