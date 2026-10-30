// Small, provider-neutral timing summaries. No request payloads or append-only logs.
import { readFile, stat, mkdir, writeFile, rename, rm } from 'node:fs/promises';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

export class OperationStats {
  constructor({ provider, file, hardTimeoutMs = 20000, now = Date.now }) {
    this.provider = provider;
    this.file = file;
    this.hardTimeoutMs = hardTimeoutMs;
    this.now = now;
    this.operations = Object.create(null);
    this.queue = { observations: 0, meanWaitMs: 0, maxDepth: 0 };
  }
  async load() {
    if (!this.file) return;
    try {
      if ((await stat(this.file)).size > 65536) return;
      const value = JSON.parse(await readFile(this.file, 'utf8'));
      if (value.version !== 1 || value.provider !== this.provider) return;
      for (const [name, item] of Object.entries(value.operations ?? {}).slice(0, 64)) {
        if (!/^[a-z_]{1,80}$/.test(name) || !item || this.now() - item.lastObservedAt > 86400000
          || item.lastObservedAt > this.now() || !Number.isFinite(item.lastObservedAt)) continue;
        if (!['successes', 'meanMs', 'deviationMs', 'budgetMs', 'failures', 'timeouts', 'lastSuccessAt', 'lastObservedAt']
          .every(key => Number.isFinite(item[key]) && item[key] >= 0 && item[key] <= Number.MAX_SAFE_INTEGER)) continue;
        this.operations[name] = {
          successes: Math.min(item.successes, 1000000), meanMs: Math.min(item.meanMs, 120000),
          deviationMs: Math.min(item.deviationMs, 120000),
          budgetMs: Math.min(this.hardTimeoutMs, Math.max(this.floorMs(), item.budgetMs)),
          failures: Math.min(item.failures, 1000000), timeouts: Math.min(item.timeouts, 1000000),
          lastSuccessAt: item.lastSuccessAt, lastObservedAt: item.lastObservedAt,
        };
      }
    } catch { /* Missing or corrupt diagnostics cannot prevent MCP startup. */ }
  }
  floorMs() { return Math.min(3000, this.hardTimeoutMs); }
  record(name, { durationMs, outcome = 'success' }) {
    if (!/^[a-z_]{1,80}$/.test(name) || !Number.isFinite(durationMs) || durationMs < 0) return;
    if (!this.operations[name] && Object.keys(this.operations).length >= 64) return;
    const value = this.operations[name] ??= { successes: 0, failures: 0, timeouts: 0,
      meanMs: 0, deviationMs: 0, budgetMs: this.hardTimeoutMs, lastSuccessAt: 0, lastObservedAt: 0 };
    value.lastObservedAt = this.now();
    if (outcome !== 'success') {
      value.failures = Math.min(1000000, value.failures + 1);
      if (outcome === 'timeout') value.timeouts = Math.min(1000000, value.timeouts + 1);
      return; // Timeouts are censored observations, never healthy latency samples.
    }
    const elapsed = Math.min(durationMs, 120000);
    if (value.successes === 0 || this.now() - value.lastSuccessAt > 86400000) {
      value.successes = 0; value.meanMs = elapsed; value.deviationMs = elapsed / 2;
      value.budgetMs = this.hardTimeoutMs;
    } else {
      value.deviationMs = 0.75 * value.deviationMs + 0.25 * Math.abs(elapsed - value.meanMs);
      value.meanMs = 0.8 * value.meanMs + 0.2 * elapsed;
    }
    value.successes = Math.min(1000000, value.successes + 1);
    value.lastSuccessAt = this.now();
    if (value.successes >= 8) {
      const target = value.meanMs + 4 * value.deviationMs + 500;
      // Increase promptly on measured slowness; decrease by at most 25% per success.
      value.budgetMs = Math.ceil(Math.min(this.hardTimeoutMs,
        Math.max(this.floorMs(), target, value.budgetMs * 0.75)));
    }
  }
  recordQueue(waitMs, depth) {
    this.queue.observations++;
    this.queue.meanWaitMs += (Math.max(0, waitMs) - this.queue.meanWaitMs) / this.queue.observations;
    this.queue.maxDepth = Math.max(this.queue.maxDepth, depth);
  }
  timeoutFor(name) {
    const value = this.operations[name];
    return value?.successes >= 8 && this.now() - value.lastSuccessAt <= 86400000
      ? value.budgetMs : this.hardTimeoutMs;
  }
  summary() {
    return { queue: { ...this.queue }, operations: structuredClone(this.operations),
      timeoutPolicy: 'successful-latency EWMA + 4 deviations + 500 ms; 8-sample minimum; hard cap',
      crossProcessCoordination: false };
  }
  async save() {
    if (!this.file) return;
    await mkdir(path.dirname(this.file), { recursive: true, mode: 0o700 });
    const temporary = `${this.file}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, JSON.stringify({ version: 1, provider: this.provider,
        operations: this.operations }), { mode: 0o600, flag: 'wx' });
      await rename(temporary, this.file);
    } finally { await rm(temporary, { force: true }); }
  }
}
