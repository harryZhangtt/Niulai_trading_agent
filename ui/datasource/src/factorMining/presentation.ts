import type { FactorMiningRun } from './viewModels';

export function instant(value: string) {
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime())
    ? new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', hour12: false }).format(parsed)
    : 'Time unavailable';
}

export function provenanceLabel(run: FactorMiningRun) {
  if (run.provenanceOrigin === 'synthetic_fixture') return 'Synthetic fixture';
  return run.provenanceEvidence === 'hash_bound' ? 'Reproduced · hash bound' : 'Reported · unverified';
}

export function performanceLabel(run: FactorMiningRun) {
  if (run.performanceState === 'withheld_fixture') return 'Fixture performance withheld';
  if (run.performanceState === 'legacy_not_recorded') return 'Structured evidence not recorded';
  if (run.performanceState === 'not_published') return 'Not published';
  if (!run.performanceLoaded) return 'Structured details not loaded';
  return run.performance.some(record => record.state === 'available') ? 'Structured records available' : 'Performance unavailable';
}

export function admissionLabel(run: FactorMiningRun) {
  if (!run.gates.length) return 'No gate evidence';
  if (run.gates.some(gate => gate.status === 'fail')) return 'Recorded gate failed';
  if (run.gates.some(gate => gate.status === 'withheld')) return 'Evidence withheld';
  if (run.gates.some(gate => gate.status === 'inconclusive')) return 'Inconclusive';
  if (run.gates.some(gate => gate.status === 'pending')) return 'Pending evidence';
  return run.gates.every(gate => gate.status === 'pass') ? 'Recorded gates pass' : 'Gate status unknown';
}

export function needsAttention(run: FactorMiningRun) {
  return run.failures.length > 0 || ['failed', 'timed_out', 'unknown'].includes(run.status)
    || run.gates.some(gate => ['fail', 'inconclusive', 'withheld'].includes(gate.status));
}
