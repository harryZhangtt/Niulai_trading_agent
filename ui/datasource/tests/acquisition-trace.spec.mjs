import { test, expect } from '../../verification/node_modules/@playwright/test/index.mjs';

function traceResponse() {
  const trace = {
    id: 'trace-1', experiment_id: 'experiment-' + 'x'.repeat(120), execution_id: 'execution-1', trace_id: 'trace-1',
    driver_sha256: 'b'.repeat(64), checker_verdict: 'pass', checker_verdict_sha256: 'a'.repeat(64),
    checker_gates: [{ id: 'complete_chains', status: 'pass', reasons: ['Exactly 1/1 independently reopened chain.'] }],
    case_id: 'case-1', questions: [{ id: 'adoption.v1:issuer', question: 'What bounded adoption evidence is supported?' }],
    operations: [{ operation_id: 'open-html', question_ids: ['adoption.v1:issuer'], proposal_sha256: 'c'.repeat(64),
      arguments_sha256: 'd'.repeat(64), arguments: { open: [{ ref_id: 'https://example.com/' + 'long-segment-'.repeat(30) }] },
      attempt_id: 'attempt-1', dispatch_id: 'dispatch-1', states: ['reserved', 'host_intent', 'captured', 'finalized'],
      provider_route: 'fallback', cache_hit: false, fetch_executed: true, status: 'captured', failure_code: null,
      started_at: null, finished_at: null, receipt_sha256: 'e'.repeat(64) }],
    accounting: { logical_operations: 1, reserved_provider_items: 1, actual_dispatches: 1, cache_hits: 0, fallbacks: 1, complete_chains: 1, credited_units: 1 },
    units: [{ unit_id: 'unit-1', question_id: 'adoption.v1:issuer', operation_id: 'open-html', assessment_sha256: 'f'.repeat(64), unit_sha256: '1'.repeat(64),
      source_id: 'src-1', source_sha256: '2'.repeat(64), raw_sha256: null, text_sha256: '3'.repeat(64), source_version: null,
      quote: '<script>SYNTHETIC_INERT_CANARY()</script> ' + 'A very long literal quote. '.repeat(30), quote_truncated: false,
      review_id: 'review-1', review_sha256: '4'.repeat(64), reviewer_id: 'reviewer-1', review_disposition: 'approve',
      review_checks: { question_relevance: true, literal_support: true, canonical_lineage: true }, review_reason: 'Literal support and canonical lineage agree.',
      lineage: { canonical_disclosure_id: null, representation_kind: 'html', representation_relationship: 'sealed_alternate' },
      times: { published_at: null, modified_at: null, available_at: null, first_observed_at: null, retrieved_at: '2026-11-05T00:00:00Z', screened_at: null, exposed_at: null } }],
    missing_links: [], limitations: ['Structural evidence only; no provider quality or investment alpha claim.'],
    scope: 'checker_approved_structural_trace_not_quality_evidence',
  };
  return { schema_version: 1, generated_at: '2026-11-05T00:00:00Z', snapshot_id: '9'.repeat(64), status: 'ok', warnings: [], subject: 'NOW',
    pagination: { offset: 0, limit: 100, total_sources: 0, total_runs: 0, total_batches: 0, total_native_collections: 0, next_offset: null },
    sources: [], runs: [], batches: [], comparisons: [{ id: 'trace_trace-1', title: 'NOW acquisition driver trace', scope: trace.scope,
      status: 'qualified', arms: [], rows: [], limitations: trace.limitations, driver_trace: trace }],
    aggregates: { cohorts: [], unknowns: {} } };
}

test('checker-approved trace is keyboard-readable, inert, and overflow-safe', async ({ page }) => {
  const payload = traceResponse();
  await page.route('**/api/datasource?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) }));
  for (const width of [320, 360, 390, 768, 1024, 1440, 2560]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/datasource?subject=NOW&view=comparisons');
    await page.addStyleTag({ content: 'html { font-size: 200%; }' });
    await expect(page.getByRole('heading', { name: 'Acquisition driver trace' })).toBeVisible();
    await expect(page.getByText('Checker-approved structural evidence.')).toBeVisible();
    await expect(page.locator('dd:visible').filter({ hasText: /^Unavailable$/ }).first()).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.locator(':focus')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await page.locator('script').filter({ hasText: 'SYNTHETIC_INERT_CANARY' }).count()).toBe(0);
    expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain('SYNTHETIC_INERT_CANARY');
  }
});

test('client boundary rejects a trace that is not checker-approved', async ({ page }) => {
  const payload = traceResponse(); payload.comparisons[0].driver_trace.checker_verdict = 'fail';
  await page.route('**/api/datasource?**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(payload) }));
  await page.goto('/datasource?subject=NOW&view=comparisons');
  await expect(page.getByText('The datasource response could not be read. Refresh to try again.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Acquisition driver trace' })).toHaveCount(0);
});
