import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeContract, verifySnapshot, verifyReference, verifyBars, expirations, summarizeSnapshots } from '../verification/options.mjs';
import { marketDate } from '../adapters/massive.mjs';

const symbol = 'AAPL261120C00342500';
const now = Date.parse('2026-10-30T12:00:00Z');
const quote = { bp: 10, ap: 11, bs: 2, as: 3, t: '2026-10-29T19:59:59Z' };

test('OCC decoding preserves fractional strikes, side and valid calendar expiry', () => {
  assert.deepEqual(decodeContract('O:' + symbol), { underlying: 'AAPL', expiration: '2026-11-20', side: 'call', strike: 342.5 });
  assert.equal(decodeContract('SPY270115P00600000').side, 'put');
  assert.throws(() => decodeContract('AAPL260230C00300000'), /invalid_occ_expiration/);
  assert.throws(() => decodeContract('anything'), /invalid_occ_symbol/);
  assert.deepEqual(expirations(now), ['2026-11-20', '2027-01-15']);
});

test('snapshot grader accepts sparse fields and rejects critical price, time, identity and Greek faults', () => {
  const valid = verifySnapshot(symbol, { latestQuote: quote }, { underlying: 'AAPL', side: 'call' }, now);
  assert.equal(valid.greeks, 0); assert.equal(valid.iv, 0); assert.equal(valid.quotes, 1);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: { ...quote, bp: 12 } }, {}, now), /crossed_quote/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: { ...quote, ap: NaN } }, {}, now), /invalid_ask/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: { ...quote, t: '2026-10-31T00:00:00Z' } }, {}, now), /invalid_or_future_timestamp/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: quote }, { underlying: 'SPY' }, now), /wrong_contract_underlying/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: quote }, { strike_min: 343 }, now), /strike_below/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: quote, greeks: { delta: -0.5 } }, {}, now), /invalid_delta_range/);
  assert.throws(() => verifySnapshot(symbol, { latestQuote: quote, greeks: { gamma: -1 } }, {}, now), /invalid_greek_sign/);
  const put = verifySnapshot('SPY270115P00600000', { latestQuote: quote, greeks: { delta: -0.4, gamma: 0.01, vega: 1 }, impliedVolatility: 0.2 }, {}, now);
  assert.equal(put.greeks, 1); assert.equal(put.iv, 1);
});

test('reference grader rejects symbol/field disagreement and identifies adjusted deliverables', () => {
  const c = { ticker: 'O:' + symbol, underlying_ticker: 'AAPL', expiration_date: '2026-11-20',
    contract_type: 'call', strike_price: 342.5, shares_per_contract: 100, exercise_style: 'american' };
  assert.equal(verifyReference(c, {}).nonstandard, false);
  assert.throws(() => verifyReference({ ...c, strike_price: 343 }, {}), /reference_occ_mismatch/);
  assert.equal(verifyReference({ ...c, shares_per_contract: 150 }, {}).nonstandard, true);
});

test('daily-bar grader checks order, requested Eastern dates, volume and OHLC bounds', () => {
  const bar = { t: Date.parse('2026-10-29T04:00:00Z'), o: 10, h: 12, l: 9, c: 11, v: 100 };
  assert.equal(verifyBars([bar], '2026-10-29', '2026-10-29', now).bars, 1);
  assert.throws(() => verifyBars([{ ...bar, h: 10 }], '2026-10-29', '2026-10-29', now), /invalid_ohlc_bounds/);
  assert.throws(() => verifyBars([{ ...bar, v: -1 }], '2026-10-29', '2026-10-29', now), /invalid_bar_v/);
  assert.throws(() => verifyBars([bar, bar], '2026-10-29', '2026-10-29', now), /unsorted_or_out_of_range/);
  assert.throws(() => verifyBars([bar], '2026-10-28', '2026-10-28', now), /unsorted_or_out_of_range/);
  assert.equal(marketDate(Date.parse('2027-01-01T02:00:00Z')), '2026-12-31');
});

test('summary distinguishes repeated observations from unique Greek coverage and retains both age ranges', () => {
  const items = [{ symbol: 'A', quotes: 1, trades: 1, greeks: 1, iv: 1, quoteAgeSeconds: 5, tradeAgeSeconds: 50 },
    { symbol: 'A', quotes: 1, trades: 1, greeks: 1, iv: 1, quoteAgeSeconds: 6, tradeAgeSeconds: 60 },
    { symbol: 'B', quotes: 1, trades: 0, greeks: 0, iv: 0, quoteAgeSeconds: 10 }];
  const result = summarizeSnapshots(items);
  assert.equal(result.checkedObservations, 3); assert.equal(result.uniqueContracts, 2);
  assert.equal(result.withGreeks, 2); assert.equal(result.uniqueContractsWithGreeks, 1);
  assert.deepEqual(result.quoteAgeSeconds, { min: 5, max: 10 });
  assert.deepEqual(result.tradeAgeSeconds, { min: 50, max: 60 });
});
