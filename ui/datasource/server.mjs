import http from 'node:http';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readFile, realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const APP = path.join(ROOT, 'ui/datasource');
const MAX_BYTES = 2 * 1024 * 1024;

function codeError(code) { return Object.assign(new Error(code), { code }); }
function json(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' });
  res.end(JSON.stringify(data));
}

export function queryOptions(url) {
  const subject = (url.searchParams.get('subject') || 'NOW').trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9_.-]{0,31}$/.test(subject)) throw codeError('INVALID_SUBJECT');
  const limit = Number(url.searchParams.get('limit') || 100);
  const offset = Number(url.searchParams.get('offset') || 0);
  const snapshot = url.searchParams.get('snapshot_id');
  if (!Number.isInteger(limit) || limit < 1 || limit > 100 || !Number.isInteger(offset) || offset < 0 || offset > 10000 ||
      (snapshot !== null && !/^[a-f0-9]{64}$/.test(snapshot))) throw codeError('INVALID_PAGINATION');
  return { subject, limit, offset, snapshot };
}

export class ProjectionBridge {
  constructor({ loader = null, ttl = 2000, timeout = 8000 } = {}) {
    this.loader = loader; this.ttl = ttl; this.timeout = timeout;
    this.cache = new Map(); this.pending = new Map(); this.children = new Set(); this.closed = false;
  }
  async load(options) {
    if (this.loader) return this.loader(options);
    const args = ['-B', '-m', 'investment.research.datasource', '--subject', options.subject,
      '--limit', String(options.limit), '--offset', String(options.offset)];
    if (options.snapshot) args.push('--snapshot-id', options.snapshot);
    return new Promise((resolve, reject) => {
      const child = execFile(path.join(ROOT, '.research-sources/.venv/bin/python'), args, {
        cwd: ROOT, timeout: this.timeout, killSignal: 'SIGKILL', maxBuffer: MAX_BYTES,
        env: { PATH: '/usr/bin:/bin:/usr/sbin:/sbin', PYTHONPATH: ROOT, PYTHONDONTWRITEBYTECODE: '1',
          TMPDIR: path.join(ROOT, 'ui/runtime/tmp'), LANG: 'en_US.UTF-8' },
      }, (error, stdout) => {
        this.children.delete(child);
        let data;
        try { data = JSON.parse(stdout); } catch { reject(codeError('PROJECTION_UNAVAILABLE')); return; }
        if (data?.warnings?.some(w => w.code === 'PROJECTION_SNAPSHOT_CHANGED')) {
          reject(codeError('PROJECTION_SNAPSHOT_CHANGED')); return;
        }
        if (error || data?.schema_version !== 1 || !Array.isArray(data.sources) || data.status === 'unavailable') {
          reject(codeError('PROJECTION_UNAVAILABLE')); return;
        }
        resolve(data);
      });
      this.children.add(child);
    });
  }
  async get(options, { force = false } = {}) {
    if (this.closed) throw codeError('SERVER_CLOSING');
    const key = JSON.stringify(options); const previous = this.cache.get(key);
    if (!force && previous && Date.now() - previous.at < this.ttl) return previous.data;
    if (this.pending.has(key)) return this.pending.get(key);
    if (this.pending.size >= 8) throw codeError('PROJECTION_BUSY');
    const promise = this.load(options).then(data => {
      if (this.cache.size >= 16 && !this.cache.has(key)) this.cache.delete(this.cache.keys().next().value);
      this.cache.set(key, { data, at: Date.now() }); return data;
    }).catch(error => {
      if (error.code === 'PROJECTION_SNAPSHOT_CHANGED' || !previous) throw error;
      return { ...previous.data, status: 'partial', projection_state: 'stale',
        warnings: [...previous.data.warnings, { code: 'PROJECTION_REFRESH_FAILED', count: 1 }] };
    }).finally(() => this.pending.delete(key));
    this.pending.set(key, promise); return promise;
  }
  close() { this.closed = true; for (const child of this.children) child.kill('SIGKILL'); this.children.clear(); }
}

export async function identity() {
  const workspace = await realpath(ROOT);
  const files = await Promise.all(['server.mjs', 'dev.mjs'].map(name => readFile(path.join(APP, name))));
  return { app: 'trading-agent-datasource', workspace_id: createHash('sha256').update(workspace).digest('hex').slice(0, 16),
    server_fingerprint: createHash('sha256').update(Buffer.concat(files)).digest('hex') };
}

export async function health(port, host = '127.0.0.1') {
  return new Promise(resolve => {
    let req; let settled = false;
    const finish = value => { if (settled) return; settled = true; clearTimeout(timer); req?.destroy(); resolve(value); };
    const timer = setTimeout(() => finish(null), 700);
    try {
      req = http.get({ host, port, path: '/api/datasource/health', timeout: 700 }, res => {
        let data = '';
        res.on('data', chunk => { data += chunk; if (data.length > 8192) finish(null); });
        res.on('aborted', () => finish(null)); res.on('error', () => finish(null));
        res.on('end', () => { try { finish(JSON.parse(data)); } catch { finish(null); } });
      });
      req.on('timeout', () => finish(null)); req.on('error', () => finish(null));
    } catch { finish(null); }
  });
}

async function listen(server, port, host) {
  return new Promise((resolve, reject) => {
    const fail = error => { server.off('listening', ready); reject(error); };
    const ready = () => { server.off('error', fail); resolve(); };
    server.once('error', fail); server.once('listening', ready); server.listen({ host, port, exclusive: true });
  });
}

export async function start({ port = 7270, bridge = new ProjectionBridge(), viteFactory = null } = {}) {
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw codeError('INVALID_PORT');
  await mkdir(path.join(ROOT, 'ui/runtime/tmp'), { recursive: true });
  const owner = await identity(); let ready = false; let vite; let closing = false;
  const handler = (req, res) => {
    const host = req.headers.host || '';
    if (![ `localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}` ].includes(host)) {
      json(res, 403, { error: { code: 'LOCALHOST_ONLY' } }); return;
    }
    if (req.headers.origin && ![`http://localhost:${port}`, `http://127.0.0.1:${port}`, `http://[::1]:${port}`].includes(req.headers.origin)) {
      json(res, 403, { error: { code: 'ORIGIN_REJECTED' } }); return;
    }
    if (!['GET', 'HEAD'].includes(req.method)) { json(res, 405, { error: { code: 'READ_ONLY' } }); return; }
    let url; try { url = new URL(req.url, `http://localhost:${port}`); } catch { json(res, 400, { error: { code: 'INVALID_URL' } }); return; }
    if (url.pathname === '/api/datasource/health') {
      json(res, 200, { ...owner, status: ready ? 'ready' : 'starting', port, read_only: true }); return;
    }
    if (url.pathname === '/api/datasource') {
      let options; try { options = queryOptions(url); } catch (error) { json(res, 400, { error: { code: error.code } }); return; }
      bridge.get(options, { force: url.searchParams.get('refresh') === '1' }).then(data => json(res, 200, data)).catch(error => {
        const changed = error.code === 'PROJECTION_SNAPSHOT_CHANGED';
        json(res, changed ? 409 : 503, { error: { code: changed ? error.code : 'PROJECTION_UNAVAILABLE' } });
      }); return;
    }
    if (url.pathname.startsWith('/api/')) { json(res, 404, { error: { code: 'NOT_FOUND' } }); return; }
    if (!ready) { json(res, 503, { error: { code: 'STARTING' } }); return; }
    if (url.pathname === '/') { res.writeHead(302, { Location: '/datasource' }); res.end(); return; }
    vite.middlewares(req, res, () => { res.writeHead(404); res.end('Not found'); });
  };
  const server = http.createServer(handler); const ipv6 = http.createServer(handler); const sockets = new Set();
  for (const listener of [server, ipv6]) {
    listener.maxConnections = 256;
    listener.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });
  }
  server.on('upgrade', (req, socket) => {
    const host = req.headers.host;
    const allowedHost = [`localhost:${port}`, `127.0.0.1:${port}`, `[::1]:${port}`].includes(host);
    const allowedOrigin = !req.headers.origin || [`http://localhost:${port}`, `http://127.0.0.1:${port}`, `http://[::1]:${port}`].includes(req.headers.origin);
    if (!allowedHost || !allowedOrigin || req.headers['sec-websocket-protocol'] !== 'vite-hmr') socket.destroy();
  });
  server.requestTimeout = ipv6.requestTimeout = 15000;
  async function close() {
    if (closing) return; closing = true; ready = false; bridge.close();
    // HTTP closeAllConnections excludes upgraded sockets. They are still ours.
    for (const socket of sockets) socket.destroy();
    if (vite) await vite.close();
    await Promise.all([server, ipv6].map(s => new Promise(resolve => {
      if (!s.listening) { resolve(); return; }
      s.close(resolve); s.closeIdleConnections(); s.closeAllConnections();
    })));
  }
  try {
    await listen(server, port, '127.0.0.1');
    try { await listen(ipv6, port, '::1'); } catch (error) {
      if (!['EAFNOSUPPORT', 'EADDRNOTAVAIL'].includes(error.code)) throw error;
    }
    ipv6.on('upgrade', (...args) => server.emit('upgrade', ...args));
    const create = viteFactory || (await import('vite')).createServer;
    vite = await create({ root: APP, publicDir: false, envPrefix: 'DATASOURCE_PUBLIC_',
      server: { middlewareMode: true, hmr: { server, clientPort: port },
        fs: { strict: true, allow: [APP, path.join(ROOT, 'node_modules'), path.join(ROOT, 'ui/runtime/datasource-vite-cache')],
          deny: ['**/.env*', '**/*.{pem,key,p12}', '**/.niulai-state/**', '**/.job-runtime/**',
            '**/niulai-private/**', '**/.research-sources/**', '**/mentor/runtime/**'] } } });
    ready = true;
    return { server, ipv6, bridge, owner, close, port };
  } catch (error) { await close(); throw error; }
}
