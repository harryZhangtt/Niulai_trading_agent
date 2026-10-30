import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, writeFile, chmod, symlink, rm } from 'node:fs/promises';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { fetchJson, readCredentials } from '../core/rest-adapter.mjs';
import { marketdataQuery, marketdataTransport } from '../adapters/marketdata.mjs';
import { alpacaQuery, alpacaTransport } from '../adapters/alpaca.mjs';
import { massiveQuery, massiveTransport } from '../adapters/massive.mjs';
import { STATE } from '../providers.mjs';

const secret = 'synthetic-secret-not-a-real-key';
async function fixture(t) {
  const parent = path.join(STATE, 'runtime');
  await mkdir(parent, { recursive: true });
  const directory = await mkdtemp(path.join(parent, 'options-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const credentialFile = path.join(directory, 'key.json');
  await writeFile(credentialFile, JSON.stringify({ api_key: secret, api_secret: secret + '-second' }), { mode: 0o600 });
  return credentialFile;
}

test('options credential reader rejects permissions, symlinks, bad fields and oversized files', async t => {
  const file = await fixture(t);
  assert.equal((await readCredentials(file, ['api_key'])).api_key, secret);
  await chmod(file, 0o644);
  await assert.rejects(readCredentials(file, ['api_key']), e => e.kind === 'auth_required');
  await chmod(file, 0o600);
  await symlink(file, file + '.link');
  await assert.rejects(readCredentials(file + '.link', ['api_key']), e => e.kind === 'auth_required');
  await writeFile(file, JSON.stringify({ api_key: 'bad\nheader' }));
  await assert.rejects(readCredentials(file, ['api_key']), e => e.kind === 'auth_required');
  await writeFile(file, 'x'.repeat(5000));
  await assert.rejects(readCredentials(file, ['api_key']), e => e.kind === 'auth_required');
});

test('REST boundary accepts 203, bounds bodies, rejects redirects and preserves safe Retry-After', async () => {
  assert.deepEqual(await fetchJson('https://example.invalid', { fetchImpl: async () => Response.json({ s: 'ok' }, { status: 203 }) }), { s: 'ok' });
  for (const [status, kind] of [[204, 'no_data'], [302, 'query_failed'], [401, 'auth_required'], [402, 'entitlement_required'], [403, 'entitlement_required'], [429, 'rate_limited'], [503, 'upstream_unavailable']]) {
    await assert.rejects(fetchJson('https://example.invalid', { fetchImpl: async (url, init) => {
      assert.equal(init.redirect, 'manual'); assert.equal(init.method, 'GET');
      return new Response(status === 204 ? null : secret, { status, headers: { 'retry-after': '5' } });
    } }), e => e.kind === kind && e.retryAfterMs === 5000 && !e.message.includes(secret));
  }
  for (const body of ['not JSON', '[]', 'x'.repeat(1024 * 1024 + 1)]) {
    await assert.rejects(fetchJson('https://example.invalid', { fetchImpl: async () => new Response(body) }), e => e.kind === 'invalid_response');
  }
});

test('Market Data forces historical mode, bounds chains, protects demo scope and secrets', async t => {
  const file = await fixture(t);
  const args = { underlying: 'AAPL', expiration: '2027-01-15', side: 'call', strike_limit: 2 };
  const result = await marketdataQuery('option_chain', args, { credentialFile: file, fetchImpl: async (url, init) => {
    assert.equal(url.origin, 'https://api.marketdata.app');
    assert.equal(url.searchParams.get('mode'), 'historical');
    assert.equal(url.searchParams.get('expiration'), args.expiration);
    assert.equal(url.searchParams.get('strikeLimit'), '2');
    assert.equal(init.headers.Authorization, `Bearer ${secret}`);
    assert.ok(!url.toString().includes(secret));
    return Response.json({ s: 'ok', optionSymbol: ['AAPL270115C00300000'], delta: [null], note: secret });
  } });
  assert.equal(result.data.delta[0], null);
  assert.ok(!JSON.stringify(result).includes(secret));
  await assert.rejects(marketdataQuery('option_chain', { ...args, strike_limit: 100 }, { credentialFile: file }), e => e.kind === 'invalid_arguments');
  await assert.rejects(marketdataQuery('option_expirations', { underlying: 'SPY' }, { credentialFile: file + '.missing' }), e => e.kind === 'auth_required');
});

test('Alpaca forces indicative feed and never returns an opaque pagination URL', async t => {
  const credentialFile = await fixture(t);
  const result = await alpacaQuery('option_snapshots', { contracts: ['AAPL270115C00300000'] }, { credentialFile, fetchImpl: async (url, init) => {
    assert.equal(url.origin, 'https://data.alpaca.markets');
    assert.equal(url.searchParams.get('feed'), 'indicative');
    assert.equal(init.headers['APCA-API-KEY-ID'], secret);
    assert.equal(init.headers['APCA-API-SECRET-KEY'], secret + '-second');
    return Response.json({ snapshots: { AAPL270115C00300000: { impliedVolatility: 0.2, greeks: { delta: 0.5 }, note: secret } }, next_page_token: secret });
  } });
  assert.equal(result.feed, 'indicative'); assert.equal(result.more_available, true);
  assert.ok(!JSON.stringify(result).includes(secret));
});

test('Massive restricts daily history and drops next_url rather than following or exposing it', async t => {
  const credentialFile = await fixture(t);
  let calls = 0;
  const result = await massiveQuery('option_contracts', { underlying: 'AAPL', limit: 2 }, { credentialFile, fetchImpl: async (url, init) => {
    calls++;
    assert.equal(url.origin, 'https://api.massive.com');
    assert.equal(url.pathname, '/v3/reference/options/contracts');
    assert.equal(init.headers.Authorization, `Bearer ${secret}`);
    return Response.json({ status: 'OK', results: [{ ticker: 'O:AAPL270115C00300000' }], next_url: `https://evil.invalid/?apiKey=${secret}` });
  } });
  assert.equal(calls, 1); assert.equal(result.more_available, true);
  assert.ok(!JSON.stringify(result).includes('evil.invalid'));
  await assert.rejects(massiveQuery('option_daily_bars', { contract: 'O:AAPL270115C00300000', from: '2026-02-30', to: '2026-03-01' }, { credentialFile }), e => e.kind === 'invalid_arguments');
  await assert.rejects(massiveQuery('option_daily_bars', { contract: 'O:AAPL270115C00300000', from: '2026-01-01', to: '2026-06-01' }, { credentialFile }), e => e.kind === 'invalid_arguments');
});

test('both chain adapters map bounded strike filters and reject reversed ranges before HTTP', async t => {
  const credentialFile = await fixture(t);
  for (const [query, name, keys, payload] of [
    [alpacaQuery, 'option_chain', ['strike_price_gte', 'strike_price_lte'], { snapshots: { AAPL270115C00300000: {} } }],
    [massiveQuery, 'option_contracts', ['strike_price.gte', 'strike_price.lte'], { status: 'OK', results: [{}] }],
  ]) {
    const args = { underlying: 'AAPL', expiration: '2027-01-15', side: 'call', strike_min: 295, strike_max: 305 };
    await query(name, args, { credentialFile, fetchImpl: async url => {
      assert.equal(url.searchParams.get(keys[0]), '295'); assert.equal(url.searchParams.get(keys[1]), '305');
      return Response.json(payload);
    } });
    await assert.rejects(query(name, { ...args, strike_min: 306 }, { credentialFile,
      fetchImpl: async () => assert.fail('invalid ranges must not perform HTTP') }), e => e.kind === 'invalid_arguments');
  }
});

test('each options MCP rejects paid/generic inputs and writes at its protocol boundary', async t => {
  const file = await fixture(t);
  for (const [make, name, args] of [
    [marketdataTransport, 'option_expirations', { underlying: 'AAPL', mode: 'live' }],
    [alpacaTransport, 'option_chain', { underlying: 'AAPL', expiration: '2027-01-15', side: 'call', feed: 'opra' }],
    [massiveTransport, 'option_contracts', { underlying: 'AAPL', url: 'https://evil.invalid' }],
  ]) {
    const client = new Client({ name: 'options-boundary-test', version: '1' });
    await client.connect(make(file));
    try {
      for (const request of [{ name, arguments: args }, { name: 'place_order', arguments: {} }]) {
        const result = await client.callTool(request);
        assert.equal(result.isError, true);
        assert.ok(!JSON.stringify(result).includes(secret));
      }
    } finally { await client.close(); }
  }
});
