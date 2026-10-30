// Thin MCP protocol boundary. All provider IO and resilience live in other modules.
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { QueryPortal } from './core/portal.mjs';
import { providerConfig, makeTransport } from './providers.mjs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { STATE } from './providers.mjs';
import { OperationStats } from './core/observations.mjs';

const provider = process.argv[2];
const config = providerConfig(provider);
const log = event => process.stderr.write(`${JSON.stringify({ time: new Date().toISOString(), ...event })}\n`);
const observations = new OperationStats({ provider, file: path.join(STATE, 'runtime', `${provider}-observations.json`) });
await observations.load();
const portal = new QueryPortal({ provider, allowedTools: config.tools,
  toolMap: config.toolMap, transportFactory: () => makeTransport(provider), log, observations });
// Schema snapshots contain only public tool definitions. Startup is network-free.
let manifest = [];
try {
  const snapshot = JSON.parse(await readFile(new URL(`./schemas/${provider}.json`, import.meta.url), 'utf8'));
  manifest = snapshot.tools.filter(tool => config.tools.includes(tool.name)
    && tool.annotations?.readOnlyHint === true && tool.annotations?.destructiveHint !== true);
} catch (error) {
  if (error.code !== 'ENOENT') throw new Error('Invalid public tool schema snapshot');
}
const statusTool = { name: 'portal_status', description: 'Local portal connection and circuit status; performs no provider network IO.',
  inputSchema: { type: 'object', properties: {}, additionalProperties: false }, annotations: { readOnlyHint: true } };
const server = new Server({ name: `${provider}-query-portal`, version: '1.0.0' },
  { capabilities: { tools: {} }, instructions: 'Read-only market data. Errors never contain substituted or cached prices.' });
server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: [statusTool, ...manifest] }));
server.setRequestHandler(CallToolRequestSchema, (request, extra) =>
  request.params.name === 'portal_status'
    ? { content: [{ type: 'text', text: JSON.stringify({ ...portal.status(),
      schemaTools: manifest.length, schemasAreLiveHealthCheck: false }) }] }
    : portal.callTool(request.params.name, request.params.arguments, extra.signal));
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  await portal.close();
  await server.close();
}
process.on('SIGINT', () => { void stop(); });
process.on('SIGTERM', () => { void stop(); });
function fatal() {
  log({ event: 'fatal_error', provider });
  void stop().finally(() => { process.exitCode = 1; });
}
process.on('uncaughtException', fatal);
process.on('unhandledRejection', fatal);
server.onclose = () => { void stop(); };
server.onerror = () => log({ event: 'protocol_error', provider });
await server.connect(new StdioServerTransport());
