"""Project-local entry points. Never registers MCP with the active host."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from shared.langchain_mcp.client import MCPClient, LOCAL, REMOTE, canonical, digest, need, read_private, write_private
from .agent import ROOT, PROMPT, source_hashes, run
from .inspect import CORE, FULL, truth

REVIEW = ROOT / '.langchain-pilot/runtime/mcp-review'
STATE = ROOT / '.langchain-pilot/runtime/mcp-agent'


def preservation():
    cases = json.loads((ROOT / 'tuning/langchain_mcp_agent/cases.json').read_text())
    for item in cases['frozen_existing_artifact_source_hashes']:
        need(hashlib.sha256((ROOT / item['path']).read_bytes()).hexdigest() == item['sha256'], 'MCP_BASELINE_DRIFT')
    # Baseline/history receipt shape is independently pinned in cases.json.
    return cases


def auxiliary(root):
    values = {}
    def visit(node):
        values[node['id']] = {key: node.get(key) for key in ('start_time', 'dotted_order', 'total_cost', 'total_tokens')}
        for child in node.get('child_runs') or []: visit(child)
    visit(root)
    return values


def prepare():
    """Seal native-reference truth before the four MCP experiment calls.

    Exact native reads form an independent reference, not an inspection fallback.
    Only two already-owned synthetic root IDs are admitted, from a private receipt.
    """
    from tuning.langchain_pilot import observability as obs, atomic_cloud as cloud
    cases = preservation()
    directory = STATE / ('manifest-' + str(uuid4()))
    directory.mkdir(parents=True, mode=0o700)
    source = read_private(REVIEW / '634cab55-a2e7-473c-994b-9d24711db1ae/manifest.json')
    specs = [('calculator', source['records'][0]), ('holdings', source['records'][1])]
    samples = {}
    native = {}
    with closing(obs.client()) as client:
        for kind, record in specs:
            root_id = record['output']['trace']['run_id']
            check = cloud.check_trace(client, kind, root_id + '.json')
            profile = cloud.local_profile(kind)
            root = obs.read_exact_run(client, root_id, project_id=profile['project_id'], children=True)
            nodes = []
            def visit(node, parents):
                row = {'id': str(node.id), 'name': node.name, 'run_type': node.run_type,
                       'status': 'error' if node.error else 'success', 'project_id': str(node.session_id),
                       'trace_id': str(node.trace_id), 'parent_run_ids': parents,
                       'outputs': node.outputs, 'end_time': node.end_time.isoformat(), 'error': node.error}
                nodes.append(row)
                for child in node.child_runs or []: visit(child, parents + [str(node.id)])
            visit(root, [])
            safe = {}
            def payload(node):
                safe[str(node.id)] = {'inputs': node.inputs, 'extra': node.extra,
                                     'metadata': (node.extra or {}).get('metadata'), 'events': node.events}
                for child in node.child_runs or []: payload(child)
            payload(root)
            if kind == 'holdings':
                from tuning.langchain_pilot.holdings import project
                need(project(root.outputs['result']) == record['output']['result'], 'MCP_REFERENCE_OUTPUT')
            else:
                need(root.outputs == record['output']['result'], 'MCP_REFERENCE_OUTPUT')
            samples[kind] = {'project_id': profile['project_id'], 'trace_id': root_id,
                             'root_id': str(root.id), 'root_output': root.outputs,
                             'nodes': truth(nodes), 'safe_payloads': safe,
                             'auxiliary': auxiliary(root.model_dump(mode='json'))}
            native[kind] = {'check': check, 'root': root.model_dump(mode='json')}
    # The captured actual query schema supplies the pinned remote contract.
    captured = read_private(REVIEW / 'langsmith-d779b1ee-a6d2-46cc-bbbc-1e63234e34c5/tools-list.json')
    remote_tools = json.loads(captured['body'])['result']['tools']
    remote_schema = next(t['inputSchema'] for t in remote_tools if t['name'] == 'query_runs')
    with MCPClient(LOCAL) as client:
        local = client.connect()
    manifest = {'version': 1, 'workspace_id': '6fc41d3c-18ae-4daa-b363-77ae31f80315',
                'min_start_time': '2026-11-15T00:00:00Z', 'max_start_time': '2026-11-16T23:59:59Z',
                'samples': samples, 'schemas': {'local': local['schemas'], 'remote': {'query_runs': digest(remote_schema)}},
                'protocols': {'local': local['protocol'], 'remote': '2025-06-18'},
                'source_hashes': source_hashes(), 'prompt_sha256': digest(PROMPT),
                'full_fields': FULL, 'compact_fields': CORE, 'logical_calls': 4,
                'reference': 'native exact readback of two owned immutable synthetic roots; independent arithmetic checked by atomic checker',
                'source_document': cases['source_document'], 'baseline_cases_sha256': digest(cases)}
    write_private(directory / 'reference.json', native)
    write_private(directory / 'manifest.json', manifest)
    return {'status': 'sealed', 'manifest': str(directory / 'manifest.json'), 'sha256': digest(manifest)}


def self_test(path):
    manifest = read_private(path)
    need(manifest['source_hashes'] == source_hashes(), 'MCP_SOURCE_DRIFT')
    directory = STATE / ('local-e2e-' + str(uuid4()))
    with MCPClient(LOCAL, expected_schemas=manifest['schemas']['local']) as client:
        discovery = client.connect()
        records = []
        for tool, selector in [('calculator', 'nominal'), ('holdings', 'public-holdings-long-short')]:
            intent_id = str(uuid4())
            # MCP graph schema directly exposes the public request field.
            result = client.text_result(client.call(tool, {'request': {'case_id': selector}}, intent_id=intent_id))
            if tool == 'calculator': need(result['result'] == {'status': 'passed', 'per_share': '10'}, 'MCP_CALCULATOR_E2E')
            else:
                metrics = result['result']['accounts'][0]['metrics']
                need(metrics['positions_value'] == '700' and metrics['gross_positions_value'] == '1100'
                     and metrics['cash'] == '300' and metrics['nav'] == '1000', 'MCP_HOLDINGS_E2E')
            write_private(directory / (tool + '.json'), {'intent_id': intent_id, 'tool': tool, 'result': result})
            records.append({'tool': tool, 'status': 'passed', 'intent_id': intent_id})
        report = {'status': 'passed', 'discovery': discovery, 'records': records,
                  'stats': client.stats, 'manifest_sha256': digest(manifest), 'model_calls': 0}
        write_private(directory / 'report.json', report)
    return {**report, 'evidence': str(directory)}


def reseal(path):
    """New candidate from preserved oracle; prior evidence is never overwritten."""
    preservation()
    previous = read_private(path)
    need(previous['version'] == 1 and previous['full_fields'] == FULL and previous['compact_fields'] == CORE,
         'MCP_MANIFEST_CONTRACT')
    origin, old = path.resolve(), previous
    for _ in range(8):
        reference_path = origin.with_name('reference.json')
        if reference_path.exists(): break
        origin = ROOT / old['predecessor_path']
        old_next = read_private(origin)
        need(digest(old_next) == old['predecessor_manifest_sha256'], 'MCP_MANIFEST_ANCESTRY')
        old = old_next
    else: raise ValueError('MCP_REFERENCE_MISSING')
    reference = read_private(reference_path)
    samples = {kind: {**value, 'auxiliary': auxiliary(reference[kind]['root'])}
               for kind, value in previous['samples'].items()}
    directory = STATE / ('manifest-' + str(uuid4()))
    write_private(directory / 'manifest.json', {**previous, 'samples': samples, 'source_hashes': source_hashes(),
                  'prompt_sha256': digest(PROMPT), 'predecessor_manifest_sha256': digest(previous),
                  'predecessor_path': str(path.resolve().relative_to(ROOT))})
    return {'status': 'sealed', 'manifest': str(directory / 'manifest.json')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'reseal', 'self-test', 'start', 'pending', 'respond', 'report'])
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--round-id')
    parser.add_argument('--reply-file', type=Path)
    args = parser.parse_args()
    if args.operation == 'prepare': result = prepare()
    else:
        need(args.manifest is not None, 'MCP_MANIFEST_REQUIRED')
        if args.operation == 'self-test': result = self_test(args.manifest)
        elif args.operation == 'reseal': result = reseal(args.manifest)
        else:
            need(args.operation == 'start' or args.round_id is not None, 'MCP_ROUND_REQUIRED')
            answer = read_private(args.reply_file, limit=262144) if args.operation == 'respond' and args.reply_file else None
            need(args.operation != 'respond' or answer is not None, 'MCP_INTERNAL_REPLY_REQUIRED')
            result = run(args.manifest, round_id=args.round_id, answer=answer, start=args.operation == 'start')
    print(canonical(result))


if __name__ == '__main__': main()
