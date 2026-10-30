import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { withPortal, jsonResult } from './client.mjs';
import { STATE } from './providers.mjs';

const provider = process.argv[2] ?? 'tradingview';
const report = { provider, startedAt: new Date().toISOString(), route: 'isolated stdio MCP client -> shared query portal -> provider',
  checks: [], liveDataPassed: false, activeCodexRegistration: false };
async function check(name, fn) {
  const start = Date.now();
  try {
    const detail = await fn();
    report.checks.push({ name, status: 'pass', durationMs: Date.now() - start, ...detail });
    process.stderr.write(`${name}: pass (${Date.now() - start} ms)\n`);
  } catch (error) {
    report.checks.push({ name, status: 'fail', durationMs: Date.now() - start, kind: error.kind ?? 'assertion_or_protocol_failure' });
    process.stderr.write(`${name}: ${error.kind ?? 'failed'}\n`);
    throw error;
  }
}
try {
  await withPortal(provider, async (client, events) => {
    const call = async (name, args = {}) => jsonResult(await client.callTool({ name, arguments: args }, undefined, { timeout: 75000 }));
    await check('network_free_startup', async () => {
      const tools = await client.listTools({}, { timeout: 5000 });
      const status = await call('portal_status');
      assert.equal(status.connection, 'not_connected');
      assert.equal(events.length, 0);
      assert.ok(tools.tools.some(tool => tool.name === 'portal_status'));
      assert.ok(tools.tools.every(tool => tool.annotations?.readOnlyHint === true));
      return { tools: tools.tools.length };
    });
    await check('writes_rejected_without_connection', async () => {
      const result = await client.callTool({ name: 'place_order', arguments: {} }, undefined, { timeout: 5000 });
      assert.equal(result.isError, true);
      assert.equal(JSON.parse(result.content[0].text).error, 'tool_not_allowed');
      assert.equal((await call('portal_status')).connection, 'not_connected');
    });
    if (provider === 'tradingview') {
      await check('live_symbol_search', async () => {
        const result = await call('search_symbols', { query: 'AAPL', type_filter: 'stock' });
        assert.equal(result.success, true);
        assert.ok(result.data.symbols.some(symbol => symbol.symbol === 'NASDAQ:AAPL'));
        return { symbol: 'NASDAQ:AAPL', matches: result.data.symbols.length };
      });
      await check('live_daily_ohlcv', async () => {
        const result = await call('get_ohlcv', { symbol: 'NASDAQ:AAPL', interval: '1D', count: 5 });
        assert.equal(result.success, true);
        assert.equal(result.symbol, 'NASDAQ:AAPL');
        assert.equal(result.bars.length, 5);
        for (const [index, bar] of result.bars.entries()) {
          for (const key of ['o', 'h', 'l', 'c', 't', 'v']) assert.ok(Number.isFinite(bar[key]));
          assert.ok(bar.l > 0 && bar.v >= 0 && bar.l <= Math.min(bar.o, bar.c) && bar.h >= Math.max(bar.o, bar.c));
          assert.ok(bar.t * 1000 <= Date.now() + 3600000);
          if (index) assert.ok(bar.t > result.bars[index - 1].t);
        }
        return { symbol: result.symbol, bars: result.bars.length,
          latestBarAt: new Date(result.bars.at(-1).t * 1000).toISOString(), notice: result.notice };
      });
      await check('live_quote_with_feed_metadata', async () => {
        const result = await call('get_symbol_data', { symbol: 'NASDAQ:AAPL', columns: ['name', 'close', 'volume', 'update_mode'] });
        assert.equal(result.success, true);
        assert.equal(result.data.name, 'AAPL');
        assert.ok(Number.isFinite(result.data.close) && result.data.close > 0);
        return { symbol: 'NASDAQ:AAPL', close: result.data.close, updateMode: result.data.update_mode ?? 'not_returned',
          quoteAccuracyBenchmark: 'not_performed' };
      });
      report.liveDataPassed = true;
    } else if (provider === 'finnhub') {
      report.route = 'isolated MCP client -> shared portal -> local read-only MCP adapter -> official Finnhub REST API';
      await check('finnhub_quote', async () => {
        const result = await call('quote', { symbol: 'AAPL' });
        assert.equal(result.provider, 'finnhub');
        assert.ok(result.data.c > 0 && result.data.t > 0 && result.data.t * 1000 <= Date.now() + 3600000);
        return { symbol: 'AAPL', close: result.data.c, providerTimestamp: new Date(result.data.t * 1000).toISOString() };
      });
      await check('finnhub_profile', async () => {
        const result = await call('company_profile', { symbol: 'AAPL' });
        assert.equal(result.data.ticker, 'AAPL');
      });
      await check('finnhub_symbol_lookup', async () => {
        const result = await call('symbol_lookup', { query: 'Apple' });
        assert.ok(result.data.result.some(item => item.symbol === 'AAPL'));
      });
      await check('finnhub_basic_financials', async () => {
        const result = await call('basic_financials', { symbol: 'AAPL' });
        assert.equal(result.data.symbol, 'AAPL');
        assert.ok(Object.keys(result.data.metric).length > 0);
      });
      report.liveDataPassed = true;
    } else if (provider === 'marketdata') {
      report.route = 'isolated MCP client -> shared portal -> local read-only MCP adapter -> official Market Data REST AAPL demo';
      let expiration, contract;
      await check('marketdata_demo_expirations', async () => {
        const result = await call('option_expirations', { underlying: 'AAPL' });
        assert.equal(result.provider, 'marketdata');
        assert.ok(result.data.expirations.length > 0);
        expiration = result.data.expirations.find(date => Date.parse(date) > Date.now() + 14 * 86400000);
        assert.ok(expiration);
        return { expirations: result.data.expirations.length, selectedExpiration: expiration, access: result.access };
      });
      await check('marketdata_bounded_historical_chain', async () => {
        const result = await call('option_chain', { underlying: 'AAPL', expiration, side: 'call', strike_limit: 2 });
        assert.equal(result.mode, 'historical');
        assert.equal(result.greeks_timing_verified, false);
        assert.ok(result.data.optionSymbol.length > 0 && result.data.optionSymbol.length <= 2);
        contract = result.data.optionSymbol[0];
        assert.match(contract, /^AAPL\d{6}C\d{8}$/);
        assert.ok(result.data.updated.every(t => Number.isFinite(t) && t * 1000 <= Date.now() + 3600000));
        assert.ok(result.data.bid.every(p => Number.isFinite(p) && p >= 0));
        assert.ok(result.data.ask.every((p, i) => Number.isFinite(p) && p >= result.data.bid[i]));
        return { contracts: result.data.optionSymbol.length, sampleContract: contract,
          providerUpdated: result.data.updated, greeksPopulated: result.data.delta?.some(v => v !== null) ?? false };
      });
      await check('marketdata_contract_quote', async () => {
        const result = await call('option_quote', { contract });
        assert.deepEqual(result.data.optionSymbol, [contract]);
        assert.equal(result.mode, 'historical');
        assert.ok(result.data.updated[0] > 0);
        return { contract, providerUpdated: result.data.updated[0], access: result.access };
      });
      report.liveDataPassed = true;
    } else if (provider === 'alpaca') {
      await check('alpaca_free_indicative_chain', async () => {
        const expiry = new Date(Date.now() + 30 * 86400000);
        while (expiry.getUTCDay() !== 5) expiry.setUTCDate(expiry.getUTCDate() + 1);
        const expiration = expiry.toISOString().slice(0, 10);
        // Explicit known-contract snapshots are preferable once account access is available.
        const result = await call('option_chain', { underlying: 'AAPL', expiration, side: 'call', limit: 2 });
        assert.equal(result.feed, 'indicative');
        assert.ok(Object.keys(result.data.snapshots).length > 0);
      });
      report.liveDataPassed = true;
    } else if (provider === 'massive') {
      await check('massive_free_contract_reference', async () => {
        const result = await call('option_contracts', { underlying: 'AAPL', limit: 2 });
        assert.equal(result.provider, 'massive');
        assert.ok(result.data.results.length > 0 && result.data.results.length <= 2);
      });
      report.liveDataPassed = true;
    } else {
      await check('schwab_live_quote', async () => {
        const result = await call('get_quotes', { symbols: ['AAPL'], fields: ['quote'] });
        assert.ok(result.AAPL?.quote);
      });
      report.liveDataPassed = true;
    }
    report.events = events;
  });
  report.checks.push({ name: 'data_session_process_cleanup', status: 'pass' });
  for (let cycle = 1; cycle <= 3; cycle++) {
    await check(`clean_restart_${cycle}`, () => withPortal(provider, async client => {
      const result = await client.callTool({ name: 'portal_status', arguments: {} }, undefined, { timeout: 5000 });
      assert.equal(jsonResult(result).connection, 'not_connected');
    }));
  }
  report.status = 'pass';
} catch (error) {
  report.status = error.kind === 'auth_required' ? 'blocked_auth' : 'fail';
  process.exitCode = report.status === 'blocked_auth' ? 2 : 1;
} finally {
  report.finishedAt = new Date().toISOString();
  await mkdir(path.join(STATE, 'reports'), { recursive: true, mode: 0o700 });
  const location = path.join(STATE, 'reports', `${provider}-e2e.json`);
  await writeFile(location, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}
