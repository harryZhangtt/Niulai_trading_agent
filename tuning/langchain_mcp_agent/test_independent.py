"""Independent mcp-atomic-v1.1 controls; synthetic responses are not live proof.

All transports are injected. The one HTTP integration owns an ephemeral loopback
server and rewrites requests inside its injected transport, never touching 2024,
2025, the cloud, global session binding, credentials, browsers or host settings.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

import requests
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.types import Command
from langsmith import get_tracing_context, tracing_context

from shared.langchain_mcp import client as protocol
from tuning.langchain_mcp_agent import agent, checkpoint, inspect as inspection
from tuning.langchain_pilot import session_model

ROOT = protocol.ROOT
TMP = ROOT / '.langchain-pilot/tmp'
MUTATION_RESULTS = []


class Clock:
    def __init__(self): self.t = 1000.0; self.sleeps = []
    def now(self): return self.t
    def sleep(self, seconds): self.sleeps.append(seconds); self.t += seconds
    def advance(self, seconds): self.t += seconds


class Body:
    def __init__(self, value=None, *, status=200, headers=None, chunks=None, clock=None, delay=0):
        self.status_code = status
        self.headers = {'Content-Type': 'application/json', **(headers or {})}
        self.chunks = chunks if chunks is not None else [protocol.canonical(value).encode()]
        self.clock, self.delay, self.closed = clock, delay, False
    def iter_content(self, chunk_size):
        for chunk in self.chunks:
            if self.clock: self.clock.advance(self.delay)
            yield chunk
    def close(self): self.closed = True


def envelope(payload, result):
    return {'jsonrpc': '2.0', 'id': payload['id'], 'result': result}


def schema():
    return {'type': 'object', 'properties': {'request': {'type': 'object'}},
            'required': ['request'], 'additionalProperties': False}


class Wire:
    def __init__(self, handler=None):
        self.handler, self.calls, self.bodies, self.closed = handler, [], [], False
    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, deepcopy(kwargs)))
        if self.handler:
            body = self.handler(endpoint, kwargs)
        else:
            payload = kwargs['json']; method = payload['method']
            if method == 'initialize':
                result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}
                body = Body(envelope(payload, result), headers={'Mcp-Session-Id': 'owned-session'})
            elif method == 'notifications/initialized': body = Body({}, status=202)
            elif method == 'tools/list':
                names = sorted(protocol.ALLOWED[endpoint])
                body = Body(envelope(payload, {'tools': [{'name': n, 'inputSchema': schema()} for n in names]}))
            else: body = Body(envelope(payload, {'content': [{'type': 'text', 'text': '{}'}]}))
        self.bodies.append(body)
        return body
    def close(self): self.closed = True


def synthetic_manifest():
    manifest = {'workspace_id': 'fixture-workspace', 'min_start_time': '2026-11-16T00:00:00Z',
                'max_start_time': '2026-11-16T00:10:00Z', 'samples': {}}
    for sample, output in [('calculator', {'per_share': '10', 'label': '仓位🙂'}),
                           ('holdings', {'net': '700', 'gross': '1100'})]:
        project, trace, root = 'fixture-project', sample + '-trace', sample + '-root'
        common = {'project_id': project, 'trace_id': trace, 'status': 'success',
                  'end_time': '2026-11-16T00:00:01+00:00', 'error': None}
        rows = [{**common, 'id': root, 'name': sample, 'run_type': 'chain', 'parent_run_ids': [], 'outputs': output},
                {**common, 'id': sample + '-child', 'name': 'tool', 'run_type': 'tool',
                 'parent_run_ids': [root], 'outputs': {'synthetic': True}}]
        manifest['samples'][sample] = {'project_id': project, 'trace_id': trace, 'root_id': root,
                                     'root_output': deepcopy(output), 'nodes': sorted(deepcopy(rows), key=lambda r: r['id']),
                                     'auxiliary': {r['id']: {'start_time': '2026-11-16T00:00:00Z',
                                         'dotted_order': 'fixture', 'total_cost': None, 'total_tokens': None} for r in rows},
                                     'safe_payloads': {r['id']: {'metadata': {'synthetic': True},
                                           'inputs': {'synthetic': True}, 'extra': {'synthetic': True}, 'events': []}
                                                       for r in rows}}
    return manifest


def synthetic_rows(manifest, sample, full=True):
    reference = manifest['samples'][sample]
    rows = deepcopy(reference['nodes'])
    for row in rows:
        row['app_path'] = (f"/o/{manifest['workspace_id']}/projects/p/{reference['project_id']}"
                           f"/trace/{reference['trace_id']}/run/{row['id']}?start_time=2026-11-16T00:00:00Z")
        row['metadata'] = {'synthetic': True}
        if full:
            row.update(inputs={'synthetic': True}, extra={'synthetic': True}, events=[],
                       start_time='2026-11-16T00:00:00Z', dotted_order='fixture', total_cost=None, total_tokens=None)
    return rows


class TraceWire:
    """Inspection adapter fixture, intentionally not claimed as real MCP E2E."""
    def __init__(self, manifest, handler=None):
        self.manifest, self.handler, self.calls = manifest, handler, []
        self.policy = protocol.policy()
        self.stats = {'http_attempts': 0, 'decoded_bytes': 0, 'retries': 0}
        self.clock = lambda: 1000.0
    def call(self, name, arguments, **kwargs):
        self.calls.append((name, deepcopy(arguments), kwargs))
        self.stats['http_attempts'] += 1
        budget = kwargs['budget']
        budget['attempts'] = budget.get('attempts', 0) + 1
        budget.setdefault('rpc_ids', []).append(str(uuid4()))
        budget.setdefault('retries', 0)
        sample = next(k for k, r in self.manifest['samples'].items() if r['trace_id'] == arguments['trace_id'])
        result = self.handler(sample, arguments) if self.handler else {
            'items': synthetic_rows(self.manifest, sample, 'INPUTS' in arguments['selects']), 'next_cursor': None}
        kwargs['budget']['bytes'] += len(protocol.canonical(result).encode())
        return result
    def text_result(self, value): return value


@contextmanager
def mutant(module, old, new):
    """Compile one altered boundary in memory; never edit production source."""
    source = Path(module.__file__).read_text()
    if source.count(old) != 1: raise AssertionError('mutation anchor is not unique')
    name = module.__name__.rsplit('.', 1)[0] + '._independent_mutant'
    changed = types.ModuleType(name); changed.__file__ = module.__file__
    changed.__package__ = module.__package__
    previous = sys.modules.get(name); sys.modules[name] = changed
    before = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    try:
        exec(compile(source.replace(old, new), module.__file__, 'exec'), changed.__dict__)
        yield changed
    finally:
        if previous is None: sys.modules.pop(name, None)
        else: sys.modules[name] = previous
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != before:
            raise AssertionError('source changed during in-memory mutation')


class Fixture(unittest.TestCase):
    def setUp(self):
        TMP.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=TMP, prefix='mcp-independent-')
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.clock = Clock()
        self.manifest = synthetic_manifest()
    def client(self, endpoint=protocol.LOCAL, wire=None, module=protocol, **kwargs):
        return module.MCPClient(endpoint, state=self.state / str(uuid4()), transport=wire or Wire(),
            clock=self.clock.now, wall=self.clock.now, sleep=self.clock.sleep,
            key_resolver=kwargs.pop('key_resolver', lambda: 'FIXTURE-KEY-CANARY'), **kwargs)
    def inspector(self, wire=None, module=inspection):
        return module.TraceInspector(wire or TraceWire(self.manifest), self.manifest, self.state / str(uuid4()))
    def reject(self, action, code):
        with self.assertRaisesRegex(ValueError, code): action()
    def killed(self, identity, module, old, new, control):
        control(module)
        with mutant(module, old, new) as changed:
            with self.assertRaises(AssertionError): control(changed)
        MUTATION_RESULTS.append({'id': identity, 'status': 'KILLED', 'source_restored': True})


class ProtocolControls(Fixture):
    def test_exact_endpoint_guard_precedes_credentials_and_dispatch(self):
        calls = []; wire = Wire()
        for url in ('http://localhost:2025/mcp', 'http://127.0.0.1:2024/mcp', protocol.LOCAL + '/',
                    protocol.LOCAL + '?x=1', protocol.REMOTE + '#x', 'https://user:pass@api.smith.langchain.com/mcp',
                    'http://api.smith.langchain.com/mcp', 'https://evil.invalid/mcp'):
            self.reject(lambda: self.client(url, wire, key_resolver=lambda: calls.append(1)), 'ENDPOINT')
        self.assertEqual((calls, wire.calls), ([], []))
        with patch.dict(os.environ, {'MCP_URL': 'https://evil.invalid/mcp', 'HTTP_PROXY': 'http://evil.invalid'}):
            with self.client(wire=wire, key_resolver=lambda: self.fail('local resolved key')) as c: c.connect()
        self.assertFalse(wire.trust_env)
        self.assertTrue(all(endpoint == protocol.LOCAL for endpoint, _ in wire.calls))

    def test_redirect_key_canary_and_response_cleanup(self):
        wire = Wire(lambda *_: Body({}, status=307, headers={'Location': 'https://evil.invalid/mcp'}))
        with self.client(protocol.REMOTE, wire) as c: self.reject(c.connect, 'REDIRECT')
        self.assertEqual(len(wire.calls), 1); self.assertTrue(wire.closed and wire.bodies[0].closed)
        self.assertFalse(wire.calls[0][1]['allow_redirects'])
        self.assertEqual(wire.calls[0][1]['headers']['X-Api-Key'], 'FIXTURE-KEY-CANARY')
        self.assertNotIn('FIXTURE-KEY-CANARY', ''.join(p.read_text() for p in self.state.rglob('*.json')))

    def test_negotiation_session_notification_order_and_timeout_contract(self):
        wire = Wire()
        with self.client(protocol.REMOTE, wire) as c: c.connect()
        self.assertEqual([k['json']['method'] for _, k in wire.calls], ['initialize', 'notifications/initialized', 'tools/list'])
        self.assertNotIn('id', wire.calls[1][1]['json'])
        self.assertEqual(wire.calls[2][1]['headers']['Mcp-Session-Id'], 'owned-session')
        self.assertEqual(wire.calls[2][1]['headers']['MCP-Protocol-Version'], '2025-06-18')
        self.assertTrue(all(0 < k['timeout'].total <= 10 for _, k in wire.calls))
        self.assertTrue(all(b.closed for b in wire.bodies))

    def test_protocol_inverses_cannot_advance(self):
        for result in ({'protocolVersion': '1999', 'capabilities': {'tools': {}}},
                       {'protocolVersion': '2025-06-18', 'capabilities': {}}):
            wire = Wire(lambda _, k: Body(envelope(k['json'], result)))
            with self.client(wire=wire) as c: self.reject(c.connect, 'NEGOTIATION')
            self.assertEqual(len(wire.calls), 1)
        wire = Wire(lambda _, k: Body(envelope(k['json'], {'protocolVersion': '2025-06-18',
                    'capabilities': {'tools': {}}}), headers={'Mcp-Session-Id': 'bad\r\nCANARY'}))
        with self.client(wire=wire) as c: self.reject(c.connect, 'SESSION_HEADER')

    def test_rpc_envelope_duplicate_nonfinite_and_utf8_inverses(self):
        handlers = [lambda k: {'jsonrpc': '2.0', 'id': 'foreign', 'result': {}},
                    lambda k: {'jsonrpc': '1.0', 'id': k['json']['id'], 'result': {}},
                    lambda k: {'jsonrpc': '2.0', 'id': k['json']['id'], 'result': {}, 'error': {}},
                    lambda k: {'jsonrpc': '2.0', 'id': k['json']['id'], 'error': {'message': 'CANARY'}}]
        for handler in handlers:
            wire = Wire(lambda _, k: Body(handler(k)))
            with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'RPC_')
            self.assertTrue(wire.bodies[0].closed)
        for raw, code in [(b'{"x":1,"x":2}', 'DUPLICATE'), (b'{"x":NaN}', 'NONFINITE'),
                          (b'\xff', 'UTF8'), (b'{broken', 'MALFORMED')]:
            wire = Wire(lambda *_: Body(chunks=[raw]))
            with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), code)
            self.assertTrue(wire.bodies[0].closed)

    def test_sse_complete_notifications_and_terminal_inverses(self):
        def stream(k, suffix='\n\n', duplicate=False):
            terminal = 'data: ' + protocol.canonical(envelope(k['json'], {}))
            text = ': heartbeat\n\ndata: {"jsonrpc":"2.0","method":"notice"}\n\n' + terminal + suffix
            if duplicate: text += terminal + '\n\n'
            return Body(chunks=[text.encode()], headers={'Content-Type': 'text/event-stream'})
        for suffix, duplicate, good in [('\n\n', False, True), ('\r\n\r\n', False, True),
                                        ('\n', False, False), ('', False, False), ('\n\n', True, False)]:
            wire = Wire(lambda _, k: stream(k, suffix, duplicate))
            with self.client(wire=wire) as c:
                if good: self.assertEqual(c.rpc('tools/list'), {})
                else: self.reject(lambda: c.rpc('tools/list'), 'SSE')
            self.assertTrue(wire.bodies[0].closed)

    def test_schema_external_refs_reject_without_urlopen(self):
        for keyword in ('$ref', '$dynamicRef', '$recursiveRef'):
            for ref in ('https://evil.invalid/schema', 'file:///private/canary', '//evil.invalid/x', 'relative.json'):
                wire = Wire()
                original = wire.post
                def handler(endpoint, **kw):
                    if kw['json']['method'] == 'tools/list':
                        s = schema(); s['properties']['request'] = {keyword: ref}
                        return Body(envelope(kw['json'], {'tools': [{'name': n, 'inputSchema': s}
                                              for n in sorted(protocol.ALLOWED[endpoint])]}))
                    return original(endpoint, **kw)
                wire.post = handler
                with patch('urllib.request.urlopen', side_effect=AssertionError('external retrieval')) as fetch:
                    with self.client(wire=wire) as c: self.reject(c.connect, 'EXTERNAL_SCHEMA_REF')
                    fetch.assert_not_called()
        protocol.local_schema({'$defs': {'x': {'type': 'string'}}, '$ref': '#/$defs/x'})

    def test_required_alias_extra_schema_and_schema_hash_controls(self):
        with self.client() as c:
            c.connect(); before = len(c.http.calls)
            for name, args in [('trading_pilot', {}), ('fetch_runs', {}), ('other', {}),
                               ('calculator', {}), ('calculator', {'request': {}, 'extra': True}),
                               ('calculator', {'request': 'wrong'})]:
                self.reject(lambda: c.call(name, args, intent_id=str(uuid4())), 'TOOL_REJECTED|ARGUMENTS')
            self.assertEqual(len(c.http.calls), before)
        with self.client(expected_schemas={'calculator': 'wrong'}) as c: self.reject(c.connect, 'SCHEMA_DRIFT')

    def test_schema_roster_depth_response_and_policy_boundaries(self):
        for key, value in [('schema_bytes', 50), ('tool_roster', 2)]:
            p = protocol.policy(); p[key] = value
            with self.client(read_policy=p) as c: self.reject(c.connect, 'SCHEMA_BYTES|TOOL_ROSTER')
        self.reject(lambda: protocol.bounded_json('[' * 33 + '0' + ']' * 33, 32), 'DEPTH')
        self.assertEqual(protocol.bounded_json('[' * 32 + '0' + ']' * 32, 32), json.loads('[' * 32 + '0' + ']' * 32))
        self.assertEqual(protocol.bounded_json('{"quoted":"[[[\\\""}', 1), {'quoted': '[[["'})
        p = protocol.policy(); p['response_bytes'] = 90; p['logical_bytes'] = 100
        wire = Wire(lambda _, k: Body(envelope(k['json'], {'x': '仓' * 20})))
        with self.client(wire=wire, read_policy=p) as c: self.reject(lambda: c.rpc('tools/list'), 'RESPONSE_BYTES')
        for key in ('attempt_seconds', 'read_seconds', 'response_bytes', 'pages'):
            p = protocol.policy(); p[key] *= 2
            self.reject(lambda: protocol.policy(p), 'EXCEEDS')

    def test_cumulative_limit_spans_separate_reads_and_closes(self):
        p = protocol.policy(); p['logical_bytes'] = 120
        wire = Wire(lambda _, k: Body(envelope(k['json'], {'text': '仓' * 3})))
        with self.client(wire=wire, read_policy=p) as c:
            budget = {'bytes': 0}; c.rpc('tools/list', budget=budget)
            self.reject(lambda: c.rpc('tools/list', budget=budget), 'RESPONSE_BYTES')
        self.assertGreater(budget['bytes'], 120); self.assertTrue(all(b.closed for b in wire.bodies))

    def test_absolute_attempt_deadline_and_cancellation_cleanup(self):
        wire = Wire(lambda _, k: Body(envelope(k['json'], {}), clock=self.clock, delay=10.01))
        with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'DEADLINE')
        self.assertTrue(wire.bodies[0].closed and wire.closed)
        self.clock = Clock()
        wire = Wire(lambda _, k: (self.clock.advance(10.01), Body(envelope(k['json'], {})))[1])
        with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'DEADLINE')
        self.assertTrue(wire.bodies[0].closed)
        wire = Wire()
        with self.client(wire=wire, cancelled=lambda: True) as c: self.reject(lambda: c.rpc('tools/list'), 'CANCELLED')
        self.assertEqual(wire.calls, []); self.assertTrue(wire.closed)

    def test_cancellation_during_body_and_after_ack_remains_inspectable(self):
        flag = {'cancelled': False}
        class CancelBody(Body):
            def iter_content(self, chunk_size):
                yield self.chunks[0]
                flag['cancelled'] = True
        wire = Wire(lambda _, k: CancelBody(envelope(k['json'], {})))
        with self.client(wire=wire, cancelled=lambda: flag['cancelled']) as c:
            self.reject(lambda: c.rpc('tools/list'), 'CANCELLED')
        self.assertTrue(wire.bodies[0].closed and wire.closed)

    def test_retry_after_date_delta_malformed_and_permanent_errors(self):
        for header, expected_delay in [('3', 3), ('Thu, 01 Jan 1970 00:16:45 GMT', 5), ('bad', 5)]:
            self.clock = Clock(); wire = Wire(); times = []
            def limited(_, k):
                times.append(self.clock.now())
                return Body({}, status=429, headers={'Retry-After': header}) if len(times) == 1 else Body(envelope(k['json'], {}))
            wire.handler = limited
            with self.client(protocol.REMOTE, wire) as c: c.rpc('tools/list')
            self.assertEqual(len(times), 2); self.assertGreaterEqual(times[1] - times[0], expected_delay)
            self.assertTrue(all(b.closed for b in wire.bodies))
        for status in (401, 403, 400, 500):
            wire = Wire(lambda *_: Body({}, status=status))
            with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'HTTP_ERROR')
            self.assertEqual(len(wire.calls), 1)

    def test_retry_attempt_cap_deferred_and_cancellation_while_waiting(self):
        wire = Wire(lambda *_: Body({}, status=429, headers={'Retry-After': '1'}))
        with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'RATE_LIMITED')
        self.assertEqual(len(wire.calls), 2)
        wire = Wire(lambda *_: Body({}, status=429, headers={'Retry-After': '30'}))
        with self.client(wire=wire) as c: self.reject(lambda: c.rpc('tools/list'), 'DEFERRED')
        self.assertEqual(len(wire.calls), 1)
        self.clock = Clock(); wire = Wire(lambda *_: Body({}, status=429, headers={'Retry-After': '5'}))
        with self.client(wire=wire, cancelled=lambda: self.clock.t > 1000.2) as c:
            self.reject(lambda: c.rpc('tools/list'), 'CANCELLED')
        self.assertEqual(len(wire.calls), 1); self.assertTrue(wire.bodies[0].closed)

    def test_retry_and_pages_share_two_attempt_logical_budget(self):
        wire = Wire(); count = []
        def reply(_, k):
            count.append(1)
            return Body({}, status=429, headers={'Retry-After': '1'}) if len(count) == 1 else Body(envelope(k['json'], {}))
        wire.handler = reply
        with self.client(protocol.REMOTE, wire) as c:
            budget = {'bytes': 0}
            c.rpc('tools/call', {'name': 'query_runs', 'arguments': {}}, budget=budget)
            self.reject(lambda: c.rpc('tools/call', {'name': 'query_runs', 'arguments': {}}, budget=budget), 'LOGICAL_HTTP_BUDGET')
            self.assertEqual((budget['attempts'], budget['retries'], c.stats['http_attempts']), (2, 1, 2))
        self.assertEqual(len(wire.calls), 2)

    def test_supplied_deadline_cannot_extend_frozen_logical_limit(self):
        wire = Wire(); times = []
        def reply(_, k):
            times.append(self.clock.now())
            return Body({}, status=429, headers={'Retry-After': '31'}) if len(times) == 1 else Body(envelope(k['json'], {}))
        wire.handler = reply
        with self.client(protocol.REMOTE, wire) as c:
            self.reject(lambda: c.rpc('tools/list', deadline=self.clock.now() + 100), 'RATE_DEFERRED')
        self.assertEqual(len(wire.calls), 1)

    def test_local_effect_unknown_ack_and_restart_fences(self):
        wire = Wire(); state = self.state / 'effects-client'
        with protocol.MCPClient(protocol.LOCAL, state=state, transport=wire, clock=self.clock.now,
                 wall=self.clock.now, sleep=self.clock.sleep) as c:
            c.connect(); identity = str(uuid4())
            wire.handler = lambda *_: (_ for _ in ()).throw(TimeoutError('FIXTURE-KEY-CANARY'))
            self.reject(lambda: c.call('calculator', {'request': {}}, intent_id=identity), 'UNKNOWN')
            self.assertEqual(c.effect_status(identity)['status'], 'unknown_fenced')
            fence = state / 'effects' / (identity + '.json'); prior = fence.read_bytes()
        other = Wire()
        with protocol.MCPClient(protocol.LOCAL, state=state, transport=other, clock=self.clock.now,
                 wall=self.clock.now, sleep=self.clock.sleep) as c:
            c.connect(); before = len(other.calls)
            self.reject(lambda: c.call('calculator', {'request': {}}, intent_id=identity), 'FENCED')
            self.assertEqual(len(other.calls), before); self.assertEqual(fence.read_bytes(), prior)
            accepted = str(uuid4()); c.call('holdings', {'request': {}}, intent_id=accepted)
            self.assertEqual(c.effect_status(accepted)['status'], 'acknowledged_fenced')
            self.reject(lambda: c.call('holdings', {'request': {}}, intent_id=accepted), 'FENCED')

    def test_remote_secret_response_and_local_tool_error_no_replay(self):
        wire = Wire(lambda _, k: Body(envelope(k['json'], {'text': 'FIXTURE-KEY-CANARY'})))
        with self.client(protocol.REMOTE, wire) as c: self.reject(lambda: c.rpc('tools/list'), 'SECRET_RESPONSE')
        self.assertNotIn('FIXTURE-KEY-CANARY', ''.join(p.read_text() for p in self.state.rglob('*.json')))
        wire = Wire()
        with self.client(wire=wire) as c:
            c.connect(); before = len(wire.calls)
            wire.handler = lambda _, k: Body(envelope(k['json'], {'isError': True, 'content': []}))
            identity = str(uuid4()); self.reject(lambda: c.call('calculator', {'request': {}}, intent_id=identity), 'TOOL_ERROR')
            self.assertEqual(len(wire.calls), before + 1); self.assertEqual(c.effect_status(identity)['status'], 'unknown_fenced')

    def test_real_requests_owned_slow_stream_deadline_cleanup(self):
        started = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers['Content-Length']); payload = json.loads(self.rfile.read(length))
                raw = protocol.canonical(envelope(payload, {})).encode()
                self.send_response(200); self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw))); self.end_headers()
                started.set()
                try:
                    self.wfile.write(raw[:1]); self.wfile.flush(); time.sleep(0.18)
                    self.wfile.write(raw[1:]); self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError): pass
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server.daemon_threads = False; server.timeout = 0.1
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01)); thread.start()
        class RewritingSession(requests.Session):
            def __init__(self): super().__init__(); self.responses = []; self.was_closed = False
            def post(self, endpoint, **kwargs):
                response = super().post(f'http://127.0.0.1:{server.server_port}/mcp', **kwargs)
                self.responses.append(response); return response
            def close(self): self.was_closed = True; super().close()
        wire = RewritingSession(); p = protocol.policy(); p['attempt_seconds'] = 0.07
        before = time.monotonic()
        try:
            with protocol.MCPClient(protocol.LOCAL, state=self.state / 'real-http', transport=wire,
                                    read_policy=p) as c:
                self.reject(lambda: c.rpc('tools/list'), 'DEADLINE|TRANSPORT_UNKNOWN')
            self.assertTrue(started.is_set()); self.assertLess(time.monotonic() - before, 0.7)
            self.assertTrue(wire.was_closed and wire.responses[0].raw.closed)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=1)
        self.assertFalse(thread.is_alive())


class InspectionControls(Fixture):
    def test_scope_fields_and_cursor_remain_adapter_owned(self):
        rows = synthetic_rows(self.manifest, 'calculator')
        wire = TraceWire(self.manifest, lambda sample, args: {'items': rows[:1] if 'cursor' not in args else rows[1:],
                                                            'next_cursor': 'owned-cursor' if 'cursor' not in args else None})
        inspector = self.inspector(wire); response = json.loads(inspector.inspect_trace('calculator', 'full'))
        self.assertEqual(response['grade']['status'], 'passed'); self.assertEqual(len(wire.calls), 2)
        first, second = wire.calls[0][1], wire.calls[1][1]
        self.assertEqual({k: v for k, v in second.items() if k != 'cursor'}, first)
        self.assertEqual(set(first), {'workspace_id', 'project_ids', 'trace_id', 'page_size', 'min_start_time', 'max_start_time', 'selects'})
        self.assertEqual(first['workspace_id'], self.manifest['workspace_id']); self.assertEqual(first['page_size'], 100)
        self.assertEqual(wire.calls[0][2]['deadline'], wire.calls[1][2]['deadline'])
        self.assertIs(wire.calls[0][2]['budget'], wire.calls[1][2]['budget'])

    def test_pagination_limits_and_returned_shape_reject(self):
        for result, code in [({'items': [], 'next_cursor': 'repeat'}, 'PAGES|CURSOR'),
                             ({'items': [], 'next_cursor': 'x' * 4097}, 'CURSOR'),
                             ({'items': [], 'foreign': True}, 'QUERY_RESULT'),
                             ({'items': [{}] * 201}, 'ROSTER_LIMIT')]:
            wire = TraceWire(self.manifest, lambda *_: result); inspector = self.inspector(wire)
            self.reject(lambda: inspector.inspect_trace('calculator', 'compact'), code)
            self.assertLessEqual(len(wire.calls), 2)
            self.assertEqual(len(list((inspector.state / 'calls').glob('*.error.json'))), 1)

    def test_grader_scope_root_output_parent_roster_status_inverses(self):
        reference = self.manifest['samples']['calculator']; original = synthetic_rows(self.manifest, 'calculator')
        self.assertEqual(inspection.grade(original, reference)['status'], 'passed')
        variants = []
        for key, value in [('project_id', 'foreign'), ('trace_id', 'foreign'), ('outputs', {'per_share': '100'}),
                           ('parent_run_ids', ['missing']), ('status', 'error'), ('error', 'failed'), ('end_time', None)]:
            rows = deepcopy(original); root = next(r for r in rows if r['id'] == reference['root_id']); root[key] = value
            variants.append(rows)
        rows = deepcopy(original); rows[0]['id'] = rows[1]['id']; variants.append(rows)
        rows = deepcopy(original); rows[0]['parent_run_ids'] = []; rows[1]['parent_run_ids'] = []; variants.append(rows)
        variants.extend([original[:1], original + [deepcopy(original[0])]])
        for rows in variants: self.reject(lambda: inspection.grade(rows, reference), 'TRACE_')
        wrong_root = deepcopy(reference); wrong_root['root_id'] = 'calculator-child'
        self.reject(lambda: inspection.grade(original, wrong_root), 'TRACE_ROOT')

    def test_payload_and_app_path_canaries_never_export(self):
        for field, value in [('metadata', {'private': 'CANARY'}), ('inputs', {'private': 'CANARY'}),
                             ('extra', {'private': 'CANARY'}), ('events', ['CANARY']),
                             ('app_path', 'https://evil.invalid/CANARY')]:
            rows = synthetic_rows(self.manifest, 'calculator'); rows[0][field] = value
            inspector = self.inspector(TraceWire(self.manifest, lambda *_: {'items': rows}))
            self.reject(lambda: inspector.inspect_trace('calculator', 'full'), 'PRIVATE_PAYLOAD|APP_PATH')
            self.assertNotIn('CANARY', ''.join(p.read_text() for p in inspector.state.rglob('*.json')))
        for suffix in ('&private=CANARY', '#CANARY'):
            rows = synthetic_rows(self.manifest, 'calculator'); rows[0]['app_path'] += suffix
            inspector = self.inspector(TraceWire(self.manifest, lambda *_: {'items': rows}))
            self.reject(lambda: inspector.inspect_trace('calculator', 'full'), 'APP_PATH')
            self.assertNotIn('CANARY', ''.join(p.read_text() for p in inspector.state.rglob('*.json')))

    def test_logical_rejected_duplicate_and_fifth_calls_count_without_dispatch(self):
        wire = TraceWire(self.manifest); inspector = self.inspector(wire)
        self.reject(lambda: inspector.inspect_trace('foreign', 'full'), 'SELECTOR')
        inspector.inspect_trace('calculator', 'full')
        self.reject(lambda: inspector.inspect_trace('calculator', 'full'), 'DUPLICATE_PAIR')
        inspector.inspect_trace('calculator', 'compact')
        self.reject(lambda: inspector.inspect_trace('holdings', 'full'), 'LOGICAL_TOOL_BUDGET')
        receipts = [protocol.read_private(p) for p in (inspector.state / 'calls').glob('*.intent.json')]
        self.assertEqual(sorted(r['ordinal'] for r in receipts), [1, 2, 3, 4, 5])
        self.assertEqual(len(wire.calls), 2)

    def test_failed_grading_counts_and_is_preserved(self):
        wire = TraceWire(self.manifest, lambda *_: {'items': []}); inspector = self.inspector(wire)
        self.reject(lambda: inspector.inspect_trace('calculator', 'full'), 'TRACE_ROSTER')
        self.assertEqual(len(list((inspector.state / 'calls').glob('*.intent.json'))), 1)
        self.assertEqual(len(list((inspector.state / 'calls').glob('*.error.json'))), 1)
        self.reject(lambda: inspection.comparison(inspector.state), 'INCOMPLETE')

    def test_matched_response_utf8_and_adverse_compact_measurements(self):
        inspector = self.inspector()
        for sample in ('calculator', 'holdings'):
            for view in ('full', 'compact'): inspector.inspect_trace(sample, view)
        records = list((inspector.state / 'calls').glob('*.result.json'))
        for path in records:
            record = protocol.read_private(path)
            self.assertEqual(record['response_utf8_bytes'], len(record['response'].encode('utf-8')))
            if record['sample'] == 'calculator': self.assertGreater(record['response_utf8_bytes'], len(record['response']))
        report = inspection.comparison(inspector.state); self.assertTrue(report['byte_reduction_supported'])
        self.assertEqual((report['logical_calls'], report['pages'], report['http_attempts']), (4, 4, 4))
        for path in records:
            record = protocol.read_private(path)
            if record['view'] == 'compact':
                value = json.loads(record['response']); value['observed_padding'] = '🙂' * 2000
                record['response'] = protocol.canonical(value)
                record['response_utf8_bytes'] = len(record['response'].encode())
                protocol.write_private(path, record, replace=True)
        adverse = inspection.comparison(inspector.state)
        self.assertEqual(adverse['status'], 'passed'); self.assertFalse(adverse['byte_reduction_supported'])

    def test_comparison_refuses_character_count_and_truth_drift(self):
        inspector = self.inspector()
        for sample in ('calculator', 'holdings'):
            for view in ('full', 'compact'): inspector.inspect_trace(sample, view)
        path = next(p for p in (inspector.state / 'calls').glob('*.result.json')
                    if protocol.read_private(p)['sample'] == 'calculator')
        record = protocol.read_private(path); record['response_utf8_bytes'] = len(record['response'])
        protocol.write_private(path, record, replace=True)
        self.reject(lambda: inspection.comparison(inspector.state), 'BYTE_COUNT')
        record['response_utf8_bytes'] = len(record['response'].encode()); record['truth_sha256'] = 'changed'
        protocol.write_private(path, record, replace=True)
        self.reject(lambda: inspection.comparison(inspector.state), 'COMPARISON_DRIFT')


class CheckpointHostControls(Fixture):
    def graph(self, directory, wire):
        binding_dir = self.state / 'binding'
        if not (binding_dir / 'binding.json').exists(): session_model.configure('independent-fixture', state=binding_dir)
        with patch.object(agent, 'SessionChatModel', lambda: session_model.SessionChatModel(state_directory=str(binding_dir))):
            return agent.build(self.manifest, directory, wire)
    def answer(self, request, message):
        return {'request_id': request['request_id'], 'binding': request['binding'], 'message': message}

    def test_real_langgraph_checkpoint_reload_handoff_four_tools_and_final(self):
        directory = self.state / 'host'; directory.mkdir()
        wire = TraceWire(self.manifest); config = {'configurable': {'thread_id': 'fixture-thread'}, 'callbacks': []}
        with tracing_context(enabled=False):
            graph = self.graph(directory, wire)
            graph.invoke({'messages': [{'role': 'user', 'content': 'fixture inspection'}]}, config)
            request = agent.pending(graph.get_state(config))
            self.assertEqual([t['function']['name'] for t in request['tools']], ['inspect_trace'])
            graph = self.graph(directory, wire)
            self.assertEqual(agent.pending(graph.get_state(config))['request_id'], request['request_id'])
            calls = [{'name': 'inspect_trace', 'args': {'sample': sample, 'view': view}}
                     for sample in ('calculator', 'holdings') for view in ('full', 'compact')]
            graph.invoke(Command(resume=self.answer(request, {'tool_calls': calls})), config)
            request = agent.pending(graph.get_state(config))
            tools = [m for m in request['messages'] if m['type'] == 'tool']
            self.assertEqual(len(tools), 4); self.assertEqual(len(wire.calls), 4)
            for tool in tools: self.assertEqual(json.loads(tool['content'])['grade']['status'], 'passed')
            graph = self.graph(directory, wire)
            graph.invoke(Command(resume=self.answer(request, {'content': '{"status":"completed","preferred_view":"compact","reason":"fixture byte counts"}'})), config)
            self.assertIsNone(agent.pending(graph.get_state(config)))
        self.assertEqual(inspection.comparison(directory)['logical_calls'], 4)
        self.assertEqual(protocol.read_private(directory / 'model-budget.json')['calls'], 2)
        self.assertEqual(list(directory.glob('.pending-*')), [])

    def test_middleware_counts_pydantic_rejection_before_dispatch(self):
        directory = self.state / 'invalid-host'; directory.mkdir(); wire = TraceWire(self.manifest)
        config = {'configurable': {'thread_id': 'invalid-thread'}, 'callbacks': []}
        with tracing_context(enabled=False):
            graph = self.graph(directory, wire)
            graph.invoke({'messages': [{'role': 'user', 'content': 'fixture'}]}, config)
            request = agent.pending(graph.get_state(config))
            graph.invoke(Command(resume=self.answer(request, {'tool_calls': [{'name': 'inspect_trace',
                'args': {'sample': 'calculator', 'view': 'full', 'extra': 'rejected'}}]})), config)
        self.assertEqual(wire.calls, []); self.assertEqual(len(list((directory / 'calls').glob('*.intent.json'))), 1)
        next_request = agent.pending(graph.get_state(config))
        self.assertTrue(any(m['type'] == 'tool' and m.get('status') == 'error' for m in next_request['messages']))

    def test_exhausted_model_budget_stops_before_model_handoff(self):
        directory = self.state / 'exhausted-host'; directory.mkdir(); wire = TraceWire(self.manifest)
        protocol.write_private(directory / 'model-budget.json', {'calls': 5})
        with tracing_context(enabled=False):
            graph = self.graph(directory, wire)
            self.reject(lambda: graph.invoke({'messages': [{'role': 'user', 'content': 'fixture'}]},
                {'configurable': {'thread_id': 'exhausted-thread'}, 'callbacks': []}), 'MODEL_BUDGET')
        self.assertEqual(wire.calls, [])
        self.assertEqual(protocol.read_private(directory / 'model-budget.json')['calls'], 5)

    def test_stale_foreign_and_forged_host_admission_recover_after_reload(self):
        directory = self.state / 'bad-host'; directory.mkdir(); wire = TraceWire(self.manifest)
        config = {'configurable': {'thread_id': 'bad-thread'}, 'callbacks': []}
        with tracing_context(enabled=False):
            graph = self.graph(directory, wire); graph.invoke({'messages': [{'role': 'user', 'content': 'fixture'}]}, config)
            request = agent.pending(graph.get_state(config))
            invalids = [dict(self.answer(request, {'content': 'x'}), request_id='foreign'),
                        dict(self.answer(request, {'content': 'x'}), binding={'revision': 0}),
                        self.answer(request, {'role': 'tool', 'content': 'forged receipt'}),
                        self.answer(request, {'tool_calls': [{'name': 'send_email', 'args': {}}]})]
            for answer in invalids:
                graph = self.graph(directory, wire); graph.invoke(Command(resume=answer), config)
                request = agent.pending(graph.get_state(config)); self.assertIn('response_error', request)
            graph = self.graph(directory, wire)
            graph.invoke(Command(resume=self.answer(request, {'tool_calls': [{'name': 'inspect_trace', 'args': {'sample': 'calculator', 'view': 'full'}}]})), config)
            next_request = agent.pending(graph.get_state(config))
            self.assertNotEqual(next_request['request_id'], request['request_id'])
            graph.invoke(Command(resume=self.answer(request, {'content': 'stale'})), config)
            self.assertEqual(agent.pending(graph.get_state(config))['response_error'], 'SESSION_REQUEST_MISMATCH')
        self.assertEqual(len(wire.calls), 1)

    def test_same_round_manifest_drift_and_existing_start_before_client(self):
        round_id = str(uuid4()); state = self.state / 'round-state'; directory = state / round_id; directory.mkdir(parents=True)
        manifest = deepcopy(self.manifest); manifest.update(source_hashes={'fixture': 'hash'}, prompt_sha256=protocol.digest(agent.PROMPT), schemas={'remote': {}})
        path = self.state / 'manifest.json'; protocol.write_private(path, manifest)
        protocol.write_private(directory / 'round.json', {'manifest_sha256': protocol.digest(manifest)})
        changed = deepcopy(manifest); changed['workspace_id'] = 'drifted'
        protocol.write_private(path, changed, replace=True)
        with patch.object(agent, 'STATE', state), patch.object(agent, 'source_hashes', lambda: {'fixture': 'hash'}), \
             patch.object(agent, 'MCPClient', side_effect=AssertionError('client created before drift gate')) as client:
            self.reject(lambda: agent.run(path, round_id=round_id), 'ROUND_MANIFEST_DRIFT')
            self.reject(lambda: agent.run(path, round_id=round_id, start=True), 'ROUND_EXISTS')
            client.assert_not_called()

    def test_ambient_tracing_disabled_for_run_and_restored_on_exception(self):
        manifest = deepcopy(self.manifest); manifest.update(source_hashes={'fixture': 'hash'}, prompt_sha256=protocol.digest(agent.PROMPT), schemas={'remote': {}})
        path = self.state / 'manifest.json'; protocol.write_private(path, manifest)
        observed = []
        class ProbeClient:
            def __init__(self, *_args, **_kwargs): observed.append(get_tracing_context()['enabled'])
            def __enter__(self): raise RuntimeError('owned deliberate stop')
            def __exit__(self, *_): pass
        with tracing_context(enabled=True):
            with patch.object(agent, 'STATE', self.state / 'tracing'), patch.object(agent, 'source_hashes', lambda: {'fixture': 'hash'}), patch.object(agent, 'MCPClient', ProbeClient):
                with self.assertRaisesRegex(RuntimeError, 'owned deliberate stop'): agent.run(path, start=True)
            self.assertTrue(get_tracing_context()['enabled'])
        self.assertEqual(observed, [False])

    def test_checkpoint_concurrent_put_and_writes_survive_reload(self):
        path = self.state / 'concurrent.json'; saver = checkpoint.FileSaver(path)
        def save(index):
            config = {'configurable': {'thread_id': f'fixture-{index}', 'checkpoint_ns': ''}}
            cp = empty_checkpoint(); cp['channel_values'] = {'value': f'仓位-{index}'}; cp['channel_versions'] = {'value': 1}
            stored = saver.put(config, cp, {'source': 'input', 'step': 0, 'parents': {}}, {'value': 1})
            saver.put_writes(stored, [('result', f'fixture-{index}')], f'task-{index}')
            return stored
        with ThreadPoolExecutor(max_workers=8) as pool: configs = list(pool.map(save, range(24)))
        reload = checkpoint.FileSaver(path)
        for index, config in enumerate(configs):
            value = reload.get_tuple(config)
            self.assertEqual(value.checkpoint['channel_values']['value'], f'仓位-{index}')
            self.assertTrue(any(write[1:] == ('result', f'fixture-{index}') for write in value.pending_writes))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_checkpoint_atomic_replace_interruption_keeps_prior_disk_state(self):
        path = self.state / 'interrupt.json'; saver = checkpoint.FileSaver(path)
        config = {'configurable': {'thread_id': 'interrupt-fixture', 'checkpoint_ns': ''}}
        first = empty_checkpoint(); first['channel_values'] = {'v': 'prior'}; first['channel_versions'] = {'v': 1}
        saver.put(config, first, {'source': 'input', 'step': 0, 'parents': {}}, {'v': 1})
        original = path.read_bytes(); second = empty_checkpoint(); second['channel_values'] = {'v': 'later'}; second['channel_versions'] = {'v': 2}
        with patch.object(protocol.os, 'replace', side_effect=OSError('disposable interruption')):
            with self.assertRaises(OSError): saver.put(config, second, {'source': 'loop', 'step': 1, 'parents': {}}, {'v': 2})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(checkpoint.FileSaver(path).get_tuple(config).checkpoint['channel_values'], {'v': 'prior'})
        self.assertEqual(list(self.state.glob('.pending-*')), [])

    def test_checkpoint_tagged_encoding_corruption_and_version_controls(self):
        value = {('key', 3): [b'\x00\xff', None, True, '仓']}
        self.assertEqual(checkpoint.decode(checkpoint.encode(value)), value)
        self.reject(lambda: checkpoint.decode(['unknown', {}]), 'CHECKPOINT_SHAPE')
        self.reject(lambda: checkpoint.encode(object()), 'CHECKPOINT_TYPE')
        path = self.state / 'bad-checkpoint.json'; protocol.write_private(path, {'version': 999, 'state': []})
        self.reject(lambda: checkpoint.FileSaver(path), 'CHECKPOINT_VERSION')


class PreservationControls(Fixture):
    def test_frozen_contract_and_baseline_failure_histories_hashes(self):
        expected = {'ACCEPTANCE.md': 'a9e6917c5551c13ea8b453213020a1a0d0bb89b5d9dc1469daf5e275c38bff8f',
                    'cases.json': '0aef57e646539fb220b66d2b37b042bdd79a4e4e7d9b210549b56d0828940fe4'}
        for name, sha in expected.items():
            self.assertEqual(hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest(), sha)
        packet = json.loads((Path(__file__).parent / 'cases.json').read_text())
        self.assertEqual(len(packet['cases']), 36); self.assertEqual(len(packet['deliberate_breaks']), 14)
        records = [packet['baseline339_manifest'], packet['previous_failed339_manifest'], *packet['owned_api_ui_history_hashes']]
        for record in records:
            self.assertEqual(hashlib.sha256((ROOT / record['owner_private_path']).read_bytes()).hexdigest(), record['sha256'])


class DeliberateBreakControls(Fixture):
    def test_mut001_removed_redirect_guard_is_killed(self):
        def control(module):
            wire = Wire(lambda *_: Body({}, status=307))
            with self.client(wire=wire, module=module) as c: self.reject(lambda: c.rpc('tools/list'), 'REDIRECT')
        self.killed('MCP-MUT-001', protocol, "need(not 300 <= response.status_code < 400, 'MCP_REDIRECT_REJECTED')",
                    "pass  # deliberate break", control)

    def test_mut002_wrong_rpc_id_is_killed(self):
        def control(module):
            wire = Wire(lambda *_: Body({'jsonrpc': '2.0', 'id': 'foreign', 'result': {}}))
            with self.client(wire=wire, module=module) as c: self.reject(lambda: c.rpc('tools/list'), 'RPC_ENVELOPE')
        self.killed('MCP-MUT-002', protocol, "and value.get('id') == rid and", 'and True and', control)

    def test_mut003_extra_arguments_is_killed(self):
        def control(module):
            wire = Wire()
            with self.client(wire=wire, module=module) as c:
                c.connect(); c.tools['calculator']['additionalProperties'] = True
                self.reject(lambda: c.call('calculator', {'request': {}, 'extra': True}, intent_id=str(uuid4())), 'ARGUMENTS')
        self.killed('MCP-MUT-003', protocol, "need(set(arguments) <= set(self.tools[name].get('properties', {})), 'MCP_ARGUMENTS')",
                    'pass  # deliberate break', control)

    def test_mut004_cumulative_bytes_is_killed(self):
        def control(module):
            p = protocol.policy(); p['logical_bytes'] = 1
            wire = Wire(lambda _, k: Body(envelope(k['json'], {})))
            with self.client(wire=wire, module=module, read_policy=p) as c:
                self.reject(lambda: c.rpc('tools/list'), 'RESPONSE_BYTES')
        self.killed('MCP-MUT-004', protocol, "and budget['bytes'] <= self.policy['logical_bytes']", 'and True', control)

    def test_mut005_ignored_retry_after_is_killed(self):
        def control(module):
            self.clock = Clock(); times = []
            def response(_, k):
                times.append(self.clock.now())
                return Body({}, status=429, headers={'Retry-After': '5'}) if len(times) == 1 else Body(envelope(k['json'], {}))
            with self.client(wire=Wire(response), module=module) as c: c.rpc('tools/list')
            self.assertGreaterEqual(times[1] - times[0], 5)
        self.killed('MCP-MUT-005', protocol, "delay = self.policy['fallback_seconds'] if after is None else after", 'delay = 0', control)

    def test_mut006_unknown_fence_cleared_is_killed(self):
        def control(module):
            with self.client(module=module) as c:
                c.connect(); identity = str(uuid4())
                c.http.handler = lambda *_: (_ for _ in ()).throw(TimeoutError('synthetic interruption'))
                self.reject(lambda: c.call('calculator', {'request': {}}, intent_id=identity), 'UNKNOWN')
                c.http.handler = None
                self.reject(lambda: c.call('calculator', {'request': {}}, intent_id=identity), 'FENCED')
        self.killed('MCP-MUT-006', protocol, "path = self.state / 'effects' / (intent_id + '.json')\n            try:",
                    "path = self.state / 'effects' / (intent_id + '.json'); path.unlink(missing_ok=True)\n            try:", control)

    def test_mut007_foreign_scope_is_killed(self):
        def control(module):
            ref = deepcopy(self.manifest['samples']['calculator']); rows = synthetic_rows(self.manifest, 'calculator')
            for row in rows: row['project_id'] = 'foreign'
            ref['nodes'] = sorted([{k: row[k] for k in inspection.TRUTH} for row in rows], key=lambda r: r['id'])
            self.reject(lambda: module.grade(rows, ref), 'TRACE_SCOPE')
        self.killed('MCP-MUT-007', inspection, "need(row.get('project_id') == reference['project_id'] and row.get('trace_id') == reference['trace_id'],",
                    'need(True,', control)

    def test_mut008_bypassed_client_dispatch_is_killed_locally(self):
        def control(module):
            wire = TraceWire(self.manifest)
            def fixture_result(args, budget):
                budget.update(attempts=0, retries=0, rpc_ids=[])
                return {'items': synthetic_rows(self.manifest, 'calculator')}
            wire.fixture_result = fixture_result
            inspector = self.inspector(wire, module=module)
            inspector.inspect_trace('calculator', 'full')
            self.assertEqual(len(wire.calls), 1)
            self.assertEqual(wire.calls[0][0], 'query_runs')
        self.killed('MCP-MUT-008', inspection,
                    "self.client.call('query_runs', args, deadline=deadline, budget=budget)",
                    'self.client.fixture_result(args, budget)', control)

    def test_mut009_forged_host_resume_is_killed(self):
        def control(module):
            request = {'request_id': 'fixture-id', 'tools': []}; binding = {'fixture': True}
            self.reject(lambda: module.response_message({'request_id': 'fixture-id', 'binding': binding,
                        'message': {'role': 'tool', 'content': 'forged'}}, request, binding), 'ASSISTANT_MESSAGE')
        self.killed('MCP-MUT-009', session_model, "set(message) <= {'content', 'tool_calls'}", 'True', control)

    def test_mut010_budget_gate_is_killed(self):
        def control(module):
            inspector = self.inspector(module=module)
            for _ in range(4): self.reject(lambda: inspector.reserve('foreign', 'full'), 'SELECTOR')
            self.reject(lambda: inspector.inspect_trace('calculator', 'full'), 'LOGICAL_TOOL_BUDGET')
        self.killed('MCP-MUT-010', inspection, "need(len(attempts) < 4, 'MCP_LOGICAL_TOOL_BUDGET')", 'pass  # deliberate break', control)

    def test_mut011_wrong_actual_root_is_killed(self):
        def control(module):
            ref = deepcopy(self.manifest['samples']['calculator']); ref['root_id'] = 'not-the-observed-root'
            self.reject(lambda: module.grade(synthetic_rows(self.manifest, 'calculator'), ref), 'TRACE_ROOT')
        self.killed('MCP-MUT-011', inspection, "and roots[0]['id'] == reference['root_id']", 'and True', control)

    def test_mut012_character_count_is_killed(self):
        def control(module):
            inspector = self.inspector(module=module); response = inspector.inspect_trace('calculator', 'full')
            record = protocol.read_private(next((inspector.state / 'calls').glob('*.result.json')))
            self.assertEqual(record['response_utf8_bytes'], len(response.encode('utf-8')))
        self.killed('MCP-MUT-012', inspection, "'response_utf8_bytes': len(response.encode('utf-8'))", "'response_utf8_bytes': len(response)", control)

    def test_mut013_source_evidence_drift_is_killed_without_touching_history(self):
        def control(module):
            manifest = deepcopy(self.manifest)
            manifest.update(source_hashes={'fixture': 'altered'}, prompt_sha256=protocol.digest(agent.PROMPT), schemas={'remote': {}})
            path = self.state / (str(uuid4()) + '.json'); protocol.write_private(path, manifest)
            with patch.object(module, 'STATE', self.state / str(uuid4())), patch.object(module, 'source_hashes', lambda: {'fixture': 'sealed'}), \
                 patch.object(module, 'MCPClient', side_effect=AssertionError('client before source gate')):
                self.reject(lambda: module.run(path, start=True), 'SOURCE_DRIFT')
        self.killed('MCP-MUT-013', agent,
                    "need(manifest['source_hashes'] == source_hashes() and manifest['prompt_sha256'] == digest(PROMPT), 'MCP_SOURCE_DRIFT')",
                    'pass  # deliberate evidence binding break', control)

    def test_mut014_skipped_body_cleanup_is_killed(self):
        def control(module):
            wire = Wire(lambda _, k: Body(envelope(k['json'], {})))
            with self.client(wire=wire, module=module) as c: c.rpc('tools/list')
            self.assertTrue(wire.bodies[0].closed)
        self.killed('MCP-MUT-014', protocol, 'if response is not None: response.close()', 'if response is not None: pass', control)


if __name__ == '__main__': unittest.main()
