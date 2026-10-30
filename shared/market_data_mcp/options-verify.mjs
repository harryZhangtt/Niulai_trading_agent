// Bounded live integration/data verification. No plan changes or trading operations.
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { withPortal, jsonResult } from './client.mjs';
import { STATE } from './providers.mjs';
import { marketDate } from './adapters/massive.mjs';
import { expirations, requireData, summarizeSnapshots, verifyBars, verifyReference, verifySnapshot } from './verification/options.mjs';

const started = Date.now();
const identity = new Date(started).toISOString().replaceAll(':', '-');
const location = path.join(STATE, 'reports', `options-verification-${identity}.json`);
const report = { startedAt: new Date(started).toISOString(), route: 'isolated MCP clients -> shared portals -> official REST APIs',
  scope: 'development integration and data consistency; not price accuracy, live-risk, host or scheduled-session acceptance',
  activeCodexRegistration: false, cases: [], dataCalls: {}, sourceHashes: {}, events: {}, limitations: [], comparisons: [] };
const budgets = { finnhub: 3, alpaca: 35, massive: 18, marketdata: 3 };
const blocked = new Map(), snapshots = new Map(), references = new Map(), series = new Map();
const observations = [];
let lastMassiveAt = 0;
const [near, far] = expirations(started);
const end = new Date(marketDate(started) + 'T00:00:00Z'); end.setUTCDate(end.getUTCDate() - 1);
const to = end.toISOString().slice(0, 10), from = new Date(end.getTime() - 13 * 86400000).toISOString().slice(0, 10);
report.matrix = { underlyings: ['AAPL', 'SPY', 'QQQ'], sides: ['call', 'put'], expirations: [near, far], historicalRange: { from, to } };

async function checkpoint() {
  await mkdir(path.dirname(location), { recursive: true, mode: 0o700 });
  await writeFile(location, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
}
async function check(name, fn) {
  const begin = Date.now();
  try {
    const detail = await fn();
    report.cases.push({ name, status: 'pass', durationMs: Date.now() - begin, ...detail });
  } catch (error) {
    const kind = error.kind ?? 'verification_failure';
    const status = ['auth_required', 'entitlement_required', 'rate_limited', 'blocked_route', 'missing_dependency'].includes(kind) ? 'blocked' : 'fail';
    report.cases.push({ name, status, durationMs: Date.now() - begin, kind });
  }
  const latest = report.cases.at(-1);
  process.stdout.write(`${name}: ${latest.status}${latest.kind ? ' (' + latest.kind + ')' : ''}\n`);
  await checkpoint();
}
async function call(client, provider, name, args, data = true) {
  requireData(Date.now() - started < 10 * 60 * 1000, 'verification_wall_budget_exceeded');
  if (data) {
    if (blocked.has(provider) || blocked.has(`${provider}:${name}`)) throw Object.assign(new Error(), { kind: 'blocked_route' });
    requireData((report.dataCalls[provider] ?? 0) < budgets[provider], 'verification_budget_exceeded');
    if (provider === 'massive') {
      await sleep(Math.max(0, lastMassiveAt + 13000 - Date.now()));
      lastMassiveAt = Date.now();
    }
    report.dataCalls[provider] = (report.dataCalls[provider] ?? 0) + 1;
  }
  try {
    return jsonResult(await client.callTool({ name, arguments: args }, undefined, { timeout: 75000 }));
  } catch (error) {
    if (data && ['auth_required', 'rate_limited'].includes(error.kind)) blocked.set(provider, error.kind);
    if (data && error.kind === 'entitlement_required') blocked.set(`${provider}:${name}`, error.kind);
    throw error;
  }
}
async function rejection(client, provider, name, args, expected, data = false) {
  try { await call(client, provider, name, args, data); }
  catch (error) { requireData(expected.includes(error.kind), 'unexpected_failure_code'); return { error: error.kind }; }
  requireData(false, 'unsafe_or_missing_data_accepted');
}
function selected(underlying, side, expiry = near) {
  const values = references.get(`${underlying}:${side}:${expiry}`);
  requireData(values?.length, 'missing_dependency');
  return values[0].ticker;
}

try {
  for (const name of ['adapters/alpaca.mjs', 'adapters/massive.mjs', 'core/portal.mjs', 'core/rest-adapter.mjs', 'schemas/alpaca.json', 'schemas/massive.json', 'verification/options.mjs', 'verification/README.md', 'options-verify.mjs']) {
    report.sourceHashes[name] = createHash('sha256').update(await readFile(new URL('./' + name, import.meta.url))).digest('hex');
  }
  const anchors = {};
  await withPortal('finnhub', async client => {
    for (const symbol of report.matrix.underlyings) await check(`anchor_${symbol}`, async () => {
      const r = await call(client, 'finnhub', 'quote', { symbol });
      requireData(Number.isFinite(r.data.c) && r.data.c > 0, 'invalid_underlying_context');
      anchors[symbol] = r.data.c;
      return { symbol, underlyingContextPrice: r.data.c, providerTimestamp: r.data.t };
    });
  });
  await withPortal('alpaca', async (alpaca, ae) => {
    for (const underlying of report.matrix.underlyings) for (const expiration of [near, far]) for (const side of ['call', 'put']) {
      await check(`alpaca_chain_${underlying}_${expiration}_${side}`, async () => {
        requireData(anchors[underlying] > 0, 'missing_dependency');
        const args = { underlying, expiration, side, limit: 3, strike_min: Math.floor(anchors[underlying] * 0.98), strike_max: Math.ceil(anchors[underlying] * 1.02) };
        const r = await call(alpaca, 'alpaca', 'option_chain', args);
        requireData(r.feed === 'indicative' && r.automatic_pagination === false, 'wrong_feed_or_pagination');
        const entries = Object.entries(r.data.snapshots);
        requireData(entries.length > 0 && entries.length <= args.limit, 'invalid_snapshot_count');
        for (const [symbol, snapshot] of entries) {
          observations.push(verifySnapshot(symbol, snapshot, args)); snapshots.set(symbol, snapshot);
        }
        return { contracts: entries.length, moreAvailable: r.more_available };
      });
    }
    await check('alpaca_limit_twenty_and_partial_page', async () => {
      const r = await call(alpaca, 'alpaca', 'option_chain', { underlying: 'AAPL', expiration: near, side: 'call', limit: 20 });
      const entries = Object.entries(r.data.snapshots);
      requireData(entries.length === 20 && r.more_available, 'page_limit_or_partial_metadata');
      for (const [symbol, snapshot] of entries) observations.push(verifySnapshot(symbol, snapshot, { underlying: 'AAPL', expiration: near, side: 'call' }));
      return { contracts: entries.length, moreAvailable: r.more_available };
    });
    await check('alpaca_queued_single_contract_snapshots', async () => {
      const keys = [...snapshots.keys()].slice(0, 3); requireData(keys.length === 3, 'missing_dependency');
      const results = await Promise.all(keys.map(contract => call(alpaca, 'alpaca', 'option_snapshots', { contracts: [contract] })));
      results.forEach((r, i) => {
        requireData(Object.keys(r.data.snapshots).length === 1 && r.data.snapshots[keys[i]], 'wrong_snapshot_identity');
        observations.push(verifySnapshot(keys[i], r.data.snapshots[keys[i]]));
      });
      return { queuedReads: results.length };
    });
    await check('alpaca_unknown_contract_no_data', () => rejection(alpaca, 'alpaca', 'option_snapshots',
      { contracts: ['ZZZZZZ' + near.replaceAll('-', '').slice(2) + 'C99999999'] }, ['no_data', 'query_failed'], true));
    for (const [name, args, expected] of [
      ['place_order', {}, ['tool_not_allowed']],
      ['option_chain', { underlying: 'AAPL', expiration: near, side: 'call', feed: 'opra' }, ['invalid_arguments']],
      ['option_chain', { underlying: 'AAPL', expiration: near, side: 'call', limit: 21 }, ['invalid_arguments']],
      ['option_chain', { underlying: 'AAPL', expiration: near, side: 'call', strike_min: 400, strike_max: 300 }, ['invalid_arguments']],
      ['option_snapshots', { contracts: [...snapshots.keys()].slice(0, 6) }, ['invalid_arguments']],
      ['option_snapshots', { contracts: ['AAPL'], url: 'https://example.invalid' }, ['invalid_arguments']],
    ]) await check(`alpaca_reject_${report.cases.length}_${name}`, () => rejection(alpaca, 'alpaca', name, args, expected));

    await withPortal('massive', async (massive, me) => {
      const matrix = report.matrix.underlyings.flatMap(underlying => ['call', 'put'].map(side => ({ underlying, side, expiration: near })));
      matrix.push(...['call', 'put'].map(side => ({ underlying: 'AAPL', side, expiration: far })));
      for (const expected of matrix) await check(`massive_reference_${expected.underlying}_${expected.expiration}_${expected.side}`, async () => {
        requireData(anchors[expected.underlying] > 0, 'missing_dependency');
        const args = { ...expected, limit: 3, strike_min: Math.floor(anchors[expected.underlying] * 0.98), strike_max: Math.ceil(anchors[expected.underlying] * 1.02) };
        const r = await call(massive, 'massive', 'option_contracts', args);
        requireData(r.data.results.length > 0 && r.data.results.length <= 3, 'invalid_reference_count');
        const standard = r.data.results.filter(c => !verifyReference(c, args).nonstandard);
        requireData(standard.length > 0, 'no_standard_contracts');
        standard.sort((a, b) => Math.abs(a.strike_price - anchors[expected.underlying]) - Math.abs(b.strike_price - anchors[expected.underlying]));
        references.set(`${expected.underlying}:${expected.side}:${expected.expiration}`, standard);
        return { contracts: r.data.results.length, standardContracts: standard.length, moreAvailable: r.more_available };
      });
      for (const underlying of report.matrix.underlyings) for (const side of ['call', 'put']) await check(`massive_daily_${underlying}_${side}`, async () => {
        const contract = selected(underlying, side);
        const r = await call(massive, 'massive', 'option_daily_bars', { contract, from, to });
        requireData(r.data.ticker === contract && r.data.adjusted === true, 'wrong_bar_contract_or_adjustment');
        const checked = verifyBars(r.data.results, from, to);
        series.set(contract, r.data.results);
        return { contract, ...checked };
      });
      await check('massive_overlapping_history_is_consistent', async () => {
        const contract = selected('AAPL', 'call'), baseline = series.get(contract); requireData(baseline, 'missing_dependency');
        const last = baseline.at(-1), date = marketDate(last.t);
        const r = await call(massive, 'massive', 'option_daily_bars', { contract, from: date, to: date });
        verifyBars(r.data.results, date, date);
        requireData(r.data.results.length === 1 && ['t', 'o', 'h', 'l', 'c', 'v'].every(k => r.data.results[0][k] === last[k]), 'historical_overlap_mismatch');
        return { contract, date, matchingFields: 6 };
      });
      await check('massive_minimum_page', async () => {
        const r = await call(massive, 'massive', 'option_contracts', { underlying: 'AAPL', expiration: near, limit: 1 });
        requireData(r.data.results.length === 1 && r.more_available, 'page_limit_or_partial_metadata');
      });
      await check('massive_unknown_underlying', () => rejection(massive, 'massive', 'option_contracts', { underlying: 'ZZZZZZ', limit: 1 }, ['no_data', 'query_failed'], true));
      await check('massive_unknown_contract', () => rejection(massive, 'massive', 'option_daily_bars',
        { contract: 'O:ZZZZZZ' + near.replaceAll('-', '').slice(2) + 'C99999999', from, to }, ['no_data', 'query_failed'], true));
      for (const [name, args, expected] of [
        ['place_order', {}, ['tool_not_allowed']],
        ['option_contracts', { underlying: 'AAPL', limit: 21 }, ['invalid_arguments']],
        ['option_contracts', { underlying: 'AAPL', strike_min: 400, strike_max: 300 }, ['invalid_arguments']],
        ['option_contracts', { underlying: 'AAPL', url: 'https://example.invalid' }, ['invalid_arguments']],
        ['option_daily_bars', { contract: 'O:AAPL' + near.replaceAll('-', '').slice(2) + 'C00350000', from, to: marketDate() }, ['invalid_arguments']],
      ]) await check(`massive_reject_${report.cases.length}_${name}`, () => rejection(massive, 'massive', name, args, expected));
      report.events.massive = [...me];
    });
    for (const underlying of report.matrix.underlyings) await check(`cross_provider_identity_${underlying}`, async () => {
      const contracts = ['call', 'put'].map(side => selected(underlying, side).slice(2));
      const r = await call(alpaca, 'alpaca', 'option_snapshots', { contracts });
      requireData(Object.keys(r.data.snapshots).length === contracts.length, 'incomplete_cross_provider_contracts');
      for (const symbol of contracts) {
        requireData(r.data.snapshots[symbol], 'cross_provider_contract_missing');
        observations.push(verifySnapshot(symbol, r.data.snapshots[symbol], { underlying, expiration: near }));
      }
      return { contracts: contracts.length, comparison: 'same OCC identity; prices/feed times deliberately not equated' };
    });
    const status = await call(alpaca, 'alpaca', 'portal_status', {}, false);
    report.portalObservations = status.observations;
    report.events.alpaca = [...ae];
  });
  await withPortal('marketdata', async client => {
    await check('aapl_historical_cross_vendor_observation', async () => {
      const contract = selected('AAPL', 'call'), bars = series.get(contract); requireData(bars?.length, 'missing_dependency');
      const bar = bars.at(-1), date = marketDate(bar.t);
      const r = await call(client, 'marketdata', 'option_quote', { contract: contract.slice(2), date });
      requireData(r.mode === 'historical' && r.data.optionSymbol[0] === contract.slice(2), 'wrong_historical_identity');
      const quoteDay = marketDate(r.data.updated[0] * 1000);
      requireData(quoteDay === date && Number.isFinite(r.data.last[0]) && r.data.last[0] >= 0, 'wrong_historical_date_or_price');
      const observation = { contract, date, massiveQualifiedTradeClose: bar.c, marketdataSnapshotLast: r.data.last[0],
        difference: r.data.last[0] - bar.c, priceAccuracyBenchmark: false };
      report.comparisons.push(observation);
      return observation;
    });
  });
  report.processCleanup = 'pass';
} catch (error) {
  report.fatal = error.kind ?? 'verification_or_cleanup_failure';
  process.exitCode = 1;
} finally {
  report.finishedAt = new Date().toISOString();
  report.counts = Object.fromEntries(['pass', 'fail', 'blocked'].map(s => [s, report.cases.filter(c => c.status === s).length]));
  report.snapshotSummary = summarizeSnapshots(observations);
  report.limitations = ['Indicative quotes are modified and trades delayed; no executable NBBO claim.',
    'Greek/IV availability is measured; calculation times and numerical accuracy are not established.',
    'Daily trade aggregates and historical quote snapshots are distinct; comparison is descriptive.',
    'Partial pages are explicit; no full-chain or all-market coverage claim.',
    'Isolated-live and offline results do not establish scheduled-session or host-rollout acceptance.'];
  report.status = report.fatal || report.counts.fail ? 'fail' : report.counts.blocked ? 'partial' : 'pass';
  if (report.status !== 'pass') process.exitCode = report.status === 'partial' ? 2 : 1;
  // The report must remain free of any known key, including unexpected provider echoes.
  for (const provider of ['alpaca', 'massive', 'finnhub']) {
    const credentials = JSON.parse(await readFile(path.join(STATE, 'credentials', `${provider}.json`), 'utf8'));
    for (const secret of Object.values(credentials)) requireData(!JSON.stringify(report).includes(secret), 'secret_in_verification_report');
  }
  await checkpoint();
  process.stdout.write(JSON.stringify({ status: report.status, counts: report.counts, dataCalls: report.dataCalls,
    snapshotSummary: report.snapshotSummary, report: location }) + '\n');
}
