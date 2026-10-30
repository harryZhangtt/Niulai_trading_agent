import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile, stat } from 'node:fs/promises';
import path from 'node:path';
import { OperationStats } from '../core/observations.mjs';
import { STATE } from '../providers.mjs';

test('learns bounded per-operation timeouts only from enough healthy samples', () => {
  const stats = new OperationStats({ provider: 'any-provider' });
  for (let sample = 0; sample < 7; sample++) stats.record('quote', { durationMs: 100 });
  assert.equal(stats.timeoutFor('quote'), 20000);
  stats.record('quote', { durationMs: 100 });
  assert.equal(stats.timeoutFor('quote'), 15000); // No sudden drop to a small value.
  assert.equal(stats.timeoutFor('history'), 20000); // Operations remain isolated.
  for (let sample = 0; sample < 30; sample++) stats.record('quote', { durationMs: 100 });
  assert.equal(stats.timeoutFor('quote'), 3000);
  stats.record('quote', { durationMs: 18000 });
  assert.ok(stats.timeoutFor('quote') > 3000 && stats.timeoutFor('quote') <= 20000);
});

test('timeouts and queue pressure never become healthy provider-latency samples', () => {
  const stats = new OperationStats({ provider: 'any-provider' });
  for (let sample = 0; sample < 8; sample++) stats.record('quote', { durationMs: 100 });
  const budget = stats.timeoutFor('quote');
  for (let sample = 0; sample < 20; sample++) stats.record('quote', { durationMs: 20000, outcome: 'timeout' });
  stats.recordQueue(45000, 16);
  assert.equal(stats.timeoutFor('quote'), budget);
  assert.equal(stats.summary().operations.quote.successes, 8);
  assert.equal(stats.summary().operations.quote.timeouts, 20);
  assert.equal(stats.summary().queue.meanWaitMs, 45000);
});

test('old observations expire and a bounded atomic summary survives clean restart', async t => {
  const parent = path.join(STATE, 'runtime');
  await mkdir(parent, { recursive: true });
  const directory = await mkdtemp(path.join(parent, 'stats-test-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'summary.json');
  let now = 100000000;
  const stats = new OperationStats({ provider: 'arbitrary-provider', file, now: () => now });
  for (let sample = 0; sample < 8; sample++) stats.record('quote', { durationMs: 200 });
  stats.record('history', { durationMs: 5000, outcome: 'connection_lost' });
  await stats.save();
  assert.equal((await stat(file)).mode & 0o777, 0o600);
  const resumed = new OperationStats({ provider: 'arbitrary-provider', file, now: () => now });
  await resumed.load();
  assert.equal(resumed.timeoutFor('quote'), stats.timeoutFor('quote'));
  assert.equal(resumed.summary().operations.history.failures, 1);
  now += 86400001;
  assert.equal(resumed.timeoutFor('quote'), 20000);
  const stale = new OperationStats({ provider: 'arbitrary-provider', file, now: () => now });
  await stale.load();
  assert.deepEqual(Object.keys(stale.operations), []);
});

test('corrupt, oversized and cross-provider summaries cannot block startup or tune timeouts', async t => {
  const directory = await mkdtemp(path.join(STATE, 'runtime/stats-invalid-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'summary.json');
  const stats = new OperationStats({ provider: 'test', file });
  for (const content of ['broken-json', 'x'.repeat(70000), JSON.stringify({ version: 1, provider: 'other', operations: {} })]) {
    await writeFile(file, content);
    await stats.load();
    assert.equal(stats.timeoutFor('quote'), 20000);
  }
  for (let index = 0; index < 100; index++) stats.record('tool_' + 'a'.repeat(index + 1), { durationMs: 1 });
  assert.ok(Object.keys(stats.operations).length <= 64);
});
