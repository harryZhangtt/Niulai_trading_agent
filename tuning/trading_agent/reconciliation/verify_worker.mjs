// Offline exact-source worker verification. No network, credentials or real store.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';

const ROOT = process.cwd();
const OUT = path.join(ROOT, 'tuning/trading_agent/reconciliation/.runtime');
fs.mkdirSync(OUT, { recursive: true, mode: 0o700 });
const TARGET = path.join(ROOT, '.niulai-state/reports/trading-agent-smoke/53cbbf3b-1c8f-48c8-af34-f621bec276d6/owner-source-supported/.sites-checkout/worker/index.js');
const EXPECTED = 'ed1b7a20b85b2444dd30039c94e67cc9594e6a7923c00b689b312b9193172ac0';
const SOURCE = fs.readFileSync(TARGET, 'utf8');
const sha = value => createHash('sha256').update(value).digest('hex');
assert.equal(sha(SOURCE), EXPECTED);
const NOW = 1700000000000;
const COMMIT = '11111111-1111-4111-8111-111111111111';
const LEASE = '22222222-2222-4222-8222-222222222222';
const OTHER = '33333333-3333-4333-8333-333333333333';
const results = [], mutations = [], observations = [];
let invocations = 0, noWriteChecks = 0, noWriteFailures = 0;
const clone = value => JSON.parse(JSON.stringify(value));

function row(options = {}) {
  return { schema: 1, revision: 7, cipher: null, committed_at: '2023-11-14T22:00:00.000Z',
    lease: { id: LEASE, until: NOW + 10000 }, last_commit: COMMIT, ...options };
}

function fixture(initial = row(), { allowWrites = false, readError = false, source = SOURCE } = {}) {
  const state = { row: clone(initial), reads: 0, writes: [], clock: NOW };
  class ClockDate extends Date { static now() { return state.clock; } }
  const sandbox = { Date: ClockDate, URL, TextEncoder, TextDecoder, Response, btoa, atob, crypto: globalThis.crypto };
  assert.equal(source.split('export default').length, 2);
  vm.runInNewContext(source.replace('export default', 'globalThis.worker ='), sandbox, { timeout: 1000 });
  const env = { VAULT_KEY: 'SYNTHETIC-CONFIGURATION-NOT-A-CREDENTIAL', BUCKET: {
    async get() {
      state.reads += 1;
      if (readError) throw new Error('SYNTHETIC-SECRET-ERROR-CANARY');
      return { etag: 'synthetic-etag', async json() { return clone(state.row); } };
    },
    async put(key, value, options) {
      state.writes.push({ key, options: clone(options ?? {}), value_sha256: sha(value) });
      if (!allowWrites) throw new Error('OFFLINE_WRITE_TRAP');
      state.row = JSON.parse(value);
      return { etag: 'synthetic-next-etag' };
    },
  } };
  return { state, env, async request(method, route, body, headers = {}) {
    invocations += 1;
    const request = new Request(`https://fixture.invalid${route}`, { method, headers,
      ...(method === 'GET' ? {} : { body: typeof body === 'string' ? body : JSON.stringify(body) }) });
    const response = await sandbox.worker.fetch(request, env);
    return { status: response.status, body: await response.json() };
  } };
}

async function noWrite(f, action) {
  const before = JSON.stringify(f.state.row), attempts = f.state.writes.length;
  const result = await action();
  noWriteChecks += 1;
  try {
    assert.equal(f.state.writes.length, attempts, 'storage mutation attempted');
    assert.equal(JSON.stringify(f.state.row), before, 'durable state changed');
  } catch (error) { noWriteFailures += 1; throw error; }
  return result;
}

async function run(id, criterion, action) {
  try { await action(); results.push({ id, criterion, status: 'PASS' }); }
  catch (error) { results.push({ id, criterion, status: 'FAIL', error: 'EXPECTATION_FAILED' }); }
}

function observe(id, value) {
  // Response examples contain only synthetic scalar status/flags; no stored row.
  observations.push({ id, response: value });
}

for (const [name, state] of [
  ['empty', row({ revision: 0, lease: null, cipher: null, last_commit: null })],
  ['active', row()], ['expired', row({ lease: { id: LEASE, until: NOW - 1 } })],
  ['at_expiry', row({ lease: { id: LEASE, until: NOW } })], ['released', row({ lease: null })],
  ['opaque_profile', row({ cipher: { iv: 'opaque', data: 'opaque' } })],
]) {
  await run(`W-HEALTH-${name}`, 'REC-W-001', async () => {
    const f = fixture(state);
    const response = await noWrite(f, () => f.request('GET', '/health'));
    assert.equal(response.status, 200);
    assert.equal(response.body.lease_busy, Boolean(state.lease && state.lease.until > NOW));
    assert.equal(response.body.revision, state.revision);
    assert.equal(response.body.initialized, Boolean(state.cipher));
    observe(`health-${name}`, response);
  });
}

for (const [name, state] of [
  ['active', row()], ['expired', row({ lease: { id: LEASE, until: NOW - 1 } })],
  ['no_lease', row({ lease: null })], ['newer_lease', row({ lease: { id: OTHER, until: NOW + 20000 } })],
]) {
  await run(`W-MATCH-${name}`, 'REC-W-002', async () => {
    const f = fixture(state);
    const response = await noWrite(f, () => f.request('POST', '/lease/checkpoint', { commit_id: COMMIT, lease_id: LEASE }));
    assert.deepEqual(response, { status: 200, body: { committed: true, revision: state.revision, idempotent: true, released: !state.lease } });
    observe(`match-${name}`, response);
  });
}

for (const [name, state, body] of [
  ['wrong_commit_active', row(), { commit_id: OTHER, lease_id: LEASE }],
  ['wrong_commit_expired', row({ lease: { id: LEASE, until: NOW - 1 } }), { commit_id: OTHER, lease_id: LEASE }],
  ['absent_commit', row({ last_commit: null }), { commit_id: COMMIT, lease_id: LEASE }],
  ['absent_commit_no_lease', row({ last_commit: null, lease: null }), { commit_id: COMMIT, lease_id: LEASE }],
  ['invalid_commit', row(), { commit_id: 'not-an-id', lease_id: LEASE }],
  ['missing_commit', row(), { lease_id: LEASE }],
  ['null_body', row(), null], ['malformed_json', row(), '{broken'],
]) {
  await run(`W-REJECT-${name}`, 'REC-W-003', async () => {
    const f = fixture(state);
    const response = await noWrite(f, () => f.request('POST', '/lease/checkpoint', body));
    assert.notEqual(response.body.committed, true);
    assert.ok(response.status >= 400);
    observe(`reject-${name}`, response);
  });
}

// Frozen inverse deliberately retained: the source does not bind lease_id in its
// idempotent branch. These must report FAIL, while no-write checks still pass.
for (const [name, body] of [
  ['wrong_lease', { commit_id: COMMIT, lease_id: OTHER }], ['missing_lease', { commit_id: COMMIT }],
]) {
  await run(`W-TUPLE-${name}`, 'REC-W-003', async () => {
    const f = fixture();
    const response = await noWrite(f, () => f.request('POST', '/lease/checkpoint', body));
    observe(`tuple-${name}`, response);
    assert.notEqual(response.body.committed, true, 'matching commit incorrectly treated as lease-bound recognition');
  });
}

await run('W-REPEAT-CONCURRENT', 'REC-W-002', async () => {
  const f = fixture();
  const responses = await noWrite(f, () => Promise.all(Array.from({ length: 8 }, () =>
    f.request('POST', '/lease/checkpoint', { commit_id: COMMIT, lease_id: LEASE }))));
  assert.ok(responses.every(response => response.body.idempotent === true));
});
await run('W-READ-FAILURE', 'REC-W-004', async () => {
  const f = fixture(row(), { readError: true });
  const response = await noWrite(f, () => f.request('GET', '/health'));
  assert.deepEqual(response, { status: 503, body: { error: 'STORE_OPERATION_FAILED' } });
});
await run('W-CROSS-ORIGIN', 'REC-W-004', async () => {
  const f = fixture();
  const response = await noWrite(f, () => f.request('GET', '/health', undefined, { Origin: 'https://other.invalid' }));
  assert.equal(response.status, 403);
});
await run('W-METHOD', 'REC-W-004', async () => {
  const f = fixture();
  const response = await noWrite(f, () => f.request('GET', '/lease/checkpoint'));
  assert.equal(response.status, 405);
});
await run('W-EXPIRED-ACQUIRE-WRITES', 'REC-W-005', async () => {
  const initial = row({ lease: { id: LEASE, until: NOW - 1 } });
  const f = fixture(initial, { allowWrites: true });
  const response = await f.request('POST', '/lease/acquire', { request_id: LEASE });
  assert.equal(response.status, 200);
  assert.equal(f.state.writes.length, 1);
  assert.equal(f.state.row.revision, initial.revision + 1);
  assert.equal(f.state.row.lease.id, LEASE);
  assert.equal(f.state.row.lease.until, NOW + 600000);
  f.state.clock = NOW + 600001;
  await f.request('POST', '/lease/acquire', { request_id: LEASE });
  assert.equal(f.state.writes.length, 2);
  assert.equal(f.state.row.revision, initial.revision + 2);
  assert.equal(f.state.row.lease.until, f.state.clock + 600000);
});
await run('W-ACTIVE-ACQUIRE-READONLY-CONTROL', 'REC-W-005', async () => {
  const f = fixture();
  const response = await noWrite(f, () => f.request('POST', '/lease/acquire', { request_id: LEASE }));
  assert.equal(response.status, 200);
});

async function breakControl(id, old, replacement, control) {
  assert.equal(SOURCE.split(old).length, 2, 'mutation anchor must be unique');
  await control(SOURCE);
  try { await control(SOURCE.replace(old, replacement)); mutations.push({ id, status: 'SURVIVED' }); }
  catch { mutations.push({ id, status: 'KILLED' }); }
}

const normalNoWriteFailures = noWriteFailures;
const normalNoWriteChecks = noWriteChecks;

await breakControl('MUT-W-HEALTH-WRITE', 'const {row}=await read(env);return reply',
  'const {row}=await read(env);await env.BUCKET.put(OBJECT,JSON.stringify(row));return reply', async source => {
    const f = fixture(row(), { source });
    await noWrite(f, () => f.request('GET', '/health'));
  });
await breakControl('MUT-W-CHECKPOINT-WRITE', 'validateProfile(body.profile);',
  'await env.BUCKET.put(OBJECT,JSON.stringify(row));validateProfile(body.profile);', async source => {
    const f = fixture(row(), { source });
    await noWrite(f, () => f.request('POST', '/lease/checkpoint', { commit_id: OTHER, lease_id: LEASE }));
  });
await breakControl('MUT-W-FALSE-ACK', 'if(row.last_commit===body.commit_id)', 'if(body.commit_id)', async source => {
  const f = fixture(row(), { source });
  const response = await noWrite(f, () => f.request('POST', '/lease/checkpoint', { commit_id: OTHER, lease_id: LEASE }));
  assert.notEqual(response.body.committed, true);
});
await breakControl('MUT-W-ACQUIRE-PERMANENT-DEDUP', 'if(row.lease && row.lease.until>now)',
  'if(row.lease && row.lease.id===body.request_id)', async source => {
    const f = fixture(row({ lease: { id: LEASE, until: NOW - 1 } }), { source, allowWrites: true });
    await f.request('POST', '/lease/acquire', { request_id: LEASE });
    assert.equal(f.state.writes.length, 1);
    assert.equal(f.state.row.lease.until, NOW + 600000);
  });

const sourceAfter = sha(fs.readFileSync(TARGET));
const report = {
  revision: 'trading-reconciliation-v1.0', source_sha256: EXPECTED,
  supplied_and_local_head_commit: 'ce58b639c137abda72f0bdea65118300355f4478',
  source_stable: sourceAfter === EXPECTED, criteria_sha256: sha(fs.readFileSync(path.join(ROOT, 'tuning/trading_agent/reconciliation/ACCEPTANCE.md'))),
  executed: results.length, passed: results.filter(x => x.status === 'PASS').length,
  failed: results.filter(x => x.status === 'FAIL').length, skipped: 0, tests: results,
  handler_invocations: invocations, mutations, mutations_killed: mutations.filter(x => x.status === 'KILLED').length,
  expected_inverse_findings: ['W-TUPLE-wrong_lease', 'W-TUPLE-missing_lease'],
  no_write_test_scope: 'GET health; checkpoint with no profile/release; normal source only',
  no_write_checks: normalNoWriteChecks, no_write_failures: normalNoWriteFailures,
  no_write_scope_status: normalNoWriteFailures === 0 && results.every(x => x.status === 'PASS' || x.id.startsWith('W-TUPLE-')) ? 'PASS' : 'FAIL',
  no_write_observation: 'All normal-source health/minimal-checkpoint fixtures attempted zero writes; injected writes were detected.',
  tuple_binding_status: 'FAIL: Worker idempotence tests commit_id only, not lease_id.',
  response_semantics: observations,
  acquire_classification: 'Write-capable after expiry even for original request_id; exercised only in isolated fake store.',
  isolation: 'No network/native/live calls, credentials, real leases, fence/profile changes or source edits.',
  platform_authentication: 'NOT RUN: enforced outside worker by Sites platform; direct fake handler cannot attest deployment authorization.',
  major_scheduled_business_email_acceptance: 'UNVERIFIED',
  node_version: process.version, harness_sha256: sha(fs.readFileSync(new URL(import.meta.url))),
};
const target = path.join(OUT, `worker-proof-${Date.now()}.json`);
fs.writeFileSync(target, JSON.stringify(report, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
console.log(JSON.stringify({ evidence: path.relative(ROOT, target), executed: report.executed, passed: report.passed,
  failed: report.failed, skipped: 0, mutations_killed: report.mutations_killed, source_stable: report.source_stable,
  no_write_scope: report.no_write_scope_status, tuple_binding: 'FAIL' }));
process.exitCode = report.failed || report.mutations.some(x => x.status !== 'KILLED') || !report.source_stable ? 1 : 0;
