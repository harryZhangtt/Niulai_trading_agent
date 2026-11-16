import { readFileSync } from 'node:fs';
import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

const sourceText = path => readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');
async function renderedContrast(locator) {
  return locator.evaluate(element => {
    const parse = value => value.match(/[\d.]+/g).slice(0, 3).map(channel => Number(channel) / 255);
    const luminance = value => parse(value).map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4)
      .reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0);
    const foreground = getComputedStyle(element).color;
    let backgroundElement = element;
    let background = getComputedStyle(backgroundElement).backgroundColor;
    while (backgroundElement.parentElement && (background === 'rgba(0, 0, 0, 0)' || background === 'transparent')) {
      backgroundElement = backgroundElement.parentElement;
      background = getComputedStyle(backgroundElement).backgroundColor;
    }
    const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
    return { foreground, background, ratio: (lighter + .05) / (darker + .05) };
  });
}
async function expectNormalTextContrast(locator) {
  const result = await renderedContrast(locator);
  expect(result.ratio, `${result.foreground} on ${result.background}`).toBeGreaterThanOrEqual(4.5);
  return result;
}

const syntheticStamp = '2026-11-05T00:00:00Z';
function syntheticSource(id, title, runId) {
  return { id, title, url: null, subject: 'TEST', scope: 'synthetic_ui_fixture', content_access: 'metadata_only', source_sha256: id === 'source-alpha' ? 'a'.repeat(64) : 'b'.repeat(64), version_sha256: null,
    timestamps: { published_at: null, available_at: null, fetched_at: syntheticStamp, recorded_at: syntheticStamp },
    labels: { publisher_kind: 'unknown', perspectives: [], document_type: 'unknown', topics: [], epistemic_status: 'unverified', annotation_status: 'provisional', policy_version: null, provenance_status: 'unverified', persistence: 'not_persisted' },
    run_ids: [runId], batch_ids: [], collection_ids: [], limitations: ['Synthetic UI fixture; no source quality claim.'], temporal: null, local_preview: null };
}
function syntheticRun(id, sourceId) {
  return { id, execution_id: id, query: `Research ${id}`, pipeline_id: 'synthetic', pipeline_version: 'fixture', config_sha256: null, status: 'completed', scope: 'synthetic_ui_fixture', started_at: syntheticStamp, finished_at: syntheticStamp, script_versions: [], phases: [], metrics: {}, source_ids: [sourceId], temporal: null, output: null };
}
function syntheticResearchPacket(patch = {}) {
  const sources = [syntheticSource('source-alpha', 'Alpha evidence record', 'run-alpha'), syntheticSource('source-beta', 'Beta evidence record', 'run-beta')];
  return { schema_version: 1, generated_at: syntheticStamp, snapshot_id: 'f'.repeat(64), status: 'ok', warnings: [], subject: 'TEST',
    pagination: { offset: 0, limit: 100, total_sources: 2, total_runs: 2, total_batches: 0, total_native_collections: 0, next_offset: null },
    sources, runs: [syntheticRun('run-alpha', 'source-alpha'), syntheticRun('run-beta', 'source-beta')], batches: [], comparisons: [],
    aggregates: { cohorts: [], unknowns: null, source_counts: { total: 2, by_scope: { synthetic_ui_fixture: 2 }, by_publisher: { unknown: 2 }, by_document_type: { unknown: 2 }, persisted_labels: 0, unknown_available_at: 2 } }, ...patch };
}

async function syntheticResearch(page, value) {
  await page.route('**/api/datasource?**', route => route.fulfill({ json: value }));
}

test('real sources, labels, run provenance, matched metrics and colored captured text', async ({ page, request }) => {
  const response = await request.get('/api/datasource?subject=NOW');
  const data = await response.json(); expect(data.sources.length).toBeGreaterThan(0);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/datasource'); await page.getByRole('link', { name: 'Evidence', exact: true }).click();
  await expect(page.locator('.source-title-button').first()).toBeVisible();
  await expect(page.locator('.source-title-button')).toHaveCount(data.sources.length);
  await page.getByText('Technical provenance and linked run IDs', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Temporal validity', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Open original source' })).toHaveAttribute('href', /^https:/);
  await page.getByRole('link', { name: 'Runs', exact: true }).click();
  const researchRow = page.locator('.execution-table tbody tr').filter({ hasText: data.runs[0].execution_id ?? data.runs[0].id });
  await researchRow.getByRole('button').click();
  await expect(page.getByRole('heading', { name: 'Research analysis details' })).toBeVisible();
  await page.getByText('Phases and script versions', { exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Scripts', exact: true })).toBeVisible();
  await page.getByRole('navigation', { name: 'Research observability views' }).getByRole('link', { name: /Comparisons/ }).click();
  await page.getByLabel('Comparison', { exact: true }).selectOption('now_captured_regrade_1.0.2');
  await expect(page.locator('.comparison-table tbody tr')).toHaveCount(8);
  await page.getByLabel('Metric', { exact: true }).selectOption('cost');
  await expect(page.locator('.comparison-table tbody tr').first()).toContainText('Unknown');
  await page.locator('.case-text-changes summary').first().click();
  await expect(page.locator('.text-change-content').first()).toBeVisible();
  expect(await page.locator('ins,del').count()).toBeGreaterThan(2);
  await page.screenshot({ path: '../runtime/datasource-comparison.png', fullPage: true });
  await page.getByRole('link', { name: 'Overview', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Run health' })).toBeVisible();
  await expect(page.getByLabel('Cohort', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test('desktop/mobile render, keyboard filter and source timeline remain usable', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/datasource'); await page.getByRole('link', { name: 'Evidence', exact: true }).click();
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
  const annotationBadge = page.locator('.annotation-badge').first();
  await annotationBadge.evaluate(element => { element.hidden = true; });
  await expect(annotationBadge).toBeHidden();
  expect(await annotationBadge.evaluate(element => getComputedStyle(element).display)).toBe('none');
  const contrast = await page.evaluate(() => {
    const tokens = getComputedStyle(document.documentElement);
    const parse = value => value.trim().match(/[a-f\d]{2}/gi).map(channel => Number.parseInt(channel, 16) / 255);
    const luminance = value => parse(value).map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4)
      .reduce((sum, channel, index) => sum + channel * [.2126, .7152, .0722][index], 0);
    const ratio = (foreground, background) => {
      const [lighter, darker] = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
      return (lighter + .05) / (darker + .05);
    };
    const accent = tokens.getPropertyValue('--text-accent');
    return { surface: ratio(accent, tokens.getPropertyValue('--surface')), blueTint: ratio(accent, tokens.getPropertyValue('--blue-tint')) };
  });
  expect(contrast.surface).toBeCloseTo(6.2102, 4);
  expect(contrast.blueTint).toBeCloseTo(5.4164, 4);
  expect(Math.min(contrast.surface, contrast.blueTint)).toBeGreaterThanOrEqual(4.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  await page.screenshot({ path: '../runtime/datasource-mobile.png', fullPage: true });
});

test('normal text accents stay AA-compliant on panels and selected run evidence', async ({ page }) => {
  const runEvidenceCss = sourceText('RunEvidence/RunEvidence.module.css');
  const globalCss = sourceText('styles.css');
  const readinessCss = sourceText('OverviewView/EvidenceReadiness/EvidenceReadiness.module.css');
  for (const rule of [
    '.ledger li > a:hover span, .ledger li.selected > a { color: var(--text-accent); }',
    '.secondary { display: flex; align-items: center; min-height: 44px; margin: 4px 16px; font-size: .82rem; color: var(--text-accent); }',
  ]) expect(runEvidenceCss).toContain(rule);
  for (const rule of [
    'a { color: var(--text-accent); text-underline-offset: 3px; }',
    'details summary { cursor: pointer; width: fit-content; color: var(--text-accent);',
    '.run-action-label { flex: 0 0 auto; display: inline-flex; align-items: center; gap: 4px; color: var(--text-accent);',
    '.text-button { color: var(--text-accent);',
    '.text-arm-name { color: var(--text-accent);',
  ]) expect(globalCss).toContain(rule);
  expect(readinessCss).toContain('.classes a:hover span:first-child { color: var(--text-accent);');

  const value = syntheticResearchPacket();
  value.aggregates.source_counts = { total: 2, by_scope: { synthetic_ui_fixture: 2 }, by_publisher: { unknown: 2 }, by_document_type: { filing: 2 }, persisted_labels: 0, unknown_available_at: 2 };
  await syntheticResearch(page, value);
  await page.goto('/datasource?subject=TEST&view=overview');

  await expectNormalTextContrast(page.getByRole('link', { name: 'Open evidence', exact: true }));
  const detailsSummary = page.getByText('Evidence-readiness data table', { exact: true });
  await expectNormalTextContrast(detailsSummary);
  const classLink = page.getByRole('link', { name: /Filing 2/ });
  await classLink.hover();
  await expectNormalTextContrast(classLink.locator('span').first());

  await page.getByRole('link', { name: 'Runs', exact: true }).click();
  const runAction = page.locator('.run-action-label').filter({ hasText: 'View analysis details' }).first();
  await expectNormalTextContrast(runAction);
  await runAction.click();
  await page.getByRole('navigation', { name: 'Run detail views' }).getByRole('link', { name: /Evidence/ }).click();
  await expectNormalTextContrast(page.getByRole('link', { name: 'Open the global evidence index' }));
  const selectedEvidence = page.getByRole('link', { name: 'Alpha evidence record' });
  await selectedEvidence.click();
  const selectedResult = await expectNormalTextContrast(selectedEvidence);
  expect(selectedResult.background).toBe('rgb(72, 49, 95)');
  await expectNormalTextContrast(page.locator('.text-button').first());

  await page.evaluate(() => {
    const surface = document.createElement('div');
    surface.dataset.contrastFixture = 'text-arm';
    surface.style.background = 'var(--surface)';
    const label = document.createElement('span');
    label.className = 'text-arm-name';
    label.textContent = 'Comparison arm A';
    surface.append(label);
    document.body.append(surface);
  });
  await expectNormalTextContrast(page.locator('[data-contrast-fixture="text-arm"] .text-arm-name'));
});

test('refresh failure keeps last good snapshot; a slower earlier subject cannot replace a later one', async ({ page, request }) => {
  const original = await (await request.get('/api/datasource?subject=NOW')).json();
  await page.goto('/datasource'); await page.getByRole('link', { name: 'Evidence', exact: true }).click(); await expect(page.locator('.source-title-button').first()).toBeVisible();
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
  await page.goto('/datasource?view=runs');
  const runRow = page.locator('.execution-table tbody tr').filter({ hasText: run.execution_id ?? run.id });
  await runRow.getByRole('button').click();
  await page.getByText('Catalog and extracted observations', { exact: true }).click();
  await expect(page.locator('.question-list li')).toHaveCount(run.output.questions.length);
  await expect(page.locator('.observation')).toHaveCount(run.output.observations.length);
  await page.screenshot({ path: '../runtime/datasource-scheduled-query.png', fullPage: true });
  await page.getByRole('link', { name: 'Evidence', exact: true }).click();
  await expect(page.locator('.source-title-button').first()).toBeVisible();
  await page.getByLabel('Used by research run', { exact: true }).selectOption(run.id);
  await page.getByText('Technical provenance and linked run IDs', { exact: true }).click();
  await expect(page.locator('.run-temporal-assessment')).toContainText('Guarded');
  await expect(page.locator('.run-temporal-assessment').getByText('eligible', { exact: true })).toBeVisible();
  const probe = data.sources.find(row => row.url === 'https://example.invalid/synthetic-future');
  expect(probe?.temporal.status).toBe('blocked'); expect(probe?.temporal.worker_visible).toBe(false);
  await page.getByLabel('Used by research run', { exact: true }).selectOption('all');
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
  await expect(page.getByRole('heading', { name: 'Overview', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Runs', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Runs', exact: true })).toBeVisible();
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

test('successful stale research snapshots remain dated and cannot appear complete', async ({ page }) => {
  await syntheticResearch(page, syntheticResearchPacket({ projection_state: 'stale' }));
  await page.goto('/datasource?subject=TEST&view=overview');
  await expect(page.getByText('Research snapshot is stale', { exact: true })).toBeVisible();
  await expect(page.locator('.dataset-bar .badge')).toHaveText('Retained snapshot');
  await expect(page.locator('.dataset-bar')).not.toContainText('Snapshot complete');
  await expect(page.locator('.snapshot-footer')).toContainText('2026-11-05 00:00:00 UTC');
  await expect(page.getByRole('heading', { name: 'Evidence readiness', exact: true })).toBeVisible();
  await expect(page.locator('[aria-labelledby="evidence-readiness-title"]')).toContainText('Availability unknown');
  await page.getByRole('link', { name: 'Evidence', exact: true }).click();
  await expect(page.locator('.source-title-button')).toHaveCount(2);
  await expect(page.getByText('Research snapshot is stale', { exact: true })).toBeVisible();
});

test('malformed nested research records fail at the read boundary and retain same-subject evidence', async ({ page }) => {
  const valid = syntheticResearchPacket(); let malformed = null;
  await page.route('**/api/datasource?**', route => route.fulfill({ json: malformed ?? valid }));
  await page.goto('/datasource?subject=TEST&view=evidence');
  await expect(page.locator('.source-title-button')).toHaveCount(2);
  for (const invalid of [{ ...valid, sources: [{ id: 'invalid-source' }] }, { ...valid, batches: [{ id: 'invalid-batch' }] }, { ...valid, comparisons: [{ id: 'invalid-comparison' }] }]) {
    malformed = invalid; await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await expect(page.getByRole('alert').getByText('Refresh failed', { exact: true })).toBeVisible();
    await expect(page.locator('.source-title-button')).toHaveCount(2);
    await expect(page.getByRole('heading', { name: 'Research observability could not be displayed', exact: true })).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(/invalid-source|invalid-batch|invalid-comparison/);
  }
});

test('evidence URL identity and browser Back restore exact run and source scope on mobile', async ({ page }) => {
  const value = syntheticResearchPacket();
  await syntheticResearch(page, value);
  await page.setViewportSize({ width: 360, height: 800 }); await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/datasource?subject=TEST&view=evidence');
  const alpha = page.getByRole('button', { name: 'Alpha evidence record', exact: true });
  await alpha.focus(); await page.keyboard.press('Enter');
  const inspector = page.getByRole('complementary', { name: 'Selected source details' });
  const alphaHeading = inspector.getByRole('heading', { name: 'Alpha evidence record', exact: true });
  await expect(alphaHeading).toBeVisible(); await expect(alphaHeading).toBeFocused();
  await expect(page).toHaveURL(/source=source-alpha/);
  await page.getByRole('button', { name: 'Back to evidence records', exact: true }).click();
  await expect(alpha).toBeFocused(); await expect(alpha).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: 'Beta evidence record', exact: true }).click();
  await expect(inspector.getByRole('heading', { name: 'Beta evidence record', exact: true })).toBeVisible();
  await page.goBack();
  await expect(inspector.getByRole('heading', { name: 'Alpha evidence record', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/source=source-alpha/);

  await page.goto('/datasource?subject=TEST&view=evidence&run=run-alpha&source=source-beta');
  await expect(page.getByLabel('Used by research run', { exact: true })).toHaveValue('run-alpha');
  await expect(page.locator('.source-title-button')).toHaveCount(1);
  await expect(page.locator('.source-title-button')).toHaveText('Alpha evidence record');
  await expect(page.getByRole('heading', { name: 'Evidence record not in this view', exact: true })).toBeVisible();
  await expect(page.locator('.inspector-title')).toHaveCount(0);

  await page.goto('/datasource?subject=TEST&view=evidence&source=no-such-source');
  await expect(page.getByRole('heading', { name: 'Evidence record not found', exact: true })).toBeVisible();
  await expect(page.locator('.inspector-title')).toHaveCount(0);
  await expect(page).toHaveURL(/source=no-such-source/);
  await page.goto('/datasource?subject=TEST&view=evidence&run=no-such-run');
  await expect(page.getByRole('heading', { name: 'Research run not found', exact: true })).toBeVisible();
  await expect(page.locator('.source-title-button')).toHaveCount(0);
  await expect(page.getByLabel('Used by research run', { exact: true })).toHaveValue('no-such-run');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
