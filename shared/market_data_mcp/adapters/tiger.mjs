// Reuse the portal without registering a host MCP server or duplicating OAuth state.
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { AjvJsonSchemaValidator } from '@modelcontextprotocol/sdk/validation/ajv';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { PortalError } from '../core/errors.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const securityTypes = { type: 'array', minItems: 1, maxItems: 4, uniqueItems: true,
  items: { type: 'string', enum: ['STK', 'OPT', 'FUT', 'FUND'] } };
export const TIGER_TOOLS = ['positions', 'assets', 'snapshot'].map(name => ({ name,
  description: `Read Tiger ${name} under the existing owner-private credential lease. Returns a receipt; data stays in private artifacts.`,
  inputSchema: { type: 'object', properties: name === 'assets' ? {} : { security_types: securityTypes }, additionalProperties: false },
  annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: false },
}));
const validator = new AjvJsonSchemaValidator();
const validators = new Map(TIGER_TOOLS.map(t => [t.name, validator.getValidator(t.inputSchema)]));

function safeReceipt(value, code) {
  if (value?.status === 'failed' && code === 2 && /^[A-Z][A-Z0-9_]{0,79}$/.test(value.error)) {
    return { status: 'failed', error: value.error, automatic_retry: false,
      reauthorization_assumed_required: false, reconciliation_required: value.reconciliation_required === true };
  }
  if (code !== 0 || value?.status !== 'queried' || value.committed !== true || value.release_requested !== true
      || value.source_read_status !== 'complete' || !validators.has(value.tool)
      || value.source !== 'existing_owner_private_store' || value.mode !== 'query'
      || !Array.isArray(value.files) || !value.files.every(f => ['holdings.json', 'assets.json', 'query.json'].includes(f))) {
    throw new PortalError('invalid_response');
  }
  const result = { status: 'queried', tool: value.tool, source_read_status: 'complete',
    committed: true, release_requested: true, mode: 'query', authorization_prompted: false,
    broker_retries_added: 0, source: value.source, files: value.files,
    holdings_read: value.holdings_read === true, assets_read: value.assets_read === true };
  if (Number.isSafeInteger(value.holdings_count) && value.holdings_count >= 0) result.holdings_count = value.holdings_count;
  if (/^[0-9a-f-]{36}$/.test(value.attempt_id)) result.attempt_id = value.attempt_id;
  return result;
}

export function runTigerWorker(context, { signal, spawnImpl = spawn, timeoutMs = 105000 } = {}) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new PortalError('timeout')); return; }
    const payload = JSON.stringify(context);
    if (Buffer.byteLength(payload) > 1024 * 1024) { reject(new PortalError('invalid_arguments')); return; }
    const child = spawnImpl(path.join(ROOT, '.niulai-state/.venv/bin/python'), ['-m', 'shared.tiger.worker'], {
      cwd: ROOT, stdio: ['pipe', 'pipe', 'ignore'],
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', TMPDIR: path.join(ROOT, '.niulai-state/tmp') },
    });
    let output = '', stopped = false, killTimer;
    function stop() {
      if (stopped) return;
      stopped = true;
      child.kill('SIGTERM');
      killTimer ??= setTimeout(() => child.kill('SIGKILL'), 1500);
      killTimer.unref();
    }
    const timer = setTimeout(stop, timeoutMs);
    signal?.addEventListener('abort', stop, { once: true });
    function cleanup() {
      clearTimeout(timer); clearTimeout(killTimer);
      signal?.removeEventListener('abort', stop);
    }
    child.on('error', () => { cleanup(); reject(new PortalError('setup_required')); });
    child.stdout.on('data', data => {
      output += data.toString();
      if (Buffer.byteLength(output) > 65536) { output = ''; stop(); }
    });
    child.stdin.on('error', () => {}); // EPIPE is reported through the bounded exit path.
    child.on('close', code => {
      cleanup();
      if (stopped) { reject(new PortalError('timeout')); return; }
      try {
        // The worker only emits credential-free receipts, never normalized account data.
        resolve(safeReceipt(JSON.parse(output), code));
      } catch { reject(new PortalError('invalid_response')); }
    });
    child.stdin.end(payload);
  });
}

export function tigerTransport(context, { execute = runTigerWorker, onReceipt = () => {} } = {}) {
  const [client, upstream] = InMemoryTransport.createLinkedPair();
  const server = new Server({ name: 'tiger-leased-readonly-adapter', version: '1.0.0' }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TIGER_TOOLS }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    const { name, arguments: args = {} } = request.params;
    let kind;
    if (!validators.has(name)) kind = 'tool_not_allowed';
    else if (!validators.get(name)(args).valid) kind = 'invalid_arguments';
    if (kind) return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: kind }) }] };
    try {
      const receipt = await execute({ ...context, query: { tool: name, arguments: args } }, { signal: extra.signal });
      onReceipt(receipt);
      return { isError: receipt.status !== 'queried', content: [{ type: 'text', text: JSON.stringify(
        receipt.status === 'queried' ? receipt : { error: 'query_failed' }) }] };
    } catch {
      // Uncertain worker exit must not trigger broker retries or reauthorization.
      onReceipt({ status: 'failed', error: 'TIGER_WORKER_OUTCOME_UNCONFIRMED',
        automatic_retry: false, reconciliation_required: true });
      return { isError: true, content: [{ type: 'text', text: '{"error":"query_failed"}' }] };
    }
  });
  void server.connect(upstream);
  return client;
}
