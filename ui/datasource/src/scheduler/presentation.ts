import type { JobRun, SchedulerJob } from './types';

export type JobView = 'current' | 'attention' | 'recurring' | 'all';
export const isRecurring = (job: SchedulerJob) => job.schedule.kind === 'daily' || job.schedule.kind === 'interval';
export const isCurrent = (job: SchedulerJob) => job.enabled && (isRecurring(job) || Boolean(job.nextRunAt) || job.jobType === 'mentor');
export const words = (value: string) => value.replaceAll('_', ' ');

export function runOutcome(run?: JobRun) {
  if (!run) return 'No runs recorded';
  if (['DAILY_NOT_DUE', 'DAILY_NO_RECOVERY_DUE', 'DAILY_NO_SENDABLE_WORK'].includes(run.code)) return 'No send due';
  return run.status === 'succeeded' ? 'Completed' : words(run.status);
}

export function attentionReason(job: SchedulerJob): string | null {
  if (job.jobType === 'standard') {
    const safety = job.providerSafety;
    if (safety?.status === 'unavailable') return 'Provider safety unavailable';
    if (safety?.status === 'available') {
      if (safety.unknownFence) return safety.replayAuthorization === 'reconciliation_required' ? 'Provider reconciliation required' : 'Provider outcome unknown';
      if (safety.replayAuthorization === 'reconciliation_required') return 'Provider reconciliation required';
      if (safety.replayAuthorization === 'not_authorized') return 'Provider replay not authorized';
      if (safety.circuit.state === 'open') return 'Provider circuit open';
      if (safety.circuit.state === 'half_open') return 'Provider circuit half-open';
      if (safety.delayedUntil) return 'Provider retry scheduled';
      if (safety.replayAuthorization === 'authorized') return 'Provider retry due';
    }
    const latest = job.history[0];
    if (!latest) return null;
    if (latest.status === 'unknown') return 'Execution outcome unknown';
    if (['failed', 'missed', 'retry_wait'].includes(latest.status)) return `Last run ${words(latest.status)}`;
    return null;
  }
  if ('status' in job.mentor) return 'Evidence unavailable';
  const truth = job.mentor;
  if (truth.progress.pendingEffects > 0 || truth.session.status === 'blocked_pending_effect' || truth.scheduler.dispatch === 'possibly_dispatched'
    || truth.scheduler.status === 'unknown' || truth.runtimeAcceptance.modelTurn === 'unknown'
    || truth.runtimeAcceptance.email === 'unknown') return 'Outcome unknown';
  if ([truth.scheduler.status, truth.runtimeAcceptance.execution, truth.runtimeAcceptance.acceptance,
    truth.runtimeAcceptance.email, truth.session.status].includes('failed')) return 'Needs attention';
  if (truth.workOrder.windowState === 'expired' && truth.runtimeAcceptance.acceptance !== 'passed') return 'Work window ended';
  return null;
}

export function visibleJobs(jobs: SchedulerJob[], view: JobView, search: string) {
  const query = search.trim().toLocaleLowerCase();
  return jobs.filter(job => (view === 'all' || view === 'current' && isCurrent(job)
    || view === 'attention' && isCurrent(job) && Boolean(attentionReason(job))
    || view === 'recurring' && job.enabled && isRecurring(job))
    && `${job.title} ${job.id}`.toLocaleLowerCase().includes(query));
}

export function jobKind(job: SchedulerJob) {
  if (job.jobType === 'mentor') return 'Mentor';
  if (job.delivery.mode === 'conditional') return 'Recovery';
  if (job.delivery.mode === 'scheduled') return 'Report';
  return job.schedule.kind === 'sequence' ? 'Finite task' : 'Task';
}
