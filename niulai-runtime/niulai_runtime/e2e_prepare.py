"""Manual scheduled-E2E historical price preparation in an isolated private DB.

This command can retrieve public Yahoo prices when explicitly invoked. It never
sends mail, accesses Tiger, runs a production slot or creates live price events.
The caller supplies copied inputs below .niulai-state/e2e; those remain unchanged.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

UTC = timezone.utc


class PreparationError(ValueError):
    pass


def require(value, code):
    if not value:
        raise PreparationError(code)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def private_path(path, workspace, existing=False):
    boundary = workspace / '.niulai-state' / 'e2e'
    p = Path(os.path.abspath(path))
    require('..' not in Path(path).parts and p.is_relative_to(boundary)
            and p.resolve().is_relative_to(boundary.resolve()), 'E2E_PATH_OUTSIDE_BOUNDARY')
    for parent in [p, *p.parents]:
        if parent == workspace:
            break
        require(not parent.is_symlink(), 'E2E_PATH_SYMLINK')
    if existing:
        require(p.is_file() and p.stat().st_uid == os.getuid(), 'E2E_INPUT_INVALID')
    return p


def completed_cutoff(session, now, calendar=None):
    require(isinstance(now, datetime) and now.tzinfo is not None, 'AWARE_CLOCK_REQUIRED')
    try:
        target = date.fromisoformat(session)
        require(target.isoformat() == session, 'SESSION_FORMAT_INVALID')
    except (TypeError, ValueError):
        raise PreparationError('SESSION_FORMAT_INVALID') from None
    now = now.astimezone(UTC)
    start = (now - timedelta(days=20)).date().isoformat()
    end = (now + timedelta(days=1)).date().isoformat()
    if calendar is None:
        import exchange_calendars
        calendar = exchange_calendars.get_calendar('XNYS', start=start, end=end)
    require(getattr(calendar, 'name', None) == 'XNYS', 'XNYS_CALENDAR_REQUIRED')
    # A weekend boundary can lie outside the calendar's actual first/last
    # session even when it was used to construct that calendar range.
    first=getattr(calendar,'first_session',None);last=getattr(calendar,'last_session',None)
    if first is not None:start=max(start,first.date().isoformat())
    if last is not None:end=min(end,last.date().isoformat())
    eligible = []
    for day in calendar.sessions_in_range(start, end):
        close = calendar.session_close(day)
        if hasattr(close, 'to_pydatetime'):
            close = close.to_pydatetime()
        require(isinstance(close, datetime) and close.tzinfo is not None, 'SESSION_CLOSE_INVALID')
        close = close.astimezone(UTC)
        if close + timedelta(minutes=1) <= now:
            iso = day.date().isoformat() if hasattr(day, 'date') else str(day)
            eligible.append((iso, close))
    require(bool(eligible), 'NO_COMPLETED_SESSION')
    latest, close = eligible[-1]
    require(session == latest, 'LAST_COMPLETED_SESSION_REQUIRED')
    # The preserved parser recognizes a completed daily range only at close+1m.
    # This is an explicit historical replay cutoff, never a forged live clock.
    return close, close + timedelta(minutes=1)


def clone_database(source, target):
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as src:
        require(src.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'SOURCE_DATABASE_INVALID')
        with sqlite3.connect(target) as dst:
            src.backup(dst)


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def live_digest(db):
    existing = tables(db)
    value = {'signals': [], 'live_runs': [], 'live_slots': []}
    if 'price_signals' in existing:
        value['signals'] = sorted(tuple(r) for r in db.execute('SELECT * FROM price_signals'))
    live_ids = set()
    if 'price_runs' in existing:
        for rid, payload in db.execute('SELECT id,payload FROM price_runs'):
            if json.loads(payload).get('mode') == 'live':
                live_ids.add(rid)
                value['live_runs'].append((rid, payload))
    if 'price_completed_slots' in existing:
        value['live_slots'] = [tuple(r) for r in db.execute('SELECT slot_id,run_id FROM price_completed_slots') if r[1] in live_ids]
    value['live_runs'].sort();value['live_slots'].sort()
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def remove_copied_replay_cache(db):
    existing = tables(db)
    if 'price_runs' not in existing:
        return 0
    replay = [rid for rid, raw in db.execute('SELECT id,payload FROM price_runs') if json.loads(raw).get('mode') == 'replay']
    for rid in replay:
        if 'price_sources' in existing:
            db.execute('DELETE FROM price_sources WHERE run_id=?', (rid,))
        if 'price_completed_slots' in existing:
            db.execute('DELETE FROM price_completed_slots WHERE run_id=?', (rid,))
        db.execute('DELETE FROM price_runs WHERE id=?', (rid,))
    db.commit()
    return len(replay)


def stage(workspace, code):
    script_root = workspace / 'niulai/skills/investment-research-financial-services/references/niulai-workflow/scripts'
    holdings = workspace / 'niulai/holdings'
    code.mkdir(mode=0o700)
    for source in [*(script_root / n for n in ('price_watch.py', 'niulai_state.py', 'price_report.py')),
                   *(holdings / n for n in ('price_summary_view.py', 'render_price_pdf.py'))]:
        require(source.is_file() and not source.is_symlink(), 'PRESERVED_SOURCE_INVALID')
        shutil.copyfile(source, code / source.name)
    fonts = holdings / 'fonts'
    require(fonts.is_dir() and not any(p.is_symlink() for p in [fonts, *fonts.rglob('*')]), 'FONT_SOURCE_INVALID')
    shutil.copytree(fonts, code / 'fonts')


def run_stage(command, *, env, cwd, timeout, log):
    cp = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    log.write_text(cp.stdout + '\n' + cp.stderr)
    require(cp.returncode == 0, 'PRICE_STAGE_FAILED')


def prepare(workspace, workflow, rules, dbclone, out, session, *, now=None, calendar=None, runner=None):
    workspace = Path(workspace).resolve(strict=True)
    workflow = private_path(workflow, workspace, True)
    rules = private_path(rules, workspace, True)
    dbclone = private_path(dbclone, workspace, True)
    out = private_path(out, workspace)
    require(not out.exists(), 'FRESH_OUTPUT_REQUIRED')
    close, cutoff = completed_cutoff(session, now or datetime.now(UTC), calendar)
    inputs = {str(p.relative_to(workspace)): digest(p) for p in (workflow, rules, dbclone)}
    out.mkdir(mode=0o700, parents=True)
    code = out / 'code';stage(workspace, code)
    for name in ('tmp', 'cache'):
        (out / name).mkdir(mode=0o700)
    working = out / 'evaluation.sqlite'
    clone_database(dbclone, working)
    with sqlite3.connect(working) as db:
        baseline = live_digest(db)
        cleared = remove_copied_replay_cache(db)
        require(live_digest(db) == baseline, 'REPLAY_CACHE_CHANGED_LIVE_STATE')
    env = {k: os.environ[k] for k in ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
        'HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'all_proxy', 'no_proxy') if k in os.environ}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(code), TMPDIR=str(out / 'tmp'), XDG_CACHE_HOME=str(out / 'cache'))
    execute = runner or run_stage
    manifest = {'schema_version': 1, 'purpose': 'manual_scheduled_e2e_historical_price_test',
        'session': session, 'session_close_utc': close.isoformat(), 'historical_cutoff_utc': cutoff.isoformat(),
        'mode': 'replay', 'copied_replay_cache_removed': cleared, 'input_sha256': inputs,
        'production_slot_completed': False, 'new_live_events': 0, 'email_status': 'not_sent'}
    try:
        execute([sys.executable, str(code / 'price_watch.py'), '--config', str(workflow), '--rules', str(rules),
            '--db', str(working), '--output', str(out / 'price_result.json'), '--role', 'existing_summary',
            '--mode', 'replay', '--as-of', cutoff.isoformat()], env=env, cwd=out, timeout=600, log=out / 'evaluate.log')
        result = json.loads((out / 'price_result.json').read_text())
        require(result.get('status') in ('completed', 'partial') and result.get('mode') == 'replay'
                and result.get('session') == session and result.get('retrospective') is True
                and result.get('new_signals') == [], 'HISTORICAL_RESULT_REQUIRED')
        coverage = result['coverage']
        require(coverage['enabled_rules'] == len(result['results']) + len(result['errors']), 'INCOMPLETE_RULE_SCOPE')
        with sqlite3.connect(working) as db:
            require(live_digest(db) == baseline, 'LIVE_STATE_CHANGED')
        view_dir = out / 'price_view'
        execute([sys.executable, str(code / 'price_summary_view.py'), '--db', str(working), '--rules', str(rules),
            '--run-id', result['id'], '--historical', '--out', str(view_dir)],
            env=env, cwd=out, timeout=60, log=out / 'view.log')
        execute([sys.executable, str(code / 'render_price_pdf.py'), str(view_dir / 'price_view.json'), str(out / 'price.pdf')],
            env=env, cwd=out, timeout=90, log=out / 'pdf.log')
        execute([sys.executable, str(code / 'price_report.py'), str(out / 'price_result.json'), str(out / 'price_full.html')],
            env=env, cwd=out, timeout=60, log=out / 'text.log')
        text = (out / 'price_full.txt').read_text()
        require(bool(text.strip()), 'FULL_PRICE_TEXT_REQUIRED')
        (out / 'price_message.txt').write_text('【Niulai triggered｜Codex scheduled E2E TEST】\n'
            '本报告为最新已完成纽约交易日的历史重评；本次重新获取来源，不是当前实时行情，不产生新实时事件。\n' + text)
        require((out / 'price.pdf').read_bytes().startswith(b'%PDF-'), 'ACTUAL_PRICE_PDF_REQUIRED')
        view = json.loads((view_dir / 'price_view.json').read_text())
        require(view.get('run_id') == result['id'] and view.get('session') == session
                and view.get('historical_presentation') is True and view.get('new_signal_records') == []
                and len(view['rows']) == coverage['enabled_rules'], 'PRICE_VIEW_PROVENANCE_INVALID')
        manifest.update(status=result['status'], run_id=result['id'], coverage=coverage,
            live_state_unchanged=True, price_view='price_view/price_view.json', price_text='price_message.txt', price_pdf='price.pdf')
    except Exception:
        manifest.update(status='failed', failure='PRICE_PREPARATION_FAILED')
        raise
    finally:
        unchanged = all(digest(workspace / path) == expected for path, expected in inputs.items())
        manifest['inputs_unchanged'] = unchanged
        (out / 'preparation_receipt.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        require(unchanged, 'INPUT_SNAPSHOT_CHANGED')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    for name in ('workflow', 'rules', 'dbclone', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--session', required=True)
    a = p.parse_args();os.umask(0o077)
    try:
        receipt = prepare(a.workspace, a.workflow, a.rules, a.dbclone, a.out, a.session)
        print(json.dumps({k: receipt[k] for k in ('status', 'session', 'coverage', 'new_live_events', 'inputs_unchanged', 'email_status')}))
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, PreparationError) else 'E2E_PREPARATION_FAILED'
        print(json.dumps({'status': 'failed', 'error': code, 'email_status': 'not_sent'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
