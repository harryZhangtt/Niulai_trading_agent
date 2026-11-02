"""Bounded live acquisition cases, not a universal source-quality certification.

``run(out)`` returns a hashed report reference.  Every network operation runs in
one killable process group; there are no automatic retries or active MCP edits.
The frozen case manifest is written before acquisition.  Discovery, document
coverage, and fallback coverage are reported separately rather than averaged.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from . import fetch
from .artifacts import ROOT, SOURCE_STATE, SourceError, private_path, read, require, save
from .toolchain import node_binary

PAPER_ID = '2407.08608v2'
ISSUER_URL = ('https://nvidianews.nvidia.com/news/'
              'nvidia-announces-financial-results-for-first-quarter-fiscal-2025')
# These exact primary URLs were inspected before defining the live checks.
CASES = {
    'openalex.discover': {'provider': 'openalex', 'capability': 'discover',
        'target': 'FlashAttention', 'expected_access': 'metadata',
        'minimum_coverage': 'A titled FlashAttention candidate with a public work identifier',
        'lineage': 'OpenAlex aggregation; original paper identity requires verification'},
    'arxiv.discover': {'provider': 'arxiv', 'capability': 'discover',
        'target': 'all:FlashAttention', 'expected_access': 'metadata',
        'minimum_coverage': 'A titled FlashAttention candidate with an arXiv abstract identifier',
        'lineage': 'arXiv manuscript metadata'},
    'arxiv.read': {'provider': 'arxiv', 'capability': 'read', 'target': PAPER_ID,
        'expected_access': 'document',
        'minimum_coverage': 'Exact revision identity and a substantive methods/results passage',
        'lineage': 'arxiv:' + PAPER_ID},
    'arxiv_mcp_candidate.read': {'provider': 'arxiv_mcp_candidate', 'capability': 'read',
        'target': PAPER_ID, 'expected_access': 'document',
        'minimum_coverage': 'Version-matched original identity plus a bounded methods/results section',
        'lineage': 'arxiv:' + PAPER_ID},
    'official_document.nvidia_release': {'provider': 'official_document', 'capability': 'read',
        'target': ISSUER_URL, 'expected_access': 'document',
        'minimum_coverage': 'NVDA Q1 FY2025 revenue 26,044 USD millions; quarter ended 2024-04-28',
        'lineage': 'NVIDIA:FY2025Q1:earnings-release'},
    'official_document.nvidia_blackwell': {'provider': 'official_document', 'capability': 'read',
        'target': 'https://docs.nvidia.com/cuda/blackwell-tuning-guide/index.html',
        'expected_access': 'document',
        'minimum_coverage': 'Blackwell tuning guidance containing memory/thread and tensor details',
        'patterns': [r'Blackwell', r'\bTensor\b', r'\b(memory|warp|thread)\b'],
        'passage_anchor': r'\b(memory|warp|thread)\b',
        'lineage': 'NVIDIA technical documentation; vendor statements'},
    'official_document.amd_rocm': {'provider': 'official_document', 'capability': 'read',
        'target': 'https://rocm.docs.amd.com/en/latest/', 'expected_access': 'document',
        'minimum_coverage': 'ROCm software-stack overview describing GPU compute and supported tooling',
        'patterns': [r'\bROCm\b', r'\bGPU', r'software\s+(stack|platform)|open.source'],
        'passage_anchor': r'software\s+(stack|platform)|open.source',
        'lineage': 'AMD technical documentation; competing vendor statements'},
    'official_document.google_tpu': {'provider': 'official_document', 'capability': 'read',
        'target': 'https://docs.cloud.google.com/tpu/docs/system-architecture-tpu-vm',
        'expected_access': 'document',
        'minimum_coverage': 'TPU architecture passage describing TensorCores and matrix-multiply units',
        'patterns': [r'Tensor\s+Processing\s+Units', r'TensorCore', r'matrix.multiply|\bMXU'],
        'passage_anchor': r'Each\s+TensorCore|matrix.multiply',
        'lineage': 'Google technical documentation; competing vendor statements'},
    'official_document.mlcommons': {'provider': 'official_document', 'capability': 'read',
        'target': 'https://mlcommons.org/benchmarks/inference-datacenter/',
        'expected_access': 'document',
        'minimum_coverage': 'Inference benchmark purpose, scenario/metric constraints, and quality targets',
        'patterns': [r'MLPerf\s+Inference', r'Scenarios\s*&\s*Metrics',
                     r'latency|throughput', r'quality\s+target'],
        'passage_anchor': r'Scenarios\s*&\s*Metrics',
        'substantive_pattern': r'load\s+generator|latency|quality\s+target',
        'lineage': 'MLCommons benchmark definitions; no independent replication assumed'},
}
MAX_OPERATIONS = 11
TOTAL_SECONDS = 420
FIXED_FACT_CACHE_SECONDS = 86400
CHECKER_VERSION = '1.1-substantive-passages'
PERMANENT_ERRORS = {'SOURCE_HTTP_401', 'SOURCE_HTTP_403', 'SOURCE_HTTP_429'}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _code(exc):
    value = str(exc)
    return value if isinstance(exc, SourceError) and re.fullmatch(r'[A-Z0-9_]{1,96}', value) else 'SOURCE_OPERATION_FAILED'


def _excerpt(text, pattern, radius=260):
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return None
    start, end = max(0, match.start() - 80), min(len(text), match.end() + radius)
    return {'locator': f'normalized-text:{start}:{end}', 'start': start, 'end': end,
            'text': text[start:end]}


def _substantive_passage(text, pattern):
    # Normalized parser lines are text nodes. Short navigation/ToC lines are
    # insufficient even when their headings contain every expected keyword.
    for node in re.finditer(r'[^\n]+', text):
        value = node.group()
        anchor = re.search(pattern, value, re.I)
        if (len(value) >= 140 and len(re.findall(r'[A-Za-z]', value)) >= 100
                and anchor and re.search(r'[.!?;]', value)):
            start = node.start() + max(0, anchor.start() - 120)
            end = min(node.end(), start + 900)
            return {'locator': f'normalized-text:{start}:{end}', 'start': start, 'end': end,
                    'text': text[start:end]}
    return None


def inspect(case_id, source_ref):
    """Outcome checks for the predeclared question; no claim-level admission."""
    case = CASES[case_id]
    receipt = read(source_ref)
    checks = {'expected_access': receipt.get('access_level') == case['expected_access'],
              'original_payload_readable': bool(read(receipt['raw'], json_value=False)),
              'provider_matches': receipt.get('provider') == case['provider']}
    evidence, limitations = {}, []
    if case['expected_access'] == 'metadata':
        candidates = receipt.get('candidates', [])
        relevant = [c for c in candidates if re.search(r'Flash\s*Attention', c.get('title') or '', re.I)
                    and isinstance(c.get('id'), str) and c['id'].startswith('http')]
        checks['relevant_identified_candidate'] = bool(relevant)
        if case_id == 'arxiv.discover':
            checks['arxiv_abstract_identity'] = bool(relevant) and all('/abs/' in c['id'] for c in relevant)
        evidence['candidates'] = [{k: c.get(k) for k in ('id', 'title', 'doi')} for c in relevant]
        limitations = ['Metadata supports discovery only; not a document read or verified business fact.',
                       'An aggregated identifier/DOI must be reconciled to the original paper.']
    else:
        text = read(receipt['text'], json_value=False).decode()
        checks.update({'substantive_text': len(text) >= 250, 'headings_present': bool(receipt.get('headings')),
                       'exact_source_url': receipt.get('source_url') ==
                       ('https://arxiv.org/html/' + PAPER_ID if case_id.startswith('arxiv') else case['target'])})
        if case_id.startswith('arxiv'):
            passage = _substantive_passage(text, r'asynchronous|warp.specializ|pipelining|\bFP8\b|\bTFLOPS\b|\bGEMM\b')
            checks.update({'exact_revision': receipt.get('upstream_id') == PAPER_ID and receipt.get('source_version') == '2',
                           'revision_availability_known': bool(receipt.get('available_at')),
                           'substantive_methods_or_results': passage is not None})
            if case_id == 'arxiv.read':
                checks['paper_title'] = bool(re.search(r'Flash\s*Attention.?3', text, re.I))
            else:
                checks['scoped_section'] = receipt.get('read_scope') == 'bounded extracted section'
                checks['primary_identity_readable'] = read(receipt['metadata']['primary_identity_receipt']).get('upstream_id') == PAPER_ID
            evidence['passage'] = passage
            limitations = ['One exact manuscript revision; peer review and general validity are not established.',
                           'MCP and direct arXiv reads share one upstream and are not independent corroboration.']
        elif case_id == 'official_document.nvidia_release':
            patterns = {'fiscal_period': r'First\s+Quarter\s+Fiscal\s+2025',
                        'period_end': r'(?:April|Apr\.?)\s+28,?\s+2024',
                        'publication_day': r'(?:May)\s+22,?\s+2024',
                        'table_units': r'\$\s+in\s+millions', 'table_column': r'Q1\s+FY25',
                        'table_revenue': r'Revenue\s+\$26,044'}
            checks.update({name: bool(re.search(pattern, text, re.I)) for name, pattern in patterns.items()})
            evidence['passages'] = {name: _excerpt(text, pattern) for name, pattern in patterns.items()}
            if all(checks.values()):
                evidence['observation'] = {'entity': 'NVDA', 'metric': 'reported consolidated quarterly revenue',
                    'period': 'FY2025Q1', 'period_end': '2024-04-28', 'value': 26044, 'unit': 'USD millions',
                    'statement_type': 'issuer_reported', 'publication_day_from_document': '2024-05-22'}
            limitations = ['Issuer-reported historical fact, not a forecast or independent outlook corroboration.',
                           'Receipt availability remains first-observed; document publication has day precision.']
        else:
            checks.update({f'topic_{i + 1}': bool(re.search(pattern, text, re.I))
                           for i, pattern in enumerate(case['patterns'])})
            evidence['passage'] = _substantive_passage(text, case.get('substantive_pattern', case['passage_anchor']))
            checks['substantive_topic_passage'] = evidence['passage'] is not None
            limitations = ['Current page content at first-observed time; historical vintage is not established.',
                           'Topic coverage alone does not establish performance claims or independent reproduction.']
            if case_id == 'official_document.mlcommons':
                limitations.append('Benchmark purpose/rules only; no specific system result or matched comparison admitted.')
    return {'status': 'pass' if all(checks.values()) else 'failed', 'checks': checks, 'checker_version': CHECKER_VERSION,
            'evidence': evidence, 'source_ref': source_ref, 'source_url': receipt['source_url'],
            'retrieved_at': receipt['retrieved_at'], 'access_level': receipt['access_level'],
            'lineage': case['lineage'], 'limitations': limitations,
            'claim_admission': 'Decision engine must still assess relevance, freshness, and independence.'}


def cached_fixed_fact(source_ref, *, now=None):
    """Narrow fallback: old observation time survives; a refresh failure is not no change."""
    check = inspect('official_document.nvidia_release', source_ref)
    observed = datetime.fromisoformat(check['retrieved_at'])
    current = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
    age = (current - observed).total_seconds()
    require(check['status'] == 'pass' and 0 <= age <= FIXED_FACT_CACHE_SECONDS, 'FIXED_FACT_CACHE_NOT_ELIGIBLE')
    return {'status': 'qualified', 'kind': 'same_original_source_cache', 'source_ref': source_ref,
            'original_observed_at': check['retrieved_at'], 'cache_age_seconds': age,
            'maximum_age_seconds': FIXED_FACT_CACHE_SECONDS, 'quality': check,
            'limitations': ['Fixed FY2025Q1 reported fact only; do not use this as current financial status.',
                            'Refresh failed in an injected test; no evidence that the source is unchanged.']}


@contextmanager
def _lock():
    directory = private_path(SOURCE_STATE / 'runtime/source-matrix', create=True)
    fd = os.open(directory / 'run.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SourceError('SOURCE_MATRIX_ALREADY_RUNNING') from None
        yield
    finally:
        os.close(fd)


def _process(args, timeout):
    """The only retry/timeout owner. Kill descendants on timeout; never echo stderr."""
    tmp = private_path(SOURCE_STATE / 'tmp', create=True)
    cache = private_path(SOURCE_STATE / 'cache/node', create=True)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', TMPDIR=str(tmp), NODE_COMPILE_CACHE=str(cache))
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=5)
        return {'ok': False, 'error': 'SOURCE_OPERATION_TIMEOUT', 'cleanup': 'process_group_killed'}
    # A crashed adapter must not leave a detached descendant in this group.
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        pass
    else:
        os.killpg(process.pid, signal.SIGKILL)
        return {'ok': False, 'error': 'SOURCE_DESCENDANT_CLEANUP_REQUIRED', 'cleanup': 'process_group_killed'}
    if process.returncode or len(stdout) > 1024 * 1024:
        return {'ok': False, 'error': 'SOURCE_OPERATION_PROCESS_FAILED', 'exit_code': process.returncode}
    try:
        return json.loads(stdout)
    except ValueError:
        return {'ok': False, 'error': 'SOURCE_OPERATION_OUTPUT_INVALID'}


def _worker(case_id, directory, primary_ref=None):
    attempts = []

    def getter(url):
        item = {'url': url, 'started_at': _now()}
        attempts.append(item)
        try:
            raw, content_type = fetch.get(url)
            item.update(status='returned', bytes=len(raw), content_type=content_type)
            return raw, content_type
        except Exception as exc:
            item.update(status='failed', error=_code(exc))
            raise
        finally:
            item['finished_at'] = _now()

    try:
        if case_id == 'openalex.discover':
            ref = fetch.discover_openalex(CASES[case_id]['target'], directory, getter=getter)
        elif case_id == 'arxiv.discover':
            ref = fetch.discover_arxiv(CASES[case_id]['target'], directory, getter=getter)
        elif case_id == 'arxiv.read':
            ref = fetch.fetch_arxiv(PAPER_ID, directory, getter=getter)
        elif case_id == 'arxiv_mcp_candidate.read':
            require(primary_ref is not None, 'MCP_PRIMARY_RECEIPT_REQUIRED')
            start_ns = time.time_ns()
            # Outer worker owns the process group; Node retains the adapter's one-attempt policy.
            result = subprocess.run([node_binary(), str(ROOT / 'shared/research_sources/mcp_probe.mjs'), 'live'],
                                    cwd=ROOT, capture_output=True, text=True)
            require(result.returncode == 0, 'MCP_PROBE_FAILED')
            report_path = SOURCE_STATE / 'runtime/arxiv-mcp-probe.json'
            require(report_path.stat().st_mtime_ns >= start_ns, 'MCP_REPORT_NOT_FRESH')
            report_ref = save(directory, json.loads(report_path.read_text()))
            ref = fetch.ingest_mcp_section(report_ref, primary_ref, directory)
            return {'ok': True, 'source_ref': ref, 'http_attempts': None, 'protocol_report_ref': report_ref,
                    'observed_protocol_operations': ['list_tools', 'materialize_paper', 'get_paper_outline', 'read_paper_section'],
                    'upstream_http_call_count': None, 'cleanup': 'adapter_verified'}
        else:
            ref = fetch.fetch_document(CASES[case_id]['target'], directory, getter=getter)
        return {'ok': True, 'source_ref': ref, 'http_attempts': attempts, 'cleanup': 'worker_exited'}
    except Exception as exc:
        return {'ok': False, 'error': _code(exc), 'http_attempts': attempts, 'cleanup': 'worker_exited'}


def _execute(case_id, directory, primary_ref=None, *, timeout):
    args = [sys.executable, '-m', 'shared.research_sources.source_matrix', '--worker', case_id, '--out', str(directory)]
    if primary_ref:
        args.extend(['--primary-ref', json.dumps(primary_ref)])
    return _process(args, timeout)


def _controlled_fallback(case_id, fallback):
    """Inject before I/O, then actually execute the allowed recovery handler."""
    scenario = {'scenario': 'controlled_primary_transport_failure', 'fault_injected': True,
                'primary_case_id': case_id, 'injection_boundary': 'before_io',
                'natural_outage_observed': False, 'injected_at': _now()}
    try:
        raise SourceError('INJECTED_PRIMARY_TRANSPORT_FAILURE')
    except SourceError as exc:
        scenario['injected_error'] = _code(exc)
        scenario['recovery_started_at'] = _now()
        return fallback(), scenario


def run(out, include_mcp=True, *, executor=None, clock=time.monotonic):
    """Run the finite source matrix. Unit-test injection never changes a live adapter."""
    directory = private_path(out, create=True)
    execute = executor or _execute
    with _lock():
        started, began = _now(), clock()
        manifest_ref = save(directory, {'schema_version': 1, 'cases': CASES,
            'checker_version': CHECKER_VERSION,
            'max_operations': MAX_OPERATIONS, 'total_seconds': TOTAL_SECONDS,
            'fixed_fact_cache_seconds': FIXED_FACT_CACHE_SECONDS, 'include_mcp': include_mcp,
            'acceptance': 'Each route requires payload-specific coverage; fallback separately graded.',
            'scope': 'Small development source sample, not a reliability estimate or complete investment review.'})
        attempts, rows, known_failures = [], [], {}

        def call(case_id, purpose, primary_ref=None):
            remaining = TOTAL_SECONDS - (clock() - began)
            item = {'attempt_id': f'call-{len(attempts) + 1}', 'case_id': case_id,
                    'purpose': purpose, 'target': CASES[case_id]['target'], 'started_at': _now(),
                    'provider': CASES[case_id]['provider'], 'fault_injected': False}
            attempts.append(item)
            if remaining <= 1 or len(attempts) > MAX_OPERATIONS:
                item.update(status='blocked', error='SOURCE_MATRIX_BUDGET_EXHAUSTED')
            elif case_id in known_failures:
                item.update(status='blocked', error='KNOWN_ACCESS_FAILURE_NOT_RETRIED',
                            prior_error=known_failures[case_id])
            else:
                timeout = min(110 if case_id.startswith('arxiv_mcp') else 50 if case_id == 'arxiv.read' else 26, remaining)
                try:
                    result = execute(case_id, directory, primary_ref, timeout=timeout)
                except Exception as exc:
                    result = {'ok': False, 'error': _code(exc)}
                item.update(result)
                item['status'] = 'returned' if result.get('ok') else 'failed'
                if result.get('error') in PERMANENT_ERRORS:
                    known_failures[case_id] = result['error']
                if result.get('ok'):
                    try:
                        item['quality'] = inspect(case_id, result['source_ref'])
                        if item['quality']['status'] != 'pass':
                            item['status'], item['error'] = 'failed', 'SOURCE_PAYLOAD_COVERAGE_FAILED'
                    except Exception as exc:
                        item['status'], item['error'] = 'failed', _code(exc)
            item['finished_at'] = _now()
            return item

        def fault(case_id, alternative, scenario, *, kind='compatible_live_fetch'):
            return {**scenario, 'kind': kind,
                    'alternative_attempt_id': alternative['attempt_id'],
                    'status': 'pass' if alternative['status'] == 'returned' else alternative['status'],
                    'same_upstream': CASES[case_id]['lineage'] == CASES[alternative['case_id']]['lineage']}

        def row(case_id, primary, fallback):
            status = ('pass' if primary['status'] == 'returned' and fallback['status'] == 'pass' else
                      'qualified' if primary['status'] == 'returned' or fallback['status'] in ('pass', 'qualified') else
                      'blocked' if primary['status'] == 'blocked' else 'failed')
            rows.append({'case_id': case_id, 'provider': CASES[case_id]['provider'],
                         'capability': CASES[case_id]['capability'], 'target': CASES[case_id]['target'],
                         'primary_attempt_id': primary['attempt_id'], 'status': status, 'fallback': fallback})

        openalex = call('openalex.discover', 'primary')
        arxiv_discovery, oa_fault = _controlled_fallback('openalex.discover',
            lambda: call('arxiv.discover', 'primary_and_openalex_injected_fallback'))
        # One live result can evidence both capabilities; it is never counted as two calls.
        openalex_fallback, ax_fault = _controlled_fallback('arxiv.discover',
            lambda: call('openalex.discover', 'arxiv_discovery_injected_fallback'))
        row('openalex.discover', openalex, fault('openalex.discover', arxiv_discovery, oa_fault))
        row('arxiv.discover', arxiv_discovery, fault('arxiv.discover', openalex_fallback, ax_fault))
        paper = call('arxiv.read', 'primary')
        primary_ref = paper.get('source_ref') if paper['status'] == 'returned' else None
        if include_mcp and primary_ref:
            mcp, paper_fault = _controlled_fallback('arxiv.read',
                lambda: call('arxiv_mcp_candidate.read', 'primary_and_arxiv_injected_fallback', primary_ref))
            paper_fallback, mcp_fault = _controlled_fallback('arxiv_mcp_candidate.read',
                lambda: call('arxiv.read', 'mcp_injected_fallback'))
            row('arxiv.read', paper, fault('arxiv.read', mcp, paper_fault))
            row('arxiv_mcp_candidate.read', mcp, fault('arxiv_mcp_candidate.read', paper_fallback, mcp_fault))
        else:
            reason = 'OPTIONAL_MCP_DISABLED' if not include_mcp else 'MCP_PRIMARY_IDENTITY_DEPENDENCY'
            rows.append({'case_id': 'arxiv_mcp_candidate.read', 'provider': 'arxiv_mcp_candidate',
                         'capability': 'read', 'target': PAPER_ID, 'status': 'blocked', 'reason': reason,
                         'fallback': {'status': 'qualified' if primary_ref else 'blocked',
                                      'kind': 'previous_actual_primary_read', 'alternative_attempt_id': paper['attempt_id']}})
            row('arxiv.read', paper, {'status': 'blocked', 'reason': reason})
        issuer = call('official_document.nvidia_release', 'primary')
        if issuer['status'] == 'returned':
            try:
                cache, issuer_fault = _controlled_fallback('official_document.nvidia_release',
                    lambda: cached_fixed_fact(issuer['source_ref']))
                cache.update(**issuer_fault, same_upstream=True, actual_cache_read=True)
            except Exception as exc:
                cache = {'status': 'failed', 'error': _code(exc)}
        else:
            cache = {'status': 'blocked', 'reason': 'NO_ELIGIBLE_FIXED_FACT_CACHE'}
        row('official_document.nvidia_release', issuer, cache)
        for case_id in CASES:
            if case_id.startswith('official_document.') and case_id != 'official_document.nvidia_release':
                document = call(case_id, 'primary')
                row(case_id, document, {'status': 'blocked', 'reason': 'NO_REVIEWED_FACT_EQUIVALENT_ALTERNATIVE',
                                       'limitations': ['Other vendor or benchmark documents are different evidence, not interchangeable observations.']})
        rows.extend([
            {'case_id': 'official_document.sec_filing', 'provider': 'official_document', 'capability': 'read',
             'target': None, 'status': 'blocked', 'reason': 'INSPECTED_SEC_FILING_LOCATOR_NOT_PROVIDED',
             'fallback': {'status': 'qualified' if issuer['status'] == 'returned' else 'blocked',
                          'kind': 'same_period_original_issuer_release', 'alternative_attempt_id': issuer['attempt_id'],
                          'limitations': ['Does not establish SEC filing access or satisfy a requirement specifically demanding a filing/footnote.']}},
            {'case_id': 'web_search.discover', 'provider': 'web_search', 'capability': 'discover',
             'target': None, 'status': 'blocked', 'reason': 'EXTERNAL_HOST_WORKFLOW_VERIFIED_SEPARATELY',
             'fallback': {'status': 'blocked', 'reason': 'NO_HOST_RECEIPT_BOUND_TO_THIS_MATRIX'}}])
        status = 'pass' if all(r['status'] == 'pass' for r in rows) else 'partial'
        report = {'schema_version': 1, 'kind': 'bounded_source_runtime_matrix', 'status': status,
                  'manifest_ref': manifest_ref, 'started_at': started, 'finished_at': _now(),
                  'elapsed_seconds': round(clock() - began, 3), 'attempts': attempts, 'routes': rows,
                  'observability': {'operation_count': len(attempts), 'max_operations': MAX_OPERATIONS,
                      'max_parallel_operations': 1, 'automatic_retries': 0,
                      'observed_direct_http_calls': sum(len(a.get('http_attempts') or []) for a in attempts),
                      'mcp_upstream_http_calls': None, 'tokens': None, 'cost': None,
                      'unknown_reason': 'Direct adapters expose HTTP attempts; MCP cache/upstream cost and model tokens are not exposed.'},
                  'limitations': ['Fixture and isolated live results do not replace future scheduled Codex acceptance and verified notification.',
                      'One bounded topic case per capability is not a reliability estimate.',
                      'A pass is scoped to payload coverage for this case; semantic admission stays in the decision engine.',
                      'Fault-injected fallback is not evidence of a natural provider outage.']}
        ref = save(directory, report)
        return {'report_ref': ref, 'status': status, 'route_statuses': {r['case_id']: r['status'] for r in rows}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--without-mcp', action='store_true')
    parser.add_argument('--worker', choices=CASES)
    parser.add_argument('--primary-ref')
    args = parser.parse_args()
    os.umask(0o077)
    if args.worker:
        result = _worker(args.worker, private_path(args.out, create=True),
                         json.loads(args.primary_ref) if args.primary_ref else None)
    else:
        result = run(args.out, include_mcp=not args.without_mcp)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
