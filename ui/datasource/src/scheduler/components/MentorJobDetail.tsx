import { useState, type ReactNode } from 'react';
import { Badge, Empty, Icon, Notice } from '../../components';
import { ResiliencePanel } from '../../scheduler-resilience-mvp';
import type { MentorBudget, MentorJob, MentorTruth } from '../types';
import { useScheduler } from '../useScheduler';
import { attentionReason } from '../presentation';
import { cadence, displayDate } from './shared';

const words = (value: string) => value.replaceAll('_', ' ');
const yesNo = (value: boolean) => value ? 'Yes' : 'No';
const fact = (label: string, value: ReactNode) => <div><dt>{label}</dt><dd>{value}</dd></div>;
const status = (value: string) => <Badge value={value}>{words(value)}</Badge>;
const budget = (label: string, value: MentorBudget) => fact(label, <><strong>{value.used}</strong> used / {value.limit} limit</>);
type MentorView = 'overview' | 'evidence' | 'recovery';

function mentorBadge(job: MentorJob) {
  const mentor = job.mentor;
  if ('status' in mentor) return <Badge value="partial">Evidence unavailable</Badge>;
  const attention = attentionReason(job);
  const accepted = mentor.runtimeAcceptance.acceptance === 'passed';
  return <Badge value={attention ? 'partial' : accepted ? 'verified' : 'unknown'}>
    {attention ?? (accepted ? 'Acceptance verified' : 'Awaiting acceptance')}
  </Badge>;
}

function RuntimeAcceptance({ truth }: { truth: MentorTruth }) {
  return <section aria-labelledby="mentor-runtime">
    <h3 id="mentor-runtime">Runtime acceptance</h3>
    <dl className="scheduler-outcomes">
      {fact('Execution', status(truth.runtimeAcceptance.execution))}
      {fact('Acceptance', status(truth.runtimeAcceptance.acceptance))}
      {fact('Model turn', status(truth.runtimeAcceptance.modelTurn))}
      {fact('Email', status(truth.runtimeAcceptance.email))}
    </dl>
    <p>Execution, acceptance and verified email are separate outcomes.</p>
  </section>;
}

function AcceptanceGates({ truth }: { truth: MentorTruth }) {
  return <section aria-labelledby="mentor-plan">
    <h3 id="mentor-plan">Plan and acceptance gates</h3>
    <dl className="mentor-grid">
      {fact('Future wake', status(truth.gates.futureWake))}
      {fact('Profile binding', status(truth.gates.profileBinding))}
      {fact('Stop propagation', status(truth.gates.stopPropagation))}
      {fact('Model turn', status(truth.gates.modelTurn))}
      {fact('Journal cycle postcondition', status(truth.gates.journalCyclePostcondition))}
      {fact('No duplicate dispatch', status(truth.gates.noDuplicateDispatch))}
    </dl>
  </section>;
}

function Overview({ truth, zone, stale, refreshing, partial }: { truth: MentorTruth; zone: string; stale: boolean; refreshing: boolean; partial: boolean }) {
  return <div className="mentor-sections">
    <RuntimeAcceptance truth={truth} />
    <section aria-labelledby="mentor-progress-overview">
      <h3 id="mentor-progress-overview">Progress and dispatch</h3>
      <dl className="mentor-grid">
        {fact('Dispatch', status(truth.scheduler.dispatch))}
        {fact('Window', status(truth.workOrder.windowState))}
        {fact('Pending effects', truth.progress.pendingEffects)}
        {budget('Cycles', truth.progress.cycles)}
        {fact('Scheduler status', status(truth.scheduler.status))}
        {fact('Ends', displayDate(truth.workOrder.endsAt, zone))}
      </dl>
    </section>
    <div className="mentor-resilience-slot"><ResiliencePanel evidence={truth.resilience} zone={zone} stale={stale} refreshing={refreshing} partial={partial} /></div>
    <AcceptanceGates truth={truth} />
  </div>;
}

function Evidence({ truth, zone }: { truth: MentorTruth; zone: string }) {
  const work = truth.workOrder;
  return <div className="mentor-sections">
    <section aria-labelledby="mentor-overview">
      <h3 id="mentor-overview">Overview and work order</h3>
      <dl className="mentor-grid">
        {fact('Work-order ID', work.id)}
        {fact('Logical session ID', work.logicalSessionId)}
        {fact('Session', status(truth.session.status))}
        {fact('Revision', truth.session.revision)}
        {fact('Starts', displayDate(work.startsAt, zone))}
        {fact('Ends', displayDate(work.endsAt, zone))}
        {fact('Window', status(work.windowState))}
        {fact('Acceptance criteria', work.acceptanceCriteriaTotal)}
        {fact('Required event kinds', work.requiredEventKinds.length ? work.requiredEventKinds.map(words).join(', ') : 'None')}
      </dl>
    </section>
    <AcceptanceGates truth={truth} />
    <section aria-labelledby="mentor-safeguards">
      <h3 id="mentor-safeguards">Safeguards and progress</h3>
      <dl className="mentor-grid">
        {budget('Cycles', truth.progress.cycles)}
        {budget('Provider threads', truth.progress.providerThreads)}
        {budget('Variants', truth.progress.variants)}
        {budget('Interventions', truth.progress.interventions)}
        {budget('Reused evaluations', truth.progress.reusedEvaluations)}
        {fact('Pending effects', truth.progress.pendingEffects)}
        {fact('Provider thread mode', words(truth.safeguards.providerThreadMode))}
        {fact('Record all variants', yesNo(truth.safeguards.recordAllVariants))}
        {fact('Worker holdout access', yesNo(truth.safeguards.workerHoldoutAccess))}
        {fact('Require no pending effects', yesNo(truth.safeguards.requireNoPendingEffects))}
        {fact('Configured replay-safe', yesNo(truth.safeguards.configuredReplaySafe))}
        {fact('Replay authorization', status(truth.safeguards.replayAuthorization))}
      </dl>
      <p className="mentor-truth">Replay-safe configuration is shown separately from authorization. This read-only surface cannot authorize or replay work.</p>
    </section>
    <section aria-labelledby="mentor-evaluation">
      <h3 id="mentor-evaluation">Evaluation and overfitting controls</h3>
      <dl className="mentor-grid">
        {fact('Attempt ledger preserved', yesNo(truth.evaluation.attemptLedgerPreserved))}
        {fact('Baseline', status(truth.evaluation.baseline))}
        {fact('Ablation', status(truth.evaluation.ablation))}
        {fact('Holdout', status(truth.evaluation.holdout))}
        {fact('Promotion', status(truth.evaluation.promotion))}
      </dl>
    </section>
    <RuntimeAcceptance truth={truth} />
    <section aria-labelledby="mentor-history">
      <h3 id="mentor-history">History and current scheduler state</h3>
      <dl className="mentor-grid">
        {fact('Scheduler status', status(truth.scheduler.status))}
        {fact('Scheduler code', <code>{truth.scheduler.code}</code>)}
        {fact('Attempts', truth.scheduler.attempts)}
        {fact('Dispatch', status(truth.scheduler.dispatch))}
        {fact('Session revision', truth.session.revision)}
      </dl>
      <p>Detailed private evidence and generic job output are intentionally not exposed.</p>
    </section>
  </div>;
}

function RecoveryTimeline({ truth, zone }: { truth: MentorTruth; zone: string }) {
  return <div className="mentor-sections">
    <section aria-labelledby="mentor-recovery">
      <h3 id="mentor-recovery">Recovery timeline</h3>
      {truth.recoveryTimeline.length ? <ol className="mentor-timeline">
        {truth.recoveryTimeline.map(item => <li key={`${item.event}-${item.at}`}>
          <span>{words(item.event)}</span>
          <Badge value={item.status}>{words(item.status)}</Badge>
          <time dateTime={item.at}>{displayDate(item.at, zone)}</time>
        </li>)}
      </ol> : <p>No recovery events are recorded.</p>}
    </section>
  </div>;
}

export function MentorJobDetail({ id, zone }: { id: string; zone: string }) {
  const { data, loading, error, refresh } = useScheduler(new URLSearchParams({ job: id }).toString());
  const [view, setView] = useState<MentorView>('overview');
  const selected = data?.jobs[0];
  const job: MentorJob | undefined = selected?.jobType === 'mentor' ? selected : undefined;
  const stale = Boolean(job && error) || data?.projectionState === 'stale';
  const incomplete = data?.status === 'partial';
  return <section className="scheduler-detail mentor-detail" id="job-detail" aria-label="Selected mentor job details" aria-busy={loading}>
    {error && !job ? <Notice kind="error" title="Mentor details unavailable">
      <p>{error}</p>
      <button className="button button-secondary" onClick={refresh} disabled={loading}>Retry details</button>
    </Notice> : null}
    {stale ? <Notice kind="warning" title="Mentor snapshot is stale">
      <p>{error ? `${error} ` : ''}The last successful snapshot remains visible. Refresh to verify the current state.</p>
      <button className="button button-secondary" onClick={refresh} disabled={loading}>Retry details</button>
    </Notice> : null}
    {incomplete ? <Notice kind="warning" title="Mentor snapshot is incomplete">
      <p>Some evidence could not be validated. Available evidence is shown without inferring missing outcomes.</p>
    </Notice> : null}
    {!job ? loading ? <p role="status">Loading mentor details…</p> : <Empty title="Mentor details unavailable">The selected response did not contain a valid mentor projection.</Empty> : <>
      <div className="section-heading">
        <div><h2>{job.title}</h2><p className="subtle">{job.description}</p></div>
        <div className="scheduler-job-actions">
          {mentorBadge(job)}
          <button className="button button-secondary button-small" aria-label="Refresh selected mentor job" onClick={refresh} disabled={loading}><Icon name="refresh" /></button>
        </div>
      </div>
      <dl className="scheduler-facts">
        {fact('Next run', displayDate(job.nextRunAt, zone))}
        {fact('Schedule', cadence(job.schedule))}
        {fact('Boundary', 'Read-only mentor acceptance evidence')}
      </dl>
      {'status' in job.mentor ? <Notice kind="warning" title="Mentor evidence unavailable">
        <p>The bounded evidence could not be validated. No success, dispatch, acceptance, or delivery is inferred.</p>
      </Notice> : <>
        <nav className="view-nav scheduler-tabs" aria-label="Mentor detail views">
          <button aria-pressed={view === 'overview'} onClick={() => setView('overview')}>Overview</button>
          <button aria-pressed={view === 'evidence'} onClick={() => setView('evidence')}>Evidence and safeguards</button>
          <button aria-pressed={view === 'recovery'} onClick={() => setView('recovery')}>Recovery timeline</button>
        </nav>
        {view === 'overview' ? <Overview truth={job.mentor} zone={zone} stale={stale} refreshing={loading} partial={incomplete} />
          : view === 'evidence' ? <Evidence truth={job.mentor} zone={zone} />
            : <RecoveryTimeline truth={job.mentor} zone={zone} />}
      </>}
      <p className="scheduler-detail-stamp subtle">Job snapshot {displayDate(data?.generatedAt, zone)}{loading ? ' · Refreshing…' : ''}</p>
    </>}
  </section>;
}
