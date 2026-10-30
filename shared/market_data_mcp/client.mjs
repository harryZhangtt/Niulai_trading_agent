// Reusable client entry point for the agent and integration checks.
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { setTimeout as sleep } from 'node:timers/promises';
import path from 'node:path';
import { ROOT, providerConfig } from './providers.mjs';

export async function withPortal(provider, callback) {
  providerConfig(provider);
  const events = [];
  const transport = new StdioClientTransport({
    command: 'python3', args: [path.join(ROOT, 'shared/market_data_mcp/manage.py'), 'serve', provider],
    cwd: ROOT, stderr: 'pipe',
  });
  let pending = '';
  transport.stderr?.on('data', data => {
    pending += data.toString();
    // Bounded, structured portal diagnostics only. Never forward arbitrary child stderr.
    if (pending.length > 16384) pending = '';
    const lines = pending.split('\n'); pending = lines.pop();
    for (const line of lines) {
      try {
        const value = JSON.parse(line);
        if (['connected', 'attempt_failed', 'retry_scheduled', 'circuit_opened',
          'upstream_protocol_error', 'protocol_error'].includes(value.event)) events.push(value);
        if (events.length > 1000) events.shift();
      } catch { /* No raw stderr in reports. */ }
    }
  });
  const client = new Client({ name: 'trading-agent-portal-client', version: '1.0.0' });
  let pid;
  try {
    await client.connect(transport, { timeout: 5000 });
    pid = transport.pid;
    return await callback(client, events);
  } finally {
    pid ??= transport.pid;
    await client.close();
    if (pid) {
      for (let attempt = 0; attempt < 40; attempt++) {
        try { process.kill(pid, 0); }
        catch (error) { if (error.code === 'ESRCH') { pid = null; break; } throw error; }
        await sleep(50);
      }
      if (pid) throw new Error('portal_process_cleanup_failed');
    }
  }
}

export function jsonResult(result) {
  if (result.isError) {
    const error = new Error('portal_query_failed');
    try { error.kind = JSON.parse(result.content[0].text).error; } catch { error.kind = 'query_failed'; }
    throw error;
  }
  return result.structuredContent ?? JSON.parse(result.content.find(item => item.type === 'text').text);
}
