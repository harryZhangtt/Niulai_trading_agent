import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, writeFile, chmod, rm } from 'node:fs/promises';
import path from 'node:path';
import { finnhubQuery } from '../adapters/finnhub.mjs';
import { STATE } from '../providers.mjs';
import { checkResult } from '../core/errors.mjs';

async function credentials(t) {
  const parent = path.join(STATE, 'runtime');
  await mkdir(parent, { recursive: true });
  const directory = await mkdtemp(path.join(parent, 'finnhub-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const credentialFile = path.join(directory, 'key.json');
  await writeFile(credentialFile, JSON.stringify({ api_key: 'fixture-only-not-a-real-key' }), { mode: 0o600 });
  return credentialFile;
}

test('Finnhub uses only an official GET endpoint and a header; key never enters the URL', async t => {
  const credentialFile = await credentials(t);
  let requests = 0;
  const result = await finnhubQuery('quote', { symbol: 'AAPL' }, { credentialFile, fetchImpl: async (url, init) => {
    requests++;
    assert.equal(url.origin, 'https://finnhub.io');
    assert.equal(url.pathname, '/api/v1/quote');
    assert.equal(url.search, '?symbol=AAPL');
    assert.equal(url.toString().includes('fixture-only'), false);
    assert.equal(init.headers['X-Finnhub-Token'], 'fixture-only-not-a-real-key');
    assert.equal(init.method, 'GET'); assert.equal(init.redirect, 'manual');
    return Response.json({ c: 1, t: 1 });
  } });
  assert.equal(requests, 1); assert.equal(result.data.c, 1);
  assert.equal(JSON.stringify(result).includes('fixture-only'), false);
});

test('Finnhub rejects writes and malformed arguments before network IO', async t => {
  const credentialFile = await credentials(t);
  const options = { credentialFile, fetchImpl: async () => assert.fail('network IO must not occur') };
  await assert.rejects(finnhubQuery('place_order', {}, options), error => error.kind === 'tool_not_allowed');
  await assert.rejects(finnhubQuery('quote', {}, options), error => error.kind === 'invalid_arguments');
  await assert.rejects(finnhubQuery('quote', { symbol: 'AAPL', token: 'never-an-argument' }, options), error => error.kind === 'invalid_arguments');
  await chmod(credentialFile, 0o644);
  await assert.rejects(finnhubQuery('quote', { symbol: 'AAPL' }, options), error => error.kind === 'auth_required');
});

test('Finnhub distinguishes entitlement, auth and throttling; Retry-After survives the MCP boundary', async t => {
  const credentialFile = await credentials(t);
  for (const [status, kind] of [[401, 'auth_required'], [403, 'entitlement_required'], [429, 'rate_limited'], [503, 'upstream_unavailable']]) {
    await assert.rejects(finnhubQuery('quote', { symbol: 'AAPL' }, { credentialFile,
      fetchImpl: async () => new Response('sensitive provider message', { status, headers: { 'retry-after': '2' } }),
    }), error => error.kind === kind && !error.message.includes('sensitive'));
  }
  assert.throws(() => checkResult({ isError: true, content: [{ type: 'text', text: JSON.stringify({ error: 'rate_limited', retry_after_ms: 2000 }) }] }),
    error => error.kind === 'rate_limited' && error.retryAfterMs === 2000);
});
