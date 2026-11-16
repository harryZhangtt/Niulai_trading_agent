import test from 'node:test';
import assert from 'node:assert/strict';
import { validateDatasourceProjection } from '../server.mjs';

function response(trace) {
  return {
    schema_version: 1,
    status: 'ok',
    sources: [],
    comparisons: [{ id: 'trace_trace-1', driver_trace: trace }],
  };
}

function approvedTrace() {
  return {
    experiment_id: 'experiment-1',
    execution_id: 'execution-1',
    trace_id: 'trace-1',
    checker_verdict: 'pass',
    checker_verdict_sha256: 'a'.repeat(64),
    operations: [{ operation_id: 'open-html', states: ['reserved', 'finalized'], arguments: { open: [{ ref_id: 'https://example.com/report.html' }] } }],
    accounting: { complete_chains: 1, credited_units: 1 },
    units: [{ unit_id: 'unit-1', review_disposition: 'approve', quote: 'Bound synthetic quote.' }],
    missing_links: [],
    limitations: ['Structural evidence only.'],
  };
}

test('server narrowing accepts one bounded checker-approved trace', () => {
  assert.equal(validateDatasourceProjection(response(approvedTrace())), true);
});

test('server narrowing rejects failed, incomplete, oversized, and secret-shaped traces', () => {
  const cases = [
    { ...approvedTrace(), checker_verdict: 'fail' },
    { ...approvedTrace(), missing_links: ['review'] },
    { ...approvedTrace(), units: [] },
    { ...approvedTrace(), raw_result: 'SYNTHETIC_SECRET_MUST_NOT_ESCAPE' },
    { ...approvedTrace(), operations: Array.from({ length: 9 }, (_, index) => ({ operation_id: `op-${index}` })) },
    { ...approvedTrace(), accounting: { complete_chains: 0, credited_units: 1 } },
  ];
  for (const trace of cases) assert.equal(validateDatasourceProjection(response(trace)), false);
});
