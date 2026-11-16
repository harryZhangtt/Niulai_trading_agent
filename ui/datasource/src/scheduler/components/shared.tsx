import type { ReactNode } from 'react';
import type { ProviderFailure, Schedule, SchedulerJob } from '../types';

export function displayDate(value: string | null | undefined, zone: string) {
  if (!value) return 'Not scheduled';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return 'Time unavailable';
  return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short', hour12: false, timeZone: zone }).format(parsed);
}
export function cadence(schedule: Schedule) {
  if (schedule.kind === 'interval') return schedule.seconds % 60 === 0 ? `Every ${schedule.seconds / 60} minutes` : `Every ${schedule.seconds} seconds`;
  if (schedule.kind === 'once') return 'One-time task';
  if (schedule.kind === 'sequence') return `Finite sequence · ${schedule.timestamps.length} scheduled ${schedule.timestamps.length === 1 ? 'run' : 'runs'}`;
  return `${schedule.times.join(' and ')} · ${schedule.timezone}`;
}
export function NextSend({ job, zone }: { job: SchedulerJob; zone: string }): ReactNode {
  if (!job.enabled) return <>Paused</>;
  if (job.jobType === 'mentor') return <>Acceptance evidence only</>;
  if (job.delivery.mode === 'conditional') return <>Only when recovery is ready</>;
  if (job.delivery.mode !== 'scheduled') return <>No message schedule declared</>;
  return <>{displayDate(job.delivery.nextSendAt, zone)}</>;
}

export const providerLabel = (provider: 'codex_cli' | 'claude_host') => provider === 'codex_cli' ? 'Codex CLI' : 'Claude host';
export const providerWords = (value: string) => value.replaceAll('_', ' ');
export const delaySourceLabel = (source: 'retry_after' | 'backoff' | 'circuit' | null) =>
  source === 'retry_after' ? 'Retry-After' : source === 'backoff' ? 'backoff' : source === 'circuit' ? 'circuit' : 'not scheduled';
export const circuitLabel = (state: 'closed' | 'open' | 'half_open' | 'unavailable') =>
  state === 'half_open' ? 'Half-open' : state === 'open' ? 'Open' : state === 'closed' ? 'Closed' : 'Unavailable';

const failureLabels: Record<ProviderFailure, string> = {
  none: 'None', timeout: 'Timeout', connection_reset: 'Connection reset', connection: 'Connection failure',
  partial_response: 'Partial response', missing_terminal: 'Terminal evidence missing', http: 'HTTP failure',
  auth: 'Authentication failure', config: 'Provider configuration failure', model: 'Model failure', policy: 'Policy refusal',
  local_config: 'Local configuration failure', provider: 'Provider failure', unknown: 'Unknown failure',
};
export const providerFailureLabel = (failure: ProviderFailure | 'unavailable') => failure === 'unavailable' ? 'Unavailable' : failureLabels[failure];
