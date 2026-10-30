// Deterministic data checks, independent of transports and credentials.
export function requireData(condition, code) {
  if (!condition) { const error = new Error(code); error.kind = code; throw error; }
}
export function decodeContract(symbol) {
  const match = /^(?:O:)?([A-Z]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$/.exec(symbol);
  requireData(match, 'invalid_occ_symbol');
  const expiration = `20${match[2]}-${match[3]}-${match[4]}`;
  requireData(Number.isFinite(Date.parse(expiration)) && new Date(expiration).toISOString().slice(0, 10) === expiration, 'invalid_occ_expiration');
  return { underlying: match[1], expiration, side: match[5] === 'C' ? 'call' : 'put', strike: Number(match[6]) / 1000 };
}
export function verifyIdentity(symbol, expected) {
  const actual = decodeContract(symbol);
  for (const key of ['underlying', 'expiration', 'side']) {
    if (expected[key]) requireData(actual[key] === expected[key], `wrong_contract_${key}`);
  }
  if (expected.strike_min !== undefined) requireData(actual.strike >= expected.strike_min, 'strike_below_requested_window');
  if (expected.strike_max !== undefined) requireData(actual.strike <= expected.strike_max, 'strike_above_requested_window');
  return actual;
}
function number(value, code) { requireData(typeof value === 'number' && Number.isFinite(value), code); return value; }
function nonnegative(value, code) { requireData(number(value, code) >= 0, code); }
function timestamp(value, now) {
  const milliseconds = typeof value === 'number' ? value : Date.parse(value);
  requireData(Number.isFinite(milliseconds) && milliseconds > 0 && milliseconds <= now + 300000, 'invalid_or_future_timestamp');
  return milliseconds;
}
export function verifySnapshot(symbol, snapshot, expected = {}, now = Date.now()) {
  const identity = verifyIdentity(symbol, expected);
  requireData(snapshot && typeof snapshot === 'object', 'invalid_snapshot');
  const quote = snapshot.latestQuote, trade = snapshot.latestTrade;
  requireData(quote || trade, 'snapshot_has_no_price_fields');
  const observation = { symbol, quotes: 0, trades: 0, greeks: 0, iv: 0, zeroBid: 0 };
  if (quote) {
    nonnegative(quote.bp, 'invalid_bid'); nonnegative(quote.ap, 'invalid_ask');
    nonnegative(quote.bs, 'invalid_bid_size'); nonnegative(quote.as, 'invalid_ask_size');
    requireData(quote.bp <= quote.ap, 'crossed_quote');
    observation.quotes = 1; observation.zeroBid = quote.bp === 0 ? 1 : 0;
    observation.quoteAgeSeconds = Math.round((now - timestamp(quote.t, now)) / 1000);
  }
  if (trade) {
    nonnegative(trade.p, 'invalid_trade_price'); nonnegative(trade.s, 'invalid_trade_size');
    observation.trades = 1;
    observation.tradeAgeSeconds = Math.round((now - timestamp(trade.t, now)) / 1000);
  }
  if (snapshot.greeks && Object.values(snapshot.greeks).some(v => v !== null)) {
    for (const [key, value] of Object.entries(snapshot.greeks)) {
      if (value === null) continue;
      number(value, 'nonfinite_greek');
      if (['gamma', 'vega'].includes(key)) requireData(value >= -1e-10, 'invalid_greek_sign');
      if (key === 'delta') requireData(identity.side === 'call'
        ? value >= -1e-10 && value <= 1 + 1e-10 : value >= -1 - 1e-10 && value <= 1e-10, 'invalid_delta_range');
    }
    observation.greeks = 1;
  }
  if (snapshot.impliedVolatility !== undefined && snapshot.impliedVolatility !== null) {
    nonnegative(snapshot.impliedVolatility, 'invalid_implied_volatility'); observation.iv = 1;
  }
  return observation;
}
export function verifyReference(contract, expected) {
  if (contract.additional_underlyings?.length || contract.shares_per_contract !== 100) return { nonstandard: true };
  const identity = verifyIdentity(contract.ticker, expected);
  requireData(contract.underlying_ticker === identity.underlying && contract.expiration_date === identity.expiration
    && contract.contract_type === identity.side && contract.strike_price === identity.strike, 'reference_occ_mismatch');
  requireData(['american', 'european', 'bermudan'].includes(contract.exercise_style), 'invalid_exercise_style');
  return { nonstandard: false, ...identity };
}
export function verifyBars(bars, from, to, now = Date.now()) {
  requireData(Array.isArray(bars) && bars.length > 0 && bars.length <= 32, 'invalid_bars_count');
  let previous = 0;
  for (const bar of bars) {
    for (const key of ['o', 'h', 'l', 'c', 'v']) nonnegative(bar[key], `invalid_bar_${key}`);
    requireData(bar.h >= Math.max(bar.o, bar.c, bar.l) && bar.l <= Math.min(bar.o, bar.c), 'invalid_ohlc_bounds');
    const time = timestamp(bar.t, now);
    const day = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(time));
    requireData(day >= from && day <= to && time > previous, 'unsorted_or_out_of_range_bar');
    previous = time;
  }
  return { bars: bars.length, firstAt: new Date(bars[0].t).toISOString(), lastAt: new Date(bars.at(-1).t).toISOString() };
}
export function expirations(now = Date.now()) {
  const today = new Date(now);
  const monthly = month => {
    const date = new Date(Date.UTC(today.getUTCFullYear(), month, 15));
    while (date.getUTCDay() !== 5) date.setUTCDate(date.getUTCDate() + 1);
    return date;
  };
  let month = today.getUTCMonth();
  while (monthly(month).getTime() < now + 14 * 86400000) month++;
  return [monthly(month), monthly(month + 2)].map(d => d.toISOString().slice(0, 10));
}

export function summarizeSnapshots(observations) {
  const count = key => observations.filter(o => o[key]).length;
  const unique = values => new Set(values.map(o => o.symbol)).size;
  const ages = key => {
    const values = observations.map(o => o[key]).filter(Number.isFinite);
    return values.length ? { min: Math.min(...values), max: Math.max(...values) } : null;
  };
  return { checkedObservations: observations.length, uniqueContracts: unique(observations),
    withQuote: count('quotes'), withTrade: count('trades'), withGreeks: count('greeks'), withIV: count('iv'),
    uniqueContractsWithGreeks: unique(observations.filter(o => o.greeks)), zeroBid: count('zeroBid'),
    quoteAgeSeconds: ages('quoteAgeSeconds'), tradeAgeSeconds: ages('tradeAgeSeconds') };
}
