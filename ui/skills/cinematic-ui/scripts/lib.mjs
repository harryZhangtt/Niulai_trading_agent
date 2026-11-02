// Shared plumbing for screening.mjs and render-film.mjs: args, a static server, a browser.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';

export function parseArgs(argv, defaults = {}) {
  const out = { _: [], ...defaults };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) { out._.push(a); continue; }
    const [key, inline] = a.slice(2).split('=');
    const next = argv[i + 1];
    if (inline !== undefined) out[key] = inline;
    else if (next !== undefined && !next.startsWith('--')) { out[key] = next; i++; }
    else out[key] = true;
  }
  return out;
}

const MIME = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.avif': 'image/avif', '.gif': 'image/gif',
  '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf', '.otf': 'font/otf', '.mp3': 'audio/mpeg',
  '.wav': 'audio/wav', '.mp4': 'video/mp4', '.webm': 'video/webm', '.glb': 'model/gltf-binary', '.gltf': 'model/gltf+json',
  '.hdr': 'application/octet-stream', '.exr': 'application/octet-stream', '.wasm': 'application/wasm', '.txt': 'text/plain',
};

/** Serve a directory on 127.0.0.1 (ES modules and import maps do not load from file://). */
export function serve(dir) {
  const rootDir = fs.realpathSync(path.resolve(dir));
  const within = (file) => file === rootDir || file.startsWith(rootDir + path.sep);
  const server = http.createServer((req, res) => {
    let rel;
    try { rel = decodeURIComponent(new URL(req.url, 'http://x').pathname); }
    catch { res.writeHead(400).end('invalid path'); return; }
    if (rel.endsWith('/')) rel += 'index.html';
    let file = path.resolve(rootDir, '.' + rel);
    if (!within(file)) { res.writeHead(403).end(); return; }
    try { file = fs.realpathSync(file); }
    catch { res.writeHead(404).end('not found'); return; }
    if (!within(file)) { res.writeHead(403).end(); return; }
    fs.stat(file, (err, st) => {
      if (err || !st.isFile()) { res.writeHead(404).end('not found'); return; }
      // Byte ranges: browsers will not seek a <video> (scrubbing, frame-exact film renders) without them.
      const head = { 'content-type': MIME[path.extname(file).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-store', 'accept-ranges': 'bytes' };
      const m = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range || '');
      if (m) {
        const start = m[1] ? Number(m[1]) : Math.max(0, st.size - Number(m[2]));
        const end = m[1] && m[2] ? Math.min(Number(m[2]), st.size - 1) : st.size - 1;
        if (start > end || start >= st.size) { res.writeHead(416, { 'content-range': `bytes */${st.size}` }).end(); return; }
        res.writeHead(206, { ...head, 'content-range': `bytes ${start}-${end}/${st.size}`, 'content-length': end - start + 1 });
        fs.createReadStream(file, { start, end }).pipe(res);
      } else {
        res.writeHead(200, { ...head, 'content-length': st.size });
        fs.createReadStream(file).pipe(res);
      }
    });
  });
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, origin: `http://127.0.0.1:${server.address().port}`, close: () => server.close() })));
}

/** A URL, an .html file or a directory → something a browser can open. */
export async function resolveTarget(target) {
  if (/^https?:\/\//i.test(target)) return { url: target, close: () => {} };
  const [file0, query = ''] = String(target).split('?');
  const abs = path.resolve(file0);
  if (!fs.existsSync(abs)) throw new Error(`Not found: ${abs}`);
  const isDir = fs.statSync(abs).isDirectory();
  const dir = isDir ? abs : path.dirname(abs);
  const file = isDir ? 'index.html' : path.basename(abs);
  const s = await serve(dir);
  return { url: `${s.origin}/${file}${query ? '?' + query : ''}`, close: s.close, dir };
}

/** Use this workspace's pinned verification dependency and managed browser only. */
export async function loadPlaywright() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  process.env.PLAYWRIGHT_BROWSERS_PATH = path.resolve(here, '../../../runtime/browsers');
  const require = createRequire(path.resolve(here, '../../../verification/package.json'));
  try { return require('@playwright/test'); }
  catch { throw new Error('Pinned UI Playwright dependency missing. Follow docs/deployment/frontend.md.'); }
}

/** Launch the pinned workspace-managed Chromium with an ephemeral profile. */
export async function launch(pw, { headed = false } = {}) {
  const args = ['--ignore-gpu-blocklist', '--enable-gpu', '--enable-unsafe-swiftshader', '--hide-scrollbars', '--autoplay-policy=no-user-gesture-required'];
  return pw.chromium.launch({ headless: !headed, args });
}

export const nextFrame = (page) => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))));
