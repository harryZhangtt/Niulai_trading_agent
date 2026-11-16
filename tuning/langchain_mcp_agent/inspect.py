"""Exact owned trace selection, projection and grading, separate from transport."""
from __future__ import annotations

import fcntl
import os
from contextvars import ContextVar
from pathlib import Path
from datetime import datetime
from urllib.parse import urlsplit, parse_qs
from uuid import uuid4

from shared.langchain_mcp.client import MCPError, canonical, digest, need, read_private, write_private

CORE = ['ID', 'APP_PATH', 'NAME', 'RUN_TYPE', 'STATUS', 'PROJECT_ID', 'TRACE_ID',
        'PARENT_RUN_IDS', 'OUTPUTS', 'METADATA', 'END_TIME', 'ERROR']
FULL = CORE + ['INPUTS', 'EXTRA', 'EVENTS', 'START_TIME', 'DOTTED_ORDER', 'TOTAL_COST', 'TOTAL_TOKENS']
TRUTH = ['id', 'name', 'run_type', 'status', 'project_id', 'trace_id',
         'parent_run_ids', 'outputs', 'end_time', 'error']
RESERVED = ContextVar('mcp_inspection_reserved', default=None)


def truth(items):
    values = [{k: row.get(k) for k in TRUTH} for row in items]
    for row in values:
        if row['end_time']:
            try: row['end_time'] = datetime.fromisoformat(row['end_time'].replace('Z', '+00:00')).isoformat()
            except (ValueError, TypeError): raise MCPError('MCP_TRACE_TIME') from None
    return sorted(values, key=lambda x: x['id'])


def grade(items, reference):
    need(isinstance(items, list) and len(items) == len(reference['nodes']), 'MCP_TRACE_ROSTER')
    need(all(isinstance(row, dict) for row in items), 'MCP_TRACE_RECORD')
    ids = [row.get('id') for row in items]
    need(all(isinstance(x, str) for x in ids) and len(set(ids)) == len(ids), 'MCP_TRACE_DUPLICATE')
    for row in items:
        need(row.get('project_id') == reference['project_id'] and row.get('trace_id') == reference['trace_id'],
             'MCP_TRACE_SCOPE')
        parents = row.get('parent_run_ids')
        need(isinstance(parents, list) and len(set(parents)) == len(parents)
             and all(p in ids and p != row['id'] for p in parents), 'MCP_TRACE_PARENT')
        need(row.get('end_time') and row.get('status') == 'success' and row.get('error') is None,
             'MCP_TRACE_TERMINAL')
    roots = [row for row in items if row['parent_run_ids'] == []]
    need(len(roots) == 1 and roots[0]['id'] == reference['root_id'], 'MCP_TRACE_ROOT')
    need(roots[0].get('outputs') == reference['root_output'], 'MCP_TRACE_ROOT_OUTPUT')
    need(truth(items) == reference['nodes'], 'MCP_TRACE_TRUTH_DRIFT')
    return {'status': 'passed', 'nodes': len(items)}


class TraceInspector:
    def __init__(self, client, manifest, state):
        self.client, self.manifest, self.state = client, manifest, Path(state)
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)

    def reserve(self, sample, view):
        with os.fdopen(os.open(self.state / 'budget.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            attempts = list((self.state / 'calls').glob('*.intent.json'))
            # All attempted invocations count, including rejected ones.
            path = self.state / 'calls' / (str(uuid4()) + '.intent.json')
            write_private(path, {'ordinal': len(attempts) + 1, 'sample': sample if sample in ('calculator', 'holdings') else 'rejected',
                                 'view': view if view in ('full', 'compact') else 'rejected'})
            need(len(attempts) < 4, 'MCP_LOGICAL_TOOL_BUDGET')
            need(isinstance(sample, str) and sample in self.manifest['samples']
                 and isinstance(view, str) and view in ('full', 'compact'), 'MCP_TRACE_SELECTOR')
            # A repeated pair is a visible rejected invocation, not hidden caching.
            need(not any((r := read_private(p)).get('sample') == sample and r.get('view') == view
                         for p in attempts), 'MCP_DUPLICATE_PAIR')
            return path

    def inspect_trace(self, sample, view):
        reserved = RESERVED.get()
        path = reserved if reserved is not None else self.reserve(sample, view)
        reference = self.manifest['samples'][sample]
        args = {'workspace_id': self.manifest['workspace_id'], 'project_ids': [reference['project_id']],
                'trace_id': reference['trace_id'], 'page_size': 100,
                'min_start_time': self.manifest['min_start_time'],
                'max_start_time': self.manifest['max_start_time'],
                'selects': FULL if view == 'full' else CORE}
        deadline = self.client.clock() + self.client.policy['read_seconds']
        budget = {'bytes': 0}
        items, cursors = [], set()
        before = dict(self.client.stats)
        try:
            for page in range(self.client.policy['pages']):
                result = self.client.text_result(self.client.call('query_runs', args, deadline=deadline, budget=budget))
                need(isinstance(result, dict) and set(result) <= {'items', 'next_cursor'}
                     and isinstance(result.get('items'), list), 'MCP_QUERY_RESULT')
                items.extend(result['items'])
                need(len(items) <= 200, 'MCP_QUERY_ROSTER_LIMIT')
                cursor = result.get('next_cursor')
                if cursor is None: break
                need(isinstance(cursor, str) and 0 < len(cursor.encode()) <= 4096 and cursor not in cursors,
                     'MCP_QUERY_CURSOR')
                need(page + 1 < self.client.policy['pages'], 'MCP_QUERY_PAGES')
                cursors.add(cursor); args = {**args, 'cursor': cursor}
            check = grade(items, reference)
            # Export only selected fields on already bound synthetic records.
            fields = {x.lower() for x in (FULL if view == 'full' else CORE)}
            exported = []
            for row in sorted(items, key=lambda x: x['id']):
                item = {k: v for k, v in row.items() if k in fields}
                allowed = reference.get('safe_payloads', {}).get(row['id'], {})
                for key in ('inputs', 'extra', 'metadata', 'events'):
                    if key in item:
                        need(key in allowed and item[key] == allowed[key], 'MCP_TRACE_PRIVATE_PAYLOAD')
                app = item.get('app_path')
                if app is not None:
                    prefix = f"/o/{self.manifest['workspace_id']}/projects/p/{reference['project_id']}/trace/{reference['trace_id']}/run/"
                    need(isinstance(app, str) and app.startswith(prefix)
                         and not urlsplit(app).netloc and urlsplit(app).path == prefix + item['id'], 'MCP_APP_PATH_SCOPE')
                    parsed = urlsplit(app)
                    try:
                        query = parse_qs(parsed.query, strict_parsing=True)
                        stamp = query.get('start_time', [])
                        expected = reference['auxiliary'][row['id']]['start_time']
                        need(not parsed.fragment and set(query) == {'start_time'} and len(stamp) == 1
                             and datetime.fromisoformat(stamp[0].replace('Z', '+00:00')).isoformat()
                                 == datetime.fromisoformat(expected.replace('Z', '+00:00')).isoformat(), 'MCP_APP_PATH_QUERY')
                    except (KeyError, ValueError, TypeError): raise MCPError('MCP_APP_PATH_QUERY') from None
                for key in ('start_time', 'dotted_order', 'total_cost', 'total_tokens'):
                    if key in item:
                        expected = reference.get('auxiliary', {}).get(row['id'], {}).get(key)
                        actual = item[key]
                        if key == 'start_time' and actual and expected:
                            actual = datetime.fromisoformat(actual.replace('Z', '+00:00')).isoformat()
                            expected = datetime.fromisoformat(expected.replace('Z', '+00:00')).isoformat()
                        need(actual == expected, 'MCP_TRACE_AUXILIARY_DRIFT')
                exported.append(item)
            response = canonical({'sample': sample, 'view': view, 'grade': check, 'items': exported})
            record = {'sample': sample, 'view': view, 'status': 'passed', 'grade': check,
                      'response': response, 'response_utf8_bytes': len(response.encode('utf-8')),
                      'truth_sha256': digest(truth(items)), 'pages': page + 1,
                      'http_attempts': budget['attempts'], 'rpc_ids': budget['rpc_ids'],
                      'decoded_bytes': budget['bytes'], 'retries': budget['retries']}
            write_private(path.with_suffix('.result.json'), record)
            return response
        except BaseException:
            write_private(path.with_suffix('.error.json'), {'sample': sample, 'view': view, 'status': 'failed'})
            raise


def comparison(state):
    records = [read_private(p) for p in (Path(state) / 'calls').glob('*.intent.result.json')]
    need(len(records) == 4 and len(list((Path(state) / 'calls').glob('*.intent.json'))) == 4,
         'MCP_COMPARISON_INCOMPLETE')
    pairs = {}
    for sample in ('calculator', 'holdings'):
        arms = {r['view']: r for r in records if r['sample'] == sample}
        need(set(arms) == {'full', 'compact'} and all(r['status'] == 'passed' for r in arms.values()),
             'MCP_COMPARISON_INCOMPLETE')
        need(arms['full']['truth_sha256'] == arms['compact']['truth_sha256'], 'MCP_COMPARISON_DRIFT')
        for arm in arms.values():
            need(arm['response_utf8_bytes'] == len(arm['response'].encode('utf-8')), 'MCP_BYTE_COUNT')
        pairs[sample] = {'full_bytes': arms['full']['response_utf8_bytes'],
                         'compact_bytes': arms['compact']['response_utf8_bytes'],
                         'truth_sha256': arms['full']['truth_sha256'],
                         'strictly_smaller': arms['compact']['response_utf8_bytes'] < arms['full']['response_utf8_bytes']}
    return {'status': 'passed', 'pairs': pairs, 'byte_reduction_supported': all(p['strictly_smaller'] for p in pairs.values()),
            'logical_calls': len(records), 'http_attempts': sum(r['http_attempts'] for r in records),
            'pages': sum(r['pages'] for r in records), 'retries': sum(r['retries'] for r in records),
            'claim_scope': 'Two fixed synthetic traces; UTF-8 bytes, not tokens, price or model quality.'}
