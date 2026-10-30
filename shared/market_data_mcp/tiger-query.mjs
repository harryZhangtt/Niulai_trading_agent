// Dedicated isolated entry: context via private parent pipe, never MCP tool arguments.
import { tigerTransport, TIGER_TOOLS } from './adapters/tiger.mjs';
import { QueryPortal } from './core/portal.mjs';

let raw = '', context, receipt, portal, inputTimer;
try {
  inputTimer = setTimeout(() => process.exit(2), 15000);
  for await (const chunk of process.stdin) {
    raw += chunk.toString();
    if (Buffer.byteLength(raw) > 1024 * 1024) throw new Error();
  }
  clearTimeout(inputTimer);
  context = JSON.parse(raw);
  raw = '';
  const query = context.query;
  delete context.query;
  portal = new QueryPortal({ provider: 'tiger', allowedTools: TIGER_TOOLS.map(t => t.name),
    transportFactory: () => tigerTransport(context, { onReceipt: value => { receipt = value; } }),
    // The remote store's idempotent retry is the only added retry layer.
    policy: { maxAttempts: 1, timeoutMs: 110000, totalTimeoutMs: 115000, maxPending: 1 } });
  const result = await portal.callTool(query.tool, query.arguments);
  if (!receipt) receipt = { status: 'failed', error: 'TIGER_QUERY_REJECTED', automatic_retry: false };
  receipt.portal = { route: 'isolated MCP adapter → official Tiger SDK',
    max_attempts: 1, query_succeeded: !result.isError, host_registered: false };
} catch {
  receipt = { status: 'failed', error: 'TIGER_PORTAL_FAILED', automatic_retry: false };
} finally {
  clearTimeout(inputTimer);
  raw = ''; context = null;
  await portal?.close();
}
process.stdout.write(JSON.stringify(receipt) + '\n');
process.exitCode = receipt.status === 'queried' && receipt.portal?.query_succeeded ? 0 : 2;
