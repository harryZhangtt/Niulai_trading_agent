import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

const obs = (value, unit) => ({ state: 'known', value, unit });
const trace = () => ({ complete: 1, credited: 1, reviewed_complete: 1, pooled_total: 1, rejected: 0, unjudged: 0 });
const arm = (richness, depth) => ({
  richness: obs(richness, 'canonical_units'),
  depth: obs(depth, 'field_state_steps'),
  precision: obs(1, 'ratio'),
  wall_seconds: obs(10, 'seconds'),
  lineages: obs(1, 'original_lineages'),
  critical_unsupported: obs(0, 'units'),
  trace: trace(),
});
const row = (id, index) => ({
  case_id: id,
  issuer_id: `ISSUER-${index}`,
  subject: 'ACME',
  window_id: `2026Q${index}`,
  evidence_level: 'confirmation',
  split: 'untouched',
  arm_order: index < 4 ? ['B0', 'F'] : ['F', 'B0'],
  request_sha256: 'a'.repeat(64),
  fact_sha256: String(index).repeat(64).slice(0, 64),
  delta_r: obs(1, 'canonical_units'),
  delta_d: obs(1, 'field_state_steps'),
  lineage_delta: obs(0, 'original_lineages'),
  arms: { B0: arm(1, 1), F: arm(2, 2) },
  hard_failures: index === 1 ? [{ code: 'TRACE_FAILURE', chain_ids: ['b'.repeat(64)] }] : [],
});
const cases = [row('case-1', 1), row('case-2', 2), row('case-3', 3)];
const metric = unit => ({
  mean: obs(1, unit), median: obs(1, unit), minimum: obs(1, unit), maximum: obs(1, unit), range: obs(0, unit), total: obs(3, unit),
  denominator: 3, wins: 3, ties: 0, losses: 0, leave_one_issuer_out: [],
});
const packet = {
  schema_version: 1,
  view: 'summary',
  evaluation_id: 'eval-1',
  registry_sha256: 'c'.repeat(64),
  result_sha256: 'd'.repeat(64),
  verdict: 'reject',
  counts: { planned: 3, confirmation: 3, development: 0 },
  evidence: {
    context_sha256: 'e'.repeat(64), fact_set_sha256: 'f'.repeat(64), policy_sha256: '1'.repeat(64), source_closure_sha256: '2'.repeat(64), summary_sha256: '3'.repeat(64),
    claim_limits: ['vector_only_no_scalar', 'not_financial_alpha'],
  },
  outcomes: { richness: metric('canonical_units'), depth: metric('field_state_steps') },
  policy_gates: [
    { name: 'aggregate_lineage', status: 'pass', observed: 0, threshold: 0, numerator: null, denominator: null, case_results: [], reason_codes: [] },
    { name: 'precision_delta', status: 'unknown', observed: null, threshold: -.05, numerator: null, denominator: null, case_results: [], reason_codes: ['PRECISION_UNKNOWN'] },
  ],
  hard_failures: [{ case_id: 'case-1', code: 'TRACE_FAILURE', chain_ids: ['b'.repeat(64)] }],
  cases,
  selection: { case_id: null, arm: null, run: null, source: null },
  case: null,
  selected_arm: null,
  projection_state: 'fresh',
  read_only: true,
};

let requests;

test.beforeEach(async ({ page }) => {
  requests = [];
  await page.route('**/api/information-yield?*', async route => {
    const url = new URL(route.request().url());
    requests.push(url);
    const id = url.searchParams.get('case');
    if (id) {
      const selected = cases.find(item => item.case_id === id);
      await route.fulfill({ json: {
        ...packet,
        view: 'detail',
        cases: [],
        selection: { case_id: id, arm: url.searchParams.get('arm'), run: url.searchParams.get('run'), source: url.searchParams.get('source') },
        case: selected ?? null,
        selected_arm: url.searchParams.get('arm') && selected ? selected.arms[url.searchParams.get('arm')] : null,
      } });
    } else await route.fulfill({ json: packet });
  });
});

test('renders vector outcomes, semantic charts, table twin and exact drilldown', async ({ page }) => {
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByRole('heading', { name: 'Information yield' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Evaluation rejected');
  await expect(page.getByText('Richness mean paired delta')).toBeVisible();
  await expect(page.getByText('Depth mean paired delta')).toBeVisible();
  await expect(page.getByRole('region', { name: 'Paired information-yield outcomes' })).toBeVisible();
  await expect(page.getByText(/EIY\s*=/)).toHaveCount(0);
  await expect(page.getByText(/alpha score/i)).toHaveCount(0);

  const chart = page.getByRole('img', { name: /Richness paired delta/ });
  await expect(chart).toBeVisible();
  await expect(chart.getByRole('link')).toHaveCount(0);
  const links = page.getByRole('list', { name: 'Richness case drilldowns' });
  await expect(links.getByRole('link', { name: 'Open case-1 detail' })).toBeVisible();

  const caseLink = page.getByRole('link', { name: 'case-1', exact: true });
  await caseLink.focus();
  await expect(caseLink).toBeFocused();
  await caseLink.click();
  await expect(page.getByRole('heading', { name: 'Exact case drilldown' })).toBeVisible();
  await expect(page.getByText('Run and source links remain withheld')).toBeVisible();
});

test('issues one summary request when no case identity exists', async ({ page }) => {
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByText('Richness mean paired delta')).toBeVisible();
  await expect.poll(() => requests.filter(url => !url.searchParams.has('case')).length).toBe(1);
  expect(requests.filter(url => url.searchParams.has('case'))).toHaveLength(0);
});

test('contains a 128-character case ID at 320px and 200% text', async ({ page }) => {
  const longId = `case-${'x'.repeat(123)}`;
  const longCases = [row(longId, 4), row('case-2', 2), row('case-3', 3)];
  const longPacket = { ...packet, cases: longCases, hard_failures: [] };
  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => route.fulfill({ json: longPacket }));
  await page.setViewportSize({ width: 320, height: 900 });
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByRole('heading', { name: 'Information yield' })).toBeVisible();
  await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
  await expect(page.getByRole('link', { name: `Open ${longId} detail` }).first()).toBeVisible();
  const overflow = await page.evaluate(() => {
    const panel = document.querySelector('[aria-labelledby="information-yield-title"]');
    if (!(panel instanceof HTMLElement)) return null;
    const panelOverflows = panel.scrollWidth > panel.clientWidth;
    const visibleWidth = document.documentElement.scrollWidth;
    panel.style.display = 'none';
    const withoutPanelWidth = document.documentElement.scrollWidth;
    panel.style.removeProperty('display');
    return { panelOverflows, documentWidthAdded: visibleWidth - withoutPanelWidth };
  });
  expect(overflow).toEqual({ panelOverflows: false, documentWidthAdded: 0 });
  await page.getByText('Policy safeguards and diagnostics').click();
  const safeguards = page.getByRole('region', { name: 'Policy safeguards' });
  await expect(safeguards.getByRole('columnheader', { name: 'Observed' })).toBeVisible();
  await expect(safeguards.getByRole('columnheader', { name: 'Threshold' })).toBeVisible();
});

test('rejects aliases at every wire-object boundary', async ({ page }) => {
  test.setTimeout(45000);
  await page.unroute('**/api/information-yield?*');
  let response = packet;
  await page.route('**/api/information-yield?*', route => route.fulfill({ json: response }));
  const probes = [
    value => { value.evaluationId = 'alias'; },
    value => { value.counts.total = 3; },
    value => { value.evidence.auth_token = 'synthetic'; },
    value => { value.outcomes.average = {}; },
    value => { value.outcomes.richness.debug = true; },
    value => { value.outcomes.richness.leave_one_issuer_out = [{ issuer_id: 'ISSUER-1', mean: 1, alias: 1 }]; },
    value => { value.outcomes.richness.mean.raw_value = 1; },
    value => { value.cases[0].private_note = 'synthetic'; },
    value => { value.cases[0].arms.alias = value.cases[0].arms.B0; },
    value => { value.cases[0].arms.F.credentials = { token: 'synthetic' }; },
    value => { value.cases[0].arms.F.trace.status = 'pass'; },
    value => { value.policy_gates[0].observed_value = 0; },
    value => { value.policy_gates[0].observed = { count: 2, distinct: true, orders: { B0_first: 1, F_first: 1, alias: 0 } }; },
    value => { value.policy_gates[0].case_results = [{ case_id: 'case-1', alias: true }]; },
    value => { value.hard_failures[0].private_code = 'synthetic'; },
    value => { value.selection.case = null; },
  ];
  for (const [index, mutate] of probes.entries()) {
    response = structuredClone(packet);
    mutate(response);
    await page.goto(`/datasource?subject=NOW&evaluation=eval-1&alias-probe=${index}`);
    await expect(page.getByRole('alert').filter({ hasText: 'Information-yield evidence' })).toContainText('response failed its local schema boundary');
  }
});

test('selector mismatch, selected-arm mismatch and pass-with-failure fail closed', async ({ page }) => {
  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => {
    const url = new URL(route.request().url());
    return route.fulfill({ json: url.searchParams.get('case') ? {
      ...packet, view: 'detail', cases: [], selection: { case_id: 'case-2', arm: 'B0', run: null, source: null }, case: cases[1], selected_arm: cases[1].arms.B0,
    } : packet });
  });
  await page.goto('/datasource?subject=NOW&evaluation=eval-1&case=case-1&arm=F');
  await expect(page.getByRole('alert').filter({ hasText: 'Requested drilldown' })).toContainText('response failed its local schema boundary');

  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => {
    const url = new URL(route.request().url());
    const selected = cases[0];
    return route.fulfill({ json: url.searchParams.get('case') ? {
      ...packet, view: 'detail', cases: [], selection: { case_id: selected.case_id, arm: 'F', run: null, source: null }, case: selected, selected_arm: selected.arms.B0,
      hard_failures: selected.hard_failures.map(failure => ({ case_id: selected.case_id, ...failure })),
    } : packet });
  });
  await page.goto('/datasource?subject=NOW&evaluation=eval-1&case=case-1&arm=F');
  await expect(page.getByRole('alert').filter({ hasText: 'Requested drilldown' })).toContainText('response failed its local schema boundary');

  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => route.fulfill({ json: { ...packet, verdict: 'pass', hard_failures: [] } }));
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByRole('alert').filter({ hasText: 'Information-yield evidence' })).toContainText('response failed its local schema boundary');
});

test('shows permission denial separately from unavailable and no-evaluation states', async ({ page }) => {
  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => route.fulfill({ status: 403, json: { error: { code: 'FORBIDDEN' } } }));
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByRole('alert').filter({ hasText: 'Information-yield access denied' })).toContainText('do not have permission');
  await expect(page.getByText('Evaluation unavailable')).toHaveCount(0);
  await expect(page.getByText('Information-yield evidence is unavailable from the local read-only service.')).toHaveCount(0);

  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => route.fulfill({ status: 503, json: { error: { code: 'UNAVAILABLE' } } }));
  await page.reload();
  await expect(page.getByRole('alert').filter({ hasText: 'Information-yield evidence unavailable' })).toContainText('unavailable from the local read-only service');

  await page.goto('/datasource?subject=NOW');
  await expect(page.getByText('No information-yield evaluation selected')).toBeVisible();
  await expect(page.getByText('Information-yield access denied')).toHaveCount(0);
});

test('malformed projection is isolated from the overview', async ({ page }) => {
  await page.unroute('**/api/information-yield?*');
  await page.route('**/api/information-yield?*', route => route.fulfill({ json: { schema_version: 1, view: 'summary' } }));
  await page.goto('/datasource?subject=NOW&evaluation=eval-1');
  await expect(page.getByText('response failed its local schema boundary')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Overview' })).toBeVisible();
});
