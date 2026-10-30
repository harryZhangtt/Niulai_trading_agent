import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { setTimeout as sleep } from 'node:timers/promises';
import { PortalError, classify, checkResult, publicFailure, TRANSIENT, RECONNECT } from './errors.mjs';

export const DEFAULT_POLICY = Object.freeze({
  maxAttempts: 3, timeoutMs: 20000, totalTimeoutMs: 65000,
  baseDelayMs: 500, maxDelayMs: 5000, maxPending: 16,
  circuitThreshold: 3, circuitCooldownMs: 30000,
  retryQuota: 4,
});

export function validatePolicy(policy) {
  for (const key of Object.keys(DEFAULT_POLICY)) {
    if (!Number.isSafeInteger(policy[key]) || policy[key] < 1) throw new Error(`Invalid portal policy: ${key}`);
  }
  if (policy.maxAttempts > 5 || policy.totalTimeoutMs > 120000 || policy.timeoutMs > policy.totalTimeoutMs) {
    throw new Error('Portal timeout or retry limits exceeded');
  }
  return policy;
}

export class QueryPortal {
  constructor({ provider, allowedTools, toolMap = {}, transportFactory, policy = {}, log = () => {}, observations,
    clientFactory = () => new Client({ name: 'market-data-portal', version: '1.0.0' }),
    wait = (ms, signal) => sleep(ms, undefined, { signal }), random = Math.random }) {
    this.provider = provider;
    this.allowed = new Set(allowedTools);
    this.toolMap = Object.fromEntries(allowedTools.map(name => [name, toolMap[name] ?? name]));
    this.aliases = new Map(Object.entries(this.toolMap).map(([alias, upstream]) => [upstream, alias]));
    this.transportFactory = transportFactory;
    this.clientFactory = clientFactory;
    this.policy = validatePolicy({ ...DEFAULT_POLICY, ...policy });
    this.observations = observations;
    this.retryTokens = this.policy.retryQuota;
    this.log = log;
    this.wait = wait;
    this.random = random;
    this.client = null;
    this.tools = null;
    this.tail = Promise.resolve();
    this.pending = 0;
    this.closed = false;
    this.failureCount = 0;
    this.openUntil = 0;
    this.lastSuccessAt = null;
    this.lastFailure = null;
  }

  async disconnect() {
    const client = this.client;
    this.client = null;
    this.tools = null;
    if (client) await client.close().catch(() => {});
  }

  async close() {
    this.closed = true;
    await this.disconnect();
    try { await this.observations?.save(); }
    catch { this.log({ event: 'observations_write_failed', provider: this.provider }); }
  }

  status() {
    return {
      provider: this.provider,
      connection: this.closed ? 'closed' : this.client && this.tools ? 'connected' : 'not_connected',
      circuit: Date.now() < this.openUntil ? 'open' : this.openUntil ? 'half_open' : 'closed',
      retryAt: Date.now() < this.openUntil ? new Date(this.openUntil).toISOString() : null,
      pending: this.pending, lastSuccessAt: this.lastSuccessAt, lastFailure: this.lastFailure,
      policy: this.policy,
      retryTokens: this.retryTokens,
      observations: this.observations?.summary() ?? null,
    };
  }

  async connect(signal) {
    if (this.client && this.tools) return this.client;
    const client = this.clientFactory();
    this.client = client;
    client.onclose = () => {
      if (this.client === client) { this.client = null; this.tools = null; }
    };
    client.onerror = () => {
      if (this.client === client && !this.closed) this.log({ event: 'upstream_protocol_error', provider: this.provider });
    };
    const started = performance.now();
    try {
      await client.connect(this.transportFactory(), { timeout: this.policy.timeoutMs, signal });
      const all = [];
      const cursors = new Set();
      let cursor;
      do {
        const page = await client.listTools(cursor ? { cursor } : {}, { timeout: this.policy.timeoutMs, signal });
        all.push(...page.tools);
        cursor = page.nextCursor;
        if (cursor && cursors.has(cursor)) throw new PortalError('invalid_response');
        if (cursor) cursors.add(cursor);
        if (cursors.size > 20) throw new PortalError('invalid_response');
      } while (cursor);
      this.tools = all.filter(tool => this.aliases.has(tool.name)
        && tool.annotations?.destructiveHint !== true && tool.annotations?.readOnlyHint !== false)
        .map(tool => ({ ...tool, name: this.aliases.get(tool.name) }));
      // A configured provider with no usable capabilities is not a healthy connection.
      if (!this.tools.length) throw new PortalError('capability_mismatch');
      this.log({ event: 'connected', provider: this.provider, tools: this.tools.length });
      this.observations?.record('__connect__', { durationMs: performance.now() - started });
      return client;
    } catch (error) {
      this.observations?.record('__connect__', { durationMs: performance.now() - started, outcome: classify(error).kind });
      await this.disconnect();
      throw error;
    }
  }

  async enqueue(action, signal) {
    if (this.closed) throw new PortalError('closed');
    if (this.pending >= this.policy.maxPending) throw new PortalError('busy');
    this.pending++;
    const queuedAt = performance.now();
    const depth = this.pending;
    const run = this.tail.then(async () => {
      if (this.closed) throw new PortalError('closed');
      if (signal?.aborted) throw new PortalError('cancelled');
      this.observations?.recordQueue(performance.now() - queuedAt, depth);
      return action();
    }).finally(() => { this.pending--; });
    this.tail = run.catch(() => {});
    // A cancelled/expired queued request releases the caller immediately. It is
    // checked again before dispatch, so it can never run later in the background.
    let abort;
    const cancelled = new Promise((_, reject) => {
      abort = () => reject(new PortalError(signal?.reason?.name === 'TimeoutError' ? 'timeout' : 'cancelled'));
      signal?.addEventListener('abort', abort, { once: true });
      if (signal?.aborted) abort();
    });
    try { return await Promise.race([run, cancelled]); }
    finally { signal?.removeEventListener('abort', abort); }
  }

  async retry(action, parentSignal, operation) {
    const deadline = Date.now() + this.policy.totalTimeoutMs;
    let last, attempts = 0;
    while (attempts < this.policy.maxAttempts) {
      if (this.closed) throw new PortalError('closed');
      if (parentSignal?.aborted) throw new PortalError(parentSignal.reason?.name === 'TimeoutError' ? 'timeout' : 'cancelled');
      const remaining = deadline - Date.now();
      if (remaining <= 0) break;
      attempts++;
      // Cold connections keep their conservative startup budget. Only warm data
      // requests learn shorter deadlines; queue wait is never a latency sample.
      const timeoutMs = this.client && operation && this.observations
        ? this.observations.timeoutFor(operation) : this.policy.timeoutMs;
      const attemptSignal = AbortSignal.timeout(Math.min(remaining, timeoutMs));
      const signal = parentSignal ? AbortSignal.any([parentSignal, attemptSignal]) : attemptSignal;
      try {
        return await action(signal, timeoutMs);
      } catch (error) {
        if (parentSignal?.aborted) throw new PortalError(parentSignal.reason?.name === 'TimeoutError' ? 'timeout' : 'cancelled');
        last = classify(error);
        this.log({ event: 'attempt_failed', provider: this.provider, attempt: attempts, kind: last.kind });
        if (RECONNECT.has(last.kind)) await this.disconnect();
        if (!TRANSIENT.has(last.kind) || attempts === this.policy.maxAttempts) break;
        // A small shared quota and queue-pressure check prevent retry amplification.
        if (this.retryTokens < 1 || this.pending > Math.max(1, this.policy.maxPending / 2)) break;
        // Do not shorten Retry-After. If it exceeds our budget, fail and let the caller retry later.
        const backoff = Math.min(this.policy.maxDelayMs, this.policy.baseDelayMs * 2 ** (attempts - 1));
        const delay = Math.max(last.retryAfterMs || 0, Math.ceil(backoff * (0.5 + this.random() * 0.5)));
        if (delay >= deadline - Date.now()) break;
        this.retryTokens--;
        this.log({ event: 'retry_scheduled', provider: this.provider, attempt: attempts, delayMs: delay });
        try { await this.wait(delay, parentSignal); }
        catch { throw new PortalError('cancelled'); }
      }
    }
    const failure = last ?? new PortalError('timeout');
    failure.attempts = attempts;
    throw failure;
  }

  async listTools(signal) {
    return this.enqueue(() => this.retry(async attemptSignal => {
      await this.connect(attemptSignal);
      return { tools: this.tools };
    }, signal), signal);
  }

  async callTool(name, args = {}, signal) {
    // Check BEFORE connecting: unknown tools and writes must never reach a provider.
    if (!this.allowed.has(name)) return publicFailure(new PortalError('tool_not_allowed'), this.provider, 0);
    const budget = AbortSignal.timeout(this.policy.totalTimeoutMs);
    const querySignal = signal ? AbortSignal.any([signal, budget]) : budget;
    try {
      return await this.enqueue(async () => {
        try {
          if (Date.now() < this.openUntil) throw new PortalError('circuit_open');
          const result = await this.retry(async (attemptSignal, timeoutMs) => {
            const client = await this.connect(attemptSignal);
            if (!this.tools.some(tool => tool.name === name)) throw new PortalError('tool_unavailable');
            const started = performance.now();
            try {
              const result = checkResult(await client.callTool({ name: this.toolMap[name], arguments: args }, undefined,
                { timeout: timeoutMs, signal: attemptSignal }));
              this.observations?.record(name, { durationMs: performance.now() - started });
              return result;
            } catch (error) {
              this.observations?.record(name, { durationMs: performance.now() - started, outcome: classify(error).kind });
              throw error;
            }
          }, querySignal, name);
          this.retryTokens = Math.min(this.policy.retryQuota, this.retryTokens + 1);
          this.failureCount = 0;
          this.openUntil = 0;
          this.lastFailure = null;
          this.lastSuccessAt = new Date().toISOString();
          return result;
        } catch (error) {
          const kind = classify(error).kind;
          this.lastFailure = kind;
          if (TRANSIENT.has(kind) && ++this.failureCount >= this.policy.circuitThreshold) {
            this.openUntil = Date.now() + this.policy.circuitCooldownMs;
            this.log({ event: 'circuit_opened', provider: this.provider, kind });
          }
          throw error;
        }
      }, querySignal);
    } catch (error) {
      return publicFailure(error, this.provider, error.attempts ?? 0);
    }
  }
}
