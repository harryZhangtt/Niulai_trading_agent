import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { QueryPortal } from '../core/portal.mjs';
import { TIGER_TOOLS, tigerTransport, runTigerWorker } from '../adapters/tiger.mjs';

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
  assert.equal((await portal.listTools()).tools.length, 3);
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
