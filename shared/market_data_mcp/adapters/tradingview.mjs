import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { LocalOAuthProvider } from '../auth/local-oauth.mjs';
import { PortalError } from '../core/errors.mjs';

export function createTradingViewFetch(fetchImpl = fetch) {
  return async (input, init = {}) => {
      const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
      if (url.protocol !== 'https:' || !['mcp.tradingview.com', 'www.tradingview.com'].includes(url.hostname)) {
        throw new PortalError('untrusted_endpoint');
      }
      const timeout = AbortSignal.timeout(20000);
      const signal = init.signal ? AbortSignal.any([init.signal, timeout]) : timeout;
      const response = await fetchImpl(input, { ...init, signal, redirect: 'manual' });
      if (response.status === 429 || [500, 502, 503, 504].includes(response.status)) {
        const header = response.headers.get('retry-after');
        const retryAfterMs = header && /^\d+(\.\d+)?$/.test(header)
          ? Number(header) * 1000 : header ? Math.max(0, Date.parse(header) - Date.now()) : undefined;
        await response.body?.cancel();
        throw new PortalError(response.status === 429 ? 'rate_limited' : 'upstream_unavailable', { retryAfterMs });
      }
      return response;
  };
}

export function tradingViewTransport(directory) {
  const serverUrl = 'https://mcp.tradingview.com/mcp';
  return new StreamableHTTPClientTransport(new URL(serverUrl), {
    authProvider: new LocalOAuthProvider(directory, serverUrl),
    redirectPolicy: 'same-origin',
    // One retry owner: the shared portal. Disable the SDK's separate SSE retry loop.
    reconnectionOptions: { maxRetries: 0, initialReconnectionDelay: 500,
      maxReconnectionDelay: 500, reconnectionDelayGrowFactor: 1 },
    fetch: createTradingViewFetch(),
  });
}
