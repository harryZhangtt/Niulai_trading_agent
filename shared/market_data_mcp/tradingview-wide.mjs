// Bounded read-only acceptance matrix; no alert/watchlist/account changes.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { withPortal, jsonResult } from './client.mjs';
import { STATE } from './providers.mjs';

const report = { startedAt: new Date().toISOString(), provider: 'tradingview',
  route: 'shared portal -> official TradingView MCP', activeCodexRegistration: false, cases: [] };
const raw = {};
const date = days => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);
function values(value) {
  if (value === null || typeof value !== 'object') return [value];
  return Object.values(value).flatMap(values);
}
function bars(result) {
  assert.equal(result.success, true);
  assert.ok(Array.isArray(result.bars) && result.bars.length > 0);
  for (const [index, row] of result.bars.entries()) {
    for (const field of ['t', 'o', 'h', 'l', 'c', 'v']) assert.ok(Number.isFinite(row[field]));
    assert.ok(row.l > 0 && row.v >= 0 && row.l <= Math.min(row.o, row.c) && row.h >= Math.max(row.o, row.c));
    assert.ok(row.t * 1000 <= Date.now() + 3600000);
    if (index) assert.ok(row.t > result.bars[index - 1].t);
  }
}
const matrix = [
  ['search_stock', 'search_symbols', { query: 'AAPL', type_filter: 'stock' }],
  ['search_etf', 'search_symbols', { query: 'SPY', type_filter: 'etf' }],
  ['search_crypto', 'search_symbols', { query: 'BTCUSDT', type_filter: 'crypto' }],
  ['search_forex', 'search_symbols', { query: 'EURUSD', type_filter: 'forex' }],
  ['daily_rows', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 5 }, bars],
  ['hourly_etf', 'get_ohlcv', { symbol: 'AMEX:SPY', interval: '1h', count: 5 }, bars],
  ['weekly_crypto', 'get_ohlcv', { symbol: 'BINANCE:BTCUSDT', interval: '1W', count: 4 }, bars],
  ['forex_history', 'get_ohlcv', { symbol: 'OANDA:EURUSD', interval: '1D', count: 3 }, bars],
  ['historical_window', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 3, date_from: '2026-10-01', date_to: '2026-10-15' }, bars],
  ['summary_only', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 10, summary: true }, r => assert.ok(r.summary?.last_close > 0)],
  ['column_layout', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 5, format: 'columns' }, r => {
    assert.equal(r.format, 'columns'); assert.ok(Array.isArray(r.bars?.t) && r.bars.t.length === 5);
  }],
  ['stock_quote_feed', 'get_symbol_data', { symbol: 'NASDAQ:AAPL', columns: ['name', 'close', 'volume', 'update_mode'] }, r => assert.ok(r.data?.close > 0)],
  ['crypto_quote', 'get_symbol_data', { symbol: 'BINANCE:BTCUSDT', columns: ['name', 'close', 'update_mode'] }, r => assert.ok(r.data?.close > 0)],
  ['batch_quotes', 'get_symbol_data_batch', { symbols: ['NASDAQ:AAPL', 'NASDAQ:MSFT', 'AMEX:SPY'], columns: ['name', 'close', 'update_mode'] }],
  ['column_catalog', 'get_screener_columns', { market: 'stock', search: 'price_earnings' }],
  ['small_screener', 'run_screener', { market: 'america', filters: { index: 'S&P 500' }, limit: 3,
    sort_by: 'volume', columns: ['name', 'close'], symbol_types: ['stock'] }],
  ['technical_rating', 'get_technicals_rating', { symbol: 'NASDAQ:AAPL', interval: '1D' }],
  ['fundamentals', 'get_financials', { symbol: 'NASDAQ:AAPL', metric: ['pe', 'revenue'], period: 'ttm' }],
  ['fundamental_history', 'get_financial_history', { symbol: 'NASDAQ:AAPL', period: 'fq', date_from: '2025-01-01', date_to: date(0) }],
  ['analyst_forecasts', 'get_forecasts', { symbol: 'NASDAQ:AAPL' }],
  ['news', 'get_news', { symbol: 'NASDAQ:AAPL', lang: 'en', limit: 2 }],
  ['documents', 'get_documents', { symbol: 'NASDAQ:AAPL', category: 'transcripts', limit: 2 }],
  ['economic_catalog', 'get_economic_symbols', { country: 'US', search: 'inflation' }],
  ['earnings_calendar', 'get_earnings_calendar', { symbols: ['NASDAQ:AAPL', 'NASDAQ:MSFT'], date_from: date(-7), date_to: date(30) }],
  ['economic_calendar', 'get_economic_calendar', { countries: 'US', date_from: date(-3), date_to: date(3), min_importance: 1 }],
  ['dividend_calendar', 'get_dividends_calendar', { symbols: ['NASDAQ:AAPL', 'NASDAQ:MSFT'] }],
];

let blocked = false;
try {
  await withPortal('tradingview', async (client, events) => {
    async function run(name, tool, args, verify, expectedError = false) {
      if (blocked && !expectedError) { report.cases.push({ name, tool, status: 'blocked', origin: 'live' }); return; }
      const started = Date.now();
      try {
        const result = await client.callTool({ name: tool, arguments: args }, undefined, { timeout: 75000 });
        if (expectedError) {
          assert.equal(result.isError, true);
          const failure = JSON.parse(result.content[0].text);
          assert.ok(['tool_not_allowed', 'query_failed', 'invalid_arguments'].includes(failure.error));
          assert.ok(failure.attempts <= 1);
        } else {
          const payload = jsonResult(result);
          if ('success' in payload) assert.equal(payload.success, true);
          assert.ok(Object.keys(payload).length > 0);
          if (verify) verify(payload);
          raw[name] = payload;
        }
        report.cases.push({ name, tool, status: 'pass', origin: expectedError ? 'negative_case' : 'live', durationMs: Date.now() - started });
      } catch (error) {
        report.cases.push({ name, tool, status: 'fail', origin: expectedError ? 'negative_case' : 'live',
          kind: error.kind ?? 'assertion_or_protocol_failure', durationMs: Date.now() - started });
        if (['connection_lost', 'auth_required', 'circuit_open', 'timeout'].includes(error.kind)) blocked = true;
      }
      process.stderr.write(`${name}: ${report.cases.at(-1).status}\n`);
    }
    const tools = (await client.listTools({}, { timeout: 5000 })).tools;
    report.exposedTools = tools.map(tool => tool.name);
    report.dedicatedOptionsTools = tools.filter(tool => /option|greek|expiry|strike|chain/i.test(tool.name)).map(tool => tool.name);
    assert.ok(tools.every(tool => tool.annotations?.readOnlyHint === true));
    for (const name of ['place_order', 'create_alert', 'create_watchlist', 'mcp-tv-delete-alert']) {
      await run(`reject_${name}`, name, {}, null, true);
    }
    // Readiness is actual data, not discovery. A failure blocks further live traffic.
    await run('baseline_one_bar', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 1 }, bars);
    for (const item of matrix) await run(...item);
    if (!blocked) {
      const previous = raw.daily_rows?.next_date_to;
      if (previous) await run('history_pagination', 'get_ohlcv', {
        symbol: 'NASDAQ:AAPL', interval: '1D', count: 3, date_to: previous,
      }, r => { bars(r); assert.ok(r.bars.at(-1).t < raw.daily_rows.bars[0].t); });
      const story = raw.news?.data?.headlines?.find(item => typeof item.id === 'string')?.id;
      if (story) await run('news_story', 'get_news_story', { id: story });
      else report.cases.push({ name: 'news_story', status: 'blocked', reason: 'no_returned_story_id' });
      function viewId(v) {
        if (!v || typeof v !== 'object') return;
        if (Array.isArray(v.views)) return v.views.find(view => typeof view.id === 'string')?.id;
        for (const child of Object.values(v)) { const found = viewId(child); if (found) return found; }
      }
      const view = viewId(raw.documents);
      if (view) await run('document_text', 'get_document_view', { view_id: view });
      else report.cases.push({ name: 'document_text', status: 'blocked', reason: 'no_returned_view_id' });
      const economic = values(raw.economic_catalog).find(v => typeof v === 'string' && v.startsWith('ECONOMICS:US'));
      if (economic) await run('economic_series', 'get_economic_data', { symbol: economic, date_from: '2025-01-01', date_to: date(0) });
      else report.cases.push({ name: 'economic_series', status: 'blocked', reason: 'no_returned_economic_symbol' });
      for (let cycle = 1; cycle <= 8; cycle++) await run(`repeat_history_${cycle}`, 'get_ohlcv', {
        symbol: 'NASDAQ:AAPL', interval: '1D', count: 1,
      }, bars);
      for (const [name, args] of [['missing_symbol', {}], ['wrong_count_type', { symbol: 'NASDAQ:AAPL', count: 'five' }],
        ['invalid_date', { symbol: 'NASDAQ:AAPL', date_from: 'not-a-date' }]]) {
        await run(name, 'get_ohlcv', args, null, true);
      }
      await run('recovery_after_bad_input', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', count: 1 }, bars);
      await run('unsupported_options_filter', 'search_symbols', { query: 'AAPL', type_filter: 'option' }, null, true);
      report.optionsSearch = { typeFilterSupported: false, result: 'provider rejected option as a search filter' };
      const concurrentAt = Date.now();
      await Promise.all([1, 2, 3].map(cycle => run(`queued_read_${cycle}`, 'get_ohlcv', { symbol: 'NASDAQ:AAPL', count: 1 }, bars)));
      report.queueExerciseDurationMs = Date.now() - concurrentAt;
      const controller = new AbortController();
      const cancellation = setTimeout(() => controller.abort(), 10);
      try {
        await assert.rejects(client.callTool({ name: 'get_ohlcv', arguments: { symbol: 'NASDAQ:AAPL', count: 1 } }, undefined,
          { timeout: 75000, signal: controller.signal }), error => error.name === 'AbortError' || /abort/i.test(error.message));
        report.cases.push({ name: 'cancel_inflight_read', status: 'pass', origin: 'live_cancellation' });
      } catch { report.cases.push({ name: 'cancel_inflight_read', status: 'fail', kind: 'cancellation_not_observed' }); }
      finally { clearTimeout(cancellation); }
      await run('recovery_after_cancellation', 'get_ohlcv', { symbol: 'NASDAQ:AAPL', count: 1 }, bars);
    }
    report.portalStatus = jsonResult(await client.callTool({ name: 'portal_status', arguments: {} }, undefined, { timeout: 5000 }));
    report.events = events;
  });
  report.processCleanup = 'pass';
} catch (error) { report.processFailure = error.kind ?? 'protocol_or_cleanup_failure'; process.exitCode = 1; }
report.finishedAt = new Date().toISOString();
report.counts = Object.fromEntries(['pass', 'fail', 'blocked'].map(status => [status, report.cases.filter(item => item.status === status).length]));
report.status = report.processFailure || report.counts.fail ? 'partial_failure' : report.counts.blocked ? 'partial' : 'pass';
if (report.counts.fail) process.exitCode = 1;
await mkdir(path.join(STATE, 'reports'), { recursive: true, mode: 0o700 });
await writeFile(path.join(STATE, 'reports/tradingview-wide.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
process.stdout.write(JSON.stringify({ status: report.status, counts: report.counts, processCleanup: report.processCleanup,
  dedicatedOptionsTools: report.dedicatedOptionsTools, optionsSearch: report.optionsSearch, cases: report.cases }, null, 2) + '\n');
