const path = require('node:path');
const { test, expect } = require(path.join(process.env.UI_TOOL_ROOT, 'node_modules/@playwright/test'));
const copy = value => JSON.parse(JSON.stringify(value));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const CANARY = 'SYNTHETIC_DIAGNOSTIC_CANARY_9j42';
function notice(id) {
  return { id, title: id === 'harbor' ? 'Harbor shuttle boards at pier 4' : 'Ridge connection resumes at noon', body: id === 'harbor' ? 'Use the covered walkway to reach the shuttle.' : 'The regular connection is operating again.', revisions: [{ id: `${id}-r0`, title: 'Initial passenger notice', at: '2026-10-29 09:00' }] };
}
async function service(page, options = {}) {
  const state = { records: { harbor: notice('harbor'), ridge: notice('ridge') }, reads: [], writes: [], lookups: [], commits: [], operations: new Map(), console: [] };
  page.on('console', message => state.console.push(message.text()));
  page.on('pageerror', error => state.console.push(error.message));
  await page.addInitScript(() => { window.__timelineRenders = 0; window.__observeTimelineRender = () => { window.__timelineRenders++; }; });
  await page.route('**/api/**', async route => {
    const req = route.request(); const url = new URL(req.url());
    const respond = async (value, status = 200, delay = 0) => { if (delay) await sleep(delay); await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }).catch(() => {}); };
    const op = url.pathname.match(/^\/api\/operations\/(.+)$/);
    if (op) {
      const key = decodeURIComponent(op[1]); state.lookups.push(key);
      return respond(state.operations.has(key) ? { state: 'committed', notice: state.operations.get(key) } : { state: 'absent' });
    }
    const match = url.pathname.match(/^\/api\/notices\/([^/]+)(\/revisions)?$/);
    if (!match) return respond({ message: 'No such endpoint' }, 404);
    const id = decodeURIComponent(match[1]);
    if (req.method() === 'GET') {
      state.reads.push(id);
      const override = options.load?.(id, state.reads.filter(item => item === id).length, state);
      if (override) return respond(override.value, override.status ?? 200, override.delay ?? 0);
      return respond(copy(state.records[id]));
    }
    const input = req.postDataJSON(); state.writes.push({ id, input: copy(input) });
    if (options.reject) return respond({ kind: 'rejected', message: `Title validation failed; Authorization: Bearer ${CANARY}` }, 422, options.saveDelay ?? 0);
    if (typeof input.operationId !== 'string' || !input.operationId || typeof input.title !== 'string' || !input.title.trim() || input.title.length > 240 || typeof input.body !== 'string' || !input.body.trim() || input.body.length > 8000) return respond({ kind: 'rejected', message: 'Invalid notice fields' }, 422);
    let result = state.operations.get(input.operationId);
    if (!result) {
      const previous = state.records[id];
      result = { ...previous, title: input.title, body: input.body, revisions: [...previous.revisions, { id: `${id}-r${previous.revisions.length}`, title: input.title, at: '2026-10-30 10:00' }] };
      state.records[id] = result; state.operations.set(input.operationId, copy(result)); state.commits.push({ id, input: copy(input) });
    }
    if (options.unknown && state.writes.length === 1) return respond({ kind: 'unknown', message: `Gateway lost reply: token=${CANARY}` }, 503, options.saveDelay ?? 0);
    return respond(copy(result), 200, options.saveDelay ?? 0);
  });
  return state;
}
async function ready(page) { await page.goto('/'); await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('harbor').title); await expect(page.getByRole('region', { name: 'Revision history' })).toBeVisible(); }
const preview = page => page.getByRole('article', { name: 'Saved notice preview' });
async function save(page) { await page.getByRole('button', { name: 'Save revision', exact: true }).click(); }

test('Q01 happy path persists one revision and remains navigable', async ({ page }) => {
  const state = await service(page); await ready(page);
  await page.getByLabel('Title', { exact: true }).fill('Harbor shuttle uses pier 6');
  await page.getByLabel('Message', { exact: true }).fill('Follow the blue signs to pier 6.'); await save(page);
  await expect.poll(() => state.commits.length).toBe(1);
  await expect(page.getByRole('status')).toContainText(/saved/i);
  expect(state.records.harbor.title).toBe('Harbor shuttle uses pier 6'); expect(state.records.harbor.revisions).toHaveLength(2);
  expect(state.records.ridge).toEqual(notice('ridge'));
  await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title);
});

test('Q02 narrow layout contains unbroken notice and history text without hiding it', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 });
  const long = 'PassengerRouteIdentifier'.repeat(9);
  await service(page, { load: id => ({ value: { ...notice(id), title: long, body: long.repeat(5), revisions: [{ id: 'long-r', title: long, at: '2026-10-30' }] } }) });
  await page.goto('/'); await expect(preview(page).getByRole('heading', { level: 2 })).toHaveText(long);
  await expect(page.getByRole('region', { name: 'Revision history' })).toContainText(long);
  const dimensions = await page.evaluate(() => ({ viewport: innerWidth, width: document.documentElement.scrollWidth, blocks: [...document.querySelectorAll('article[aria-label="Saved notice preview"] h2,article[aria-label="Saved notice preview"] p,section[aria-label="Revision history"] li')].map(el => ({ width: el.clientWidth, scroll: el.scrollWidth, clipped: ['hidden', 'clip'].includes(getComputedStyle(el).overflowX), display: getComputedStyle(el).display })) }));
  expect(dimensions.width).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.blocks.length).toBeGreaterThanOrEqual(3);
  for (const block of dimensions.blocks) { expect(block.display).not.toBe('none'); expect(block.clipped).toBe(false); expect(block.scroll).toBeLessThanOrEqual(block.width + 1); }
});

test('Q03 late decoded success cannot replace the selected notice', async ({ page }) => {
  await service(page, { load: id => id === 'harbor' ? { value: { ...notice(id), deliveryLagMs: 500 } } : null });
  await page.goto('/'); await page.waitForTimeout(80); await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title); await page.waitForTimeout(700);
  await expect(page.getByLabel('Notice', { exact: true })).toHaveValue('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title);
  await expect(preview(page)).toContainText(notice('ridge').body);
});

test('Q04 late decoded failure cannot poison a different edit session', async ({ page }) => {
  await service(page, { load: id => id === 'harbor' ? { value: { deliveryLagMs: 500, message: 'Harbor service temporarily unavailable', kind: 'rejected' }, status: 503 } : null });
  await page.goto('/'); await page.waitForTimeout(80); await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title); await page.waitForTimeout(650);
  await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save revision', exact: true })).toBeEnabled();
});

test('Q05 a pending save does not erase later same-notice edits', async ({ page }) => {
  const state = await service(page, { saveDelay: 500 }); await ready(page);
  const title = page.getByLabel('Title', { exact: true }); await title.fill('Submitted harbor title'); await save(page);
  let expected = 'Submitted harbor title';
  if (await title.isEnabled()) { expected = 'Newer unsaved harbor draft'; await title.fill(expected); }
  await page.waitForTimeout(700);
  await expect(title).toHaveValue(expected); expect(state.records.harbor.title).toBe('Submitted harbor title'); expect(state.commits).toHaveLength(1);
  await expect(preview(page)).toContainText('Submitted harbor title');
});

test('Q06 a pending save stays attached to its initiating notice', async ({ page }) => {
  const state = await service(page, { saveDelay: 500 }); await ready(page);
  await page.getByLabel('Title', { exact: true }).fill('Harbor only change'); await save(page);
  await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title);
  await page.getByLabel('Title', { exact: true }).fill('Unsubmitted ridge draft'); await page.waitForTimeout(700);
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Unsubmitted ridge draft');
  await expect(preview(page)).toContainText(notice('ridge').body);
  expect(state.records.harbor.title).toBe('Harbor only change'); expect(state.records.ridge).toEqual(notice('ridge')); expect(state.commits).toHaveLength(1);
});

test('Q07 rapid duplicate activation creates one business revision', async ({ page }) => {
  const state = await service(page, { saveDelay: 300 }); await ready(page);
  await page.getByLabel('Title', { exact: true }).fill('One requested revision');
  await page.getByRole('button', { name: 'Save revision', exact: true }).evaluate(button => { button.click(); button.click(); });
  await page.waitForTimeout(550);
  expect(state.commits).toHaveLength(1); expect(state.records.harbor.revisions).toHaveLength(2);
  expect(new Set(state.writes.map(item => item.input.operationId)).size).toBe(1);
});

test('Q08 lost write reply can recover without a new business operation', async ({ page }) => {
  const state = await service(page, { unknown: true }); await ready(page);
  await page.getByLabel('Title', { exact: true }).fill('Committed despite lost reply'); await save(page);
  await page.waitForTimeout(350);
  const recovery = page.getByRole('button').filter({ hasText: /retry|check|reconcile|recover|verify/i });
  if (await recovery.count()) await recovery.first().click();
  await page.waitForTimeout(700);
  expect(state.commits).toHaveLength(1); expect(state.records.harbor.revisions).toHaveLength(2);
  expect(new Set(state.writes.map(item => item.input.operationId)).size).toBe(1);
  await expect(page.getByRole('status')).toContainText(/saved|confirmed|committed/i);
  await expect(preview(page)).toContainText('Committed despite lost reply');
  expect(await page.locator('body').innerText()).not.toContain(CANARY); expect(state.console.join('\n')).not.toContain(CANARY);
});

test('Q09 malformed service data produces a contained useful load failure', async ({ page }) => {
  const state = await service(page, { load: id => id === 'harbor' ? { value: { id, title: { internal: CANARY }, body: 'Not a valid notice', revisions: 'broken' } } : null });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Dispatch Desk', exact: true })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText(/notice|load|data/i);
  expect(await page.locator('body').innerText()).not.toContain(CANARY); expect(state.console.join('\n')).not.toContain(CANARY); expect(state.writes).toHaveLength(0);
  await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title);
});

test('Q10 rejected writes preserve draft and expose sanitized actionable feedback', async ({ page }) => {
  const state = await service(page, { reject: true }); await ready(page);
  await page.getByLabel('Title', { exact: true }).fill('Keep this draft after rejection'); await save(page);
  await expect(page.getByRole('alert')).toContainText(/save|revision|title|message/i);
  await expect(page.getByLabel('Title', { exact: true })).toHaveValue('Keep this draft after rejection');
  expect(state.commits).toHaveLength(0); expect(state.records.harbor).toEqual(notice('harbor'));
  expect(await page.locator('body').innerText()).not.toContain(CANARY); expect(state.console.join('\n')).not.toContain(CANARY);
});

test('Q11 the exported preview is prop driven and works without service access', async ({ page }) => {
  const state = await service(page); await page.goto('/preview.html');
  await page.waitForFunction(() => typeof window.renderNoticePreview === 'function');
  await page.evaluate(value => window.renderNoticePreview(value), notice('harbor'));
  await expect(preview(page)).toContainText(notice('harbor').title);
  const replacement = { ...notice('ridge'), title: 'Standalone revised title', body: 'Standalone replacement body' };
  await page.evaluate(value => window.renderNoticePreview(value), replacement);
  await expect(preview(page)).toContainText(replacement.title); await expect(preview(page)).toContainText(replacement.body);
  await expect(page.getByRole('region', { name: 'Revision history' })).toContainText('Initial passenger notice');
  expect(state.reads).toHaveLength(0); expect(state.writes).toHaveLength(0);
});

test('Q12 unrelated draft keystrokes avoid repeated expensive history work', async ({ page }) => {
  const state = await service(page); await ready(page); await page.waitForTimeout(150);
  const before = await page.evaluate(() => window.__timelineRenders);
  expect(before).toBeGreaterThan(0);
  await page.getByLabel('Title', { exact: true }).pressSequentially(' twelve keys');
  await page.waitForTimeout(100);
  const after = await page.evaluate(() => window.__timelineRenders);
  expect(after - before).toBeLessThanOrEqual(1);
  await expect(page.getByRole('region', { name: 'Revision history' })).toContainText('Initial passenger notice');
  expect(state.writes).toHaveLength(0);
});
