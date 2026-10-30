// Read-only REST/MCP boundary shared by the options adapters. Retries belong to QueryPortal.
import { open, constants } from 'node:fs/promises';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { AjvJsonSchemaValidator } from '@modelcontextprotocol/sdk/validation/ajv';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { PortalError, classify } from './errors.mjs';

export async function readCredentials(file, fields, { optional = false } = {}) {
  let handle;
  try {
    handle = await open(file, constants.O_RDONLY | constants.O_NOFOLLOW);
    const info = await handle.stat();
    if (!info.isFile() || (info.mode & 0o077) || info.size > 4096) throw new Error('credential policy');
    const bytes = Buffer.alloc(4097);
    const { bytesRead } = await handle.read(bytes, 0, bytes.length, 0);
    if (bytesRead > 4096) throw new Error('credential size');
    const data = JSON.parse(bytes.subarray(0, bytesRead).toString('utf8'));
    if (!fields.every(field => typeof data[field] === 'string' && data[field].length > 0
      && data[field].length < 1024 && !/[\s\x00-\x1f\x7f]/.test(data[field]))) throw new Error('credential fields');
    return Object.fromEntries(fields.map(field => [field, data[field]]));
  } catch (error) {
    if (optional && error.code === 'ENOENT') return null;
    throw new PortalError('auth_required');
  } finally { await handle?.close(); }
}

export async function fetchJson(url, { headers = {}, signal, fetchImpl = fetch } = {}) {
  const deadline = AbortSignal.timeout(20000);
  const response = await fetchImpl(url, { method: 'GET', headers: { Accept: 'application/json', ...headers },
    redirect: 'manual', signal: signal ? AbortSignal.any([signal, deadline]) : deadline });
  if (!response.ok || response.status === 204) {
    const value = response.headers.get('retry-after');
    const retryAfterMs = value && /^\d+(\.\d+)?$/.test(value) ? Number(value) * 1000
      : value ? Math.max(0, Date.parse(value) - Date.now()) : undefined;
    await response.body?.cancel();
    throw new PortalError(response.status === 401 ? 'auth_required'
      : [402, 403].includes(response.status) ? 'entitlement_required'
      : [204, 404].includes(response.status) ? 'no_data'
      : response.status === 429 ? 'rate_limited'
      : response.status >= 500 ? 'upstream_unavailable' : 'query_failed', { retryAfterMs });
  }
  const reader = response.body?.getReader();
  if (!reader) throw new PortalError('invalid_response');
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1024 * 1024) { await reader.cancel(); throw new PortalError('invalid_response'); }
      chunks.push(Buffer.from(value));
    }
    let data;
    try { data = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { throw new PortalError('invalid_response'); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new PortalError('invalid_response');
    return data;
  } finally { reader.releaseLock(); }
}

// Redact known credential values even if a provider unexpectedly echoes one in a successful body.
export function redact(value, secrets) {
  const safe = secrets.filter(Boolean);
  const clean = text => safe.reduce((result, secret) => result.split(secret).join('[REDACTED]'), text);
  const visit = item => typeof item === 'string' ? clean(item) : Array.isArray(item) ? item.map(visit)
    : item && typeof item === 'object' ? Object.fromEntries(Object.entries(item).map(([key, child]) => [clean(key), visit(child)])) : item;
  return visit(value);
}

export function restTransport(provider, tools, query) {
  const [client, upstream] = InMemoryTransport.createLinkedPair();
  const server = new Server({ name: `${provider}-rest-readonly-adapter`, version: '1.0.0' }, { capabilities: { tools: {} } });
  const validator = new AjvJsonSchemaValidator();
  const checks = new Map(tools.map(tool => [tool.name, validator.getValidator(tool.inputSchema)]));
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    try {
      const { name, arguments: args = {} } = request.params;
      if (!checks.has(name)) throw new PortalError('tool_not_allowed');
      if (!checks.get(name)(args).valid) throw new PortalError('invalid_arguments');
      const data = await query(name, args, extra.signal);
      return { content: [{ type: 'text', text: JSON.stringify(data) }] };
    } catch (error) {
      return { isError: true, content: [{ type: 'text', text: JSON.stringify({
        error: classify(error).kind, retry_after_ms: error.retryAfterMs }) }] };
    }
  });
  void server.connect(upstream);
  return client;
}

export function validDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value))
    && new Date(value).toISOString().slice(0, 10) === value;
}
