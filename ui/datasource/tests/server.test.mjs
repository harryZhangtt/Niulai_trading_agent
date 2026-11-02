import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { start, health, ProjectionBridge, queryOptions, ROOT } from '../server.mjs';

const run = promisify(execFile);
const options = { subject: 'NOW', limit: 100, offset: 0, snapshot: null };
const sample = { schema_version: 1, generated_at: '2026-01-01T00:00:00Z', sources: [], warnings: [], status: 'ok' };
const fakeVite = async () => ({ middlewares: (_req, res) => res.end('<h1>Datasource</h1>'), close: async () => {} });
async function freePort() {
  const s = http.createServer(); await new Promise(resolve => s.listen(0, '127.0.0.1', resolve));
  const port = s.address().port; await new Promise(resolve => s.close(resolve)); return port;
}
function request(port, { pathname = '/api/datasource', method = 'GET', headers = {} } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path: pathname, method, headers }, res => {
      let text = ''; res.on('data', chunk => text += chunk);
      res.on('end', () => resolve({ status: res.statusCode, text }));
    }); req.on('error', reject); req.end();
  });
}

test('singleflight coalesces 100 readers; failed refresh preserves dated last-good snapshot', async () => {
  let calls = 0; let fail = false;
  const bridge = new ProjectionBridge({ ttl: 0, loader: async () => {
    calls++; await new Promise(resolve => setTimeout(resolve, 10));
    if (fail) throw new Error('SYNTHETIC_SECRET_MUST_NOT_ESCAPE'); return sample;
  } });
  const rows = await Promise.all(Array.from({ length: 100 }, () => bridge.get(options)));
  assert.equal(calls, 1); assert.ok(rows.every(x => x === sample)); fail = true;
  const stale = await bridge.get(options, { force: true });
  assert.equal(stale.generated_at, sample.generated_at); assert.equal(stale.projection_state, 'stale');
  assert.ok(!JSON.stringify(stale).includes('SYNTHETIC_SECRET')); bridge.close();
});

test('snapshot drift cannot be hidden by fallback; bounded pending work rejects overload', async () => {
  let changed = false;
  const bridge = new ProjectionBridge({ ttl: 0, loader: async () => {
    if (changed) throw Object.assign(new Error('changed'), { code: 'PROJECTION_SNAPSHOT_CHANGED' }); return sample;
  } });
  await bridge.get(options); changed = true;
  await assert.rejects(bridge.get(options), { code: 'PROJECTION_SNAPSHOT_CHANGED' }); bridge.close();
  let resolve;
  const busy = new ProjectionBridge({ loader: () => new Promise(r => { resolve = r; }) });
  const waiting = busy.get(options);
  busy.pending.set('a', waiting); busy.pending.set('b', waiting); busy.pending.set('c', waiting);
  busy.pending.set('d', waiting); busy.pending.set('e', waiting); busy.pending.set('f', waiting); busy.pending.set('g', waiting);
  await assert.rejects(busy.get({ ...options, subject: 'AMD' }), { code: 'PROJECTION_BUSY' });
  resolve(sample); await waiting; busy.close();
});

test('query validation rejects paths, oversized paging and invalid snapshots', () => {
  for (const search of ['subject=../../private', 'subject=^GSPC', 'limit=1001', 'offset=-1', 'snapshot_id=bad', 'subject=%24%28env%29']) {
    assert.throws(() => queryOptions(new URL('http://localhost/?' + search)));
  }
  assert.equal(queryOptions(new URL('http://localhost/?subject=brk.b')).subject, 'BRK.B');
});

test('loopback service serves reads, rejects foreign Host/Origin and writes, duplicate launch reuses', async () => {
  const port = await freePort(); const service = await start({ port, bridge: new ProjectionBridge({ loader: async () => sample }), viteFactory: fakeVite });
  try {
    assert.equal((await request(port)).status, 200);
    assert.equal((await request(port, { method: 'POST' })).status, 405);
    assert.equal((await request(port, { headers: { Host: 'foreign.example' } })).status, 403);
    assert.equal((await request(port, { headers: { Origin: 'https://foreign.example' } })).status, 403);
    assert.equal((await request(port, { pathname: '/api/unknown' })).status, 404);
    assert.equal((await request(port, { pathname: '/datasource' })).status, 200);
    const duplicate = await run(process.execPath, ['ui/datasource/dev.mjs'], { cwd: ROOT, timeout: 6000,
      env: { ...process.env, DATASOURCE_PORT: String(port) } });
    assert.match(duplicate.stdout, /already running/); assert.ok(service.server.listening);
  } finally { await service.close(); }
  const next = http.createServer(); await new Promise(resolve => next.listen(port, '127.0.0.1', resolve));
  await new Promise(resolve => next.close(resolve));
});

test('foreign occupied port is preserved, and failed Vite startup releases owned listeners', async () => {
  const port = await freePort(); const foreign = http.createServer((_req, res) => res.end('foreign'));
  await new Promise(resolve => foreign.listen(port, '127.0.0.1', resolve));
  try {
    await assert.rejects(run(process.execPath, ['ui/datasource/dev.mjs'], { cwd: ROOT, timeout: 6000,
      env: { ...process.env, DATASOURCE_PORT: String(port) } }), error => error.code === 1 && /No process was stopped/.test(error.stderr));
    assert.equal((await request(port)).text, 'foreign');
  } finally { await new Promise(resolve => foreign.close(resolve)); }
  await assert.rejects(start({ port, viteFactory: async () => { throw new Error('synthetic startup'); } }));
  const next = http.createServer(); await new Promise(resolve => next.listen(port, '127.0.0.1', resolve));
  await new Promise(resolve => next.close(resolve));
});

test('foreign streaming or truncated health has an absolute bound and settles on abort', async () => {
  const port = await freePort();
  const foreign = http.createServer((_req, res) => {
    res.writeHead(200); res.write(' ');
    const timer = setInterval(() => res.write(' '), 75); res.on('close', () => clearInterval(timer));
  });
  await new Promise(resolve => foreign.listen(port, '127.0.0.1', resolve));
  try {
    const started = Date.now(); assert.equal(await health(port), null);
    assert.ok(Date.now() - started < 1800);
  } finally { foreign.closeAllConnections(); await new Promise(resolve => foreign.close(resolve)); }
  const truncated = http.createServer((_req, res) => { res.writeHead(200); res.write('{'); res.destroy(); });
  await new Promise(resolve => truncated.listen(port, '127.0.0.1', resolve));
  try { assert.equal(await health(port), null); }
  finally { await new Promise(resolve => truncated.close(resolve)); }
});

test('foreign status payload is not printed and unknown upgrades cannot hold shutdown', async () => {
  const port = await freePort();
  const foreign = http.createServer((_req, res) => res.end(JSON.stringify({ app: 'foreign', api_key: 'SYNTHETIC_DO_NOT_PRINT' })));
  await new Promise(resolve => foreign.listen(port, '127.0.0.1', resolve));
  try {
    await assert.rejects(run(process.execPath, ['ui/datasource/dev.mjs', '--status'], { cwd: ROOT, timeout: 2500,
      env: { ...process.env, DATASOURCE_PORT: String(port) } }), error => error.code === 1 && !error.stdout.includes('SYNTHETIC_DO_NOT_PRINT'));
  } finally { await new Promise(resolve => foreign.close(resolve)); }
  const service = await start({ port, viteFactory: fakeVite });
  const socket = net.connect(port, '127.0.0.1');
  await new Promise(resolve => socket.once('connect', resolve));
  socket.write(`GET / HTTP/1.1\r\nHost: localhost:${port}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Protocol: unhandled-protocol\r\n\r\n`);
  await new Promise(resolve => setTimeout(resolve, 20));
  try { await Promise.race([service.close(), new Promise((_, reject) => setTimeout(() => reject(new Error('shutdown hung')), 1000).unref())]); }
  finally { socket.destroy(); }
});
