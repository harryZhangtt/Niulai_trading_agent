import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

const stamp = '2026-11-04T00:00:00+00:00';
function run(id, patch = {}) {
  return {
    id, revision: 1, manifest_sha256: 'a'.repeat(64), created_at: stamp, status: 'succeeded',
    provenance: { origin: 'synthetic_fixture', evidence: 'fixture_only' },
    engine: { rdagent_revision: '1'.repeat(40), rdagent_tree: '2'.repeat(40), qlib_profile: 'qlib-rdagent-compatible', qlib_revision: '3'.repeat(40), qlib_tree: '4'.repeat(40), adapter_version: 'rdagent-adapter-v1' },
    protocol_sha256: null, dataset_snapshot_sha256: null,
    stages: ['proposal', 'coding', 'factor-output', 'feedback'].map(stage => ({ id: stage, status: 'succeeded', attempt_count: 1, receipt_sha256: 'b'.repeat(64), failure_code: null })),
    factors: [],
    gates: [
      { id: 'implementation', dimension: 'implementation', status: 'pass', reason_code: 'synthetic-boundary-passed', evidence_sha256: 'c'.repeat(64) },
      { id: 'predictive', dimension: 'predictive', status: 'withheld', reason_code: 'fixture-only', evidence_sha256: null },
      { id: 'economic', dimension: 'economic', status: 'withheld', reason_code: 'fixture-only', evidence_sha256: null },
      { id: 'publication', dimension: 'publication', status: 'withheld', reason_code: 'fixture-only', evidence_sha256: null },
    ], failures: [], resources: { wall_seconds: 0.12, cpu_seconds: 0.02, peak_rss_bytes: 4096, cache_hit: false },
    limitations: ['Synthetic fixture only; no alpha evidence.'], artifact_count: 2,
    artifacts: [{ id: 'factor-output', kind: 'factor-data', sha256: 'd'.repeat(64), size_bytes: 128 }],
    ...patch,
  };
}
function packet(runs, patch = {}) { return { schema_version: 1, generated_at: stamp, read_only: true, scope: 'factor_mining', status: runs.length ? 'ok' : 'empty', projection_state: 'fresh', runs, warnings: [], ...patch }; }
async function fixtures(page, handler) {
  await page.route('**/api/factor-mining*', async route => {
    const params = new URL(route.request().url()).searchParams;
    const value = await handler(params, route);
    if (value !== undefined) await route.fulfill({ json: value });
  });
}
const factorViews = page => page.getByRole('navigation', { name: 'Factor run views' });
const factorRows = page => page.getByRole('region', { name: 'Factor-mining runs' }).locator('ul').getByRole('button');
const factorRow = (page, id) => factorRows(page).filter({ hasText: id });
async function openFactorView(page, name) {
  await factorViews(page).getByRole('button', { name, exact: true }).click();
}

test('fixture run is visible while predictive, economic and publication evidence stay withheld', async ({ page }) => {
  const alpha = run('fixture-alpha');
  await fixtures(page, async params => packet(params.get('run') ? [alpha] : [alpha]));
  await page.goto('/factor-mining');
  await expect(page.getByRole('heading', { name: 'Factor mining', exact: true })).toBeVisible();
  await expect(factorViews(page).getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('Fixture evidence only', { exact: true })).toBeVisible();
  await openFactorView(page, 'Evidence');
  await expect(page.getByRole('table', { name: 'Factor admission gates' })).toContainText('Withheld');
  await openFactorView(page, 'Factors');
  await expect(page.getByRole('heading', { name: 'No factor metrics recorded' })).toBeVisible();
  await expect(page.getByText('EV and Kelly stay withheld', { exact: false })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Workspace' }).getByRole('link', { name: 'Scheduler' })).toBeVisible();
});

test('structured reproduced performance renders comparable intervals and an exact table', async ({ page }) => {
  const evidence = '9'.repeat(64);
  const factors = [
    { id: 'factor-a', family: 'macro', formula_sha256: '7'.repeat(64), status: 'evaluated', metrics: {} },
    { id: 'factor-b', family: 'credit', formula_sha256: '8'.repeat(64), status: 'evaluated', metrics: {} },
  ];
  const context = { availability: 'available', reason_code: null, metric_id: 'net_log_growth', estimate_unit: 'percentage_points', uncertainty: { kind: 'block_bootstrap', lower: -0.1, upper: 0.3, level: 0.95 }, sample: { size: 33, unit: 'monthly_origins' }, period: { id: 'protected', start: '2022-01-01', end: '2025-01-01' }, baseline_id: 'rv20', evidence_sha256: evidence };
  const performance = [
    { ...context, id: 'standalone-a', subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, point_estimate: 0.08 },
    { ...context, id: 'combo-ab', subject: { kind: 'combination', factor_ids: ['factor-a', 'factor-b'], omitted_factor_id: null }, point_estimate: 0.12 },
    { ...context, id: 'without-b', subject: { kind: 'leave_one_out', factor_ids: ['factor-a'], omitted_factor_id: 'factor-b' }, point_estimate: 0.04 },
  ];
  const reproduced = run('reproduced-alpha', { manifest_schema_version: 2, provenance: { origin: 'reproduced_local', evidence: 'hash_bound' }, protocol_sha256: '5'.repeat(64), dataset_snapshot_sha256: '6'.repeat(64), factors, performance_state: 'available_hash_bound', performance, artifacts: [{ id: 'evaluation', kind: 'evaluation', sha256: evidence, size_bytes: 512 }], artifact_count: 1 });
  const overview = { ...reproduced, performance: undefined, artifacts: undefined };
  await fixtures(page, async params => packet(params.get('run') ? [reproduced] : [overview]));
  await page.goto('/factor-mining');
  await openFactorView(page, 'Performance');
  const table = page.getByRole('table', { name: /exact performance records/ });
  await expect(table).toContainText('factor-a');
  await expect(table).toContainText('Combination: factor-a + factor-b');
  await expect(table).toContainText('Combination without factor-b');
  await expect(table).toContainText('-0.1 to 0.3');
  await expect(table).toContainText('33 monthly origins');
  await expect(table).toContainText('Reproduced · hash bound');
  await expect(page.getByRole('img', { name: /point estimates and uncertainty intervals/ })).toBeVisible();
});

test('fixture scalar metrics are suppressed rather than shown as performance', async ({ page }) => {
  const fixture = run('fixture-with-metric', { factors: [{ id: 'factor-a', family: 'macro', formula_sha256: null, status: 'evaluated', metrics: { suspicious_alpha: 12345 } }] });
  await fixtures(page, async params => packet(params.get('run') ? [fixture] : [fixture]));
  await page.goto('/factor-mining');
  await openFactorView(page, 'Performance');
  await expect(page.getByText('Fixture performance is withheld')).toBeVisible();
  await openFactorView(page, 'Factors');
  await expect(page.locator('body')).not.toContainText('12345');
});

test('reported structured performance stays visibly unverified', async ({ page }) => {
  const evidence = '9'.repeat(64);
  const reported = run('reported-alpha', { manifest_schema_version: 2, provenance: { origin: 'reported_external', evidence: 'unverified' }, factors: [{ id: 'factor-a', family: 'macro', formula_sha256: null, status: 'evaluated', metrics: { mse: 1.2 } }], performance_state: 'available_unverified', performance: [{ id: 'reported-a', subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, availability: 'available', reason_code: null, metric_id: 'mse', estimate_unit: 'ratio', point_estimate: 1.2, uncertainty: { kind: 'reported_interval', lower: 1, upper: 1.4, level: null }, sample: { size: 10, unit: 'origins' }, period: { id: 'reported_period', start: '2022-01-01', end: '2025-01-01' }, baseline_id: 'historical_mean', evidence_sha256: evidence }], artifacts: [{ id: 'evaluation', kind: 'evaluation', sha256: evidence, size_bytes: 256 }], artifact_count: 1 });
  await fixtures(page, async params => packet(params.get('run') ? [reported] : [reported]));
  await page.goto('/factor-mining');
  await expect(page.getByText('Reported evidence is unverified', { exact: true })).toBeVisible();
  await openFactorView(page, 'Performance');
  await expect(page.getByRole('table', { name: /exact performance records/ })).toContainText('Reported · unverified');
});

test('explicitly unavailable performance stays unavailable without a zero default', async ({ page }) => {
  const unavailable = run('unavailable-alpha', { manifest_schema_version: 2, provenance: { origin: 'reproduced_local', evidence: 'hash_bound' }, protocol_sha256: '5'.repeat(64), dataset_snapshot_sha256: '6'.repeat(64), factors: [{ id: 'factor-a', family: 'macro', formula_sha256: '7'.repeat(64), status: 'unavailable', metrics: {} }], performance_state: 'unavailable', performance: [{ id: 'missing-a', subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, availability: 'unavailable', reason_code: 'insufficient_effective_sample', metric_id: 'net_log_growth', estimate_unit: null, point_estimate: null, uncertainty: null, sample: null, period: null, baseline_id: null, evidence_sha256: null }], artifacts: [], artifact_count: 0 });
  await fixtures(page, async params => packet(params.get('run') ? [unavailable] : [unavailable]));
  await page.goto('/factor-mining');
  await openFactorView(page, 'Performance');
  const table = page.getByRole('table', { name: /exact performance records/ });
  await expect(table).toContainText('insufficient effective sample');
  await expect(table).not.toContainText('0 percentage');
  await expect(page.getByRole('img', { name: /point estimates/ })).toHaveCount(0);
});

test('invalid provenance, manifest version and performance-state combinations fail closed', async ({ page }) => {
  const evidence = '9'.repeat(64);
  const observation = { id: 'standalone-a', subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, availability: 'available', reason_code: null, metric_id: 'mse', estimate_unit: 'ratio', point_estimate: 1.2, uncertainty: { kind: 'block_bootstrap', lower: 1, upper: 1.4, level: 0.95 }, sample: { size: 10, unit: 'origins' }, period: { id: 'protected', start: '2022-01-01', end: '2025-01-01' }, baseline_id: 'historical_mean', evidence_sha256: evidence };
  const valid = run('invalid-contract', { manifest_schema_version: 2, provenance: { origin: 'reproduced_local', evidence: 'hash_bound' }, protocol_sha256: '5'.repeat(64), dataset_snapshot_sha256: '6'.repeat(64), factors: [{ id: 'factor-a', family: 'macro', formula_sha256: '7'.repeat(64), status: 'evaluated', metrics: { mse: 1.2 } }], performance_state: 'available_hash_bound', performance: [observation], artifacts: [{ id: 'evaluation', kind: 'evaluation', sha256: evidence, size_bytes: 256 }], artifact_count: 1 });
  const invalid = [
    { ...valid, protocol_sha256: null, dataset_snapshot_sha256: null },
    { ...valid, manifest_schema_version: 1 },
    { ...valid, performance_state: 'not_published' },
    { ...valid, performance_state: 'unavailable' },
    { ...valid, performance_state: undefined },
    { ...valid, performance_state: 'available' },
  ];
  let current = invalid[0];
  await fixtures(page, async () => packet([current]));
  for (const [index, payload] of invalid.entries()) {
    current = payload;
    await page.goto(`/factor-mining?case=${index}`);
    await expect(page.getByRole('alert').getByText('Factor registry unavailable', { exact: true })).toBeVisible();
  }
});

test('contradictory empty and duplicate immutable factor identities fail before rendering', async ({ page }) => {
  const alpha = run('contradiction-alpha');
  let current = packet([alpha], { status: 'empty' });
  await fixtures(page, async () => current);
  await page.goto('/factor-mining');
  await expect(page.getByRole('alert').getByText('Factor registry unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: alpha.id, exact: true })).toHaveCount(0);
  current = packet([alpha, { ...alpha, revision: 2, manifest_sha256: 'e'.repeat(64) }]);
  await page.reload();
  await expect(page.getByRole('alert').getByText('Factor registry unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: alpha.id, exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Factor mining', exact: true })).toBeVisible();
});

test('paginated performance cohorts retain one scale and contain 200 percent text at 320px', async ({ page }) => {
  const evidence = '9'.repeat(64);
  const factors = [{ id: 'factor-a', family: 'macro', formula_sha256: '7'.repeat(64), status: 'evaluated', metrics: { mse: 1.2 } }];
  const performance = Array.from({ length: 51 }, (_, index) => ({ id: `estimate-${index}`, subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, availability: 'available', reason_code: null, metric_id: 'mse', estimate_unit: 'ratio', point_estimate: index === 50 ? 50 : 0.5, uncertainty: { kind: 'block_bootstrap', lower: index === 50 ? -100 : -1, upper: index === 50 ? 100 : 1, level: 0.95 }, sample: { size: 10, unit: 'origins' }, period: { id: 'protected', start: '2022-01-01', end: '2025-01-01' }, baseline_id: 'historical_mean', evidence_sha256: evidence }));
  const reproduced = run('scale-stable', { manifest_schema_version: 2, provenance: { origin: 'reproduced_local', evidence: 'hash_bound' }, protocol_sha256: '5'.repeat(64), dataset_snapshot_sha256: '6'.repeat(64), factors, performance_state: 'available_hash_bound', performance, artifacts: [{ id: 'evaluation', kind: 'evaluation', sha256: evidence, size_bytes: 256 }], artifact_count: 1 });
  await fixtures(page, async params => packet(params.get('run') ? [reproduced] : [{ ...reproduced, performance: undefined, artifacts: undefined }]));
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto('/factor-mining');
  await factorRow(page, reproduced.id).click();
  await openFactorView(page, 'Performance');
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  const chart = page.getByRole('img', { name: /point estimates and uncertainty intervals/ });
  await expect(chart).toBeVisible();
  const firstAxis = (await chart.locator('text').allTextContents()).slice(-3);
  await page.getByRole('button', { name: 'Next' }).click();
  const secondAxis = (await page.getByRole('img', { name: /point estimates and uncertainty intervals/ }).locator('text').allTextContents()).slice(-3);
  expect(secondAxis).toEqual(firstAxis);
  const overflow = await page.locator('body *').evaluateAll(nodes => nodes.filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0, 12).map(element => ({ tag: element.tagName, className: element.className, left: element.getBoundingClientRect().left, right: element.getBoundingClientRect().right, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), JSON.stringify(overflow)).toBe(true);
});

test('late detail response for A cannot overwrite selected B', async ({ page }) => {
  const alpha = run('alpha'); const beta = run('beta', { manifest_sha256: 'e'.repeat(64) });
  let release; let arrived; const gate = new Promise(resolve => { release = resolve; }); const seen = new Promise(resolve => { arrived = resolve; });
  await fixtures(page, async params => {
    if (!params.get('run')) return packet([alpha, beta]);
    if (params.get('run') === 'alpha') { arrived(); await gate; return packet([alpha]); }
    return packet([beta]);
  });
  await page.goto('/factor-mining'); await seen;
  await factorRow(page, 'beta').click();
  await expect(page.getByRole('heading', { name: 'beta', exact: true })).toBeVisible();
  release();
  await expect(page.getByRole('heading', { name: 'alpha', exact: true })).toHaveCount(0);
});

test('factor details that begin without selection start their own visible-page polling after registry load', async ({ page }) => {
  const alpha = run('poll-after-selection');
  let overviewCalls = 0; let detailCalls = 0;
  await page.clock.install({ time: new Date('2026-11-04T00:00:00Z') });
  await fixtures(page, async params => {
    if (params.get('run')) detailCalls++; else overviewCalls++;
    return packet([alpha]);
  });
  await page.goto('/factor-mining');
  await expect(page.getByRole('heading', { name: alpha.id, exact: true })).toBeVisible();
  await expect(factorViews(page).getByRole('button', { name: 'Overview', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('button', { name: 'Refresh runs', exact: true })).toBeEnabled();
  await page.clock.pauseAt(new Date('2026-11-04T00:00:05Z'));
  const overviewBefore = overviewCalls; const detailBefore = detailCalls;
  expect(detailBefore).toBeGreaterThan(0);
  await page.clock.runFor(30_000);
  await expect.poll(() => overviewCalls).toBeGreaterThan(overviewBefore);
  await expect.poll(() => detailCalls).toBeGreaterThan(detailBefore);
  await expect(page.getByRole('heading', { name: alpha.id, exact: true })).toBeVisible();
});

test('empty registry and failed refresh are explicit without raw diagnostics', async ({ page }) => {
  let fail = false;
  await fixtures(page, async (_params, route) => {
    if (fail) { await route.fulfill({ status: 503, json: { error: { message: 'SYNTHETIC_PRIVATE' } } }); return; }
    return packet([]);
  });
  await page.goto('/factor-mining');
  await expect(page.getByRole('heading', { name: 'No factor-mining runs available' })).toBeVisible();
  fail = true; await page.getByRole('button', { name: 'Refresh runs' }).click();
  await expect(page.getByRole('alert').getByText('Factor registry unavailable', { exact: true })).toBeVisible();
  await expect(page.locator('body')).not.toContainText('SYNTHETIC_PRIVATE');
});

test('malformed manifests fail at the adapter boundary without crashing page shell', async ({ page }) => {
  await fixtures(page, async () => packet([{ ...run('broken'), resources: { wall_seconds: Number.NaN } }]));
  await page.goto('/factor-mining');
  await expect(page.getByRole('alert').getByText('Factor registry unavailable', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Factor mining', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Factor mining could not be displayed' })).toHaveCount(0);
});

test('narrow layout, keyboard focus and long identities remain usable', async ({ page }) => {
  const long = run('run-' + 'w'.repeat(80), { limitations: ['X'.repeat(900)] });
  await fixtures(page, async params => packet(params.get('run') ? [long] : [long]));
  await page.setViewportSize({ width: 320, height: 800 }); await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/factor-mining');
  const button = factorRow(page, long.id); await button.focus();
  expect(await button.evaluate(element => element.matches(':focus-visible'))).toBe(true);
  await page.keyboard.press('Enter');await openFactorView(page, 'Evidence');
  const overflow = await page.locator('body *').evaluateAll(nodes => nodes.filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0, 10).map(element => ({ tag: element.tagName, className: element.className, right: element.getBoundingClientRect().right })));
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), JSON.stringify(overflow)).toBe(true);
});

test('factor run deep links stay exact and unknown identities never substitute the first run', async ({ page }) => {
  const alpha = run('alpha-linked'); const beta = run('beta-linked', { manifest_sha256: 'e'.repeat(64) });
  const runs = [alpha, beta];
  await fixtures(page, async params => packet(params.get('run') ? runs.filter(item => item.id === params.get('run')) : runs));
  await page.goto('/factor-mining?run=beta-linked');
  await expect(page.getByRole('heading', { name: 'beta-linked', exact: true })).toBeVisible();
  await expect(factorRow(page, 'beta-linked')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('heading', { name: 'alpha-linked', exact: true })).toHaveCount(0);
  await page.goto('/factor-mining?run=unknown-linked');
  await expect(page.getByRole('heading', { name: 'Requested run not found', exact: true })).toBeVisible();
  await expect(page).toHaveURL(/run=unknown-linked/);
  await expect(page.getByRole('heading', { name: 'alpha-linked', exact: true })).toHaveCount(0);
  await expect(factorRow(page, 'alpha-linked')).toHaveAttribute('aria-pressed', 'false');
});

test('independently stale and partial factor details remain labelled while the registry is fresh', async ({ page }) => {
  const alpha = run('retained-factor'); let partial = false;
  await fixtures(page, async params => params.get('run') ? packet([alpha], partial ? { status: 'partial' } : { projection_state: 'stale' }) : packet([alpha]));
  await page.goto('/factor-mining');
  await expect(page.getByText('Run snapshot is stale', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'retained-factor', exact: true })).toBeVisible();
  await expect(page.getByText('Fixture evidence only', { exact: true })).toBeVisible();
  partial = true; await page.getByRole('button', { name: 'Refresh runs', exact: true }).click();
  await expect(page.getByText('Run snapshot is incomplete', { exact: true })).toBeVisible();
  await expect(page.getByText('Run snapshot is stale', { exact: true })).toHaveCount(0);
});

test('factor selection scopes comparable performance and mobile Back restores run focus', async ({ page }) => {
  const evidence = '9'.repeat(64);
  const factors = [
    { id: 'factor-a', family: 'macro', formula_sha256: '7'.repeat(64), status: 'evaluated', metrics: {} },
    { id: 'factor-b', family: 'credit', formula_sha256: '8'.repeat(64), status: 'evaluated', metrics: {} },
  ];
  const context = { availability: 'available', reason_code: null, metric_id: 'net_log_growth', estimate_unit: 'percentage_points', uncertainty: { kind: 'block_bootstrap', lower: -0.1, upper: 0.3, level: 0.95 }, sample: { size: 33, unit: 'monthly_origins' }, period: { id: 'protected', start: '2022-01-01', end: '2025-01-01' }, baseline_id: 'rv20', evidence_sha256: evidence };
  const performance = [
    { ...context, id: 'standalone-a', subject: { kind: 'standalone', factor_ids: ['factor-a'], omitted_factor_id: null }, point_estimate: 0.08 },
    { ...context, id: 'standalone-b', subject: { kind: 'standalone', factor_ids: ['factor-b'], omitted_factor_id: null }, point_estimate: 0.1 },
    { ...context, id: 'combo-ab', subject: { kind: 'combination', factor_ids: ['factor-a', 'factor-b'], omitted_factor_id: null }, point_estimate: 0.12 },
    { ...context, id: 'without-b', subject: { kind: 'leave_one_out', factor_ids: ['factor-a'], omitted_factor_id: 'factor-b' }, point_estimate: 0.04 },
  ];
  const reproduced = run('factor-selection', { manifest_schema_version: 2, provenance: { origin: 'reproduced_local', evidence: 'hash_bound' }, protocol_sha256: '5'.repeat(64), dataset_snapshot_sha256: '6'.repeat(64), factors, performance_state: 'available_hash_bound', performance, artifacts: [{ id: 'evaluation', kind: 'evaluation', sha256: evidence, size_bytes: 512 }], artifact_count: 1 });
  await fixtures(page, async params => packet(params.get('run') ? [reproduced] : [{ ...reproduced, performance: undefined, artifacts: undefined }]));
  await page.setViewportSize({ width: 360, height: 800 }); await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/factor-mining');
  const row = factorRow(page, reproduced.id); await row.focus(); await page.keyboard.press('Enter');
  const heading = page.getByRole('heading', { name: reproduced.id, exact: true }); await expect(heading).toBeVisible(); await expect(heading).toBeFocused();
  await openFactorView(page, 'Factors');
  await page.getByRole('combobox', { name: 'Inspect factor', exact: true }).selectOption('factor-a');
  await expect(factorViews(page).getByRole('button', { name: 'Performance', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('combobox', { name: 'Factor scope', exact: true })).toHaveValue('factor-a');
  await page.getByRole('combobox', { name: 'Performance view', exact: true }).selectOption({ label: 'Standalone' });
  const table = page.getByRole('table', { name: /exact performance records/ });
  await expect(table.getByRole('rowheader', { name: 'factor-a', exact: true })).toBeVisible();
  await expect(table.getByRole('rowheader', { name: 'factor-b', exact: true })).toHaveCount(0);
  await page.getByRole('combobox', { name: 'Factor scope', exact: true }).selectOption('factor-b');
  await page.getByRole('combobox', { name: 'Performance view', exact: true }).selectOption({ label: 'Contribution checks' });
  await expect(table).toContainText('Combination: factor-a + factor-b');
  await expect(table).toContainText('Combination without factor-b');
  await expect(table).toContainText('33 monthly origins'); await expect(table).toContainText('Reproduced · hash bound');
  await page.getByRole('button', { name: 'Back to runs', exact: true }).click();
  await expect(row).toBeFocused(); await expect(row).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test('live factor registry remains empty and shows readiness without synthetic seed runs', async ({ page, request }) => {
  const reply = await request.get('/api/factor-mining?refresh=1'); expect(reply.ok()).toBe(true);
  const actual = await reply.json(); expect(actual.read_only).toBe(true); expect(actual.scope).toBe('factor_mining'); expect(actual.status).toBe('empty'); expect(actual.runs).toEqual([]);
  const methods = []; page.on('request', current => { if (new URL(current.url()).pathname === '/api/factor-mining') methods.push(current.method()); });
  await page.goto('/factor-mining');
  await expect(page.getByRole('heading', { name: 'No factor-mining runs available', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'How factor evidence progresses', exact: true })).toBeVisible();
  expect(await page.getByText('No run evidence', { exact: true }).count()).toBeGreaterThan(1);
  await expect(factorRows(page)).toHaveCount(0); await expect(page.getByRole('table', { name: /exact performance records/ })).toHaveCount(0);
  expect(methods.length).toBeGreaterThan(0); expect(methods.every(method => method === 'GET')).toBe(true);
  await expect(page.getByRole('button', { name: /Run experiment|Start mining|Promote|Send|Replay/i })).toHaveCount(0);
});
