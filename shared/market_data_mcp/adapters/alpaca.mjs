import { readFile } from 'node:fs/promises';
import { PortalError } from '../core/errors.mjs';
import { fetchJson, readCredentials, redact, restTransport, validDate } from '../core/rest-adapter.mjs';

export const ALPACA_TOOLS = JSON.parse(await readFile(new URL('../schemas/alpaca.json', import.meta.url), 'utf8')).tools;
export async function alpacaQuery(name, args, { credentialFile, fetchImpl = fetch, signal } = {}) {
  if (!['option_chain', 'option_snapshots'].includes(name)) throw new PortalError('tool_not_allowed');
  const limit = name === 'option_chain' ? (args.limit ?? 5) : args.contracts?.length;
  if (!Number.isInteger(limit) || limit < 1 || limit > (name === 'option_chain' ? 20 : 5)) throw new PortalError('invalid_arguments');
  if (name === 'option_chain' && (!/^[A-Z][A-Z0-9.]{0,9}$/.test(args.underlying)
    || !validDate(args.expiration) || !['call', 'put'].includes(args.side))) throw new PortalError('invalid_arguments');
  if (name === 'option_snapshots' && (!Array.isArray(args.contracts)
    || !args.contracts.every(s => /^[A-Z]{1,6}\d{6}[CP]\d{8}$/.test(s)))) throw new PortalError('invalid_arguments');
  for (const key of ['strike_min', 'strike_max']) {
    if (args[key] !== undefined && (!Number.isFinite(args[key]) || args[key] <= 0)) throw new PortalError('invalid_arguments');
  }
  if (args.strike_min !== undefined && args.strike_max !== undefined && args.strike_min > args.strike_max) throw new PortalError('invalid_arguments');
  const credentials = await readCredentials(credentialFile, ['api_key', 'api_secret']);
  const url = new URL('https://data.alpaca.markets/v1beta1/options/snapshots'
    + (name === 'option_chain' ? `/${encodeURIComponent(args.underlying)}` : ''));
  url.searchParams.set('feed', 'indicative');
  url.searchParams.set('limit', limit);
  if (name === 'option_chain') {
    url.searchParams.set('expiration_date', args.expiration);
    url.searchParams.set('type', args.side);
    if (args.strike_min !== undefined) url.searchParams.set('strike_price_gte', args.strike_min);
    if (args.strike_max !== undefined) url.searchParams.set('strike_price_lte', args.strike_max);
  } else url.searchParams.set('symbols', args.contracts.join(','));
  const payload = await fetchJson(url, { headers: { 'APCA-API-KEY-ID': credentials.api_key,
    'APCA-API-SECRET-KEY': credentials.api_secret }, signal, fetchImpl });
  if (payload.message || payload.code) throw new PortalError('query_failed');
  if (!payload.snapshots || !Object.keys(payload.snapshots).length) throw new PortalError('no_data');
  if (Object.keys(payload.snapshots).length > limit) throw new PortalError('invalid_response');
  return redact({ provider: 'alpaca', source: 'official REST API via local read-only MCP adapter',
    feed: 'indicative', freshness: 'Free indicative feed: trades delayed, quotes modified; not executable NBBO.',
    retrieved_at: new Date().toISOString(), greeks: 'Provider-supplied values only; availability and calculation times are not guaranteed.',
    greeks_timing_verified: false,
    more_available: Boolean(payload.next_page_token), automatic_pagination: false,
    data: { snapshots: payload.snapshots } }, Object.values(credentials));
}

export const alpacaTransport = file => restTransport('alpaca', ALPACA_TOOLS,
  (name, args, signal) => alpacaQuery(name, args, { credentialFile: file, signal }));
