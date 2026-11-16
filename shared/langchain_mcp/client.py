"""Bounded Streamable HTTP MCP, with semantic read retries and durable effect fences.

No SDK auto-retry, inherited proxies, redirects, registration, or tool discovery
fan-out. Credentials are resolved only for the exact remote endpoint.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time
from uuid import uuid4

import jsonschema
import requests
from urllib3.util import Timeout
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
LOCAL = 'http://127.0.0.1:2025/mcp'
REMOTE = 'https://api.smith.langchain.com/mcp'
STATE = ROOT / '.langchain-pilot/runtime/mcp-client'
VERSIONS = {'2025-06-18', '2025-11-25'}
ALLOWED = {LOCAL: {'calculator', 'holdings', 'calculator_session'}, REMOTE: {'query_runs'}}


class MCPError(ValueError):
    """Stable credential-free diagnostic; provider text is never interpolated."""


def need(condition, code):
    if not condition:
        raise MCPError(code)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def write_private(path, value, *, replace=False):
    path = Path(path)
    need(path.resolve().is_relative_to(ROOT), 'MCP_WORKSPACE_REQUIRED')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = (canonical(value) + '\n').encode('utf-8')
    if not replace:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    else:
        fd, name = tempfile.mkstemp(dir=path.parent, prefix='.pending-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)


def read_private(path, limit=8388608):
    path = Path(path)
    need(path.resolve().is_relative_to(ROOT), 'MCP_WORKSPACE_REQUIRED')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= limit,
             'MCP_PRIVATE_FILE_REQUIRED')
        return json.loads(stream.read())


def langsmith_key():
    path = ROOT / '.langchain-pilot/langsmith.env'
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
             and stat.S_IMODE(info.st_mode) == 0o600 and info.st_size <= 16384,
             'MCP_PRIVATE_KEY_REQUIRED')
        values = dotenv_values(stream=stream, interpolate=False)
    need(set(values) == {'LANGSMITH_API_KEY'} and bool(values['LANGSMITH_API_KEY']),
         'MCP_KEY_REQUIRED')
    return values['LANGSMITH_API_KEY']


def policy(value=None):
    defaults = json.loads(Path(__file__).with_name('policy.json').read_text())
    value = defaults if value is None else dict(value)
    need(set(value) == set(defaults) and all(type(x) in (int, float) and math.isfinite(x)
         and x > 0 for x in value.values()), 'MCP_POLICY_INVALID')
    for key in ('attempt_seconds', 'read_seconds', 'read_attempts', 'response_bytes',
                'logical_bytes', 'schema_bytes', 'json_depth', 'tool_roster', 'pages'):
        need(value[key] <= defaults[key], 'MCP_POLICY_EXCEEDS_FROZEN_BOUND')
    for key in ('read_attempts', 'response_bytes', 'logical_bytes', 'schema_bytes',
                'json_depth', 'tool_roster', 'pages'):
        need(type(value[key]) is int, 'MCP_POLICY_INVALID')
    return value


def retry_after(value, now):
    if not isinstance(value, str): return None
    try:
        number = float(value)
        if math.isfinite(number) and number >= 0: return number
    except ValueError: pass
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is None: date = date.replace(tzinfo=timezone.utc)
        return max(0.0, date.timestamp() - now)
    except (ValueError, TypeError, OverflowError): return None


def bounded_json(text, max_depth):
    # Check depth before json.loads (including malicious deeply nested schemas).
    quoted = escaped = False
    depth = 0
    for char in text:
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '[{':
            depth += 1
            need(depth <= max_depth, 'MCP_JSON_DEPTH')
        elif char in ']}': depth -= 1
    def pairs(items):
        value = {}
        for key, item in items:
            need(key not in value, 'MCP_DUPLICATE_JSON_KEY')
            value[key] = item
        return value
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(MCPError('MCP_NONFINITE_JSON')))
    except MCPError: raise
    except (ValueError, TypeError, RecursionError):
        raise MCPError('MCP_MALFORMED_JSON') from None


def local_schema(schema):
    """No implicit URL/file fetch may bypass the exact endpoint boundary."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key in ('$ref', '$dynamicRef', '$recursiveRef'):
                need(isinstance(value, str) and value.startswith('#'), 'MCP_EXTERNAL_SCHEMA_REF')
            local_schema(value)
    elif isinstance(schema, list):
        for item in schema: local_schema(item)


class MCPClient:
    def __init__(self, endpoint, *, state=STATE, expected_schemas=None, key_resolver=langsmith_key,
                 transport=None, read_policy=None, clock=time.monotonic, wall=time.time, sleep=time.sleep,
                 cancelled=lambda: False):
        need(endpoint in ALLOWED, 'MCP_ENDPOINT_REJECTED')
        self.endpoint, self.state = endpoint, Path(state)
        need(self.state.resolve().is_relative_to(ROOT), 'MCP_WORKSPACE_REQUIRED')
        self.policy = policy(read_policy)
        self.clock, self.wall, self.sleep, self.cancelled = clock, wall, sleep, cancelled
        self.key_resolver = key_resolver
        self.expected_schemas = expected_schemas
        self.http = transport if transport is not None else requests.Session()
        self.http.trust_env = False
        self.version, self.session_id, self.tools = None, None, {}
        self.stats = {'http_attempts': 0, 'decoded_bytes': 0, 'retries': 0}
        self.state.mkdir(mode=0o700, parents=True, exist_ok=True)

    def __enter__(self): return self
    def __exit__(self, *_): self.close()
    def close(self): self.http.close()

    def event(self, rid, disposition, **fields):
        # This boundary records only our enums, counts, hashes and numbers.
        write_private(self.state / 'events' / (str(uuid4()) + '.json'),
                      {'request_id': rid, 'at': self.wall(), 'endpoint': self.endpoint,
                       'disposition': disposition, **fields})

    def alive(self, deadline):
        need(not self.cancelled(), 'MCP_CANCELLED')
        need(self.clock() < deadline, 'MCP_DEADLINE')

    def wait(self, seconds, deadline):
        self.alive(deadline)
        need(self.clock() + seconds < deadline, 'MCP_RATE_DEFERRED')
        # Cancellation remains responsive during a server-requested wait.
        end = self.clock() + seconds
        while self.clock() < end:
            self.alive(deadline)
            self.sleep(min(0.1, end - self.clock()))

    @contextmanager
    def slot(self, category, deadline, rid):
        prefix = 'remote' if self.endpoint == REMOTE else 'local'
        with os.fdopen(os.open(self.state / (prefix + '-pacing.lock'),
                               os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600), 'w') as lock:
            while True:
                self.alive(deadline)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
                except BlockingIOError: self.wait(0.02, deadline)
            path = self.state / (prefix + '-pacing.json')
            prior = read_private(path) if path.exists() else {}
            delay = max(0.0, prior.get(category, 0) - self.wall())
            if delay:
                self.event(rid, 'pacing_wait', delay_seconds=delay)
                self.wait(delay, deadline)
            try: yield
            finally:
                interval = self.policy['query_interval_seconds' if category == 'query'
                                       else 'read_interval_seconds']
                write_private(path, {**prior, category: self.wall() + interval}, replace=path.exists())

    def parse(self, response, rid, deadline, budget):
        raw = bytearray()
        try:
            def chunks():
                if isinstance(response, requests.Response):
                    # read1 avoids read(n) waiting to accumulate an entire chunk.
                    # Each network read receives the remaining absolute budget.
                    sock = getattr(getattr(getattr(getattr(response.raw, '_fp', None), 'fp', None), 'raw', None), '_sock', None)
                    need(sock is not None and hasattr(response.raw, 'read1'), 'MCP_BOUNDED_STREAM_UNAVAILABLE')
                    while True:
                        self.alive(deadline)
                        sock.settimeout(max(0.001, deadline - self.clock()))
                        chunk = response.raw.read1(8192, decode_content=True)
                        if not chunk: break
                        yield chunk
                else:
                    # Injected transports must implement controlled bounded reads.
                    yield from response.iter_content(chunk_size=8192)
            for chunk in chunks():
                self.alive(deadline)
                budget['bytes'] += len(chunk)
                self.stats['decoded_bytes'] += len(chunk)
                need(len(raw) + len(chunk) <= self.policy['response_bytes']
                     and budget['bytes'] <= self.policy['logical_bytes'], 'MCP_RESPONSE_BYTES')
                raw.extend(chunk)
            self.alive(deadline)
            text = raw.decode('utf-8', errors='strict')
        except UnicodeError: raise MCPError('MCP_UTF8_REQUIRED') from None
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        if content_type == 'text/event-stream':
            need(text.replace('\r\n', '\n').endswith('\n\n'), 'MCP_UNTERMINATED_SSE')
            envelopes = []
            for block in text.replace('\r\n', '\n').split('\n\n'):
                data = '\n'.join(line[5:].lstrip(' ') for line in block.splitlines() if line.startswith('data:'))
                if data: envelopes.append(bounded_json(data, self.policy['json_depth']))
            # Notifications are permitted; exactly one terminal matching result.
            terminals = [x for x in envelopes if isinstance(x, dict) and 'id' in x]
            need(len(terminals) == 1, 'MCP_SSE_TERMINAL_REQUIRED')
            value = terminals[0]
        else:
            need(content_type == 'application/json', 'MCP_CONTENT_TYPE')
            value = bounded_json(text, self.policy['json_depth'])
        need(isinstance(value, dict) and value.get('jsonrpc') == '2.0'
             and value.get('id') == rid and ('result' in value) != ('error' in value), 'MCP_RPC_ENVELOPE')
        need('error' not in value, 'MCP_RPC_ERROR')
        need(isinstance(value['result'], dict), 'MCP_RESULT_SHAPE')
        return value['result']

    def rpc(self, method, params=None, *, readonly=True, notification=False, deadline=None, budget=None):
        rid = str(uuid4())
        maximum_deadline = self.clock() + self.policy['read_seconds']
        deadline = maximum_deadline if deadline is None else min(deadline, maximum_deadline)
        budget = {'bytes': 0} if budget is None else budget
        budget.setdefault('attempts', 0)
        budget.setdefault('retries', 0)
        budget.setdefault('rpc_ids', [])
        budget['rpc_ids'].append(rid)
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.version: headers['MCP-Protocol-Version'] = self.version
        if self.session_id: headers['Mcp-Session-Id'] = self.session_id
        key = self.key_resolver() if self.endpoint == REMOTE else None
        if key: headers['X-Api-Key'] = key
        payload = {'jsonrpc': '2.0', 'method': method}
        if not notification: payload['id'] = rid
        if params is not None: payload['params'] = params
        attempts = self.policy['read_attempts'] if readonly and not notification else 1
        if method == 'tools/call' and readonly:
            attempts = min(attempts, self.policy['read_attempts'] - budget['attempts'])
            need(attempts > 0, 'MCP_LOGICAL_HTTP_BUDGET')
        category = 'query' if method == 'tools/call' and readonly else 'read'
        for attempt in range(1, attempts + 1):
            response = None
            try:
                with self.slot(category, deadline, rid):
                    self.alive(deadline)
                    self.event(rid, 'dispatch', method=method, attempt=attempt, readonly=readonly)
                    self.stats['http_attempts'] += 1
                    budget['attempts'] += 1
                    attempt_deadline = min(deadline, self.clock() + self.policy['attempt_seconds'])
                    timeout = max(0.001, attempt_deadline - self.clock())
                    # One authority for all HTTP retry behavior.
                    response = self.http.post(self.endpoint, json=payload, headers=headers,
                        timeout=Timeout(total=timeout, connect=timeout, read=timeout),
                        stream=True, allow_redirects=False)
                    self.alive(attempt_deadline)
                    need(not 300 <= response.status_code < 400, 'MCP_REDIRECT_REJECTED')
                    if response.status_code == 429:
                        after = retry_after(response.headers.get('Retry-After'), self.wall())
                        delay = self.policy['fallback_seconds'] if after is None else after
                        self.event(rid, 'rate_limited', attempt=attempt, delay_seconds=delay,
                                   retry_after_valid=after is not None)
                        if not readonly or attempt == attempts: raise MCPError('MCP_RATE_LIMITED')
                    else:
                        need(200 <= response.status_code < 300, 'MCP_HTTP_ERROR')
                        if notification:
                            self.event(rid, 'notification_ack', attempt=attempt)
                            return {}
                        result = self.parse(response, rid, attempt_deadline, budget)
                        if key: need(key not in canonical(result), 'MCP_SECRET_RESPONSE')
                        if method == 'initialize':
                            session = response.headers.get('Mcp-Session-Id')
                            need(session is None or (isinstance(session, str) and 0 < len(session) <= 512
                                 and re.fullmatch(r'[A-Za-z0-9_.:-]+', session)), 'MCP_SESSION_HEADER')
                            self.session_id = session
                        self.event(rid, 'acknowledged', attempt=attempt, response_sha256=digest(result))
                        return result
            except MCPError: raise
            except BaseException as error:
                self.event(rid, 'failed_or_unknown', attempt=attempt, readonly=readonly)
                if isinstance(error, (KeyboardInterrupt, SystemExit)): raise
                raise MCPError('MCP_TRANSPORT_UNKNOWN') from None
            finally:
                if response is not None: response.close()
            self.wait(delay, deadline)
            self.stats['retries'] += 1
            budget['retries'] += 1
            self.event(rid, 'retry', attempt=attempt + 1)
        raise MCPError('MCP_NO_RESULT')

    def connect(self):
        need(self.version is None, 'MCP_ALREADY_INITIALIZED')
        deadline = self.clock() + self.policy['read_seconds']
        self.event(str(uuid4()), 'warmup', delay_seconds=self.policy['warmup_seconds'])
        self.wait(self.policy['warmup_seconds'], deadline)
        result = self.rpc('initialize', {'protocolVersion': '2025-11-25',
            'capabilities': {}, 'clientInfo': {'name': 'trading-agent-isolated-inspector', 'version': '1.0'}},
            deadline=deadline)
        need(result.get('protocolVersion') in VERSIONS
             and isinstance(result.get('capabilities', {}).get('tools'), dict), 'MCP_NEGOTIATION')
        self.version = result['protocolVersion']
        self.rpc('notifications/initialized', notification=True, deadline=deadline)
        result = self.rpc('tools/list', deadline=deadline)
        need(len(canonical(result).encode()) <= self.policy['schema_bytes'], 'MCP_SCHEMA_BYTES')
        roster = result.get('tools')
        need(isinstance(roster, list) and len(roster) <= self.policy['tool_roster']
             and not result.get('nextCursor'), 'MCP_TOOL_ROSTER')
        selected = {}
        names = set()
        for tool in roster:
            need(isinstance(tool, dict) and isinstance(tool.get('name'), str)
                 and tool['name'] not in names, 'MCP_TOOL_ROSTER')
            names.add(tool['name'])
            if tool['name'] not in ALLOWED[self.endpoint]: continue
            schema = tool.get('inputSchema')
            need(isinstance(schema, dict), 'MCP_TOOL_SCHEMA')
            local_schema(schema)
            try: jsonschema.Draft202012Validator.check_schema(schema)
            except (jsonschema.SchemaError, RecursionError): raise MCPError('MCP_TOOL_SCHEMA') from None
            selected[tool['name']] = schema
        need(set(selected) == ALLOWED[self.endpoint], 'MCP_REQUIRED_TOOL_MISSING')
        if self.expected_schemas is not None:
            need({name: digest(schema) for name, schema in selected.items()} == self.expected_schemas,
                 'MCP_SCHEMA_DRIFT')
        self.tools = selected
        return {'protocol': self.version, 'schemas': {n: digest(s) for n, s in selected.items()}}

    def call(self, name, arguments, *, intent_id=None, deadline=None, budget=None):
        need(self.version is not None and name in self.tools and name in ALLOWED[self.endpoint],
             'MCP_TOOL_REJECTED')
        need(isinstance(arguments, dict), 'MCP_ARGUMENTS')
        # Reject extras even where a graph-generated JSON schema omits this flag.
        need(set(arguments) <= set(self.tools[name].get('properties', {})), 'MCP_ARGUMENTS')
        try: jsonschema.Draft202012Validator(self.tools[name]).validate(arguments)
        except (jsonschema.ValidationError, TypeError, RecursionError): raise MCPError('MCP_ARGUMENTS') from None
        readonly = self.endpoint == REMOTE and name == 'query_runs'
        path = None
        if not readonly:
            need(isinstance(intent_id, str) and re.fullmatch(r'[0-9a-f-]{36}', intent_id), 'MCP_INTENT_REQUIRED')
            path = self.state / 'effects' / (intent_id + '.json')
            try:
                write_private(path, {'intent_id': intent_id, 'tool': name,
                                    'args_sha256': digest(arguments), 'status': 'dispatching'})
            except FileExistsError: raise MCPError('MCP_EFFECT_FENCED') from None
        try:
            result = self.rpc('tools/call', {'name': name, 'arguments': arguments},
                              readonly=readonly, deadline=deadline, budget=budget)
            need(result.get('isError', False) is False and isinstance(result.get('content'), list),
                 'MCP_TOOL_ERROR')
            if path:
                write_private(path.with_suffix('.receipt.json'),
                              {'status': 'acknowledged', 'intent_id': intent_id,
                               'result_sha256': digest(result), 'result': result})
            return result
        except BaseException:
            if path:
                write_private(path.with_suffix('.unknown.json'), {'intent_id': intent_id, 'status': 'unknown'})
            raise

    def text_result(self, result):
        blocks = result.get('content')
        need(isinstance(blocks, list) and len(blocks) == 1
             and blocks[0].get('type') == 'text' and isinstance(blocks[0].get('text'), str), 'MCP_TEXT_RESULT')
        text = blocks[0]['text']
        need(len(text.encode()) <= self.policy['response_bytes'], 'MCP_RESPONSE_BYTES')
        return bounded_json(text, self.policy['json_depth'])

    def effect_status(self, intent_id):
        """Read-only recovery. Never clears an unknown fence or creates a run."""
        need(isinstance(intent_id, str) and re.fullmatch(r'[0-9a-f-]{36}', intent_id), 'MCP_INTENT_REQUIRED')
        path = self.state / 'effects' / (intent_id + '.json')
        need(path.exists(), 'MCP_EFFECT_NOT_FOUND')
        intent = read_private(path)
        receipt_path = path.with_suffix('.receipt.json')
        if receipt_path.exists():
            receipt = read_private(receipt_path)
            need(receipt['intent_id'] == intent_id and digest(receipt['result']) == receipt['result_sha256'],
                 'MCP_EFFECT_RECEIPT_DRIFT')
            return {'status': 'acknowledged_fenced', 'intent': intent, 'receipt': receipt}
        return {'status': 'unknown_fenced', 'intent': intent,
                'recovery': 'Reconcile independently using an exact owned server identity if available; no automatic replay.'}
