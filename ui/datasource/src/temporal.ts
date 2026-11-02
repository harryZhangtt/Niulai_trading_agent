import type { Run, Source, TemporalSourceDecision } from './types';

export function runSourceDecision(source: Source | undefined, run: Run | undefined): TemporalSourceDecision | null {
  const temporal = run?.temporal;
  if (!source?.source_sha256 || !run?.execution_id || !temporal || temporal.status !== 'guarded'
    || temporal.semantics !== 'run_bound_diagnostic' || temporal.execution_id !== run.execution_id) return null;
  return temporal.source_decisions.find(decision => decision.source_sha256 === source.source_sha256) ?? null;
}

export function ledgerTemporal(source: Source, run?: Run): { status: string; cutoff: string | null; scope: string } {
  const diagnostic = run ? runSourceDecision(source, run) : source.temporal;
  return {
    status: typeof diagnostic?.status === 'string' ? diagnostic.status : 'unknown',
    cutoff: typeof diagnostic?.cutoff === 'string' ? diagnostic.cutoff : run?.temporal?.cutoff ?? null,
    scope: run ? 'Selected-run check' : 'Source-level check',
  };
}
