import { Badge, Icon } from '../../components';
import type { StandardJob } from '../types';
import { cadence, circuitLabel, delaySourceLabel, displayDate, NextSend, providerLabel, providerWords } from './shared';
import { attentionReason, jobKind, runOutcome } from '../presentation';

export function StandardJobRow({ job, zone, selected, onSelect }: { job: StandardJob; zone: string; selected: boolean; onSelect: () => void }) {
  const finiteFinished = (job.schedule.kind === 'once' || job.schedule.kind === 'sequence') && !job.nextRunAt;
  const attention = attentionReason(job);
  const safety = job.providerSafety;
  return <button id={`job-row-${job.id}`} aria-pressed={selected} aria-controls="job-detail" onClick={onSelect}>
    <span className="scheduler-row-meta"><span>{jobKind(job)}</span><Badge value={attention ? 'partial' : job.enabled && !finiteFinished ? 'verified' : 'neutral'}>{attention ?? (job.enabled ? finiteFinished ? 'Finished' : 'Enabled' : 'Disabled')}</Badge></span>
    <span className="scheduler-job-title">{job.title}<Icon name="chevron" size={16} /></span>
    <span className="scheduler-job-time"><span>{job.delivery.mode === 'conditional' ? 'Next recovery check' : 'Next run'}</span><strong>{displayDate(job.nextRunAt, zone)}</strong></span>
    <span className="scheduler-job-schedule">{cadence(job.schedule)}</span>
    {safety ? safety.status === 'unavailable' ? <span className="scheduler-provider-state"><Badge value="partial">Provider safety unavailable</Badge></span> : <>
      <span className="scheduler-provider-state"><strong>{providerLabel(safety.provider)}</strong><span>Latest attempt: {safety.latestAttempt ? providerWords(safety.latestAttempt.status) : 'none recorded'} · Queue: {safety.queue.depth}</span></span>
      {safety.unknownFence ? <span className="scheduler-provider-alert"><Badge value="partial">{safety.replayAuthorization === 'reconciliation_required' ? 'Unknown outcome—reconciliation required' : 'Unknown outcome—replay not authorized'}</Badge></span> : null}
      {safety.delayedUntil ? <span className="scheduler-provider-alert">Retry scheduled until {displayDate(safety.delayedUntil, zone)} · {delaySourceLabel(safety.delaySource)}</span> : safety.replayAuthorization === 'authorized' ? <span className="scheduler-provider-alert">Provider retry is due now</span> : null}
      {safety.circuit.state === 'open' || safety.circuit.state === 'half_open' ? <span className="scheduler-provider-alert">Circuit {circuitLabel(safety.circuit.state)}{safety.circuit.state === 'open' ? ` until ${displayDate(safety.circuit.openUntil, zone)}` : ` · probe until ${displayDate(safety.circuit.probeUntil, zone)}`}</span> : null}
    </> : null}
    <span className="scheduler-job-last">Last run: {runOutcome(job.history[0])}{job.delivery.mode === 'conditional' ? ' · Only when recovery is ready' : ''}</span>
    {job.delivery.mode === 'scheduled' ? <span className="scheduler-job-send">Next send: <NextSend job={job} zone={zone} /></span> : null}
  </button>;
}
