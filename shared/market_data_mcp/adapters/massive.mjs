import { readFile } from 'node:fs/promises';
import { PortalError } from '../core/errors.mjs';
import { fetchJson, readCredentials, redact, restTransport, validDate } from '../core/rest-adapter.mjs';

export const MASSIVE_TOOLS = JSON.parse(await readFile(new URL('../schemas/massive.json', import.meta.url), 'utf8')).tools;
export const marketDate = (now = Date.now()) => new Intl.DateTimeFormat('en-CA', {
  timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date(now));
export async function massiveQuery(name, args, { credentialFile, fetchImpl = fetch, signal } = {}) {
  let url;
  if (name === 'option_contracts') {
    if (!/^[A-Z][A-Z0-9.]{0,9}$/.test(args.underlying) || (args.expiration && !validDate(args.expiration))
      || (args.side && !['call', 'put'].includes(args.side))
      || (args.limit !== undefined && (!Number.isInteger(args.limit) || args.limit < 1 || args.limit > 20))) throw new PortalError('invalid_arguments');
    url = new URL('https://api.massive.com/v3/reference/options/contracts');
    url.searchParams.set('underlying_ticker', args.underlying);
    url.searchParams.set('limit', args.limit ?? 5);
    if (args.expiration) url.searchParams.set('expiration_date', args.expiration);
    if (args.side) url.searchParams.set('contract_type', args.side);
    for (const key of ['strike_min', 'strike_max']) {
      if (args[key] !== undefined && (!Number.isFinite(args[key]) || args[key] <= 0)) throw new PortalError('invalid_arguments');
    }
    if (args.strike_min !== undefined && args.strike_max !== undefined && args.strike_min > args.strike_max) throw new PortalError('invalid_arguments');
    if (args.strike_min !== undefined) url.searchParams.set('strike_price.gte', args.strike_min);
    if (args.strike_max !== undefined) url.searchParams.set('strike_price.lte', args.strike_max);
  } else if (name === 'option_daily_bars') {
    const from = Date.parse(args.from), to = Date.parse(args.to);
    if (!/^O:[A-Z]{1,6}\d{6}[CP]\d{8}$/.test(args.contract) || !validDate(args.from) || !validDate(args.to)
      || from > to || to - from > 31 * 86400000 || args.to >= marketDate()
      || Date.now() - from > 730 * 86400000) throw new PortalError('invalid_arguments');
    url = new URL(`https://api.massive.com/v2/aggs/ticker/${encodeURIComponent(args.contract)}/range/1/day/${args.from}/${args.to}`);
    url.searchParams.set('limit', '32');
    url.searchParams.set('sort', 'asc');
    url.searchParams.set('adjusted', 'true');
  } else throw new PortalError('tool_not_allowed');
  const credentials = await readCredentials(credentialFile, ['api_key']);
  const payload = await fetchJson(url, { headers: { Authorization: `Bearer ${credentials.api_key}` }, signal, fetchImpl });
  if (payload.error || !['OK', 'DELAYED'].includes(payload.status)) throw new PortalError('query_failed');
  if (!Array.isArray(payload.results) || !payload.results.length) throw new PortalError('no_data');
  if (payload.results.length > (name === 'option_contracts' ? args.limit ?? 5 : 32)) throw new PortalError('invalid_response');
  // Never return or follow next_url, which can contain API credentials or arbitrary origins.
  return redact({ provider: 'massive', source: 'official REST API via local read-only MCP adapter',
    scope: name === 'option_contracts' ? 'daily-updated contract reference' : 'historical daily OHLC; EOD free-tier scope',
    retrieved_at: new Date().toISOString(), greeks: 'Not provided by this free-compatible adapter.',
    more_available: Boolean(payload.next_url), automatic_pagination: false,
    data: { results: payload.results, ticker: payload.ticker, adjusted: payload.adjusted } }, Object.values(credentials));
}

export const massiveTransport = file => restTransport('massive', MASSIVE_TOOLS,
  (name, args, signal) => massiveQuery(name, args, { credentialFile: file, signal }));
