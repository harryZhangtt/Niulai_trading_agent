import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

test('real sources, labels, run provenance, matched metrics and colored captured text', async ({ page, request }) => {
  const response = await request.get('/api/datasource?subject=NOW');
  const data = await response.json(); expect(data.sources.length).toBeGreaterThan(0);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/datasource'); await page.getByRole('button', { name: 'Source ledger', exact: true }).click();
  await expect(page.locator('.source-title-button').first()).toBeVisible();
  await expect(page.locator('.source-title-button')).toHaveCount(data.sources.length);
  await expect(page.getByRole('heading', { name: 'Temporal validity', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open original source' })).toHaveAttribute('href', /^https:/);
  await page.getByLabel('Research pipeline', { exact: true }).selectOption(data.runs[0].id);
  await expect(page.getByRole('heading', { name: 'Execution provenance' })).toBeVisible();
  await page.getByText('Phases and script versions', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Scripts', exact: true })).toBeVisible();
  await page.getByRole('button', { name: /A\/B evaluation/ }).click();
  await page.getByLabel('Comparison', { exact: true }).selectOption('now_captured_regrade_1.0.2');
  await expect(page.locator('.comparison-table tbody tr')).toHaveCount(8);
  await page.getByLabel('Metric', { exact: true }).selectOption('cost');
  await expect(page.locator('.comparison-table tbody tr').first()).toContainText('Unknown');
  await page.locator('.case-text-changes summary').first().click();
  await expect(page.locator('.text-change-content').first()).toBeVisible();
  expect(await page.locator('ins,del').count()).toBeGreaterThan(2);
  await page.screenshot({ path: '../runtime/datasource-comparison.png', fullPage: true });
  await page.getByRole('button', { name: 'Consistency', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Single execution' })).toBeVisible();
  await expect(page.getByLabel(/Aggregate cohort/)).toBeVisible();
  expect(errors).toEqual([]);
});

test('desktop/mobile render, keyboard filter and source timeline remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/datasource'); await page.getByRole('button', { name: 'Source ledger', exact: true }).click();
  await expect(page.locator('.source-title-button').first()).toBeVisible();
  await page.screenshot({ path: '../runtime/datasource-desktop.png', fullPage: false });
  await page.getByLabel('Filter this page').fill('no-such-source-canary');
  await expect(page.getByRole('heading', { name: 'No sources match this filter' })).toBeVisible();
  await page.getByLabel('Filter this page').fill('');
  const first = page.locator('.source-title-button').first(); await first.focus(); await page.keyboard.press('Enter');
  await expect(first).toHaveAttribute('aria-pressed', 'true');
  await page.setViewportSize({ width: 360, height: 800 });
  await page.emulateMedia({ reducedMotion: 'reduce' }); await first.click();
  await expect(page.getByRole('heading', { name: 'Source timeline' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: '../runtime/datasource-mobile.png', fullPage: true });
});

test('refresh failure keeps last good snapshot; a slower earlier subject cannot replace a later one', async ({ page, request }) => {
  const original = await (await request.get('/api/datasource?subject=NOW')).json();
  await page.goto('/datasource'); await page.getByRole('button', { name: 'Source ledger', exact: true }).click(); await expect(page.locator('.source-title-button').first()).toBeVisible();
  await page.route('**/api/datasource?**', route => route.fulfill({ status: 503, json: { error: { code: 'SYNTHETIC' } } }));
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('last successfully loaded snapshot');
  await expect(page.locator('.source-title-button')).toHaveCount(original.sources.length);
  await page.unroute('**/api/datasource?**');
  await page.route('**/api/datasource?**', async route => {
    const subject = new URL(route.request().url()).searchParams.get('subject');
    if (subject === 'SLOW') await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({ json: { ...original, subject, sources: [], runs: [], comparisons: [],
      pagination: { ...original.pagination, total_sources: 0, total_runs: 0, next_offset: null } } });
  });
  await page.getByLabel('Subject', { exact: true }).fill('SLOW'); await page.getByRole('button', { name: 'Load subject' }).click();
  await page.getByLabel('Subject', { exact: true }).fill('FAST'); await page.getByRole('button', { name: 'Load subject' }).click();
  await expect(page.locator('.subject-pill')).toHaveText('FAST');
  await expect(page.getByRole('heading', { name: 'No source records available' })).toBeVisible();
  await page.waitForTimeout(300); await expect(page.locator('.subject-pill')).toHaveText('FAST');
});

test('private files and foreign web origins cannot use the local data API', async ({ request }) => {
  const privatePath = '/@fs' + process.cwd().replace(/\/ui\/datasource$/, '') + '/.job-runtime/config/runtime.json?raw';
  const reply = await request.get(privatePath); expect(reply.status()).toBe(403);
  expect(await reply.text()).not.toContain('auth_home');
  expect((await request.get('/api/datasource', { headers: { Origin: 'https://foreign.example' } })).status()).toBe(403);
  expect((await request.post('/api/datasource')).status()).toBe(405);
});

test('scheduled model query exposes its exact guarded catalog; future probes remain reviewer-only', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW&refresh=1')).json();
  const run = data.runs.find(row => row.output && row.temporal?.status === 'guarded');
  expect(run, 'requires the fresh scheduled acceptance, not a fabricated UI fixture').toBeTruthy();
  expect(run.output.questions.length).toBeGreaterThanOrEqual(5);
  expect(run.output.observations.length).toBeGreaterThan(0);
  await page.goto('/datasource'); await page.getByRole('button', { name: 'Source ledger', exact: true }).click();
  await expect(page.locator('.source-title-button').first()).toBeVisible();
  await page.getByLabel('Research pipeline', { exact: true }).selectOption(run.id);
  await page.getByText('Catalog and extracted observations', { exact: true }).click();
  await expect(page.locator('.question-list li')).toHaveCount(run.output.questions.length);
  await expect(page.locator('.observation')).toHaveCount(run.output.observations.length);
  await expect(page.locator('.run-temporal-assessment')).toContainText('Guarded');
  await expect(page.locator('.run-temporal-assessment').getByText('eligible', { exact: true })).toBeVisible();
  await page.screenshot({ path: '../runtime/datasource-scheduled-query.png', fullPage: true });
  const probe = data.sources.find(row => row.url === 'https://example.invalid/synthetic-future');
  expect(probe?.temporal.status).toBe('blocked'); expect(probe?.temporal.worker_visible).toBe(false);
  await page.getByLabel('Research pipeline', { exact: true }).selectOption('all');
  await page.getByLabel('Filter this page').fill(probe.title);
  await page.locator('.source-title-button').first().click();
  await expect(page.locator('.temporal-panel .badge')).toContainText('Blocked');
  await expect(page.locator('.source-temporal-assessment')).toContainText(probe.temporal.reason_codes[0]);
  await page.screenshot({ path: '../runtime/datasource-leakage-probe.png', fullPage: true });
});

test('execution-first dashboard follows actual cold/warm batch IDs and retained receipts', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW&refresh=1')).json();
  expect(data.batches.length).toBeGreaterThanOrEqual(2);
  await page.goto('/datasource');
  await expect(page.getByRole('heading', { name: 'Datasource executions', exact: true })).toBeVisible();
  const warm = data.batches.find(batch => batch.metrics.cache_hits > 0 && batch.metrics.provider_calls === 0);
  const cold = data.batches.find(batch => batch.metrics.provider_calls > 0 && batch.metrics.cache_hits === 0 && batch.metrics.fallbacks === 0);
  expect(warm).toBeTruthy(); expect(cold).toBeTruthy(); expect(warm.execution_id).not.toBe(cold.execution_id);
  const warmRow = page.locator('.execution-table tbody tr').filter({ hasText: warm.execution_id });
  await warmRow.getByRole('button').click();
  await expect(page.locator('.batch-details')).toContainText(warm.execution_id);
  await expect(page.locator('.batch-details')).toContainText('Durable snapshot references');
  await expect(page.locator('.batch-details')).toContainText('0');
  await page.screenshot({ path: '../runtime/datasource-executions.png', fullPage: true });
});
