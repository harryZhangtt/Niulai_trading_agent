// Isolated candidate only. Never registered in active host/provider configuration.
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdirSync } from 'node:fs';
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');

export function arxivResearchTransport() {
  const state = path.join(ROOT, '.niulai-state/reports/research-sources');
  for (const part of ['runtime/arxiv', 'runtime/arxiv/papers', 'tmp', 'cache']) {
    mkdirSync(path.join(state, part), { recursive: true, mode: 0o700 });
  }
  const env = {};
  for (const key of ['PATH', 'HOME', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'HTTPS_PROXY', 'https_proxy']) {
    if (process.env[key]) env[key] = process.env[key];
  }
  Object.assign(env, { PYTHONDONTWRITEBYTECODE: '1', TMPDIR: path.join(state, 'tmp'),
    XDG_CACHE_HOME: path.join(state, 'cache'), TRANSPORT: 'stdio', REQUEST_TIMEOUT: '15',
    ARXIV_REQUEST_TIMEOUT: '15', ARXIV_MAX_TOTAL_TIME: '25', ARXIV_MAX_RETRIES: '0' });
  const transport = new StdioClientTransport({ command: path.join(ROOT, '.research-sources/.venv/bin/arxiv-mcp-server'),
    args: ['--storage-path', path.join(state, 'runtime/arxiv/papers')],
    cwd: path.join(state, 'runtime/arxiv'), env, stderr: 'pipe' });
  transport.stderr?.on('data', () => {});
  return transport;
}

export async function materializeArxivPaper(paperId, signal) {
  if (!/^\d{4}\.\d{4,5}v[1-9]\d*$/.test(paperId)) throw new Error('versioned_paper_id_required');
  const transport = arxivResearchTransport();
  const client = new Client({ name: 'explicit-arxiv-cache-fetch', version: '1.0.0' });
  try {
    await client.connect(transport, { timeout: 5000, signal });
    // This is a separate, explicitly bounded local-cache mutation. The general
    // read-only portal continues to reject all tools annotated readOnlyHint=false.
    return await client.callTool({ name: 'download_paper',
      arguments: { paper_id: paperId, max_chars: 2000, force: false, return_full_text: false } },
      undefined, { timeout: 45000, signal });
  } finally {
    await client.close();
  }
}
