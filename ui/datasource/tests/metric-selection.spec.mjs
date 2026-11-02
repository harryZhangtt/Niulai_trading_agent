import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

test('matched-case controls visibly identify the selected metric and distinguish equal, nonzero, and unknown values', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW')).json();
  const comparison = data.comparisons.find(item => item.id === 'now_captured_regrade_1.0.2');
  expect(comparison?.rows.length).toBe(8);
  await page.goto('/datasource');
  await page.getByRole('button', { name: /A\/B evaluation/ }).click();
  await page.getByLabel('Comparison', { exact: true }).selectOption(comparison.id);
  const metric = page.getByLabel('Metric', { exact: true });
  await metric.selectOption('baseline_novelty');
  await expect(page.locator('.selected-metric')).toContainText('Novelty classification accuracy rubric');
  await expect(page.locator('.selected-metric')).toContainText('0–2 rubric points');
  await expect(page.locator('.selected-metric')).toContainText('All known paired values are equal');
  await metric.selectOption('tokens');
  await expect(page.locator('.selected-metric')).toContainText('Showing: Tokens');
  await expect(page.locator('.selected-metric')).toContainText('Unit: tokens');
  await expect(page.locator('.selected-metric')).not.toContainText('All known paired values are equal');
  const nonzero = comparison.rows.find(row => row.differences.tokens !== 0 && row.differences.tokens != null);
  expect(nonzero).toBeTruthy();
  const row = page.locator('.comparison-table tbody tr').filter({ has: page.getByRole('rowheader', { name: nonzero.case_id, exact: true }) });
  await expect(row.locator('td').nth(0)).toHaveText(new Intl.NumberFormat('en-US').format(nonzero.A.metrics.tokens));
  await expect(row.locator('td').nth(1)).toHaveText(new Intl.NumberFormat('en-US').format(nonzero.B.metrics.tokens));
  await expect(row.locator('.delta')).toContainText(String(Math.abs(nonzero.differences.tokens)));
  await metric.selectOption('cost');
  await expect(page.locator('.selected-metric')).toContainText('Showing: Cost');
  await expect(page.locator('.selected-metric')).toContainText('0 of 8 pairs have both values');
  await expect(page.locator('.comparison-table tbody tr').first()).toContainText('Unknown');
  await page.getByLabel('Comparison', { exact: true }).selectOption('now_original_1.0.0');
  await expect(page.getByRole('heading', { name: 'No matched case values recorded' })).toBeVisible();
  await expect(page.locator('.selected-metric')).toHaveCount(0);
});

test('captured review passes remain distinct from blocked executions and review-order disagreements', async ({ page }) => {
  await page.goto('/datasource');
  await page.getByRole('button', { name: /A\/B evaluation/ }).click();
  await page.getByLabel('Comparison', { exact: true }).selectOption('now_captured_regrade_1.0.2');
  await expect(page.locator('.comparison-section > .section-heading')).toContainText('Limited comparison');
  const margin = page.locator('.comparison-table tbody tr').filter({ has: page.getByRole('rowheader', { name: 'margin_counterevidence', exact: true }) });
  await expect(margin.locator('.arm-result').first().locator('.arm-review')).toHaveText('Review passed');
  await expect(margin.locator('.arm-result').first().locator('.arm-runtime')).toHaveText('Execution blocked');
  await expect(margin.locator('.pipeline-reason')).toContainText('CONTRIBUTION_QUOTE_NOT_IN_SOURCE');
  const acv = page.locator('.comparison-table tbody tr').filter({ has: page.getByRole('rowheader', { name: 'acv_target', exact: true }) });
  await expect(acv.locator('.review-order')).toContainText('Disagrees');
  await expect(acv.locator('.review-order')).toContainText('tie / B');
  await page.getByLabel('Metric', { exact: true }).selectOption('unproved_links');
  await expect(page.locator('.selected-metric')).toContainText('Unproved-link reasoning rubric');
  await expect(page.locator('.selected-metric')).toContainText('0–2 rubric points');
});
