import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

test('registered NOW checkpoint shows actual catalog JSON and an explicit missing-body state without a URL', async ({ page, request }) => {
  const data = await (await request.get('/api/datasource?subject=NOW&refresh=1')).json();
  const source = data.sources.find(item => item.title === 'NOW_Research_Checkpoint_2026-10-18.json');
  expect(source).toBeTruthy();
  expect(source.url).toBeNull();
  expect(source.local_preview.status).toBe('missing');
  expect(source.local_preview.text).toContain('catalog_record');
  expect(source.local_preview.text).toContain('market_price_cutoff_utc');
  expect(source.local_preview.text).not.toContain('/Users/');
  expect(source.local_preview.text).not.toContain('/workspace/');
  expect(source.timestamps.available_at).toBeNull();
  await page.goto('/datasource');
  await page.getByRole('button', { name: 'Source ledger', exact: true }).click();
  await page.getByLabel('Filter this page').fill(source.title);
  await page.getByRole('button', { name: source.title, exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Document contents', exact: true })).toBeVisible();
  await expect(page.locator('.document-preview')).toContainText('Document body missing');
  await expect(page.getByLabel('Research document JSON preview')).toContainText('catalog_record');
  await expect(page.getByLabel('Research document JSON preview')).toContainText('market_price_cutoff_utc');
  await expect(page.locator('.document-preview')).toContainText('Declared SHA-256 (unverified)');
  await expect(page.locator('.document-preview')).toContainText('Original availability');
  expect(await page.locator('.document-preview img, .document-preview script').count()).toBe(0);
});
