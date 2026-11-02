// Independent browser checks for a generated combined-skill example.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { parseArgs } from 'node:util';
import { fileURLToPath } from 'node:url';

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const { values } = parseArgs({ options: { site: { type: 'string' }, output: { type: 'string' } } });
if (!values.site || !values.output) throw new Error('--site and --output are required');
const site = await fs.realpath(path.resolve(workspace, values.site));
const output = path.resolve(workspace, values.output);
const within = p => p.startsWith(workspace + path.sep);
if (!within(site) || !within(output)) throw new Error('Workspace-local paths required');
await fs.mkdir(output, { recursive: true });
try { await fs.access(path.join(output, 'results.json')); throw new Error('Refusing result overwrite'); }
catch (error) { if (error.code !== 'ENOENT') throw error; }
const temporary = path.join(workspace, 'ui/runtime/tmp');
await fs.mkdir(temporary, { recursive: true });
process.env.TMPDIR = temporary;
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(workspace, 'ui/runtime/browsers');
const { chromium } = await import('../verification/node_modules/@playwright/test/index.mjs');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' };
const server = http.createServer(async (request, response) => {
  try {
    const name = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const file = await fs.realpath(path.join(site, name === '/' ? 'index.html' : name));
    if (!file.startsWith(site + path.sep)) throw new Error('Outside fixture');
    response.writeHead(200, { 'Content-Type': types[path.extname(file)] || 'application/octet-stream' });
    response.end(await fs.readFile(file));
  } catch { response.writeHead(404); response.end('Not found'); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const baseURL = `http://127.0.0.1:${server.address().port}`;
const results = [], failures = [];
let browser;
async function check(name, work) {
  try { const detail = await work(); results.push({ name, status: 'passed', detail }); }
  catch (error) { results.push({ name, status: 'failed', error: error.message }); failures.push(name); }
}
try {
  browser = await chromium.launch({ headless: true, channel: 'chromium' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await check('real-page-and-gsap-load', async () => {
    const response = await page.goto(baseURL);
    assert.equal(response.status(), 200);
    await page.getByRole('heading', { level: 1 }).waitFor();
    assert.match(await page.evaluate(() => window.__gsap?.version || ''), /^3\./);
    assert.equal(errors.length, 0);
  });
  await check('normal-motion-and-scene-mount', async () => {
    const toggle = page.getByRole('button', { name: 'Show sky scenes', exact: true });
    assert.equal(await toggle.getAttribute('aria-pressed'), 'true');
    assert.ok(await page.locator('[data-motion-target]').count() > 0);
    const triggers = await page.evaluate(() => window.__gsap.core.globals().ScrollTrigger.getAll().length);
    assert.ok(triggers > 0, 'No actual ScrollTrigger registered');
    return { triggers };
  });
  await check('keyboard-navigation-focus', async () => {
    await page.keyboard.press('ControlOrMeta+Home');
    await page.evaluate(() => document.activeElement?.blur());
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      const style = getComputedStyle(el);
      return { tag: el.tagName, outline: style.outlineStyle, shadow: style.boxShadow, text: el.textContent.trim() };
    });
    assert.ok(['A', 'BUTTON', 'INPUT', 'SELECT'].includes(focused.tag));
    assert.ok(focused.outline !== 'none' || focused.shadow !== 'none', 'No visible keyboard focus');
    return focused;
  });
  await check('320px-layout-and-extreme-heading', async () => {
    await page.setViewportSize({ width: 320, height: 760 });
    await page.waitForTimeout(100);
    const before = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(before.scroll <= before.width + 2, JSON.stringify(before));
    const heading = page.getByRole('heading', { level: 1 }).first();
    await heading.evaluate(el => { el.textContent += ' ' + 'UnbrokenAstronomicalObservation'.repeat(12); });
    const after = await page.evaluate(() => ({ width: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth }));
    assert.ok(after.scroll <= after.width + 2, JSON.stringify(after));
    await page.screenshot({ path: path.join(output, 'mobile-extreme.png'), fullPage: true });
    return { before, after };
  });
  await check('scoped-unmount-cleans-tweens-and-triggers', async () => {
    await page.evaluate(() => { window.__removedTargets = [...document.querySelectorAll('[data-motion-target]')]; });
    await page.getByRole('button', { name: 'Show sky scenes', exact: true }).click();
    await page.waitForTimeout(80);
    const cleanup = await page.evaluate(() => ({
      mountedTargets: document.querySelectorAll('[data-motion-target]').length,
      retainedTargetTweens: window.__removedTargets.reduce((n, target) => n + window.__gsap.getTweensOf(target).length, 0),
      disconnectedTriggers: window.__gsap.core.globals().ScrollTrigger.getAll().filter(t => t.trigger instanceof Element && !t.trigger.isConnected).length,
    }));
    assert.deepEqual(cleanup, { mountedTargets: 0, retainedTargetTweens: 0, disconnectedTriggers: 0 });
    return cleanup;
  });
  await check('repeat-remount-does-not-duplicate-owned-triggers', async () => {
    const toggle = page.getByRole('button', { name: 'Show sky scenes', exact: true });
    await toggle.click();
    const first = await page.evaluate(() => window.__gsap.core.globals().ScrollTrigger.getAll().length);
    await toggle.click();
    await toggle.click();
    const second = await page.evaluate(() => window.__gsap.core.globals().ScrollTrigger.getAll().length);
    assert.ok(first > 0);
    assert.equal(second, first);
    assert.equal(errors.length, 0);
    return { first, second };
  });
  await page.close();
  const reduced = await browser.newPage({ viewport: { width: 360, height: 780 }, reducedMotion: 'reduce' });
  await check('reduced-motion-visible-stable-content', async () => {
    await reduced.goto(baseURL);
    await reduced.getByRole('heading', { level: 1 }).waitFor();
    const sample = () => reduced.locator('[data-motion-target]').evaluateAll(nodes => nodes.map(el => {
      const style = getComputedStyle(el);
      return { transform: style.transform, opacity: style.opacity, display: style.display, visibility: style.visibility };
    }));
    const first = await sample();
    assert.ok(first.length > 0);
    await reduced.waitForTimeout(350);
    const second = await sample();
    assert.deepEqual(second, first);
    assert.ok(second.every(s => Number(s.opacity) > 0 && s.display !== 'none' && s.visibility !== 'hidden'));
    assert.equal(await reduced.evaluate(() => window.__gsap.core.globals().ScrollTrigger?.getAll().length || 0), 0);
    await reduced.screenshot({ path: path.join(output, 'reduced-motion.png'), fullPage: true });
    return { targetCount: first.length };
  });
  await reduced.close();
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
  await fs.writeFile(path.join(output, 'results.json'), JSON.stringify({ results, failed: failures.length, serverClosed: !server.listening }, null, 2) + '\n');
}
console.log(JSON.stringify({ passed: results.length - failures.length, failed: failures.length, output: path.relative(workspace, output) }));
process.exitCode = failures.length ? 1 : 0;
