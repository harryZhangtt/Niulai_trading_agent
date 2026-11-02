"""One bounded source/cache validation workload for an actual agent tool call.

Live acquisition and replay remain separate. This command makes no investments,
changes no host configuration and sends no mail. The supervisor independently
reopens receipts instead of trusting the agent's prose.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

from .artifacts import private_path, read, require, save
from .source_matrix import run as sources_run, inspect


def run(out):
    from .cache_matrix import run as cache_run
    directory = private_path(out, create=True)
    source = sources_run(directory / 'sources')
    cache = cache_run(directory / 'cache', source_matrix_ref=source['report_ref'])
    result = {'schema_version': 1, 'kind': 'source_cache_agent_workload',
              'source': source, 'cache': cache}
    status = 'failed' if cache['status'] == 'failed' else 'partial' if source['status'] != 'pass' or cache['status'] != 'pass' else 'pass'
    return {'report_ref': save(directory, result), 'status': status}


def verify(ref, *, not_before=None):
    from .cache_matrix import verify as verify_cache
    result = read(ref)
    require(result.get('kind') == 'source_cache_agent_workload', 'RUNTIME_WORKLOAD_KIND')
    source = read(result['source']['report_ref']); read(source['manifest_ref'])
    require(source['observability']['operation_count'] <= source['observability']['max_operations'], 'RUNTIME_SOURCE_BUDGET')
    accepted, failed = [], []
    for attempt in source['attempts']:
        if attempt['status'] != 'returned':
            failed.append({'case_id': attempt['case_id'], 'reason': attempt.get('error')})
            continue
        receipt = read(attempt['source_ref'])
        if not_before is not None:
            require(datetime.fromisoformat(receipt['retrieved_at']) >= datetime.fromisoformat(not_before), 'RUNTIME_SOURCE_NOT_FRESH')
        checked = inspect(attempt['case_id'], attempt['source_ref'])
        # Inspect returns a receipt; coverage must independently pass again.
        require(checked.get('status') in ('pass', 'supported') or checked.get('usable') is True,
                'RUNTIME_SOURCE_COVERAGE')
        accepted.append(attempt['case_id'])
    require('official_document.nvidia_release' in accepted, 'RUNTIME_ISSUER_MISSING')
    cache = verify_cache(result['cache']['report_ref'])
    cache_report = read(result['cache']['report_ref'])
    cache_manifest = read(cache_report['manifest_ref'])
    require(cache_manifest['source_matrix_ref'] == result['source']['report_ref'], 'RUNTIME_CACHE_SOURCE_BINDING')
    if not_before is not None:
        require(datetime.fromisoformat(cache_report['started_at']) >= datetime.fromisoformat(not_before), 'RUNTIME_CACHE_NOT_FRESH')
    return {'verified': cache.get('verified') is True, 'source_coverage_status': source['status'],
            'distinct_usable_cases': sorted(set(accepted)), 'source_accepted_attempts': accepted, 'source_failed_attempts': failed,
            'routes': source['routes'], 'source_observability': source['observability'], 'cache': cache,
            'scope': 'bounded workload mechanics; per-route coverage is separate. MCP proves protocol/local materialization, not fresh upstream HTTP; host web/SEC gaps remain explicit'}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True)
    args = parser.parse_args(); directory = private_path(args.out, create=True)
    result = run(directory)
    pointer = directory / 'result.json'
    from shared.job_runtime.service import atomic
    atomic(pointer, result)
    print(json.dumps(result))


if __name__ == '__main__': main()
