export class PortalError extends Error {
  constructor(kind, { retryAfterMs, cause } = {}) {
    super(kind, { cause });
    this.kind = kind;
    this.retryAfterMs = retryAfterMs;
  }
}

// Error messages may contain credentials. Classify them in memory; expose codes only.
export function classify(error) {
  if (error instanceof PortalError || error?.kind) return error;
  const message = String(error?.message ?? error).toLowerCase();
  // Preserve codes from small local adapters without treating their error as text.
  if (['auth_required', 'entitlement_required', 'invalid_arguments', 'no_data', 'tool_not_allowed'].includes(message)) {
    return new PortalError(message);
  }
  const status = Number(error?.status ?? error?.statusCode ?? error?.cause?.status);
  const code = error?.code ?? error?.cause?.code;
  const header = error?.headers?.get?.('retry-after');
  let retryAfterMs;
  if (header) retryAfterMs = /^\d+(\.\d+)?$/.test(header)
    ? Number(header) * 1000 : Math.max(0, Date.parse(header) - Date.now());
  if ([401, 403].includes(status) || /\b(401|403)\b|unauthori[sz]ed|forbidden|oauth|authentication|api key is required|credentials|not logged in|no token|token.*expir|invalid.*token/.test(message)) {
    return new PortalError('auth_required');
  }
  if (status === 429 || /\b429\b|rate.?limit|too many requests/.test(message)) {
    return new PortalError('rate_limited', { retryAfterMs });
  }
  if (error?.name === 'AbortError' || error?.name === 'TimeoutError' || code === -32001 || /timeout|timed out/.test(message)) {
    return new PortalError('timeout');
  }
  if ([500, 502, 503, 504].includes(status) || /\b(500|502|503|504)\b|temporarily unavailable|service unavailable/.test(message)) {
    return new PortalError('upstream_unavailable', { retryAfterMs });
  }
  if (['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'EPIPE', 'EAI_AGAIN', 'ENETUNREACH'].includes(code)
      || /connection closed|connection reset|fetch failed|socket hang up|failed to fetch/.test(message)) {
    return new PortalError('connection_lost');
  }
  if (code === 'ENOENT' || /cannot find module/.test(message)) return new PortalError('setup_required');
  return new PortalError('query_failed');
}

export const TRANSIENT = new Set(['timeout', 'rate_limited', 'upstream_unavailable', 'connection_lost']);
export const RECONNECT = new Set(['timeout', 'connection_lost']);

export function checkResult(result) {
  if (!result || !Array.isArray(result.content)) throw new PortalError('invalid_response');
  // Some servers return JSON {error: ...} while incorrectly setting isError=false.
  const structured = result.structuredContent;
  let failed = result.isError || (structured && (structured.error || structured.status === 'error' || structured.success === false));
  let message = structured?.error?.message ?? structured?.error ?? '';
  for (const item of result.content) {
    if (item.type !== 'text') continue;
    message += ` ${item.text}`;
    try {
      const obj = JSON.parse(item.text);
      if (obj && (obj.error || obj.status === 'error' || obj.success === false)) {
        failed = true;
        if (typeof obj.error === 'string' && ['auth_required', 'entitlement_required', 'invalid_arguments', 'no_data',
          'tool_not_allowed', 'rate_limited', 'upstream_unavailable', 'timeout', 'connection_lost', 'invalid_response'].includes(obj.error)) {
          throw new PortalError(obj.error, { retryAfterMs: obj.retry_after_ms });
        }
      }
    } catch (error) { if (error instanceof PortalError) throw error; /* Text is valid MCP content. */ }
  }
  if (failed) throw classify(new Error(message || 'upstream tool error'));
  return result;
}

export function publicFailure(error, provider, attempts) {
  const kind = classify(error).kind;
  return {
    isError: true,
    content: [{ type: 'text', text: JSON.stringify({
      error: kind, provider, attempts,
      action: kind === 'auth_required'
        ? `Run python3 shared/market_data_mcp/manage.py auth ${provider}`
        : kind === 'setup_required' ? 'See shared/market_data_mcp/README.md'
        : 'Retry the read-only query later; no data was substituted.',
    }) }],
  };
}
