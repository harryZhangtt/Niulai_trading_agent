import { Badge } from '../../components';
import type { MentorJob } from '../types';
import { cadence, displayDate } from './shared';
import { attentionReason } from '../presentation';

const words = (value: string) => value.replaceAll('_', ' ');
export function MentorJobRow({ job, zone, selected, onSelect }: { job: MentorJob; zone: string; selected: boolean; onSelect: () => void }) {
  if ('status' in job.mentor) {
    return <button id={`job-row-${job.id}`} aria-pressed={selected} aria-controls="job-detail" onClick={onSelect}><span className="scheduler-row-meta"><span>Mentor</span><Badge value="partial">Evidence unavailable</Badge></span><span className="scheduler-job-title">{job.title}</span><span className="scheduler-job-time"><span>Next run</span><strong>{displayDate(job.nextRunAt, zone)}</strong></span><span className="scheduler-job-schedule">{cadence(job.schedule)}</span><span className="scheduler-job-last">No success inferred from missing evidence</span></button>;
  }
  const truth = job.mentor;
  const attention = attentionReason(job);
  return <button id={`job-row-${job.id}`} aria-pressed={selected} aria-controls="job-detail" onClick={onSelect}><span className="scheduler-row-meta"><span>Mentor</span><Badge value={attention ? 'partial' : truth.runtimeAcceptance.acceptance === 'passed' ? 'verified' : 'unknown'}>{attention ?? (truth.runtimeAcceptance.acceptance === 'passed' ? 'Acceptance verified' : 'Awaiting acceptance')}</Badge></span><span className="scheduler-job-title">{job.title}</span><span className="scheduler-job-time"><span>Next run</span><strong>{displayDate(job.nextRunAt, zone)}</strong></span><span className="scheduler-job-schedule">{cadence(job.schedule)} · {words(truth.workOrder.windowState)} window</span><span className="scheduler-job-last">{truth.progress.cycles.used}/{truth.progress.cycles.limit} cycles · {truth.progress.pendingEffects} pending effects · Execution {words(truth.runtimeAcceptance.execution)}</span></button>;
}
