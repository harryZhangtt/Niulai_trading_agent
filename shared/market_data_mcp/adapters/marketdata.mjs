import { readFile } from 'node:fs/promises';
import { PortalError } from '../core/errors.mjs';
import { fetchJson, readCredentials, redact, restTransport, validDate } from '../core/rest-adapter.mjs';

export const MARKETDATA_TOOLS = JSON.parse(await readFile(new URL('../schemas/marketdata.json', import.meta.url), 'utf8')).tools;
export async function marketdataQuery(name, args, { credentialFile, fetchImpl = fetch, signal } = {}) {
  const endpoint = { option_expirations: 'expirations', option_chain: 'chain', option_quote: 'quotes' }[name];
  if (!endpoint) throw new PortalError('tool_not_allowed');
  const symbol = name === 'option_quote' ? args.contract : args.underlying;
  if (typeof symbol !== 'string' || !(name === 'option_quote' ? /^[A-Z]{1,6}\d{6}[CP]\d{8}$/ : /^[A-Z][A-Z0-9.]{0,9}$/).test(symbol)) throw new PortalError('invalid_arguments');
  if ((args.date && (!validDate(args.date) || args.date >= new Date().toISOString().slice(0, 10)))
    || (name === 'option_chain' && (!validDate(args.expiration) || !['call', 'put'].includes(args.side)
      || (args.strike_limit !== undefined && (!Number.isInteger(args.strike_limit) || args.strike_limit < 1 || args.strike_limit > 10))))) throw new PortalError('invalid_arguments');
  const credentials = await readCredentials(credentialFile, ['api_key'], { optional: true });
  if (!credentials && !(name === 'option_quote' ? /^AAPL\d{6}[CP]\d{8}$/.test(symbol) : symbol === 'AAPL')) throw new PortalError('auth_required');
  const url = new URL(`https://api.marketdata.app/v1/options/${endpoint}/${encodeURIComponent(symbol)}/`);
  if (name !== 'option_expirations') url.searchParams.set('mode', 'historical');
  if (args.date) url.searchParams.set('date', args.date);
  if (name === 'option_chain') {
    url.searchParams.set('expiration', args.expiration);
    url.searchParams.set('side', args.side);
    url.searchParams.set('strikeLimit', args.strike_limit ?? 3);
    url.searchParams.set('nonstandard', 'false');
  }
  const payload = await fetchJson(url, { headers: credentials ? { Authorization: `Bearer ${credentials.api_key}` } : {}, signal, fetchImpl });
  if (payload.s === 'no_data') throw new PortalError('no_data');
  if (payload.s !== 'ok') throw new PortalError('query_failed');
  const rows = name === 'option_expirations' ? payload.expirations : payload.optionSymbol;
  if (!Array.isArray(rows) || !rows.length) throw new PortalError('no_data');
  if (name === 'option_chain' && rows.length > (args.strike_limit ?? 3)) throw new PortalError('invalid_response');
  if (name === 'option_quote' && (rows.length !== 1 || rows[0] !== symbol)) throw new PortalError('invalid_response');
  delete payload.errmsg;
  return redact({ provider: 'marketdata', source: 'official REST API via local read-only MCP adapter',
    access: credentials ? 'account-key; free-compatible historical requests' : 'unauthenticated AAPL demo',
    mode: name === 'option_expirations' ? 'reference' : 'historical', retrieved_at: new Date().toISOString(),
    freshness: 'Use provider updated timestamps; not a live quote feed. Free/trial uses fully closed sessions.',
    greeks: 'Provider fields preserved. Explicit-date history omits Greeks/IV; demo mode may return values without verified calculation times.',
    greeks_timing_verified: false, data: payload }, Object.values(credentials ?? {}));
}

export const marketdataTransport = file => restTransport('marketdata', MARKETDATA_TOOLS,
  (name, args, signal) => marketdataQuery(name, args, { credentialFile: file, signal }));
