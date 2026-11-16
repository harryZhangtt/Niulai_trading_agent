import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { FactorMiningBridge, factorMiningOptions, start } from '../server.mjs';

async function freePort() {
  const server = http.createServer(); await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port; await new Promise(resolve => server.close(resolve)); return port;
}
const packet = { schema_version: 1, scope: 'factor_mining', read_only: true, status: 'empty', projection_state: 'fresh', runs: [], warnings: [] };

test('factor-mining query accepts immutable identities only', () => {
  for (const search of ['run=../../auth', 'manifest=' + 'a'.repeat(64), 'run=x&manifest=bad', 'path=.env']) {
    assert.throws(() => factorMiningOptions(new URL('http://localhost/api/factor-mining?' + search)),
      { code: 'INVALID_FACTOR_MINING_QUERY' });
  }
  assert.deepEqual(factorMiningOptions(new URL('http://localhost/api/factor-mining?run=run.a&manifest=' + 'a'.repeat(64))),
    { run: 'run.a', manifest: 'a'.repeat(64) });
});

test('factor-mining bridge coalesces refreshes and returns stale-last-good without diagnostics', async () => {
  let calls = 0; let fail = false;
  const bridge = new FactorMiningBridge({ ttl: 0, loader: async () => {
    calls++; await new Promise(resolve => setTimeout(resolve, 10));
    if (fail) throw Error('SYNTHETIC_PRIVATE'); return packet;
  } });
  const values = await Promise.all(Array.from({ length: 20 }, () => bridge.get({ run: null, manifest: null })));
  assert.equal(calls, 1); assert.ok(values.every(value => value === packet));
  fail = true;
  const stale = await bridge.get({ run: null, manifest: null }, { force: true });
  assert.equal(stale.projection_state, 'stale');
  assert.ok(!JSON.stringify(stale).includes('SYNTHETIC_PRIVATE'));
  bridge.close(); await assert.rejects(bridge.get({ run: null, manifest: null }), { code: 'SERVER_CLOSING' });
});

test('loopback factor endpoint is read-only, isolated, and sanitizes failures', async () => {
  const port = await freePort(); let actual;
  const factorMining = new FactorMiningBridge({ loader: async options => {
    actual = options; if (options.run === 'fail') throw Error('SYNTHETIC_PRIVATE'); return packet;
  } });
  const service = await start({ port, factorMining,
    viteFactory: async () => ({ middlewares: (_request, response) => response.end('fixture'), close: async () => {} }) });
  try {
    const origin = 'http://127.0.0.1:' + port;
    let response = await fetch(origin + '/api/factor-mining?run=example');
    assert.equal(response.status, 200); assert.deepEqual(actual, { run: 'example', manifest: null });
    assert.deepEqual(await response.json(), packet);
    response = await fetch(origin + '/api/factor-mining?run=fail');
    assert.equal(response.status, 503); assert.ok(!(await response.text()).includes('SYNTHETIC_PRIVATE'));
    response = await fetch(origin + '/api/factor-mining', { method: 'POST' }); assert.equal(response.status, 405);
    response = await fetch(origin + '/api/factor-mining', { headers: { Origin: 'https://evil.example' } }); assert.equal(response.status, 403);
    response = await fetch(origin + '/api/factor-mining?run=../../auth'); assert.equal(response.status, 400);
    response = await fetch(origin + '/api/scheduler'); assert.notEqual(response.status, 404);
    response = await fetch(origin + '/api/datasource/health'); assert.equal(response.status, 200);
  } finally { await service.close(); }
});
