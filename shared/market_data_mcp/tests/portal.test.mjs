import test from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { QueryPortal } from '../core/portal.mjs';
import { classify, checkResult } from '../core/errors.mjs';

const ok = data => ({ content: [{ type: 'text', text: JSON.stringify(data) }] });
const failure = result => JSON.parse(result.content[0].text);
function fixture(t, handle, policy = {}, tools) {
  const servers = [];
  const state = { calls: 0, connections: 0, events: [] };
  const portal = new QueryPortal({
    provider: 'test', allowedTools: ['quote'], toolMap: { quote: 'upstream_quote' },
    policy: { timeoutMs: 100, totalTimeoutMs: 1000, baseDelayMs: 1, maxDelayMs: 5, ...policy },
    log: event => state.events.push(event),
    transportFactory: () => {
      state.connections++;
      const [client, upstream] = InMemoryTransport.createLinkedPair();
      const server = new Server({ name: 'test-upstream', version: '1' }, { capabilities: { tools: {} } });
      servers.push(server);
      server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: tools ?? [
        { name: 'upstream_quote', inputSchema: { type: 'object' }, annotations: { readOnlyHint: true } },
        { name: 'place_order', inputSchema: { type: 'object' } },
      ] }));
      server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
        state.calls++;
        return handle({ state, request, extra, upstream });
      });
      void server.connect(upstream);
      return client;
    },
  });
  t.after(async () => { await portal.close(); await Promise.all(servers.map(server => server.close())); });
  return { portal, state };
}

test('discovers only allowed queries, maps names, blocks writes before IO', async t => {
  const { portal, state } = fixture(t, ({ request }) => {
    assert.equal(request.params.name, 'upstream_quote');
    return ok({ price: 1 });
  });
  assert.equal(failure(await portal.callTool('place_order')).error, 'tool_not_allowed');
  assert.equal(state.connections, 0);
  assert.deepEqual((await portal.listTools()).tools.map(tool => tool.name), ['quote']);
  assert.equal((await portal.callTool('quote')).isError, undefined);
  assert.equal(state.calls, 1);
});

test('retries HTTP 429 tool errors with bounded jitter, then returns actual data', async t => {
  const { portal, state } = fixture(t, ({ state }) => state.calls < 3
    ? { isError: true, ...ok({ error: 'HTTP 429 rate limited' }) } : ok({ price: 17 }));
  assert.equal(JSON.parse((await portal.callTool('quote')).content[0].text).price, 17);
  assert.equal(state.calls, 3);
  assert.equal(state.events.filter(event => event.event === 'retry_scheduled').length, 2);
});

test('recognizes isError=false JSON errors; retries transient 503 only', async t => {
  const { portal, state } = fixture(t, ({ state }) => state.calls === 1
    ? ok({ success: false, error: 'HTTP 503 temporarily unavailable' }) : ok({ price: 2 }));
  assert.equal((await portal.callTool('quote')).isError, undefined);
  assert.equal(state.calls, 2);
});

test('authentication errors never retry or disclose upstream secrets', async t => {
  const { portal, state } = fixture(t, () => ({ isError: true, ...ok({ error: 'HTTP 401 Bearer private-secret' }) }));
  const result = await portal.callTool('quote');
  assert.equal(failure(result).error, 'auth_required');
  assert.equal(state.calls, 1);
  assert.equal(JSON.stringify({ result, events: state.events }).includes('private-secret'), false);
});

test('validation errors are not retried', async t => {
  const { portal, state } = fixture(t, () => ({ isError: true, ...ok({ error: 'invalid symbol' }) }));
  assert.equal(failure(await portal.callTool('quote')).error, 'query_failed');
  assert.equal(state.calls, 1);
});

test('reconnects after a real MCP transport disconnection', async t => {
  const { portal, state } = fixture(t, async ({ state, upstream }) => {
    if (state.calls === 1) { await upstream.close(); return ok({ ignored: true }); }
    return ok({ recovered: true });
  });
  assert.equal(JSON.parse((await portal.callTool('quote')).content[0].text).recovered, true);
  assert.equal(state.connections, 2);
});

test('hung upstream requests time out and receive cancellation', async t => {
  let cancelled = 0;
  const { portal, state } = fixture(t, ({ extra }) => new Promise(resolve => {
    extra.signal.addEventListener('abort', () => { cancelled++; resolve(ok({ cancelled: true })); }, { once: true });
  }), { timeoutMs: 30, totalTimeoutMs: 200, maxAttempts: 2 });
  const started = Date.now();
  assert.equal(failure(await portal.callTool('quote')).error, 'timeout');
  assert.ok(Date.now() - started < 500);
  assert.equal(state.calls, 2);
  assert.equal(cancelled, 2);
});

test('circuit opens after exhausted failures and one probe recovers after cooldown', async t => {
  const { portal, state } = fixture(t, ({ state }) => state.calls <= 2
    ? { isError: true, ...ok({ error: 'HTTP 503' }) } : ok({ recovered: true }),
  { maxAttempts: 1, circuitThreshold: 2, circuitCooldownMs: 30 });
  await portal.callTool('quote'); await portal.callTool('quote');
  assert.equal(failure(await portal.callTool('quote')).error, 'circuit_open');
  assert.equal(state.calls, 2);
  assert.equal(portal.status().circuit, 'open');
  await sleep(40);
  assert.equal((await portal.callTool('quote')).isError, undefined);
  assert.equal(portal.status().circuit, 'closed');
});

test('bounded queue rejects overload and cancelled queued queries never dispatch', async t => {
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const { portal, state } = fixture(t, async () => { await blocked; return ok({ price: 1 }); }, { maxPending: 2 });
  const first = portal.callTool('quote');
  const abort = new AbortController();
  const second = portal.callTool('quote', {}, abort.signal);
  assert.equal(failure(await portal.callTool('quote')).error, 'busy');
  abort.abort();
  assert.equal(failure(await second).error, 'cancelled');
  release(); await first; await portal.tail;
  assert.equal(state.calls, 1);
  assert.equal(portal.status().pending, 0);
});

test('caller cancellation stops retries', async t => {
  const abort = new AbortController();
  const { portal, state } = fixture(t, ({ extra }) => new Promise(resolve => {
    abort.abort();
    extra.signal.addEventListener('abort', () => resolve(ok({ cancelled: true })), { once: true });
  }));
  assert.equal(failure(await portal.callTool('quote', {}, abort.signal)).error, 'cancelled');
  assert.equal(state.calls, 1);
});

test('Retry-After exceeding the total budget fails without early retry', async t => {
  const { portal, state } = fixture(t, () => ok({ price: 1 }));
  let calls = 0;
  await assert.rejects(portal.retry(async () => {
    calls++;
    const error = new Error('HTTP 429');
    error.status = 429; error.headers = new Headers({ 'retry-after': '120' });
    throw error;
  }), error => error.kind === 'rate_limited');
  assert.equal(calls, 1);
  assert.equal(state.events.some(event => event.event === 'retry_scheduled'), false);
});

test('rejects a formerly allowed tool if upstream marks it writable', async t => {
  const { portal, state } = fixture(t, () => ok({}), {}, [
    { name: 'upstream_quote', inputSchema: { type: 'object' }, annotations: { readOnlyHint: false } },
  ]);
  assert.equal(failure(await portal.callTool('quote')).error, 'capability_mismatch');
  assert.equal(state.calls, 0);
});

test('shutdown refuses subsequent work; invalid policies fail before provider IO', async t => {
  const { portal, state } = fixture(t, () => ok({}));
  await portal.close();
  assert.equal(failure(await portal.callTool('quote')).error, 'closed');
  assert.equal(state.connections, 0);
  assert.throws(() => new QueryPortal({ provider: 'test', allowedTools: [], policy: { maxAttempts: 10 } }));
});

test('structured error payloads and malformed responses cannot look successful', () => {
  assert.throws(() => checkResult({ content: [], structuredContent: { success: false, error: 'HTTP 403' } }),
    error => error.kind === 'auth_required');
  assert.throws(() => checkResult({}), error => error.kind === 'invalid_response');
  assert.equal(classify({ status: 429, headers: new Headers({ 'retry-after': '2' }) }).retryAfterMs, 2000);
});

test('shared retry quota limits amplification across repeated requests and replenishes on success', async t => {
  let healthy = false;
  const { portal, state } = fixture(t, () => healthy ? ok({ price: 1 }) : { isError: true, ...ok({ error: 'HTTP 503' }) },
    { retryQuota: 1, circuitThreshold: 10 });
  await portal.callTool('quote');
  assert.equal(state.calls, 2);
  assert.equal(portal.status().retryTokens, 0);
  await portal.callTool('quote');
  assert.equal(state.calls, 3); // Initial requests still work; only retries are suppressed.
  healthy = true;
  await portal.callTool('quote');
  assert.equal(portal.status().retryTokens, 1);
});
