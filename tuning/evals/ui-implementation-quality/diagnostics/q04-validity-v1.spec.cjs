const path = require('node:path');
const fs = require('node:fs/promises');
const { test, expect } = require(path.join(process.env.UI_TOOL_ROOT, 'node_modules/@playwright/test'));
const copy = value => JSON.parse(JSON.stringify(value));
function notice(id) {
  return { id, title: id === 'harbor' ? 'Harbor shuttle boards at pier 4' : 'Ridge connection resumes at noon', body: id === 'harbor' ? 'Use the covered walkway to reach the shuttle.' : 'The regular connection is operating again.', revisions: [{ id: `${id}-r0`, title: 'Initial passenger notice', at: '2026-10-29 09:00' }] };
}
async function service(page, lateFailure) {
  const state = { records: { harbor: notice('harbor'), ridge: notice('ridge') }, reads: [], writes: [], commits: [], console: [], events: [] };
  const operations = new Map();
  page.on('console', message => state.console.push(message.text()));
  page.on('pageerror', error => state.console.push(error.message));
  await page.route('**/api/**', async route => {
    const req = route.request(); const url = new URL(req.url());
    const respond = (value, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }).catch(() => {});
    const op = url.pathname.match(/^\/api\/operations\/(.+)$/);
    if (op) return respond(operations.has(op[1]) ? { state: 'committed', notice: operations.get(op[1]) } : { state: 'absent' });
    const match = url.pathname.match(/^\/api\/notices\/([^/]+)(\/revisions)?$/);
    if (!match) return respond({ message: 'No such endpoint' }, 404);
    const id = decodeURIComponent(match[1]);
    if (req.method() === 'GET') {
      state.reads.push(id); state.events.push({ event: 'read-response', id, time: Date.now(), lateFailure: lateFailure && id === 'harbor' });
      if (lateFailure && id === 'harbor') return respond({ deliveryLagMs: 500, message: 'Harbor service temporarily unavailable', kind: 'rejected' }, 503);
      return respond(copy(state.records[id]));
    }
    const input = req.postDataJSON(); state.writes.push({ id, input: copy(input) });
    if (typeof input.operationId !== 'string' || !input.operationId || typeof input.title !== 'string' || !input.title.trim() || input.title.length > 240 || typeof input.body !== 'string' || !input.body.trim() || input.body.length > 8000) return respond({ kind: 'rejected', message: 'Invalid notice fields' }, 422);
    let result = operations.get(input.operationId);
    if (!result) {
      const previous = state.records[id];
      result = { ...previous, title: input.title, body: input.body, revisions: [...previous.revisions, { id: `${id}-r${previous.revisions.length}`, title: input.title, at: '2026-10-30 10:00' }] };
      state.records[id] = result; operations.set(input.operationId, copy(result)); state.commits.push({ id, input: copy(input) });
    }
    state.events.push({ event: 'write-response', id, time: Date.now() });
    return respond(copy(result));
  });
  return state;
}
async function snapshot(page, label) {
  const save = page.getByRole('button', { name: 'Save revision', exact: true });
  return { label, time: Date.now(), selected: await page.getByLabel('Notice', { exact: true }).inputValue(), title: await page.getByLabel('Title', { exact: true }).inputValue(), body: await page.getByLabel('Message', { exact: true }).inputValue(), saveDisabled: await save.isDisabled(), alerts: await page.getByRole('alert').allTextContents(), statuses: await page.getByRole('status').allTextContents(), preview: await page.getByLabel('Saved notice preview', { exact: true }).innerText() };
}
for (const scenario of [
  { id: 'D01', name: 'healthy Ridge pristine then valid edit and save', lateFailure: false, editBeforeLate: false },
  { id: 'D02', name: 'late Harbor failure with pristine Ridge then valid edit and save', lateFailure: true, editBeforeLate: false },
  { id: 'D03', name: 'valid Ridge edit before late Harbor failure then save', lateFailure: true, editBeforeLate: true },
]) {
  test(`${scenario.id} ${scenario.name}`, async ({ page }, testInfo) => {
    const state = await service(page, scenario.lateFailure);
    const edited = `Ridge passengers use the north stairwell ${scenario.id}`;
    const record = { identity: 'q04-validity-diagnostic-v1', subject: testInfo.project.name, scenario: scenario.id, lateFailure: scenario.lateFailure, editBeforeLate: scenario.editBeforeLate, snapshots: [], saveAttempted: false, saveSucceeded: false };
    try {
      const responsePromise = page.waitForResponse(response => new URL(response.url()).pathname === '/api/notices/harbor' && response.request().method() === 'GET');
      await page.goto('/');
      await (await responsePromise).finished();
      if (scenario.lateFailure) await page.waitForTimeout(80);
      else await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('harbor').title);
      state.events.push({ event: 'select-ridge', time: Date.now() });
      await page.getByLabel('Notice', { exact: true }).selectOption('ridge');
      await expect(page.getByLabel('Title', { exact: true })).toHaveValue(notice('ridge').title);
      record.snapshots.push(await snapshot(page, 'ridge-initial-pristine'));
      if (scenario.editBeforeLate) {
        await page.getByLabel('Title', { exact: true }).fill(edited);
        record.snapshots.push(await snapshot(page, 'ridge-edited-before-late-completion'));
      }
      await page.waitForTimeout(650);
      record.snapshots.push(await snapshot(page, 'ridge-after-matched-settle'));
      await page.screenshot({ path: testInfo.outputPath('before-save.png') });
      if (!scenario.editBeforeLate) await page.getByLabel('Title', { exact: true }).fill(edited);
      record.snapshots.push(await snapshot(page, 'valid-edited-ridge-before-save'));
      await expect(page.getByLabel('Title', { exact: true })).toHaveValue(edited);
      const save = page.getByRole('button', { name: 'Save revision', exact: true });
      await expect(save).toBeEnabled(); record.saveAttempted = true; await save.click();
      await expect.poll(() => state.commits.length).toBe(1);
      await expect(page.getByRole('status')).toContainText(/saved|confirmed|committed/i);
      await expect(page.getByLabel('Notice', { exact: true })).toHaveValue('ridge');
      await expect(page.getByLabel('Title', { exact: true })).toHaveValue(edited);
      expect(state.commits).toHaveLength(1); expect(state.writes).toHaveLength(1);
      expect(state.commits[0].id).toBe('ridge'); expect(state.records.ridge.title).toBe(edited);
      expect(state.records.ridge.body).toBe(notice('ridge').body); expect(state.records.ridge.revisions).toHaveLength(2);
      expect(state.records.harbor).toEqual(notice('harbor'));
      record.saveSucceeded = true;
      record.snapshots.push(await snapshot(page, 'ridge-after-successful-save'));
    } finally {
      record.service = state;
      await fs.writeFile(testInfo.outputPath('observations.json'), JSON.stringify(record, null, 2) + '\n');
      await testInfo.attach('observations', { path: testInfo.outputPath('observations.json'), contentType: 'application/json' });
    }
  });
}
