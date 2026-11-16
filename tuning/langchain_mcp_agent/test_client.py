"""Implementer atomic regressions; independent cases live in test_independent."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from shared.langchain_mcp.client import MCPClient, MCPError, LOCAL, REMOTE, ROOT, bounded_json, policy, retry_after


class Clock:
    def __init__(self): self.t = 1000.0
    def now(self): return self.t
    def sleep(self, seconds): self.t += seconds


class Response:
    def __init__(self, value, status=200, headers=None, chunks=None):
        self.headers = {'Content-Type': 'application/json', **(headers or {})}
        self.status_code, self.closed = status, False
        self.chunks = chunks if chunks is not None else [json.dumps(value).encode()]
    def iter_content(self, chunk_size): yield from self.chunks
    def close(self): self.closed = True


class Transport:
    def __init__(self, handler=None): self.calls, self.responses, self.closed, self.handler = [], [], False, handler
    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if self.handler: response = self.handler(endpoint, kwargs)
        else:
            payload = kwargs['json']; method = payload['method']
            if method == 'initialize': result = {'protocolVersion': '2025-06-18', 'capabilities': {'tools': {}}}
            elif method == 'notifications/initialized': return Response({}, status=202)
            elif method == 'tools/list':
                names = ['query_runs'] if endpoint == REMOTE else ['calculator', 'holdings', 'calculator_session']
                result = {'tools': [{'name': n, 'inputSchema': {'type': 'object', 'properties': {'request': {'type': 'object'}},
                          'additionalProperties': False}} for n in names]}
            else: result = {'content': [{'type': 'text', 'text': '{}'}]}
            response = Response({'jsonrpc': '2.0', 'id': payload.get('id'), 'result': result})
        self.responses.append(response); return response
    def close(self): self.closed = True


class ClientTests(unittest.TestCase):
    def setUp(self):
        root = ROOT / '.langchain-pilot/tmp'; root.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
    def client(self, endpoint=LOCAL, transport=None, **kwargs):
        return MCPClient(endpoint, state=Path(self.tmp.name), transport=transport or Transport(),
                         clock=self.clock.now, wall=self.clock.now, sleep=self.clock.sleep,
                         key_resolver=kwargs.pop('key_resolver', lambda: 'SYNTHETIC-KEY-987'), **kwargs)

    def test_wrong_endpoint_never_dispatches(self):
        transport = Transport()
        for endpoint in ('http://localhost:2025/mcp', LOCAL + '?override=1', 'https://evil.example/mcp'):
            with self.assertRaisesRegex(MCPError, 'ENDPOINT'): self.client(endpoint, transport=transport)
        self.assertEqual(transport.calls, [])

    def test_protocol_and_key_headers(self):
        transport = Transport()
        with self.client(REMOTE, transport) as client:
            result = client.connect()
            self.assertEqual(result['protocol'], '2025-06-18')
            self.assertEqual(transport.calls[1][1]['headers']['MCP-Protocol-Version'], '2025-06-18')
            self.assertTrue(all(c[1]['headers']['X-Api-Key'] == 'SYNTHETIC-KEY-987' for c in transport.calls))
        self.assertTrue(transport.closed)

    def test_secret_not_resolved_for_local(self):
        def forbidden(): raise AssertionError('local resolved remote credential')
        with self.client(key_resolver=forbidden) as client: client.connect()

    def test_redirect_and_body_cleanup(self):
        transport = Transport(lambda *_: Response({}, 302, {'Location': 'https://evil.example'}))
        with self.client(REMOTE, transport) as client:
            with self.assertRaisesRegex(MCPError, 'REDIRECT'): client.connect()
        self.assertEqual(len(transport.calls), 1)
        self.assertTrue(transport.responses[0].closed)
        self.assertFalse(transport.calls[0][1]['allow_redirects'])

    def test_invalid_rpc_id_rejected(self):
        transport = Transport(lambda *_: Response({'jsonrpc':'2.0','id':'foreign','result':{}}))
        with self.client(transport=transport) as client:
            with self.assertRaisesRegex(MCPError,'ENVELOPE'): client.connect()

    def test_error_envelope_not_http_success(self):
        def error(_, kwargs): return Response({'jsonrpc':'2.0','id':kwargs['json']['id'],'error':{'message':'SYNTHETIC-SECRET'}})
        with self.client(transport=Transport(error)) as client:
            with self.assertRaisesRegex(MCPError,'RPC_ERROR'): client.connect()

    def test_unknown_protocol_cannot_advance(self):
        def handler(_, kwargs): return Response({'jsonrpc':'2.0','id':kwargs['json']['id'],'result':{'protocolVersion':'1999','capabilities':{'tools':{}}}})
        transport = Transport(handler)
        with self.client(transport=transport) as client:
            with self.assertRaisesRegex(MCPError,'NEGOTIATION'): client.connect()
        self.assertEqual(len(transport.calls),1)

    def test_schema_drift_and_unallowlisted_alias(self):
        with self.client(expected_schemas={'calculator':'wrong'}) as client:
            with self.assertRaisesRegex(MCPError, 'DRIFT'): client.connect()
        with self.client() as client:
            client.connect(); count = len(client.http.calls)
            with self.assertRaisesRegex(MCPError,'TOOL_REJECTED'): client.call('trading_pilot',{})
            with self.assertRaisesRegex(MCPError,'ARGUMENTS'): client.call('calculator',{'extra':True})
            self.assertEqual(len(client.http.calls),count)

    def test_local_unknown_is_once_and_fenced(self):
        with self.client() as client:
            client.connect(); count = len(client.http.calls)
            def fail(*_): raise TimeoutError('SYNTHETIC-KEY-987')
            client.http.handler = fail
            identity = str(uuid4())
            with self.assertRaisesRegex(MCPError,'TRANSPORT_UNKNOWN'): client.call('calculator',{},intent_id=identity)
            with self.assertRaisesRegex(MCPError,'FENCED'): client.call('calculator',{},intent_id=identity)
            self.assertEqual(len(client.http.calls),count+1)
            events=''.join(p.read_text() for p in Path(self.tmp.name).rglob('*.json'))
            self.assertNotIn('SYNTHETIC-KEY-987',events)

    def test_remote_429_retries_once_after_server_delay(self):
        with self.client(REMOTE) as client:
            client.connect(); start=self.clock.t; seen=[]
            def handler(_,kwargs):
                seen.append(self.clock.t)
                if len(seen)==1:return Response({},429,{'Retry-After':'3'})
                return Response({'jsonrpc':'2.0','id':kwargs['json']['id'],'result':{'content':[{'type':'text','text':'{}'}]}})
            client.http.handler=handler
            client.call('query_runs',{})
            self.assertEqual(len(seen),2)
            self.assertGreaterEqual(seen[1]-seen[0],3)
            self.assertEqual(client.stats['retries'],1)

    def test_rate_delay_beyond_deadline_does_not_dispatch_again(self):
        with self.client(REMOTE) as client:
            client.connect(); calls=[]
            def handler(*_): calls.append(1); return Response({},429,{'Retry-After':'99'})
            client.http.handler=handler
            with self.assertRaisesRegex(MCPError,'DEFERRED'): client.call('query_runs',{})
            self.assertEqual(len(calls),1)

    def test_permanent_auth_not_retried(self):
        transport=Transport(lambda *_:Response({},401))
        with self.client(REMOTE,transport) as client:
            with self.assertRaisesRegex(MCPError,'HTTP_ERROR'):client.connect()
        self.assertEqual(len(transport.calls),1)

    def test_cumulative_utf8_bound_and_response_closed(self):
        chosen=policy();chosen['response_bytes']=60;chosen['logical_bytes']=70
        transport=Transport(lambda *_:Response({},chunks=[('仓'*11).encode(),('仓'*11).encode()]))
        with self.client(transport=transport,read_policy=chosen) as client:
            with self.assertRaisesRegex(MCPError,'RESPONSE_BYTES'):client.connect()
        self.assertTrue(transport.responses[0].closed)

    def test_cancellation_closes_body_and_client(self):
        state={'cancelled':False}
        class CancelResponse(Response):
            def iter_content(self,chunk_size):state['cancelled']=True;yield b'{}'
        transport=Transport(lambda *_:CancelResponse({}))
        with self.client(transport=transport,cancelled=lambda:state['cancelled']) as client:
            with self.assertRaisesRegex(MCPError,'CANCELLED'):client.connect()
        self.assertTrue(transport.responses[0].closed);self.assertTrue(transport.closed)

    def test_deep_duplicate_and_nonfinite_json(self):
        for value in ('['*33+'0'+']'*33,'{"k":1,"k":2}','{"x":NaN}'):
            with self.assertRaises(MCPError):bounded_json(value,32)
        self.assertEqual(bounded_json('{"x":"[not depth]"}',2),{'x':'[not depth]'})

    def test_retry_date_and_malformed(self):
        self.assertEqual(retry_after('Thu, 01 Jan 1970 00:16:45 GMT',1000),5)
        self.assertIsNone(retry_after('invalid',1000))
        self.assertIsNone(retry_after('NaN',1000))


if __name__=='__main__':unittest.main()
