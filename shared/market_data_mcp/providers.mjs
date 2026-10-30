// Provider-specific capabilities and transports. No retry or server logic here.
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { tradingViewTransport } from './adapters/tradingview.mjs';
import { finnhubTransport } from './adapters/finnhub.mjs';
import { marketdataTransport } from './adapters/marketdata.mjs';
import { alpacaTransport } from './adapters/alpaca.mjs';
import { massiveTransport } from './adapters/massive.mjs';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const STATE = path.join(ROOT, '.market-data-mcp');
export const PROVIDERS = {
  alpaca: {
    official: false,
    upstream: 'https://docs.alpaca.markets/us/reference/optionchain',
    authUrl: 'https://app.alpaca.markets/',
    tools: ['option_chain', 'option_snapshots'],
  },
  massive: {
    official: false,
    upstream: 'https://massive.com/docs/rest/options/contracts/all-contracts',
    authUrl: 'https://massive.com/dashboard/',
    tools: ['option_contracts', 'option_daily_bars'],
  },
  marketdata: {
    official: false,
    upstream: 'https://www.marketdata.app/docs/api/',
    authUrl: 'https://www.marketdata.app/signup/',
    tools: ['option_expirations', 'option_chain', 'option_quote'],
  },
  finnhub: {
    official: false,
    upstream: 'https://finnhub.io/docs/api/introduction',
    hostedMcp: 'https://mcp.finnhub.io/mcp',
    authUrl: 'https://finnhub.io/static/finnhub-how-to-connect-mcp-server.html',
    tools: ['quote', 'company_profile', 'symbol_lookup', 'basic_financials'],
  },
  tradingview: {
    official: true,
    url: 'https://mcp.tradingview.com/mcp',
    authUrl: 'https://www.tradingview.com/mcp/docs',
    tools: [
      'get_ohlcv', 'get_economic_data', 'get_economic_symbols', 'search_symbols',
      'get_symbol_data', 'run_screener', 'get_symbol_data_batch',
      'get_screener_columns', 'get_technicals_rating', 'get_news', 'get_news_story',
      'get_forecasts', 'get_financials', 'get_financial_history', 'get_documents',
      'get_document_view', 'get_earnings_calendar', 'get_economic_calendar',
      'get_dividends_calendar',
    ],
  },
  schwab: {
    official: false,
    upstream: 'https://github.com/itsmostafa/schwab-mcp/tree/v0.2.3',
    authUrl: 'https://developer.schwab.com/',
    tools: [
      'get_quotes', 'get_option_chain', 'get_option_expirations',
      'get_price_history', 'get_movers', 'get_market_hours',
      'search_instruments', 'get_instrument',
    ],
  },
};

export function providerConfig(name) {
  const config = PROVIDERS[name];
  if (!config) throw new Error(`Unsupported provider: ${name}`);
  return { ...config, toolMap: Object.fromEntries(config.tools.map(tool => [tool,
    name === 'tradingview' ? `mcp-tv-${tool.replaceAll('_', '-')}` : tool])) };
}

export function makeTransport(name, env = process.env) {
  providerConfig(name);
  if (name === 'tradingview') return tradingViewTransport(path.join(STATE, 'tradingview'));
  if (name === 'finnhub') return finnhubTransport(path.join(STATE, 'credentials/finnhub.json'));
  if (name === 'marketdata') return marketdataTransport(path.join(STATE, 'credentials/marketdata.json'));
  if (name === 'alpaca') return alpacaTransport(path.join(STATE, 'credentials/alpaca.json'));
  if (name === 'massive') return massiveTransport(path.join(STATE, 'credentials/massive.json'));
  if (!env.SCHWAB_APP_KEY || !env.SCHWAB_APP_SECRET) {
    const error = new Error('Schwab Developer app credentials are missing.');
    error.kind = 'auth_required';
    throw error;
  }
  const transport = new StdioClientTransport({
    command: path.join(STATE, 'bin/schwab'), args: ['mcp'], cwd: ROOT, stderr: 'pipe',
    env: Object.fromEntries(Object.entries({
      ...env,
      MCP_REMOTE_CONFIG_DIR: path.join(STATE, 'tradingview'),
      SCHWAB_TOKEN_FILE: path.join(STATE, 'schwab/token.json'),
      SCHWAB_ALLOW_TRADING: 'false', SCHWAB_ALLOW_MARKET_ORDERS: 'false',
      TMPDIR: path.join(STATE, 'tmp'),
    }).filter(([, value]) => typeof value === 'string')),
  });
  // Upstream diagnostics can contain OAuth URLs and tool payloads. Never relay them.
  transport.stderr?.on('data', () => {});
  return transport;
}
