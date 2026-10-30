"""Scoped scheduled acceptance: real acquisition, negative admission, real gates.

No mail is sent here. The supervisor verifies the scheduled attempt and synchronizes
one owner notification under docs/deployment/runtime-acceptance.md.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
from shared.research_sources.artifacts import ROOT, SOURCE_STATE, INVESTMENT_STATE, SourceError, digest, read, require, save
from shared.research_sources.fetch import discover_openalex, fetch_arxiv, fetch_document, ingest_mcp_section
from shared.research_sources.toolchain import node_binary
from .requirements import freeze
from .coverage import validate

PATTERNS = ['investment/research/*.py', 'investment/research/profiles/*.json',
    'investment/research/tests/*.py', 'shared/research_sources/*.py',
    'shared/research_sources/*.mjs', 'shared/research_sources/*.json',
    'shared/research_sources/*requirements.txt', 'shared/research_sources/tests/*.py',
    'shared/market_data_mcp/adapters/research-stdio.mjs', 'AGENTS.md', 'investment/AGENTS.md']


def fingerprint():
    values = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for pattern in PATTERNS for p in ROOT.glob(pattern) if p.is_file()}
    return {'sha256': digest(values), 'files': values}


def exercise(change, attempt, scheduled_at):
    os.umask(0o077)
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', change) and
            re.fullmatch(r'[0-9a-f-]{36}', attempt), 'ACCEPTANCE_ID_INVALID')
    folder = ROOT / '.job-runtime/acceptance' / change
    declared = json.loads((folder / 'record.json').read_text())
    if fingerprint()['sha256'] != declared['candidate']['source_fingerprint']:
        raise SourceError('ACCEPTANCE_CANDIDATE_CHANGED')
    require(hashlib.sha256((SOURCE_STATE / 'toolchain.json').read_bytes()).hexdigest()
            == declared['candidate']['toolchain_sha256'], 'ACCEPTANCE_TOOLCHAIN_CHANGED')
    state = INVESTMENT_STATE / change / attempt
    blobs = SOURCE_STATE / 'runtime' / change / attempt
    start = datetime.now(timezone.utc)
    cutoff = start.replace(hour=23, minute=59, second=59, microsecond=0).isoformat()
    contract = freeze({'subject': 'NVDA', 'as_of': cutoff, 'profile': 'accelerated-compute',
        'claims': [{'id': 'efficiency', 'question': 'How does workload-specific efficiency reach paid GPU demand and vendor value capture?'}]}, state)
    before = read(contract['requirements'])
    def stage(name):
        with (state / 'stages.jsonl').open('a') as stream:
            stream.write(json.dumps({'stage': name, 'at': datetime.now(timezone.utc).isoformat()}) + '\n')
    stage('requirements_frozen')
    arxiv = fetch_arxiv('2407.08608v2', blobs)
    stage('arxiv_read')
    openalex = discover_openalex('FlashAttention', blobs)
    stage('openalex_discovery')
    nvidia = fetch_document('https://docs.nvidia.com/cuda/blackwell-tuning-guide/index.html', blobs)
    stage('nvidia_document')
    negative = save(state, {'requirements_sha256': contract['expected_sha256'],
        'evidence': [{'requirement_id': 'efficiency:technical_research', 'source': openalex}]})
    try:
        validate(contract, negative)
    except SourceError as exc:
        if str(exc) != 'SOURCE_ACCESS_INSUFFICIENT': raise
        blocked = str(exc)
    else:
        raise SourceError('METADATA_INCORRECTLY_ACCEPTED')
    stage('metadata_blocked')
    (SOURCE_STATE / 'tmp').mkdir(parents=True, exist_ok=True, mode=0o700)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(SOURCE_STATE / 'tmp'),
               NODE_COMPILE_CACHE=str(SOURCE_STATE / 'cache/node'))
    stage('mcp_started')
    mcp = subprocess.run([node_binary(), 'shared/research_sources/mcp_probe.mjs', 'live'], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=110)
    if mcp.returncode: raise SourceError('SCHEDULED_MCP_PROBE_FAILED')
    mcp_report = save(blobs, json.loads((SOURCE_STATE / 'runtime/arxiv-mcp-probe.json').read_text()))
    section = ingest_mcp_section(mcp_report, arxiv, blobs)
    stage('mcp_section_read')
    checks = []
    for directory in ['investment/research/tests', 'shared/research_sources/tests']:
        result = subprocess.run([str(ROOT / '.research-sources/.venv/bin/python'), '-m', 'unittest',
            'discover', '-s', directory, '-q'], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        checks.append({'suite': directory, 'exit_code': result.returncode,
                       'output': result.stdout + result.stderr})
    stage('pipeline_checks_completed')
    report = {'schema_version': 1, 'attempt_id': attempt, 'scheduled_at': scheduled_at,
        'started_at': start.isoformat(), 'finished_at': datetime.now(timezone.utc).isoformat(),
        'candidate_sha256': fingerprint()['sha256'], 'contract': contract,
        'requirements_unchanged': read(contract['requirements']) == before,
        'sources': {'arxiv': arxiv, 'openalex': openalex, 'nvidia': nvidia, 'mcp_section': section},
        'metadata_admission_error': blocked, 'mcp_report': mcp_report, 'checks': checks,
        'claim': 'Scoped retrieval and gate mechanics only; no real investment conclusion fabricated.'}
    ref = save(state, report)
    with (state / 'run-index.json').open('x') as stream: json.dump({'report': ref}, stream)
    return {'status': 'completed', 'code': 'RESEARCH_SOURCE_COMPONENT_EXERCISED',
            'report_directory': str(state), 'delivery_verified': False}


def verify(options, workspace, context, result):
    folder = ROOT / '.job-runtime/acceptance' / options['change_id']
    path = INVESTMENT_STATE / options['change_id'] / context['attempt_id'] / 'run-index.json'
    try:
        report = read(json.loads(path.read_text())['report'])
        declared = json.loads((folder / 'record.json').read_text())
        pin = declared['candidate']['source_fingerprint']
        if hashlib.sha256((SOURCE_STATE / 'toolchain.json').read_bytes()).hexdigest() != declared['candidate']['toolchain_sha256']:
            return {'verified': False}
        if report['attempt_id'] != context['attempt_id'] or report['candidate_sha256'] != pin or fingerprint()['sha256'] != pin:
            return {'verified': False}
        due = datetime.fromisoformat(context['scheduled_at'])
        if datetime.fromisoformat(report['started_at']) < due or not report['requirements_unchanged']:
            return {'verified': False}
        if (datetime.fromisoformat(report['finished_at']) - due).total_seconds() > declared['criteria']['completion_timeout_seconds']:
            return {'verified': False}
        for provider, ref in report['sources'].items():
            receipt = read(ref)
            if datetime.fromisoformat(receipt['retrieved_at']) < due: return {'verified': False}
            read(receipt['raw'], json_value=False)
            if provider != 'openalex': read(receipt['text'], json_value=False)
        if read(report['sources']['arxiv'])['upstream_id'] != '2407.08608v2': return {'verified': False}
        if read(report['sources']['openalex'])['access_level'] != 'metadata': return {'verified': False}
        if report['metadata_admission_error'] != 'SOURCE_ACCESS_INSUFFICIENT': return {'verified': False}
        mcp = read(report['mcp_report'])
        if not mcp['process_cleanup_verified'] or not mcp['queried']: return {'verified': False}
        if len(report['checks']) != 2 or any(c['exit_code'] != 0 or 'OK' not in c['output'] for c in report['checks']):
            return {'verified': False}
        return {'verified': True, 'component_report': json.loads(path.read_text())['report'],
            'candidate_sha256': pin, 'metadata_blocked': True, 'source_receipts_checked': 4,
            'scope': 'Source separation and gate mechanics; no completed NVDA investment thesis'}
    except Exception:
        return {'verified': False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--change-id', required=True)
    p.add_argument('--attempt-id', required=True); p.add_argument('--scheduled-at', required=True); a = p.parse_args()
    try: print(json.dumps(exercise(a.change_id, a.attempt_id, a.scheduled_at)))
    except Exception as exc:
        state = INVESTMENT_STATE / a.change_id / a.attempt_id
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', a.change_id) and re.fullmatch(r'[0-9a-f-]{36}', a.attempt_id) and state.is_dir():
            with (state / 'failure.json').open('w') as stream:
                json.dump({'error': str(exc) if isinstance(exc, SourceError) else 'SOURCE_ACCEPTANCE_FAILED',
                           'exception_type': type(exc).__name__}, stream)
        print(json.dumps({'status': 'failed', 'code': str(exc) if isinstance(exc, SourceError) else 'SOURCE_ACCEPTANCE_FAILED'}))
        raise SystemExit(2)
