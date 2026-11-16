import { useState } from 'react';
import { Badge, Empty, Icon, Notice } from '../../components';
import type { JobRun, SavedMessage, StandardJob } from '../types';
import { useScheduler } from '../useScheduler';
import { cadence, circuitLabel, delaySourceLabel, displayDate, NextSend, providerFailureLabel, providerLabel, providerWords } from './shared';

type DetailView = 'overview' | 'runs' | 'messages' | 'custody';

function outcome(run?: JobRun) {
  if (!run) return 'No runs recorded';
  if (['DAILY_NOT_DUE', 'DAILY_NO_RECOVERY_DUE', 'DAILY_NO_SENDABLE_WORK'].includes(run.code)) return 'No send due';
  return run.status === 'succeeded' ? 'Completed' : run.status.replaceAll('_', ' ');
}
function deliveryOutcome(message?: SavedMessage) {
  if (!message) return 'No delivery record';
  if (message.status === 'accepted') return message.verified ? 'Delivery verified' : 'Accepted, verification pending';
  if (message.status === 'unknown') return 'Delivery unknown';
  return message.status.replaceAll('_', ' ');
}

function Preview({ job, outputId }: { job: string; outputId: string }) {
  const { data, loading, error, refresh } = useScheduler(new URLSearchParams({ job, output: outputId }).toString());
  const selected = data?.jobs[0];
  const output = selected?.jobType === 'standard' ? selected.output : undefined;
  const stale = data?.projectionState === 'stale';
  const incomplete = stale || data?.status === 'partial';
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'; base-uri 'none'">`;
  return <section className="scheduler-preview" aria-label="Saved message evidence" aria-busy={loading}>
    {error ? <Notice kind="error" title="Message preview unavailable">
      <p>{error}{output ? ' The last successful preview remains visible.' : ''}</p>
      <button className="button button-secondary" onClick={refresh} disabled={loading}>Retry preview</button>
    </Notice> : null}
    {incomplete ? <Notice kind="warning" title="Saved message evidence is incomplete">
      <p>{stale ? 'This preview is showing a retained stale snapshot.' : 'This preview comes from a partial snapshot.'} Refresh to retry; it does not establish a new delivery.</p>
    </Notice> : null}
    {output ? <>
      <h3>{output.subject}</h3>
      <p className="subtle">Saved content. External resources and active content are blocked.</p>
      <iframe title="Saved message preview" sandbox="" referrerPolicy="no-referrer" srcDoc={policy + output.html} />
      {output.attachments.length ? <p className="subtle">Saved attachments: {output.attachments.map(item => item.name).join(', ')}</p> : null}
    </> : loading ? <p role="status">Loading saved message…</p> : null}
    {data ? <p className="scheduler-detail-stamp subtle">
      Message snapshot {displayDate(data.generatedAt, 'UTC')} UTC
      {loading ? ' · Refreshing…' : ''}{error || incomplete ? ' · Retained or incomplete evidence' : ''}
    </p> : null}
  </section>;
}

function ProviderSafetyPanel({ job, zone }: { job: StandardJob; zone: string }) {
  const safety = job.providerSafety;
  if (!safety) return null;
  if (safety.status === 'unavailable') return <section className="scheduler-section scheduler-provider-panel" aria-labelledby="provider-safety-title">
    <h3 id="provider-safety-title">Provider retry and circuit</h3>
    <Notice kind="warning" title="Provider safety unavailable"><p>Retry, circuit and outcome-fence evidence could not be validated. No provider success or safe replay is inferred.</p></Notice>
    <p className="subtle">Provider execution safety is separate from the job’s business result and email delivery.</p>
  </section>;
  const attempt = safety.latestAttempt;
  return <section className="scheduler-section scheduler-provider-panel" aria-labelledby="provider-safety-title">
    <div className="scheduler-provider-heading"><h3 id="provider-safety-title">Provider retry and circuit</h3><Badge value={safety.unknownFence || safety.circuit.state === 'open' ? 'partial' : safety.delayedUntil ? 'unknown' : 'verified'}>{providerLabel(safety.provider)}</Badge></div>
    {safety.unknownFence ? <Notice kind="warning" title={safety.replayAuthorization === 'reconciliation_required' ? 'Unknown outcome—reconciliation required' : 'Unknown outcome—replay not authorized'}>
      <p>The provider may have accepted work. Reconciliation is required before any replay; this dashboard cannot retry or reconcile it.</p>
    </Notice> : null}
    <dl className="scheduler-definition scheduler-provider-facts">
      <div><dt>Provider</dt><dd>{providerLabel(safety.provider)}</dd></div>
      <div><dt>Latest provider attempt</dt><dd>{attempt ? <Badge value={attempt.status === 'failed' || attempt.status === 'unknown' ? 'partial' : attempt.status}>{providerWords(attempt.status)}</Badge> : 'No attempt recorded'}</dd></div>
      <div><dt>Attempt phase</dt><dd>{attempt ? providerWords(attempt.phase) : 'Not available'}</dd></div>
      <div><dt>Submission evidence</dt><dd>{attempt ? providerWords(attempt.submission) : 'Not available'}</dd></div>
      <div><dt>Terminal proof</dt><dd>{attempt ? providerWords(attempt.terminalProof) : 'Not available'}</dd></div>
      <div><dt>Failure classification</dt><dd>{attempt ? providerFailureLabel(attempt.failure) : 'Not available'}</dd></div>
      <div><dt>Retry schedule</dt><dd>{safety.delayedUntil ? `Until ${displayDate(safety.delayedUntil, zone)} · ${delaySourceLabel(safety.delaySource)}` : safety.replayAuthorization === 'authorized' ? 'Due now; awaiting scheduler' : 'No provider retry scheduled'}</dd></div>
      <div><dt>Circuit</dt><dd><Badge value={safety.circuit.state === 'open' ? 'partial' : safety.circuit.state === 'half_open' ? 'unknown' : safety.circuit.state}>{circuitLabel(safety.circuit.state)}</Badge>{safety.circuit.state === 'open' ? ` until ${displayDate(safety.circuit.openUntil, zone)}` : safety.circuit.state === 'half_open' ? ` · Probe until ${displayDate(safety.circuit.probeUntil, zone)}` : ''}</dd></div>
      <div><dt>Replay authorization</dt><dd>{providerWords(safety.replayAuthorization)}</dd></div>
      <div><dt>Provider queue</dt><dd>{safety.queue.depth} {safety.queue.depth === 1 ? 'attempt' : 'attempts'}{safety.queue.oldestDelayedAt ? ` · Oldest delayed ${displayDate(safety.queue.oldestDelayedAt, zone)}` : ''}</dd></div>
    </dl>
    <p className="subtle scheduler-provider-boundary">Provider retry and circuit state describe execution transport only. They do not prove the business task completed or an email was delivered.</p>
  </section>;
}

function Overview({ job, zone }: { job: StandardJob; zone: string }) {
  const lastRun = job.history[0];
  const lastMessage = job.outputs[0];
  const deliveryVerified = lastMessage?.status === 'accepted' && lastMessage.verified;
  return <div className="scheduler-overview">
    <dl className="scheduler-outcomes">
      <div><dt>Last execution</dt><dd>
        <Badge value={lastRun?.status ?? 'unknown'}>{outcome(lastRun)}</Badge>
        <p>{lastRun ? displayDate(lastRun.scheduledAt, zone) : 'The scheduler has not recorded a run.'}</p>
      </dd></div>
      <div><dt>Recorded delivery</dt><dd>
        <Badge value={deliveryVerified ? 'verified' : lastMessage?.status === 'unknown' ? 'partial' : 'unknown'}>{deliveryOutcome(lastMessage)}</Badge>
        <p>{lastMessage ? `${lastMessage.subject} · ${displayDate(lastMessage.createdAt, zone)}` : 'No saved message evidence is available for this job.'}</p>
      </dd></div>
    </dl>
    <p className="subtle scheduler-outcome-note">A completed run does not, by itself, prove a message was sent. Delivery evidence is recorded separately.</p>
    <ProviderSafetyPanel job={job} zone={zone} />
    <section className="scheduler-section" aria-labelledby="standard-schedule-title">
      <h3 id="standard-schedule-title">Schedule and delivery</h3>
      <dl className="scheduler-facts">
        <div><dt>Next run</dt><dd>{displayDate(job.nextRunAt, zone)}</dd></div>
        <div><dt>Next scheduled send</dt><dd><NextSend job={job} zone={zone} /></dd></div>
        <div><dt>Schedule</dt><dd>{cadence(job.schedule)}</dd></div>
        <div><dt>Send condition</dt><dd>{job.delivery.note}</dd></div>
      </dl>
      <p className="subtle">Scheduled times are starts, not guaranteed message arrival.</p>
    </section>
    {lastRun ? <section className="scheduler-section" aria-labelledby="standard-last-run-title">
      <h3 id="standard-last-run-title">Latest run record</h3>
      <dl className="scheduler-definition">
        <div><dt>Recorded result</dt><dd>{outcome(lastRun)}</dd></div>
        <div><dt>Attempts</dt><dd>{lastRun.attempts}</dd></div>
        <div><dt>Last updated</dt><dd>{displayDate(lastRun.updatedAt, zone)}</dd></div>
      </dl>
      <details><summary>Scheduler result code</summary><code>{lastRun.code}</code></details>
    </section> : null}
  </div>;
}

export function StandardJobDetail({ id, zone }: { id: string; zone: string }) {
  const { data, loading, error, refresh } = useScheduler(new URLSearchParams({ job: id }).toString());
  const [tab, setTab] = useState<DetailView>('overview');
  const [outputId, setOutputId] = useState('');
  const selected = data?.jobs[0];
  const job: StandardJob | undefined = selected?.jobType === 'standard' ? selected : undefined;
  const finiteFinished = job ? (job.schedule.kind === 'once' || job.schedule.kind === 'sequence') && !job.nextRunAt : false;
  const stale = data?.projectionState === 'stale';
  const incomplete = stale || data?.status === 'partial';
  const views: Array<[DetailView, string]> = [
    ['overview', 'Overview'], ['runs', 'Run history'], ['messages', 'Saved messages'], ['custody', 'Prompt custody'],
  ];
  return <section className="scheduler-detail" id="job-detail" aria-label="Selected job details" aria-busy={loading}>
    {error ? <Notice kind="error" title="Job details unavailable">
      <p>{error}{job ? ' The last successful snapshot remains visible.' : ''}</p>
      <button className="button button-secondary" onClick={refresh} disabled={loading}>Retry details</button>
    </Notice> : null}
    {incomplete ? <Notice kind="warning" title="Job evidence is incomplete">
      <p>{stale ? 'This job is showing a retained stale snapshot.' : 'This job has a partial snapshot.'} Recorded evidence remains visible; refresh to retry.</p>
    </Notice> : null}
    {!job ? loading ? <p role="status">Loading job details…</p> : <Empty title="Job details unavailable">
      The selected job response did not match its expected type.
    </Empty> : <>
      <div className="section-heading">
        <div><h2>{job.title}</h2><p className="subtle">{job.description}</p></div>
        <div className="scheduler-job-actions">
          <Badge value={job.enabled && !finiteFinished ? 'verified' : 'unknown'}>{job.enabled ? finiteFinished ? 'Finished' : 'Enabled' : 'Disabled'}</Badge>
          <button className="button button-secondary button-small" aria-label="Refresh selected job" onClick={refresh} disabled={loading}><Icon name="refresh" /></button>
        </div>
      </div>
      <nav className="view-nav scheduler-tabs" aria-label="Job detail views">
        {views.map(([key, title]) => <button key={key} aria-pressed={tab === key} onClick={() => setTab(key)}>
          {title}{key === 'messages' ? ` (${job.outputs.length})` : ''}
        </button>)}
      </nav>
      {tab === 'overview' ? <Overview job={job} zone={zone} /> : tab === 'custody' ? <section className="scheduler-section" aria-labelledby="prompt-custody-title">
        <h3 id="prompt-custody-title">Prompt custody</h3>
        <p className="subtle">Instruction bodies, file locations, references, and digests are intentionally not exposed by this dashboard.</p>
        <dl className="scheduler-definition">
          <div><dt>Status</dt><dd><Badge value={job.promptCustody.status === 'bound' || job.promptCustody.status === 'backfilled' ? 'verified' : 'unknown'}>{job.promptCustody.status.replaceAll('_', ' ')}</Badge></dd></div>
          <div><dt>Attempts bound</dt><dd>{job.promptCustody.attemptsBound}</dd></div>
          <div><dt>Model</dt><dd>{job.model ?? 'Not recorded'} · {job.effort ?? 'Effort not recorded'}</dd></div>
        </dl>
      </section> : tab === 'runs' ? job.history.length ? <section className="scheduler-section">
        <p className="subtle">Last 20 scheduler runs. A completed run does not, by itself, prove a message was sent.</p>
        <ol className="scheduler-runs">{job.history.map(run => <li key={run.id}>
          <div><strong>{displayDate(run.scheduledAt, zone)}</strong><Badge value={run.status === 'failed' || run.status === 'unknown' ? 'partial' : run.status}>{outcome(run)}</Badge></div>
          <p>{run.code.replaceAll('_', ' ').toLowerCase()} · {run.attempts} {run.attempts === 1 ? 'attempt' : 'attempts'}</p>
        </li>)}</ol>
      </section> : <Empty title="No runs recorded">A run will appear after the scheduler processes this job.</Empty> : <section className="scheduler-section">
        {job.outputs.length ? <>
          <label htmlFor="saved-message">Saved message</label>
          <select id="saved-message" value={outputId} onChange={event => setOutputId(event.target.value)}>
            <option value="">Choose a message</option>
            {job.outputs.map(output => <option key={output.id} value={output.id}>{displayDate(output.createdAt, zone)} · {output.subject} · {output.status === 'accepted' && output.verified ? 'Delivery verified' : output.status}</option>)}
          </select>
          {outputId && job.outputs.some(item => item.id === outputId) ? <Preview key={outputId} job={id} outputId={outputId} /> : null}
        </> : <Empty title="No production messages saved yet">Prepared reports and verified delivery records will appear here after this job produces one. Test sends are kept separate.</Empty>}
      </section>}
      <p className="scheduler-detail-stamp subtle">
        Job snapshot {displayDate(data?.generatedAt, zone)}{loading ? ' · Refreshing…' : ''}
        {error || incomplete ? ' · Retained or incomplete evidence' : ''}
      </p>
    </>}
  </section>;
}
