// Local read-only MCP adapter. Secrets go only in the official API's token header.
import { readFile, stat } from 'node:fs/promises';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { AjvJsonSchemaValidator } from '@modelcontextprotocol/sdk/validation/ajv';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { PortalError, classify } from '../core/errors.mjs';

export const FINNHUB_TOOLS = JSON.parse(await readFile(new URL('../schemas/finnhub.json', import.meta.url), 'utf8')).tools;
const validator = new AjvJsonSchemaValidator();
const validate = new Map(FINNHUB_TOOLS.map(tool => [tool.name, validator.getValidator(tool.inputSchema)]));
const endpoints = { quote: '/quote', company_profile: '/stock/profile2', symbol_lookup: '/search', basic_financials: '/stock/metric' };

export async function finnhubQuery(name, args, { credentialFile, fetchImpl = fetch, signal }) {
  if (!endpoints[name]) throw new PortalError('tool_not_allowed');
  if (!validate.get(name)(args).valid) throw new PortalError('invalid_arguments');
  let key;
  try {
    if ((await stat(credentialFile)).mode & 0o077) throw new Error('insecure permissions');
    key = JSON.parse(await readFile(credentialFile, 'utf8')).api_key;
    if (typeof key !== 'string' || !key.trim()) throw new Error('missing key');
  } catch { throw new PortalError('auth_required'); }
  const url = new URL('https://finnhub.io/api/v1' + endpoints[name]);
  url.searchParams.set(name === 'symbol_lookup' ? 'q' : 'symbol', name === 'symbol_lookup' ? args.query : args.symbol);
  if (name === 'basic_financials') url.searchParams.set('metric', 'all');
  const timeout = AbortSignal.timeout(20000);
  const response = await fetchImpl(url, { method: 'GET', headers: { 'X-Finnhub-Token': key, Accept: 'application/json' },
    signal: signal ? AbortSignal.any([signal, timeout]) : timeout, redirect: 'manual' });
  if (!response.ok) {
    const header = response.headers.get('retry-after');
    await response.body?.cancel();
    const kind = response.status === 401 ? 'auth_required' : response.status === 403 ? 'entitlement_required'
      : response.status === 429 ? 'rate_limited' : response.status >= 500 ? 'upstream_unavailable' : 'query_failed';
    throw new PortalError(kind, { retryAfterMs: header && /^\d+(\.\d+)?$/.test(header) ? Number(header) * 1000 : undefined });
  }
  const payload = await response.json();
  if (payload?.error) throw classify(new Error(String(payload.error)));
  if (!payload || !Object.keys(payload).length || (name === 'quote' && !(payload.c > 0))) throw new PortalError('no_data');
  return { provider: 'finnhub', source: 'official REST API via local read-only MCP adapter', data: payload };
}

export function finnhubTransport(credentialFile) {
  const [client, upstream] = InMemoryTransport.createLinkedPair();
  const server = new Server({ name: 'finnhub-rest-readonly-adapter', version: '1.0.0' }, { capabilities: { tools: {} } });
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: FINNHUB_TOOLS }));
  server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
    try {
      const data = await finnhubQuery(request.params.name, request.params.arguments ?? {}, { credentialFile, signal: extra.signal });
      return { content: [{ type: 'text', text: JSON.stringify(data) }] };
    } catch (error) {
      // Stable typed codes survive the internal MCP boundary; no headers/URLs/errors leak.
      const kind = classify(error).kind;
      return { isError: true, content: [{ type: 'text', text: JSON.stringify({ error: kind,
        retry_after_ms: error.retryAfterMs }) }] };
    }
  });
  void server.connect(upstream);
  return client;
}
