import { test, expect } from '@playwright/test';

async function profiles(page) {
  await page.route('**/api/entities/*', route => route.fulfill({ json: { name: route.request().url().endsWith('/A') ? 'Alpha profile' : 'Beta profile' } }));
  await page.goto('/');
  await expect(page.getByLabel('Display name')).toHaveValue('Alpha profile');
}

test('narrow E2E saves the selected entity and records one business operation', async ({ page }) => {
  const operations = [];
  await page.route('**/api/operations', route => {
    operations.push(route.request().postDataJSON());
    return route.fulfill({ json: { status: 'complete' } });
  });
  await profiles(page);
  await page.getByLabel('Display name').fill('Edited alpha');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toHaveText('Changes saved.');
  expect(operations).toHaveLength(1);
  expect(operations[0]).toMatchObject({ entity: 'A', name: 'Edited alpha' });
});

test('late A response cannot replace B or its draft', async ({ page }) => {
  let releaseA;
  let handledA;
  const aPending = new Promise(resolve => { releaseA = resolve; });
  const aHandled = new Promise(resolve => { handledA = resolve; });
  await page.route('**/api/entities/*', async route => {
    if (route.request().url().endsWith('/A')) await aPending;
    await route.fulfill({ json: { name: route.request().url().endsWith('/A') ? 'Late alpha' : 'Beta profile' } }).catch(() => {});
    if (route.request().url().endsWith('/A')) handledA();
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Profile B' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('Beta profile');
  await page.getByLabel('Display name').fill('Beta draft');
  releaseA();
  await aHandled;
  await expect(page.getByLabel('Display name')).toHaveValue('Beta draft');
  await expect(page.getByRole('heading', { name: 'Editing profile B' })).toBeVisible();
});

test('rapid Save triggers one operation; no credentials appear in failure UI or console', async ({ page }) => {
  let calls = 0;
  const logs = [];
  page.on('console', event => logs.push(event.text()));
  await page.route('**/api/operations', route => {
    calls++;
    return route.fulfill({ status: 500, json: { secret: 'SYNTHETIC_SECRET_CANARY_NEVER_REAL', error: 'provider failed' } });
  });
  await profiles(page);
  await page.getByLabel('Display name').fill('Changed alpha');
  await page.getByRole('button', { name: 'Save changes' }).evaluate(button => { button.click(); button.click(); });
  await expect(page.getByRole('status')).toContainText('Save result unknown');
  expect(calls).toBe(1);
  expect(await page.locator('body').innerText()).not.toContain('SYNTHETIC_SECRET_CANARY');
  expect(logs.join('\n')).not.toContain('SYNTHETIC_SECRET_CANARY');
});

test('accepted write with lost response reconciles without another mutation', async ({ page }) => {
  const operations = new Map();
  let writes = 0;
  await page.route('**/api/operations', route => {
    writes++;
    const op = route.request().postDataJSON();
    expect(route.request().headers()['idempotency-key']).toBe(op.id);
    operations.set(op.id, op);
    return route.abort('connectionreset');
  });
  await page.route('**/api/operations/*', route => route.fulfill({ json: { status: operations.has(route.request().url().split('/').pop()) ? 'complete' : 'unknown' } }));
  await profiles(page);
  await page.getByLabel('Display name').fill('Retained draft');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByRole('status')).toContainText('Save result unknown');
  await expect(page.getByRole('button', { name: 'Save changes' })).toBeDisabled();
  await expect(page.getByLabel('Display name')).toBeDisabled();
  await expect(page.getByLabel('Display name')).toHaveValue('Retained draft');
  await page.getByRole('button', { name: 'Check save result' }).click();
  await expect(page.getByRole('status')).toHaveText('Changes saved.');
  expect(writes).toBe(1);
  expect(operations.size).toBe(1);
});

test('pending operation freezes its draft while another entity stays editable', async ({ page }) => {
  const names = { A: 'Alpha profile', B: 'Beta profile' };
  let release;
  let started;
  const pendingWrite = new Promise(resolve => { release = resolve; });
  const writeStarted = new Promise(resolve => { started = resolve; });
  await page.route('**/api/entities/*', route => route.fulfill({ json: { name: names[route.request().url().split('/').pop()] } }));
  await page.route('**/api/operations', async route => {
    const op = route.request().postDataJSON();
    started();
    await pendingWrite;
    names[op.entity] = op.name;
    await route.fulfill({ json: { status: 'complete' } });
  });
  await page.goto('/');
  await expect(page.getByLabel('Display name')).toHaveValue('Alpha profile');
  await page.getByLabel('Display name').fill('Captured alpha');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await writeStarted;
  await expect(page.getByLabel('Display name')).toBeDisabled();
  await page.getByRole('button', { name: 'Profile B' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('Beta profile');
  await page.getByLabel('Display name').fill('Beta unsaved draft');
  release();
  await expect.poll(() => names.A).toBe('Captured alpha');
  await expect(page.getByLabel('Display name')).toHaveValue('Beta unsaved draft');
  await page.getByRole('button', { name: 'Profile A' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('Captured alpha');
  await page.getByRole('button', { name: 'Profile B' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('Beta unsaved draft');
});

test('validation retains draft, focuses input and does not write', async ({ page }) => {
  let writes = 0;
  await page.route('**/api/operations', route => { writes++; return route.fulfill({ json: {} }); });
  await profiles(page);
  await page.getByLabel('Display name').fill('x');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('x');
  await expect(page.getByLabel('Display name')).toBeFocused();
  await expect(page.getByLabel('Display name')).toHaveAttribute('aria-invalid', 'true');
  expect(writes).toBe(0);
});

test('server validation failure retains the submitted draft', async ({ page }) => {
  await page.route('**/api/operations', route => route.fulfill({ status: 422, json: { error: 'invalid field' } }));
  await profiles(page);
  await page.getByLabel('Display name').fill('Server-rejected draft');
  await page.getByRole('button', { name: 'Save changes' }).click();
  await expect(page.getByLabel('Display name')).toHaveValue('Server-rejected draft');
  await expect(page.getByLabel('Display name')).toHaveAttribute('aria-invalid', 'true');
});

test('empty state, keyboard focus, narrow layout and reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 740 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.route('**/api/entities/*', route => route.fulfill({ json: { name: null } }));
  await page.goto('/');
  await expect(page.getByText('No profile details yet. Add a name to get started.')).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Profile A' })).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.getByRole('status').evaluate(node => getComputedStyle(node).transitionDuration)).toBe('0s');
  await page.screenshot({ path: '../runtime/narrow-reduced-motion.png', fullPage: true });
});
