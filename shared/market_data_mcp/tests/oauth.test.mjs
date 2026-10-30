import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, readdir, rm, stat } from 'node:fs/promises';
import path from 'node:path';
import { STATE } from '../providers.mjs';
import { LocalOAuthProvider } from '../auth/local-oauth.mjs';
import { createTradingViewFetch } from '../adapters/tradingview.mjs';

test('OAuth refresh cache is atomic, private and compatible; query auth never opens browsers', async t => {
  const parent = path.join(STATE, 'runtime');
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const directory = await mkdtemp(path.join(parent, 'oauth-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const oauth = new LocalOAuthProvider(directory, 'https://mcp.tradingview.com/mcp');
  assert.equal(await oauth.tokens(), undefined);
  assert.throws(() => oauth.redirectToAuthorization(new URL('https://www.tradingview.com')), error => error.kind === 'auth_required');
  await oauth.saveTokens({ access_token: 'fixture-not-a-real-token', token_type: 'Bearer', expires_in: 60 });
  const files = await readdir(oauth.directory);
  assert.equal(files.length, 1);
  const location = path.join(oauth.directory, files[0]);
  assert.equal((await stat(location)).mode & 0o777, 0o600);
  const saved = JSON.parse(await readFile(location));
  assert.ok(saved.expires_at > Date.now() && saved.expires_at < Date.now() + 61000);
  assert.equal((await oauth.tokens()).access_token, 'fixture-not-a-real-token');
});

test('TradingView refuses untrusted endpoints before sending credentials', async () => {
  let fetched = false;
  const fetch = createTradingViewFetch(async () => { fetched = true; });
  await assert.rejects(fetch('https://example.org/token'), error => error.kind === 'untrusted_endpoint');
  await assert.rejects(fetch('http://mcp.tradingview.com/mcp'), error => error.kind === 'untrusted_endpoint');
  assert.equal(fetched, false);
});

test('TradingView forwards Retry-After as a typed transient error without a nested retry loop', async () => {
  let calls = 0;
  const fetch = createTradingViewFetch(async () => {
    calls++; return new Response('rate limited', { status: 429, headers: { 'retry-after': '7' } });
  });
  await assert.rejects(fetch('https://mcp.tradingview.com/mcp'), error =>
    error.kind === 'rate_limited' && error.retryAfterMs === 7000);
  assert.equal(calls, 1);
});
