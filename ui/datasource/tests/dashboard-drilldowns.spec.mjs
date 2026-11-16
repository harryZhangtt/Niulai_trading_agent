import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

test('collection run exposes configuration JSON and exact captured evidence drilldown', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW&refresh=1')).json();
  const batch = data.batches.find(item => item.batch_id === 'now-official-source') ?? data.batches[0];
  expect(batch).toBeTruthy(); expect(batch.sources.length).toBeGreaterThan(0);
  await page.goto(`/datasource?subject=NOW&view=runs&kind=collection&run=${encodeURIComponent(batch.id)}`);
  await expect(page.locator('.batch-details')).toContainText(batch.execution_id);
  await page.getByText('Configuration, routes, and scripts', { exact: true }).click();
  await page.getByText('Configuration JSON', { exact: true }).click();
  const config = page.getByLabel(`Configuration JSON for ${batch.batch_id}`);
  await expect(config).toContainText('"budget"');
  await expect(config).toContainText('"requirements"');
  const source = batch.sources[0];
  await page.getByRole('navigation', { name: 'Run detail views' }).getByRole('link', { name: /Evidence/ }).click();
  const runEvidence = page.getByRole('region', { name: 'Evidence bound to this run' });
  await expect(runEvidence).toContainText(source.title || source.id);
  await runEvidence.getByRole('link', { name: source.title || 'Untitled source', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`view=runs.*runTab=evidence.*source=${encodeURIComponent(source.id)}`));
  await expect(runEvidence.locator('.inspector-title')).toHaveText(source.title || 'Untitled source');
  if (source.url) await expect(runEvidence.getByRole('link', { name: 'Open original source' })).toHaveAttribute('href', source.url);
  await expect(runEvidence.getByRole('link', { name: 'Open the global evidence index' })).toHaveAttribute('href', /view=evidence/);
});

test('collection and research rows route from the run list to focused detail screens', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const batch = data.batches[0];
  const run = data.runs[0];
  expect(batch).toBeTruthy(); expect(run).toBeTruthy();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/datasource?subject=NOW&view=runs');
  await expect(page.getByText('Fetches or reuses source records and saves provenance.', { exact: false })).toBeVisible();
  await expect(page.getByText('Reads a bounded evidence packet and produces questions, observations, or analysis.', { exact: false })).toBeVisible();
  await expect(page.locator('.run-detail-anchor')).toHaveCount(0);

  const collectionRow = page.locator('.execution-table tbody tr').filter({ hasText: batch.execution_id });
  await collectionRow.getByRole('button', { name: /View collection details/ }).click();
  const collectionDetail = page.getByLabel('Selected data collection details');
  await expect(page.getByRole('heading', { name: 'Data collection details' })).toBeVisible();
  await expect(collectionDetail).toBeVisible();
  await expect(collectionDetail).toContainText(batch.execution_id);
  await expect(page).toHaveURL(new RegExp(`kind=collection.*run=${encodeURIComponent(batch.id)}`));
  await expect(collectionDetail).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toHaveCount(0);

  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toBeVisible();
  const researchRow = page.locator('.execution-table tbody tr').filter({ hasText: run.execution_id ?? run.id });
  await researchRow.getByRole('button', { name: /View analysis details/ }).click();
  const researchDetail = page.getByLabel('Selected research analysis details');
  await expect(page.getByRole('heading', { name: 'Research run', exact: true })).toBeVisible();
  await expect(researchDetail).toContainText(run.execution_id ?? run.id);
  await expect(page).toHaveURL(new RegExp(`kind=research.*run=${encodeURIComponent(run.id)}`));
  await expect(researchDetail).toBeFocused();
  await expect(page.getByRole('heading', { name: 'Research analysis runs' })).toHaveCount(0);

  await page.getByRole('button', { name: 'Back to runs' }).click();
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toBeVisible();
  await expect(page.locator('.run-detail-anchor')).toHaveCount(0);
});

test('overview charts reconcile actual snapshot denominators and retain table equivalents', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const native = data.comparisons.flatMap(item => item.acquisition?.collections ?? []);
  await page.goto('/datasource?subject=NOW&view=overview');
  await expect(page.getByRole('heading', { name: 'Run health' })).toBeVisible();
  await expect(page.getByText(`Research runs${data.runs.length} runs`, { exact: false })).toBeVisible();
  await expect(page.getByText(`Collection runs${data.batches.length} runs`, { exact: false })).toBeVisible();
  await expect(page.getByText(`Comparison runs${native.length} runs`, { exact: false })).toBeVisible();
  await page.getByText('Run-status data table', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Run-status data' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Evidence readiness' })).toBeVisible();
  await expect(page.locator('[aria-label="Snapshot summary"]')).toContainText(String(data.pagination.total_sources));
  await page.getByText('Recorded-start data table', { exact: true }).click();
  await expect(page.getByRole('region', { name: 'Recorded run starts by UTC date' })).toBeVisible();
});

test('comparison rows route to an exact arm detail screen', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const comparison = data.comparisons.find(item => item.acquisition);
  const collection = comparison.acquisition.collections[0];
  await page.goto('/datasource?subject=NOW&view=runs');
  const row = page.locator('.execution-table tbody tr').filter({ hasText: collection.execution_id });
  await row.getByRole('button', { name: /View arm details/ }).click();
  await expect(page).toHaveURL(new RegExp(`kind=comparison.*run=${encodeURIComponent(collection.execution_id)}`));
  await expect(page.getByRole('heading', { name: 'A/B comparison arm details' })).toBeVisible();
  await expect(page.locator('.comparison-run-detail')).toContainText(collection.execution_id);
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toHaveCount(0);
  const full = page.locator('.comparison-run-detail').getByRole('link', { name: 'Open full comparison' });
  await expect(full).toHaveAttribute('href', new RegExp(`comparison=${encodeURIComponent(comparison.id)}.*collection=${encodeURIComponent(collection.execution_id)}`));
});

test('direct run links resolve exact identities and invalid identities stay on a not-found detail screen', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const run = data.runs[0];
  await page.goto(`/datasource?subject=NOW&view=runs&kind=research&run=${encodeURIComponent(run.id)}`);
  await expect(page.getByLabel('Selected research analysis details')).toContainText(run.execution_id ?? run.id);
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toHaveCount(0);

  await page.goto('/datasource?subject=NOW&view=runs&kind=collection&run=no-such-run');
  await expect(page.getByRole('heading', { name: 'Collection run not found' })).toBeVisible();
  await expect(page.getByText('No collection run matches no-such-run', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Back to runs' }).click();
  await expect(page.getByRole('heading', { name: 'Data collection runs' })).toBeVisible();
});

test('run evidence tabs stay scoped to exact collection, research and comparison identities', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const research = data.runs.find(run => data.sources.some(source => source.run_ids.includes(run.id) || (run.execution_id && source.run_ids.includes(run.execution_id))));
  expect(research, 'requires one research run with an explicit source.run_ids relationship').toBeTruthy();
  const researchIds = new Set([research.id, research.execution_id].filter(Boolean));
  const researchSources = data.sources.filter(source => source.run_ids.some(id => researchIds.has(id)));
  const unrelated = data.sources.find(source => !researchSources.some(candidate => candidate.id === source.id));
  expect(researchSources.length).toBeGreaterThan(0);

  await page.goto(`/datasource?subject=NOW&view=runs&kind=research&run=${encodeURIComponent(research.id)}&runTab=evidence`);
  const researchEvidence = page.getByRole('region', { name: 'Evidence bound to this run' });
  await expect(researchEvidence).toBeVisible();
  for (const source of researchSources) await expect(researchEvidence).toContainText(source.id);
  if (unrelated) await expect(researchEvidence).not.toContainText(unrelated.id);
  const source = researchSources[0];
  await researchEvidence.locator(`a[href*="source=${encodeURIComponent(source.id)}"]`).click();
  await expect(page).toHaveURL(new RegExp(`runTab=evidence.*source=${encodeURIComponent(source.id)}`));
  await expect(researchEvidence.locator('.inspector-title')).toHaveText(source.title || 'Untitled source');
  await page.goBack();
  await expect(page.getByRole('heading', { name: 'Choose run evidence' })).toBeVisible();

  await page.goto(`/datasource?subject=NOW&view=runs&kind=research&run=${encodeURIComponent(research.id)}&runTab=evidence&source=no-such-source`);
  await expect(page.getByRole('heading', { name: 'Evidence record not found for this run' })).toBeVisible();
  await expect(researchEvidence.locator('.inspector-title')).toHaveCount(0);

  const comparison = data.comparisons.find(item => item.acquisition?.collections.some(collection => collection.sources.length));
  expect(comparison).toBeTruthy();
  const arm = comparison.acquisition.collections.find(collection => collection.sources.length);
  await page.goto(`/datasource?subject=NOW&view=runs&kind=comparison&run=${encodeURIComponent(arm.execution_id)}&runTab=evidence`);
  const comparisonEvidence = page.getByRole('region', { name: 'Evidence bound to this run' });
  for (const armSource of arm.sources) await expect(comparisonEvidence).toContainText(armSource.id);
  const outsideArm = data.sources.find(candidate => !arm.sources.some(armSource => armSource.id === candidate.id));
  if (outsideArm) await expect(comparisonEvidence).not.toContainText(outsideArm.id);
});

test('partial source pages disclose incomplete run relationship coverage', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const research = data.runs.find(run => data.sources.some(source => source.run_ids.includes(run.id) || (run.execution_id && source.run_ids.includes(run.execution_id))));
  expect(research).toBeTruthy();
  await page.route('**/api/datasource?**', route => route.fulfill({ json: { ...data, pagination: { ...data.pagination, next_offset: data.pagination.limit } } }));
  await page.goto(`/datasource?subject=NOW&view=runs&kind=research&run=${encodeURIComponent(research.id)}&runTab=evidence`);
  await expect(page.getByText('This snapshot does not contain every evidence page.', { exact: false })).toBeVisible();
});

test('long run, source and JSON values stay reachable at 320px and 200 percent text', async ({ page, request }) => {
  const original = await (await request.get('/api/datasource?subject=NOW')).json();
  const long = 'W'.repeat(1000);
  const batch = original.batches[0];
  const source = { ...batch.sources[0], title: long, url: `https://example.com/${long}` };
  const patchedBatch = { ...batch, batch_id: `long-${long}`, query: long, sources: [source], configuration: { ...batch.configuration, requirements: batch.configuration.requirements.map((item, index) => index ? item : { ...item, id: long, routes: [{ capability: 'official_document.read', parameters: { url: source.url } }] }) } };
  await page.route('**/api/datasource?**', route => route.fulfill({ json: { ...original, batches: [patchedBatch], pagination: { ...original.pagination, total_batches: 1 } } }));
  await page.setViewportSize({ width: 320, height: 568 });
  await page.goto('/datasource?subject=NOW&view=runs');
  await page.locator('.execution-table tbody tr').first().getByRole('button').click();
  await page.getByText('Configuration, routes, and scripts', { exact: true }).click();
  await page.getByText('Configuration JSON', { exact: true }).click();
  await page.addStyleTag({ content: 'html { font-size: 200%; }' });
  const pre = page.getByLabel(new RegExp('Configuration JSON for long-'));
  await pre.focus();
  await expect(pre).toBeVisible();
  const overflow = await page.locator('body *').evaluateAll(nodes => nodes.filter(node => node.getBoundingClientRect().right > innerWidth + 1 && !node.closest('.table-wrap')).slice(0, 10).map(node => ({ tag: node.tagName, className: String(node.className).slice(0, 80), width: Math.round(node.getBoundingClientRect().width), right: Math.round(node.getBoundingClientRect().right) })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), JSON.stringify(overflow)).toBe(true);
  expect(await pre.evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
});

test('unprojected source body is stated explicitly without fabricated document text', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const source = data.sources.find(item => !item.local_preview);
  expect(source).toBeTruthy();
  await page.goto(`/datasource?subject=NOW&view=evidence&source=${encodeURIComponent(source.id)}`);
  await expect(page.locator('.source-body-state')).toContainText('captured source body is not projected');
  await expect(page.locator('.document-preview')).toHaveCount(0);
});

test('paginated overview separates loaded-page run counts from subject totals and keeps unknown metric denominators exact', async ({ page }) => {
  const stamp = '2026-11-05T00:00:00Z';
  const run = { id: 'page-run', execution_id: 'page-run', query: 'Synthetic page run', pipeline_id: null, pipeline_version: null, config_sha256: null, status: 'completed', scope: 'synthetic_ui_fixture', started_at: stamp, finished_at: stamp, script_versions: [], phases: [], metrics: {}, source_ids: [], temporal: null, output: null };
  const value = { schema_version: 1, generated_at: stamp, snapshot_id: 'f'.repeat(64), status: 'ok', warnings: [], subject: 'TEST',
    pagination: { offset: 100, limit: 100, total_sources: 250, total_runs: 12, total_batches: 0, total_native_collections: 0, next_offset: 200 },
    sources: [], runs: [run], batches: [], comparisons: [],
    metric_definitions: { cost: { label: 'Cost', unit: 'currency_unknown', caveat: 'Currency was not recorded.' } },
    aggregates: { cohorts: [{ id: 'pipeline_runs:fixture', scope: 'Synthetic measured cohort; full subject denominator.', denominator: 12, metrics: { cost: { sum: null, mean: null, known: 0, unknown: 12, denominator: 12, unit: 'currency_unknown' } }, unknowns: { cost: 12 } }], unknowns: null, source_counts: { total: 250, by_scope: {}, by_publisher: {}, by_document_type: {}, persisted_labels: 7, unknown_available_at: 200 } } };
  await page.route('**/api/datasource?**', route => route.fulfill({ json: value }));
  await page.goto('/datasource?subject=TEST&view=overview');
  await expect(page.locator('[aria-label="Snapshot summary"]')).toContainText('12');
  await expect(page.locator('[aria-label="Snapshot summary"]')).toContainText('250');
  await expect(page.locator('[aria-labelledby="run-health-title"]')).toContainText(/loaded page/i);
  await page.getByText('Run-status data table', { exact: true }).click();
  const statusRow = page.getByRole('region', { name: 'Run-status data' }).getByRole('row').filter({ has: page.getByRole('rowheader', { name: 'Research runs', exact: true }) });
  await expect(statusRow).toContainText('1');
  await expect(page.getByText('Relationship coverage is page-only because more evidence pages exist.', { exact: true })).toBeVisible();
  const metricRow = page.locator('.metric-table tbody tr').filter({ hasText: 'Cost' });
  await expect(metricRow.locator('td').nth(0)).toHaveText('Unknown');
  await expect(metricRow.locator('td').nth(1)).toHaveText('Unknown');
  await expect(metricRow.locator('td').nth(2)).toHaveText('0 / 12');
  await expect(metricRow.locator('td').nth(3)).toHaveText('12');
});
