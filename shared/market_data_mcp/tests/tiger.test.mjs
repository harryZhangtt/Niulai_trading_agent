import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { QueryPortal } from '../core/portal.mjs';
import { TIGER_TOOLS, tigerTransport, runTigerWorker } from '../adapters/tiger.mjs';


const SAMPLE_SELECTION = JSON.parse(readFileSync(new URL('../../../mentor/runtime/probabilistic-manifold-leverage-20261107/evidence/market-pilot-sample-selection-20261110-v1/sample-selection-v1.json', import.meta.url), 'utf8'));
function canonical(value) {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
function digest(value) { return createHash('sha256').update(canonical(value)).digest('hex'); }

const success = { status: 'queried', tool: 'snapshot', source_read_status: 'complete',
  committed: true, release_requested: true, mode: 'query', source: 'existing_owner_private_store',
  files: ['holdings.json', 'assets.json', 'query.json'], holdings_read: true, assets_read: true, holdings_count: 2 };
function fixture(t, execute) {
  const receipts = [];
  const portal = new QueryPortal({ provider: 'tiger', allowedTools: TIGER_TOOLS.map(x => x.name),
    policy: { maxAttempts: 1, timeoutMs: 100, totalTimeoutMs: 500 },
    transportFactory: () => tigerTransport({ site: { synthetic_secret: 'do-not-echo' } },
      { execute, onReceipt: r => receipts.push(r) }) });
  t.after(() => portal.close());
  return { portal, receipts };
}

test('discovery is network-free; writes and invalid arguments never acquire credentials', async t => {
  let calls = 0;
  const { portal } = fixture(t, () => { calls++; return success; });
  assert.equal((await portal.listTools()).tools.length, 4);
  for (const [name, args] of [['place_order', {}], ['positions', { account: 'other' }],
    ['assets', { security_types: ['STK'] }], ['positions', { security_types: [] }],
    ['positions', { security_types: ['STK', 'STK'] }]]) {
    assert.equal((await portal.callTool(name, args)).isError, true);
  }
  assert.equal(calls, 0);
});

test('portal uses one isolated leased read and exposes only the safe receipt', async t => {
  let calls = 0;
  const { portal, receipts } = fixture(t, async context => {
    calls++;
    assert.equal(context.site.synthetic_secret, 'do-not-echo');
    assert.deepEqual(context.query, { tool: 'snapshot', arguments: { security_types: ['STK'] } });
    return success;
  });
  const result = await portal.callTool('snapshot', { security_types: ['STK'] });
  assert.equal(result.isError, false);
  assert.equal(calls, 1);
  assert.equal(receipts.length, 1);
  assert.equal(JSON.stringify(result).includes('do-not-echo'), false);
});

test('uncertain worker or checkpoint is never retried or called authorization expiry', async t => {
  for (const failure of [new Error('HTTP 503 Bearer synthetic-secret'),
    { status: 'failed', error: 'STORE_COMMIT_UNCONFIRMED', reconciliation_required: true }]) {
    let calls = 0;
    const { portal, receipts } = fixture(t, async () => {
      calls++;
      if (failure instanceof Error) throw failure;
      return failure;
    });
    const result = await portal.callTool('snapshot');
    assert.equal(result.isError, true);
    assert.equal(calls, 1);
    assert.equal(receipts[0].reconciliation_required, true);
    assert.equal(JSON.stringify({ result, receipts }).includes('synthetic-secret'), false);
    assert.equal(JSON.stringify(result).includes('auth_required'), false);
  }
});

function subprocessFixture(source, onChild = () => {}) {
  return (command, args, options) => {
    assert.match(command, /\.niulai-state\/\.venv\/bin\/python$/);
    assert.deepEqual(args, ['-m', 'shared.tiger.worker']);
    assert.equal(options.stdio[2], 'ignore');
    assert.equal(JSON.stringify({ args, env: options.env }).includes('stdin-only-synthetic-secret'), false);
    const child = spawn(process.execPath, ['-e', source], options);
    onChild(child);
    return child;
  };
}

test('worker context travels by pipe; extra stdout fields and stderr never escape', async () => {
  const source = `let raw=''; process.stdin.on('data', x=>raw+=x); process.stdin.on('end',()=>{
    if(JSON.parse(raw).site.secret!=='stdin-only-synthetic-secret') process.exit(1);
    console.error('stderr-synthetic-secret');
    console.log(JSON.stringify({...${JSON.stringify(success)}, secret:'stdout-synthetic-secret'})); });`;
  const result = await runTigerWorker({ site: { secret: 'stdin-only-synthetic-secret' } },
    { spawnImpl: subprocessFixture(source), timeoutMs: 2000 });
  assert.equal(result.status, 'queried');
  assert.equal(JSON.stringify(result).includes('secret'), false);
});

test('worker nonzero exit and malformed output fail without exposing output', async () => {
  for (const source of [`console.log('malformed-synthetic-secret')`,
    `console.log(${JSON.stringify(JSON.stringify(success))}); process.exitCode=1`]) {
    await assert.rejects(runTigerWorker({}, { spawnImpl: subprocessFixture(source), timeoutMs: 2000 }),
      error => error.kind === 'invalid_response' && !String(error).includes('secret'));
  }
});

test('timeout terminates the actual child and waits for process cleanup', async () => {
  let child;
  const started = Date.now();
  await assert.rejects(runTigerWorker({}, { timeoutMs: 60,
    spawnImpl: subprocessFixture('setInterval(()=>{},1000)', c => { child = c; }) }),
    error => error.kind === 'timeout');
  assert.ok(Date.now() - started < 2500);
  assert.ok(child.exitCode !== null || child.signalCode !== null);
  assert.throws(() => process.kill(child.pid, 0), { code: 'ESRCH' });
});

test('oversized context and already-cancelled requests never spawn a worker', async () => {
  let calls = 0;
  const spawnImpl = () => { calls++; throw new Error('must not spawn'); };
  await assert.rejects(runTigerWorker({ site: 'x'.repeat(1024 * 1024) }, { spawnImpl }),
    error => error.kind === 'invalid_arguments');
  await assert.rejects(runTigerWorker({}, { spawnImpl, signal: AbortSignal.abort() }),
    error => error.kind === 'timeout');
  assert.equal(calls, 0);
});


function marketArgs() {
  const selection = structuredClone(SAMPLE_SELECTION);
  return { as_of: '2020-12-31T23:59:59Z', authorization_id: 'mpa_' + '1'.repeat(32), authorization_sha256: 'e'.repeat(64), corporate_action_start: '2020-01-01',
    corporate_actions: ['split'], contract: { calibration_sha256: 'a'.repeat(64), promotion_sha256: 'b'.repeat(64), roster_sha256: selection.roster.packet.sha256, sample_selection_sha256: digest(selection) },
    fields: { briefs: ['latest_price'], stock_fundamental: ['market_cap'], financial_daily: ['shares_outstanding'], financial_report: ['net_income'] },
    fx_currencies: ['USD'], sample_selection: selection, symbols: structuredClone(selection.cohorts.calibration.query_symbol_records) };
}

test('market snapshot is fixed-schema and receipt contains hashes not values', async t => {
  let calls = 0;
  const marketSuccess = { status: 'queried', tool: 'market_snapshot', source_read_status: 'complete', committed: true,
    release_requested: true, mode: 'query', source: 'existing_owner_private_store',
    files: ['market_raw.json', 'market_manifest.json', 'market_query.json'], symbols_count: 1,
    method_counts: { briefs: 1 }, response_sha256: { briefs: 'a'.repeat(64) },
    authorization_id: 'mpa_' + '1'.repeat(32), authorization_sha256: 'e'.repeat(64), authorization_status: 'consumed',
    authorization_path: '/private/secret', secret: 'bearer-secret' };
  const { portal } = fixture(t, async context => { calls++; assert.equal(context.query.tool, 'market_snapshot'); return marketSuccess; });
  const result = await portal.callTool('market_snapshot', marketArgs());
  assert.equal(result.isError, false); assert.equal(calls, 1);
  assert.equal(JSON.stringify(result).includes('AAPL'), false); assert.equal(JSON.stringify(result).includes('123.45'), false);
  assert.equal(JSON.stringify(result).includes('/private/secret'), false); assert.equal(JSON.stringify(result).includes('bearer-secret'), false);
  assert.equal(result.content[0].text.includes('mpa_' + '1'.repeat(32)), true);
  const mutations = [a => { a.provider = 'yahoo'; }, a => { a.account = 'x'; }, a => { a.url = 'https://attacker.test'; },
    a => { a.fields.financial_report = ['arbitrary']; }, a => { a.authorization_id = '../private/path'; }, a => { a.authorization_path = '/secret'; },
    a => { a.symbols = structuredClone(a.sample_selection.cohorts.reserved_promotion.query_symbol_records); },
    a => { a.symbols.reverse(); }, a => { a.sample_selection.builder.path = 'modified'; },
    a => { a.contract.sample_selection_sha256 = '0'.repeat(64); },
    a => { a.sample_selection.cohorts.calibration.cohort_sha256 = '0'.repeat(64); },
    a => { a.sample_selection.cohorts.calibration.ordered_query_symbols_sha256 = '0'.repeat(64); },
    a => { const p = structuredClone(a.sample_selection.cohorts.reserved_promotion); p.cohort_id = 'calibration'; a.sample_selection.cohorts.calibration = p; a.symbols = structuredClone(p.query_symbol_records); a.contract.sample_selection_sha256 = digest(a.sample_selection); },
    a => { a.symbols[0].roster_row_sha256 = '0'.repeat(64); }, a => { a.sample_selection.extra = true; },
    a => { a.sample_selection = 'malformed'; }, a => { a.sample_selection.builder.path = 'x'.repeat(300000); }];
  for (const mutation of mutations) {
    const args = marketArgs(); mutation(args); assert.equal((await portal.callTool('market_snapshot', args)).isError, true);
  }
  assert.equal(calls, 1);
});
