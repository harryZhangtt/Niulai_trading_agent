import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import ts from '../../node_modules/typescript/lib/typescript.js';

const here = dirname(fileURLToPath(import.meta.url));

async function read(name) {
  return readFile(join(here, name), 'utf8');
}

async function loadAdapter() {
  const source = await read('adaptResilience.ts');
  const result = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: 'adaptResilience.ts',
    reportDiagnostics: true,
  });
  const errors = (result.diagnostics ?? []).filter((item) => item.category === ts.DiagnosticCategory.Error);
  assert.deepEqual(errors, []);
  const encoded = Buffer.from(result.outputText).toString('base64');
  return import(`data:text/javascript;base64,${encoded}`);
}

const completeWire = {
  generated_at: '2030-02-03T04:05:06Z',
  status: 'partial',
  projection_state: 'stale',
  scheduler: { status: 'retry_wait', attempts: 2 },
  provider_safety: {
    latest_attempt: { phase: 'terminal', status: 'unknown' },
    delayed_until: '2030-02-03T04:10:00Z',
    delay_source: 'backoff',
    unknown_fence: true,
    replay_authorization: 'reconciliation_required',
  },
  mentor: {
    cycles: 4,
    no_progress: { used: 2, limit: 4 },
    repeated: { used: 2, limit: 3 },
    evidence_reset: false,
  },
  health: {
    heartbeat_age_seconds: 48,
    watchdog_healthy: true,
    last_tick_at: '2030-02-03T04:04:18Z',
    catch_up: 'coalesced',
  },
};

test('Python scheduler projection fixture is consumed by the TypeScript adapter', async () => {
  const { adaptResilience } = await loadAdapter();
  const fixture = JSON.parse(await read('pythonProjectionFixture.json'));
  const result = adaptResilience(fixture);
  assert.equal(result.snapshot.generatedAt.text, '2026-11-05T02:00:00+00:00');
  assert.equal(result.activeWork.schedulerStatus.text, 'failed');
  assert.equal(result.recovery.noProgressCycles.text, '0');
  assert.equal(result.recovery.retryDelay.text, 'No retry scheduled');
  assert.equal(result.activeWork.providerLatestPhase.availability, 'unavailable');
});

test('adapter returns the exact ViewModel key contract', async () => {
  const { adaptResilience } = await loadAdapter();
  const result = adaptResilience(completeWire);
  assert.deepEqual(Object.keys(result), ['snapshot', 'activeWork', 'recovery', 'hostTiming']);
  assert.deepEqual(Object.keys(result.snapshot), ['generatedAt', 'status', 'projectionFreshness']);
  assert.deepEqual(Object.keys(result.activeWork), [
    'schedulerStatus',
    'schedulerAttempts',
    'providerLatestPhase',
    'providerLatestStatus',
  ]);
  assert.deepEqual(Object.keys(result.recovery), [
    'mentorCycles',
    'noProgressCycles',
    'noProgressLimit',
    'repeatedCycles',
    'repeatedLimit',
    'evidenceReset',
    'retryDelay',
    'retrySource',
    'unknownFence',
    'replayAuthorization',
  ]);
  assert.deepEqual(Object.keys(result.hostTiming), ['heartbeatAge', 'watchdog', 'lastTick', 'catchUp']);
});

test('adapter preserves stale, unknown, unavailable, and not-recorded distinctions', async () => {
  const { adaptResilience } = await loadAdapter();
  const complete = adaptResilience(completeWire);
  assert.deepEqual(complete.snapshot.projectionFreshness, {
    text: 'Stale', availability: 'recorded', severity: 'warning',
  });
  assert.deepEqual(complete.activeWork.providerLatestStatus, {
    text: 'Unknown', availability: 'unknown', severity: 'neutral',
  });
  assert.equal(complete.recovery.retrySource.text, 'backoff');
  assert.deepEqual(complete.recovery.unknownFence, {
    text: 'Outcome unknown; replay fenced', availability: 'recorded', severity: 'critical',
  });
  assert.deepEqual(complete.recovery.replayAuthorization, {
    text: 'reconciliation required', availability: 'recorded', severity: 'critical',
  });

  const missing = adaptResilience({});
  assert.equal(missing.snapshot.projectionFreshness.availability, 'not-recorded');
  assert.equal(missing.hostTiming.lastTick.text, 'Not recorded');
  assert.equal(missing.hostTiming.catchUp.text, 'Not recorded');

  const unavailable = adaptResilience(null);
  assert.equal(unavailable.snapshot.generatedAt.availability, 'unavailable');
  assert.equal(unavailable.recovery.replayAuthorization.text, 'Unavailable');

  const noRetry = adaptResilience({provider_safety:{delayed_until:null,delay_source:null}});
  assert.equal(noRetry.recovery.retryDelay.text, 'No retry scheduled');
  assert.equal(noRetry.recovery.retryDelay.availability, 'recorded');
  assert.equal(noRetry.recovery.retrySource.text, 'No retry source');

  const safe = adaptResilience({provider_safety:{unknown_fence:false,replay_authorization:'not_applicable'}});
  assert.equal(safe.recovery.unknownFence.severity, 'positive');
  assert.equal(safe.recovery.replayAuthorization.severity, 'neutral');
  const blocked = adaptResilience({provider_safety:{unknown_fence:true,replay_authorization:'not_authorized'}});
  assert.equal(blocked.recovery.replayAuthorization.severity, 'warning');
  const authorized = adaptResilience({provider_safety:{unknown_fence:false,replay_authorization:'authorized'}});
  assert.equal(authorized.recovery.replayAuthorization.severity, 'positive');
  const missingSource = adaptResilience({provider_safety:{delayed_until:'2030-02-03T04:10:00Z'}});
  assert.equal(missingSource.recovery.retrySource.text, 'Not recorded');
  const unavailableSource = adaptResilience({provider_safety:null});
  assert.equal(unavailableSource.recovery.retrySource.text, 'Unavailable');

  const fractional = adaptResilience({scheduler:{attempts:1.5},mentor:{cycles:2.5,no_progress:{used:.5,limit:2},repeated:{used:1,limit:1}}});
  assert.equal(fractional.activeWork.schedulerAttempts.availability, 'unavailable');
  assert.equal(fractional.recovery.mentorCycles.availability, 'unavailable');
  assert.equal(fractional.recovery.noProgressCycles.availability, 'unavailable');
});

test('no-progress severity crosses info, half-limit warning, and limit critical', async () => {
  const { adaptResilience } = await loadAdapter();
  const severity = (used, limit) => adaptResilience({
    mentor: { no_progress: { used, limit } },
  }).recovery.noProgressCycles.severity;
  assert.equal(severity(1, 4), 'info');
  assert.equal(severity(2, 4), 'warning');
  assert.equal(severity(4, 4), 'critical');
});

test('repeated evidence severity follows the configured limit unless reset', async () => {
  const { adaptResilience } = await loadAdapter();
  const severity = (used, limit, evidence_reset = false) => adaptResilience({
    mentor: { repeated: { used, limit }, evidence_reset },
  }).recovery.repeatedCycles.severity;
  assert.equal(severity(0, 1), 'positive');
  assert.equal(severity(1, 1), 'critical');
  assert.equal(severity(1, 2), 'info');
  assert.equal(severity(2, 2), 'critical');
  assert.equal(severity(2, 3), 'warning');
  assert.equal(severity(3, 3), 'critical');
  assert.equal(severity(3, 3, true), 'positive');
});

test('panel is compact, semantic, read-only, and receives selected-detail context', async () => {
  const component = await read('ResiliencePanel.tsx');
  const types = await read('types.ts');
  assert.match(component, /<h3>Resilience<\/h3>/);
  assert.match(component, /<h4 id=/);
  assert.match(component, /useId/);
  assert.match(component, /headingPrefix/);
  assert.match(component, /<dl>/);
  assert.match(component, /<time dateTime=/);
  assert.match(component, /<bdi>/);
  assert.match(component, /displayDate/);
  assert.match(component, /semanticSeverityLabel/);
  assert.match(component, /indicator: 'semantic'/);
  assert.match(component, /labelled\('Source', source\)/);
  assert.match(component, /aria-live="polite" aria-atomic="true"/);
  assert.equal((component.match(/role="status"/g) ?? []).length, 1);
  assert.match(component, /Provider execution, business acceptance and email delivery are separate outcomes/);
  for (const label of ['Unknown-outcome fence', 'Provider replay authorization', 'Last tick', 'Catch-up']) assert.match(component, new RegExp(`label: '${label}'`));
  assert.ok(component.indexOf("label: 'Unknown-outcome fence'") < component.indexOf("label: 'Mentor cycles'"));
  assert.ok(component.indexOf("label: 'Provider replay authorization'") < component.indexOf("label: 'Mentor cycles'"));
  assert.equal((component.match(/label: '/g) ?? []).length, 16);
  assert.match(component, /stale[\s\S]*Retained stale snapshot/);
  assert.match(component, /refreshing[\s\S]*Updating retained stale snapshot/);
  assert.match(component, /partial[\s\S]*Evidence completeness is partial/);
  for (const prop of ['zone: string', 'stale: boolean', 'refreshing: boolean', 'partial: boolean']) assert.match(types, new RegExp(prop));
  assert.doesNotMatch(component, /evidenceAvailabilityLabel/);
  assert.doesNotMatch(component, /<(?:button|form|input|select|textarea)\b/i);
  assert.doesNotMatch(component, /\bon(?:Click|Submit|Change|KeyDown)\s*=/);
});

test('CSS covers mobile, logical layout, RTL-safe flow, forced colors, motion, and long IDs', async () => {
  const css = await read('ResiliencePanel.module.css');
  assert.match(css, /@media \(max-width: 360px\)/);
  assert.match(css, /\.container \{[\s\S]*container-type: inline-size/);
  assert.doesNotMatch(css, /\.panel \{\s*container-type:/);
  assert.match(css, /@container \(min-width: 40rem\)/);
  assert.match(css, /@container \(max-width: 26rem\)/);
  assert.match(css, /@media \(forced-colors: active\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /padding-inline:/);
  assert.match(css, /margin-block/);
  assert.match(css, /overflow-wrap: anywhere/);
  assert.match(css, /font-variant-numeric: tabular-nums/);
  assert.match(css, /font-size: 16px/);
  assert.match(css, /font-size: 14px/);
  assert.doesNotMatch(css, /(?:margin|padding|border)-(?:left|right)|\b(?:left|right):/);
  assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i);
});

test('same-identity refresh retains stale error until success while identity change clears it', async () => {
  const hook = await read('../scheduler/useScheduler.ts');
  assert.match(hook, /error: previous\.key === query \? previous\.error : null/);
  assert.match(hook, /setState\(\{ key: query, data, loading: false, error: null \}\)/);
  assert.match(hook, /const current = \+\+identity\.current/);
  assert.match(hook, /current === identity\.current && !controller\.signal\.aborted/);
  assert.match(hook, /controller\.abort\(\)/);
});

test('fixtures and product source contain no private canaries', async () => {
  const files = await Promise.all([
    read('types.ts'),
    read('adaptResilience.ts'),
    read('ResiliencePanel.tsx'),
    read('syntheticFixtures.ts'),
    read('README.md'),
  ]);
  const source = files.join('\n');
  assert.doesNotMatch(source, /niulai-private|Bearer\s+|api[_-]?key|client[_-]?secret|\/Users\//i);
  assert.doesNotMatch(source, /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i);
});
