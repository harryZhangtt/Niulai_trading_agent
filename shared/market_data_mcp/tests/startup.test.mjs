import test from 'node:test';
import assert from 'node:assert/strict';
import { withPortal, jsonResult } from '../client.mjs';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import path from 'node:path';
import { ROOT } from '../providers.mjs';

for (const provider of ['tradingview', 'schwab', 'finnhub', 'marketdata', 'alpaca', 'massive']) {
  test(`${provider}: network-free protocol startup, safe status, denied writes, child cleanup`, { timeout: 10000 }, async () => {
    await withPortal(provider, async (client, events) => {
      const tools = await client.listTools({}, { timeout: 2000 });
      assert.ok(tools.tools.some(tool => tool.name === 'portal_status'));
      const status = jsonResult(await client.callTool({ name: 'portal_status', arguments: {} }, undefined, { timeout: 2000 }));
      assert.equal(status.connection, 'not_connected');
      assert.equal(status.schemasAreLiveHealthCheck, false);
      assert.equal(events.length, 0);
      const denied = await client.callTool({ name: 'place_order', arguments: {} }, undefined, { timeout: 2000 });
      assert.equal(JSON.parse(denied.content[0].text).error, 'tool_not_allowed');
      assert.equal(events.length, 0);
    });
  });
}

test('repeated offline restarts and SIGTERM leave no portal process behind', { timeout: 10000 }, async () => {
  for (let cycle = 0; cycle < 3; cycle++) {
    await withPortal('tradingview', async client => {
      const closed = new Promise(resolve => { client.onclose = resolve; });
      process.kill(client.transport.pid, 'SIGTERM');
      await closed;
    });
  }
});

test('malformed JSON is contained; subsequent protocol initialization succeeds', { timeout: 5000 }, async t => {
  const child = spawn(process.execPath, [path.join(ROOT, 'shared/market_data_mcp/server.mjs'), 'tradingview'],
    { cwd: ROOT, stdio: ['pipe', 'pipe', 'pipe'] });
  child.stderr.resume();
  t.after(async () => { if (child.exitCode === null) { const closed = once(child, 'close'); child.kill('SIGTERM'); await closed; } });
  const response = new Promise((resolve, reject) => {
    let buffer = '';
    child.stdout.on('data', chunk => {
      buffer += chunk;
      for (const line of buffer.split('\n').slice(0, -1)) {
        const value = JSON.parse(line);
        if (value.id === 1) resolve(value);
      }
    });
    child.once('error', reject);
  });
  child.stdin.write('malformed-json\n');
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: {
    protocolVersion: '2025-03-26', capabilities: {}, clientInfo: { name: 'malformed-input-test', version: '1' },
  } }) + '\n');
  const value = await response;
  assert.equal(value.result.serverInfo.name, 'tradingview-query-portal');
});
