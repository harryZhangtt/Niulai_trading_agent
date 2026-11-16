import { adaptResilience } from '../../../scheduler-resilience-mvp';
import type { ResilienceEvidence } from '../../../scheduler-resilience-mvp';
import type { SchedulerWireJob, SchedulerWirePacket } from '../../../types/schedulerApi';
import type { EvaluationState, GateState, JobRun, MentorBudget, MentorTruth, ProviderSafety, ProviderSafetySummary, SavedMessage, Schedule, SchedulerData, SchedulerJob, StandardJob } from '../../../scheduler/types';

const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
const exact = (value: Record<string, unknown>, keys: readonly string[]) => Object.keys(value).length === keys.length && keys.every(key => key in value);
const text = (value: unknown): value is string => typeof value === 'string';
const boundedText = (value: unknown, max = 1024): value is string => text(value) && value.length > 0 && value.length <= max;
const optionalText = (value: unknown): value is string | undefined => value === undefined || text(value);
const nullableText = (value: unknown): value is string | null => value === null || text(value);
const count = (value: unknown): value is number => Number.isInteger(value) && (value as number) >= 0 && (value as number) <= 1_000_000;
const aggregateCount = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0 && (value as number) <= 100_000_000;
const member = <T extends string>(value: unknown, values: readonly T[]): value is T => text(value) && values.includes(value as T);
const schedulerCode = (value: unknown): value is string => text(value) && /^[A-Z][A-Z0-9_]{0,99}$/.test(value);
const schedulerJobId = (value: unknown): value is string => text(value) && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$/.test(value);
function utcTimestamp(value: unknown): value is string {
  if (!boundedText(value, 64)) return false;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:Z|\+00:00)$/.exec(value);
  if (!match) return false;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, fraction = ''] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return false;
  const instant = new Date(0);
  instant.setUTCHours(0, 0, 0, 0);
  instant.setUTCFullYear(year, month - 1, day);
  instant.setUTCHours(hour, minute, second, Number((fraction + '000').slice(0, 3)));
  return instant.getUTCFullYear() === year && instant.getUTCMonth() === month - 1 && instant.getUTCDate() === day &&
    instant.getUTCHours() === hour && instant.getUTCMinutes() === minute && instant.getUTCSeconds() === second;
}
const awareTimestamp = utcTimestamp;
const codeText = (value: unknown): value is string => boundedText(value, 100) && /^[a-z][a-z0-9_]*$/.test(value);

const providerFailures = ['none','timeout','connection_reset','connection','partial_response','missing_terminal','http','auth','config','model','policy','local_config','provider','unknown'] as const;
const retryReasons = ['PROVIDER_SUCCEEDED','PROVIDER_OUTCOME_UNKNOWN','PROVIDER_TERMINAL_FAILURE','PERMANENT_LOCAL_FAILURE','PROVIDER_RETRY_DENIED','REPLAY_AUTHORITY_ABSENT','HTTP_STATUS_NOT_RETRYABLE','ATTEMPTS_EXHAUSTED','PROVIDER_WAIT_INVALID','PROVIDER_WAIT_EXCEEDS_MAX','RETRY_DEADLINE_EXCEEDED','RETRY_SCHEDULED','PROCESS_EXITED_OUTCOME_UNKNOWN','RECONCILIATION_ABSENT_RETRY'] as const;

function providerSafety(value: unknown, generatedAt: string): ProviderSafety {
  if (!object(value)) throw Error('shape');
  if (exact(value, ['status']) && value.status === 'unavailable') return { status: 'unavailable' };
  if (!exact(value, ['status','provider','latest_attempt','delayed_until','delay_source','retry_reason','replay_authorization','circuit','unknown_fence','queue']) ||
      value.status !== 'available' || !member(value.provider, ['codex_cli','claude_host'] as const) ||
      !(value.delayed_until === null || utcTimestamp(value.delayed_until)) || !(value.delay_source === null || member(value.delay_source, ['retry_after','backoff','circuit'] as const)) ||
      !(value.retry_reason === null || member(value.retry_reason, retryReasons)) ||
      !member(value.replay_authorization, ['authorized','reconciliation_required','not_authorized','not_applicable','unavailable'] as const) ||
      typeof value.unknown_fence !== 'boolean') throw Error('shape');
  if ((value.delayed_until === null) !== (value.delay_source === null) ||
      (value.delayed_until !== null && Date.parse(value.delayed_until) <= Date.parse(generatedAt))) throw Error('shape');

  let latestAttempt: Exclude<ProviderSafety, { status: 'unavailable' }>['latestAttempt'] = null;
  if (value.latest_attempt !== null) {
    const attempt = value.latest_attempt;
    if (!object(attempt) || !exact(attempt, ['phase','submission','terminal_proof','status','failure']) ||
        !member(attempt.phase, ['not_started','connecting','submitted','streaming','terminal','unavailable'] as const) ||
        !member(attempt.submission, ['not_submitted','definitely_submitted','possibly_submitted','unavailable'] as const) ||
        !member(attempt.terminal_proof, ['verified','absent','contradictory','unavailable'] as const) ||
        !member(attempt.status, ['running','succeeded','retryable','failed','unknown'] as const) ||
        !member(attempt.failure, [...providerFailures, 'unavailable'] as const)) throw Error('shape');
    const unavailableAttempt = attempt.phase === 'unavailable' || attempt.submission === 'unavailable' || attempt.terminal_proof === 'unavailable' || attempt.failure === 'unavailable';
    if (unavailableAttempt) {
      if (!(attempt.phase === 'unavailable' && attempt.submission === 'unavailable' && attempt.terminal_proof === 'unavailable' && attempt.status === 'running' && attempt.failure === 'unavailable')) throw Error('shape');
    } else {
      const nonterminal = attempt.phase !== 'terminal';
      const beforeSubmission = attempt.phase === 'not_started' || attempt.phase === 'connecting';
      if (attempt.status === 'running' ||
          (beforeSubmission && attempt.submission !== 'not_submitted') ||
          ((attempt.phase === 'submitted' || attempt.phase === 'streaming') && attempt.submission === 'not_submitted') ||
          (attempt.terminal_proof === 'verified' && attempt.phase !== 'terminal') ||
          (nonterminal && attempt.terminal_proof !== 'absent') ||
          (attempt.status === 'succeeded' && !(attempt.phase === 'terminal' && attempt.terminal_proof === 'verified' && attempt.failure === 'none')) ||
          (attempt.status !== 'succeeded' && attempt.failure === 'none') ||
          (attempt.status === 'retryable' && !(beforeSubmission && attempt.submission === 'not_submitted')) ||
          (['auth','config','model','policy','local_config'].includes(attempt.failure) && attempt.status !== 'failed') ||
          (attempt.terminal_proof === 'contradictory' && attempt.status !== 'unknown') ||
          (attempt.failure === 'missing_terminal' && attempt.status !== 'unknown') ||
          (attempt.submission !== 'not_submitted' && ['timeout','connection_reset','partial_response','missing_terminal'].includes(attempt.failure) && attempt.status !== 'unknown')) throw Error('shape');
    }
    latestAttempt = { phase: attempt.phase, submission: attempt.submission, terminalProof: attempt.terminal_proof, status: attempt.status, failure: attempt.failure };
  }

  const circuit = value.circuit;
  if (!object(circuit) || !exact(circuit, ['state','open_until','probe_until','probe_eligible']) ||
      !member(circuit.state, ['closed','open','half_open','unavailable'] as const) || typeof circuit.probe_eligible !== 'boolean' ||
      !(circuit.open_until === null || utcTimestamp(circuit.open_until)) || !(circuit.probe_until === null || utcTimestamp(circuit.probe_until)) ||
      (circuit.state === 'closed' && (circuit.open_until !== null || circuit.probe_until !== null || circuit.probe_eligible)) ||
      (circuit.state === 'open' && (circuit.open_until === null || circuit.probe_until !== null || circuit.probe_eligible !== (Date.parse(circuit.open_until) <= Date.parse(generatedAt)))) ||
      (circuit.state === 'half_open' && (circuit.open_until !== null || circuit.probe_until === null || circuit.probe_eligible !== (Date.parse(circuit.probe_until) <= Date.parse(generatedAt)))) ||
      (circuit.state === 'unavailable' && (circuit.open_until !== null || circuit.probe_until !== null || circuit.probe_eligible))) throw Error('shape');
  const queue = value.queue;
  if (!object(queue) || !exact(queue, ['depth','oldest_delayed_at']) || !count(queue.depth) || queue.depth > 100_000 ||
      !(queue.oldest_delayed_at === null || utcTimestamp(queue.oldest_delayed_at)) || ((queue.depth === 0) !== (queue.oldest_delayed_at === null)) ||
      (queue.oldest_delayed_at !== null && Date.parse(queue.oldest_delayed_at) <= Date.parse(generatedAt))) throw Error('shape');
  if (value.delay_source === 'circuit' && (circuit.state !== 'open' || value.delayed_until !== circuit.open_until)) throw Error('shape');
  if (value.retry_reason === 'RETRY_SCHEDULED' && value.replay_authorization !== 'authorized') throw Error('shape');
  if (value.replay_authorization === 'authorized' && value.retry_reason !== 'RETRY_SCHEDULED') throw Error('shape');
  if (value.unknown_fence && (latestAttempt?.status !== 'unknown' || !['reconciliation_required','not_authorized'].includes(value.replay_authorization))) throw Error('shape');
  if (!value.unknown_fence && value.replay_authorization === 'reconciliation_required') throw Error('shape');

  return {
    status: 'available', provider: value.provider, latestAttempt, delayedUntil: value.delayed_until,
    delaySource: value.delay_source as 'retry_after' | 'backoff' | 'circuit' | null, retryReason: value.retry_reason,
    replayAuthorization: value.replay_authorization,
    circuit: { state: circuit.state, openUntil: circuit.open_until, probeUntil: circuit.probe_until },
    unknownFence: value.unknown_fence, queue: { depth: queue.depth, oldestDelayedAt: queue.oldest_delayed_at },
  };
}

function providerSummary(value: unknown): ProviderSafetySummary {
  if (!object(value) || !exact(value, ['status','jobs','available_jobs','unknown_fences','delayed_jobs','queue_depth','circuits']) ||
      !member(value.status, ['not_applicable','available','partial','unavailable'] as const) || !count(value.jobs) || value.jobs > 1000 || !count(value.available_jobs) ||
      !count(value.unknown_fences) || !count(value.delayed_jobs) || !aggregateCount(value.queue_depth) || value.available_jobs > value.jobs ||
      value.unknown_fences > value.available_jobs || value.delayed_jobs > value.available_jobs) throw Error('shape');
  const circuits = value.circuits;
  if (!object(circuits) || !exact(circuits, ['closed','open','half_open','unavailable']) || !count(circuits.closed) || !count(circuits.open) ||
      !count(circuits.half_open) || !count(circuits.unavailable) || circuits.closed + circuits.open + circuits.half_open + circuits.unavailable !== value.available_jobs) throw Error('shape');
  const expected = value.jobs === 0 ? 'not_applicable' : value.available_jobs === 0 ? 'unavailable' : value.available_jobs === value.jobs ? 'available' : 'partial';
  if (value.status !== expected) throw Error('shape');
  return { status: value.status, jobs: value.jobs, availableJobs: value.available_jobs, unknownFences: value.unknown_fences,
    delayedJobs: value.delayed_jobs, queueDepth: value.queue_depth,
    circuits: { closed: circuits.closed, open: circuits.open, halfOpen: circuits.half_open, unavailable: circuits.unavailable } };
}

function summarizeProviderSafety(jobs: SchedulerJob[]): ProviderSafetySummary {
  const items = jobs.flatMap(job => job.providerSafety ? [job.providerSafety] : []);
  const available = items.filter((item): item is Extract<ProviderSafety, { status: 'available' }> => item.status === 'available');
  const circuits = { closed: 0, open: 0, halfOpen: 0, unavailable: 0 };
  for (const item of available) {
    if (item.circuit.state === 'half_open') circuits.halfOpen++;
    else circuits[item.circuit.state]++;
  }
  return {
    status: items.length === 0 ? 'not_applicable' : available.length === 0 ? 'unavailable' : available.length === items.length ? 'available' : 'partial',
    jobs: items.length, availableJobs: available.length, unknownFences: available.filter(item => item.unknownFence).length,
    delayedJobs: available.filter(item => item.delayedUntil !== null).length,
    queueDepth: available.reduce((total, item) => total + item.queue.depth, 0), circuits,
  };
}
function sameProviderSummary(left: ProviderSafetySummary, right: ProviderSafetySummary) {
  return left.status === right.status && left.jobs === right.jobs && left.availableJobs === right.availableJobs &&
    left.unknownFences === right.unknownFences && left.delayedJobs === right.delayedJobs && left.queueDepth === right.queueDepth &&
    left.circuits.closed === right.circuits.closed && left.circuits.open === right.circuits.open &&
    left.circuits.halfOpen === right.circuits.halfOpen && left.circuits.unavailable === right.circuits.unavailable;
}
function providerDetailDegraded(value: unknown, generatedAt: string) {
  if (!object(value) || value.provider_safety === undefined) return false;
  try { providerSafety(value.provider_safety, generatedAt); return false; }
  catch { return true; }
}

function schedule(value: unknown): Schedule {
  if (!object(value) || !text(value.kind)) throw Error('shape');
  if (value.kind === 'interval') {
    if (!(exact(value, ['kind', 'seconds']) || exact(value, ['kind', 'seconds', 'grace_seconds'])) ||
        !count(value.seconds) || value.seconds < 1 || value.seconds > 31_536_000 ||
        (value.grace_seconds !== undefined && (!count(value.grace_seconds) || value.grace_seconds < 1 || value.grace_seconds > 604_800))) throw Error('shape');
    return { kind: 'interval', seconds: value.seconds, ...(value.grace_seconds === undefined ? {} : { grace_seconds: value.grace_seconds }) };
  }
  if (value.kind === 'daily') {
    if (!exact(value, ['kind', 'timezone', 'times', 'grace_seconds']) || !boundedText(value.timezone, 128) ||
        !Array.isArray(value.times) || value.times.length < 1 || value.times.length > 24 ||
        !value.times.every(item => text(item) && /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/.test(item)) ||
        new Set(value.times).size !== value.times.length || !count(value.grace_seconds) || value.grace_seconds < 1 || value.grace_seconds > 604_800) throw Error('shape');
    return { kind: 'daily', timezone: value.timezone, times: value.times, grace_seconds: value.grace_seconds };
  }
  if (value.kind === 'once') {
    if (!exact(value, ['kind', 'at', 'grace_seconds']) || !utcTimestamp(value.at) ||
        !count(value.grace_seconds) || value.grace_seconds < 1 || value.grace_seconds > 604_800) throw Error('shape');
    return { kind: 'once', at: value.at, grace_seconds: value.grace_seconds };
  }
  if (value.kind === 'sequence') {
    if (!exact(value, ['kind', 'timestamps', 'grace_seconds']) || !Array.isArray(value.timestamps) ||
        !count(value.grace_seconds) || value.grace_seconds < 1 || value.grace_seconds > 604_800) throw Error('shape');
    const timestamps = value.timestamps;
    if (timestamps.length < 1 || timestamps.length > 128 || !timestamps.every(utcTimestamp) ||
        timestamps.some((stamp, index) => index > 0 && Date.parse(timestamps[index - 1]) >= Date.parse(stamp))) throw Error('shape');
    return { kind: 'sequence', timestamps, grace_seconds: value.grace_seconds };
  }
  throw Error('shape');
}
function delivery(value: unknown) {
  if (!object(value) || !(exact(value, ['mode','next_send_at','note']) || exact(value, ['mode','next_send_at','note','calendar'])) || !text(value.mode) || !nullableText(value.next_send_at) || !text(value.note) ||
      (value.calendar !== undefined && !nullableText(value.calendar))) throw Error('shape');
  return { mode: value.mode, nextSendAt: value.next_send_at, note: value.note, ...(value.calendar !== undefined ? { calendar: value.calendar } : {}) };
}
function run(value: unknown): JobRun {
  if (!object(value) || !exact(value, ['id','scheduled_at','updated_at','status','code','attempts']) || !text(value.id) || !text(value.scheduled_at) || !text(value.updated_at) || !text(value.status) || !text(value.code) || !count(value.attempts)) throw Error('shape');
  return { id: value.id, scheduledAt: value.scheduled_at, updatedAt: value.updated_at, status: value.status, code: value.code, attempts: value.attempts };
}
function saved(value: unknown): SavedMessage {
  if (!object(value) || !exact(value, ['id','subject','status','verified','created_at','verified_at','kind']) || !text(value.id) || !text(value.subject) || !text(value.status) || typeof value.verified !== 'boolean' || !text(value.created_at) || !nullableText(value.verified_at) || !text(value.kind)) throw Error('shape');
  return { id: value.id, subject: value.subject, status: value.status, verified: value.verified, createdAt: value.created_at, verifiedAt: value.verified_at, kind: value.kind };
}
function common(job: SchedulerWireJob, generatedAt: string) {
  if (!schedulerJobId(job.id) || !text(job.title) || !text(job.description) || typeof job.enabled !== 'boolean' ||
      !(job.next_run_at === null || utcTimestamp(job.next_run_at)) || typeof job.replay_safe !== 'boolean' || !optionalText(job.model) || !optionalText(job.effort)) throw Error('shape');
  const parsedSchedule = schedule(job.schedule);
  if (parsedSchedule.kind === 'sequence') {
    const expected = job.enabled ? parsedSchedule.timestamps.find(stamp => Date.parse(stamp) > Date.parse(generatedAt)) ?? null : null;
    if ((expected === null) !== (job.next_run_at === null) || (expected !== null && Date.parse(expected) !== Date.parse(job.next_run_at as string))) throw Error('shape');
  }
  let adaptedProviderSafety: ProviderSafety | undefined;
  if (job.provider_safety !== undefined) {
    try { adaptedProviderSafety = providerSafety(job.provider_safety, generatedAt); }
    catch { adaptedProviderSafety = { status: 'unavailable' }; }
  }
  return { id: job.id, title: job.title, description: job.description, enabled: job.enabled, schedule: parsedSchedule, nextRunAt: job.next_run_at, replaySafe: job.replay_safe, model: job.model, effort: job.effort, delivery: delivery(job.delivery), ...(adaptedProviderSafety ? { providerSafety: adaptedProviderSafety } : {}) };
}

const budgetKeys = ['used', 'limit'] as const;
function budget(value: unknown): MentorBudget {
  if (!object(value) || !exact(value, budgetKeys) || !count(value.used) || !count(value.limit) || value.used > value.limit) throw Error('shape');
  return { used: value.used, limit: value.limit };
}
const gate = (value: unknown): value is GateState => member(value, ['verified', 'failed', 'not_verified'] as const);
const evaluation = (value: unknown): value is EvaluationState => member(value, ['pending', 'preserved', 'not_required', 'unverified', 'inconclusive', 'passed', 'failed'] as const);

function resilience(value: unknown, generatedAt: string): ResilienceEvidence {
  if (!object(value) || !exact(value, ['generated_at','status','projection_state','scheduler','provider_safety','mentor','health']) ||
      value.generated_at !== generatedAt || !member(value.status, ['ok','partial'] as const) ||
      !member(value.projection_state, ['current','stale','unknown'] as const)) throw Error('shape');
  const scheduler = value.scheduler;
  if (!object(scheduler) || !exact(scheduler, ['status','attempts']) ||
      !member(scheduler.status, ['ready','running','retry_wait','succeeded','failed','unknown','missed','coalesced'] as const) ||
      !count(scheduler.attempts)) throw Error('shape');
  const provider = value.provider_safety;
  if (!object(provider) || !exact(provider, ['latest_attempt','delayed_until','delay_source','unknown_fence','replay_authorization']) ||
      !(provider.delayed_until === null || utcTimestamp(provider.delayed_until)) ||
      !(provider.delay_source === null || member(provider.delay_source, ['retry_after','backoff','circuit'] as const)) ||
      (provider.delayed_until === null) !== (provider.delay_source === null) ||
      (provider.delayed_until !== null && Date.parse(provider.delayed_until) <= Date.parse(generatedAt)) ||
      typeof provider.unknown_fence !== 'boolean' ||
      !member(provider.replay_authorization, ['authorized','reconciliation_required','not_authorized','not_applicable','unavailable'] as const)) throw Error('shape');
  if (provider.latest_attempt !== null) {
    const latest = provider.latest_attempt;
    if (!object(latest) || !exact(latest, ['phase','status']) ||
        !member(latest.phase, ['not_started','connecting','submitted','streaming','terminal','unavailable'] as const) ||
        !member(latest.status, ['running','succeeded','retryable','failed','unknown'] as const)) throw Error('shape');
  }
  if ((provider.unknown_fence &&
      ((provider.latest_attempt !== null && (!object(provider.latest_attempt) || provider.latest_attempt.status !== 'unknown')) ||
       !['reconciliation_required','not_authorized'].includes(provider.replay_authorization))) ||
      (!provider.unknown_fence && provider.replay_authorization === 'reconciliation_required')) throw Error('shape');
  const mentorEvidence = value.mentor;
  if (!object(mentorEvidence) || !exact(mentorEvidence, ['cycles','no_progress','repeated','evidence_reset']) ||
      !count(mentorEvidence.cycles) || typeof mentorEvidence.evidence_reset !== 'boolean') throw Error('shape');
  budget(mentorEvidence.no_progress);
  budget(mentorEvidence.repeated);
  const health = value.health;
  if (!object(health) || !exact(health, ['heartbeat_age_seconds','watchdog_healthy']) ||
      !(health.heartbeat_age_seconds === null || (typeof health.heartbeat_age_seconds === 'number' && Number.isFinite(health.heartbeat_age_seconds) && health.heartbeat_age_seconds >= 0)) ||
      !(health.watchdog_healthy === null || typeof health.watchdog_healthy === 'boolean')) throw Error('shape');
  return adaptResilience(value);
}

function mentor(value: unknown, generatedAt: string): MentorTruth | { status: 'unavailable' } {
  if (!object(value)) throw Error('shape');
  if (exact(value, ['status']) && value.status === 'unavailable') return { status: 'unavailable' };
  if (!exact(value, ['work_order','scheduler','session','progress','safeguards','gates','evaluation','resilience','runtime_acceptance','recovery_timeline'])) throw Error('shape');
  const work = value.work_order;
  const scheduler = value.scheduler;
  const session = value.session;
  const progress = value.progress;
  const safeguards = value.safeguards;
  const gates = value.gates;
  const evaluationGroup = value.evaluation;
  const resilienceEvidence = resilience(value.resilience, generatedAt);
  const runtime = value.runtime_acceptance;
  const timeline = value.recovery_timeline;
  if (!object(work) || !exact(work, ['id','logical_session_id','starts_at','ends_at','window_state','acceptance_criteria_total','required_event_kinds']) ||
      !boundedText(work.id) || !boundedText(work.logical_session_id) || work.id !== work.logical_session_id || !awareTimestamp(work.starts_at) || !awareTimestamp(work.ends_at) || Date.parse(work.starts_at) >= Date.parse(work.ends_at) ||
      !member(work.window_state, ['upcoming','open','expired'] as const) || !count(work.acceptance_criteria_total) || !Array.isArray(work.required_event_kinds) || work.required_event_kinds.length > 64 || !work.required_event_kinds.every(codeText) || new Set(work.required_event_kinds).size !== work.required_event_kinds.length) throw Error('shape');
  const generated = Date.parse(generatedAt), starts = Date.parse(work.starts_at), ends = Date.parse(work.ends_at);
  const expectedWindow = generated < starts ? 'upcoming' : generated < ends ? 'open' : 'expired';
  if (work.window_state !== expectedWindow) throw Error('shape');
  if (!object(scheduler) || !exact(scheduler, ['status','code','attempts','dispatch']) || !member(scheduler.status, ['ready','running','retry_wait','succeeded','failed','unknown','missed','coalesced'] as const) || !schedulerCode(scheduler.code) || !count(scheduler.attempts) || !member(scheduler.dispatch, ['not_attempted','definitely_not_dispatched','possibly_dispatched','confirmed_dispatched'] as const) || (scheduler.dispatch === 'not_attempted' && scheduler.attempts !== 0)) throw Error('shape');
  if (!object(session) || !exact(session, ['status','revision']) || !member(session.status, ['active','blocked_pending_effect','completed','failed','cancelled'] as const) || !count(session.revision)) throw Error('shape');
  if (!object(progress) || !exact(progress, ['cycles','provider_threads','variants','interventions','reused_evaluations','pending_effects']) || !count(progress.pending_effects)) throw Error('shape');
  const cycles = budget(progress.cycles); const providerThreads = budget(progress.provider_threads); const variants = budget(progress.variants); const interventions = budget(progress.interventions); const reusedEvaluations = budget(progress.reused_evaluations);
  if (!object(safeguards) || !exact(safeguards, ['provider_thread_mode','record_all_variants','worker_holdout_access','require_no_pending_effects','configured_replay_safe','replay_authorization']) || safeguards.provider_thread_mode !== 'ephemeral_threads' || safeguards.record_all_variants !== true || safeguards.worker_holdout_access !== false || safeguards.require_no_pending_effects !== true || typeof safeguards.configured_replay_safe !== 'boolean' || safeguards.replay_authorization !== 'not_authorized') throw Error('shape');
  if (!object(gates) || !exact(gates, ['future_wake','profile_binding','stop_propagation','model_turn','journal_cycle_postcondition','no_duplicate_dispatch']) || !gate(gates.future_wake) || !gate(gates.profile_binding) || !gate(gates.stop_propagation) || !gate(gates.model_turn) || !gate(gates.journal_cycle_postcondition) || !gate(gates.no_duplicate_dispatch)) throw Error('shape');
  const expectedDuplicate = scheduler.attempts === 0 ? 'not_verified' : scheduler.attempts === 1 ? 'verified' : 'failed';
  if (gates.no_duplicate_dispatch !== expectedDuplicate) throw Error('shape');
  if (!object(evaluationGroup) || !exact(evaluationGroup, ['attempt_ledger_preserved','baseline','ablation','holdout','promotion']) || evaluationGroup.attempt_ledger_preserved !== true || !evaluation(evaluationGroup.baseline) || !evaluation(evaluationGroup.ablation) || !evaluation(evaluationGroup.holdout) || !evaluation(evaluationGroup.promotion)) throw Error('shape');
  if (!object(runtime) || !exact(runtime, ['execution','acceptance','model_turn','email']) || !member(runtime.execution, ['pending','running','passed','partial','failed','unverified'] as const) || !member(runtime.acceptance, ['pending','passed','partial','failed','unverified'] as const) || !member(runtime.model_turn, ['completed','started','not_started','unknown'] as const) || !member(runtime.email, ['pending','verified','failed','unknown'] as const)) throw Error('shape');
  if ((runtime.acceptance === 'passed' && (runtime.execution !== 'passed' || runtime.email !== 'verified')) || (['partial','failed'].includes(runtime.acceptance) && runtime.execution !== runtime.acceptance) || (runtime.acceptance === 'pending' && !['pending','running'].includes(runtime.execution)) || (runtime.acceptance === 'unverified' && (!['pending','running','unverified','passed'].includes(runtime.execution) || (runtime.execution === 'passed' && runtime.email === 'verified')))) throw Error('shape');
  if (!Array.isArray(timeline) || timeline.length > 4) throw Error('shape');
  const order = ['scheduled','attempt_started','dispatch_failed','operator_reconciled'] as const;
  const statuses = { scheduled: 'recorded', attempt_started: 'recorded', dispatch_failed: 'failed', operator_reconciled: 'resolved' } as const;
  let previous = -1; let previousAt = -Infinity;
  const recoveryTimeline = timeline.map(item => {
    if (!object(item) || !exact(item, ['event','status','at']) || !member(item.event, order) || item.status !== statuses[item.event] || !awareTimestamp(item.at)) throw Error('shape');
    const index = order.indexOf(item.event); const at = Date.parse(item.at);
    if (index <= previous || at < previousAt) throw Error('shape');
    previous = index; previousAt = at;
    return { event: item.event, status: item.status as 'recorded' | 'failed' | 'resolved', at: item.at };
  });
  if (runtime.acceptance === 'passed' && (runtime.model_turn !== 'completed' || scheduler.attempts !== 1 || session.status !== 'completed' || Object.values(gates).some(state => state !== 'verified'))) throw Error('shape');
  return {
    workOrder: { id: work.id, logicalSessionId: work.logical_session_id, startsAt: work.starts_at, endsAt: work.ends_at, windowState: work.window_state, acceptanceCriteriaTotal: work.acceptance_criteria_total, requiredEventKinds: work.required_event_kinds },
    scheduler: { status: scheduler.status, code: scheduler.code, attempts: scheduler.attempts, dispatch: scheduler.dispatch },
    session: { status: session.status, revision: session.revision },
    progress: { cycles, providerThreads, variants, interventions, reusedEvaluations, pendingEffects: progress.pending_effects },
    safeguards: { providerThreadMode: safeguards.provider_thread_mode, recordAllVariants: true, workerHoldoutAccess: false, requireNoPendingEffects: true, configuredReplaySafe: safeguards.configured_replay_safe, replayAuthorization: 'not_authorized' },
    gates: { futureWake: gates.future_wake, profileBinding: gates.profile_binding, stopPropagation: gates.stop_propagation, modelTurn: gates.model_turn, journalCyclePostcondition: gates.journal_cycle_postcondition, noDuplicateDispatch: gates.no_duplicate_dispatch },
    evaluation: { attemptLedgerPreserved: true, baseline: evaluationGroup.baseline, ablation: evaluationGroup.ablation, holdout: evaluationGroup.holdout, promotion: evaluationGroup.promotion },
    resilience: resilienceEvidence,
    runtimeAcceptance: { execution: runtime.execution, acceptance: runtime.acceptance, modelTurn: runtime.model_turn, email: runtime.email }, recoveryTimeline,
  };
}
function promptCustody(value: unknown): StandardJob['promptCustody'] {
  if (!object(value) || !exact(value, ['status','attempts_bound']) ||
      !member(value.status, ['bound','backfilled','legacy_unbound','unavailable'] as const) || !count(value.attempts_bound)) {
    return { status: 'unavailable', attemptsBound: 0 };
  }
  return { status: value.status, attemptsBound: value.attempts_bound };
}
function promptCustodyDegraded(value: unknown) {
  return promptCustody(value).status === 'unavailable' && (!object(value) || value.status !== 'unavailable');
}
function standard(job: SchedulerWireJob, generatedAt: string): StandardJob {
  if (!Array.isArray(job.history) || !Array.isArray(job.outputs)) throw Error('shape');
  let output: StandardJob['output'];
  if (job.output !== undefined) {
    if (!object(job.output) || !exact(job.output, ['id','subject','html','attachments']) || !text(job.output.id) || !text(job.output.subject) || !text(job.output.html) || !Array.isArray(job.output.attachments)) throw Error('shape');
    const attachments = job.output.attachments.map(item => { if (!object(item) || !exact(item, ['name','type']) || !text(item.name) || !nullableText(item.type)) throw Error('shape'); return { name: item.name, type: item.type ?? '' }; });
    output = { id: job.output.id, subject: job.output.subject, html: job.output.html, attachments };
  }
  return { ...common(job, generatedAt), jobType: 'standard', history: job.history.map(run), outputs: job.outputs.map(saved), promptCustody: promptCustody(job.prompt_custody), ...(output ? { output } : {}) };
}
function adaptJob(value: unknown, generatedAt: string): SchedulerJob {
  if (!object(value)) throw Error('shape');
  const commonKeys = ['id','title','description','enabled','schedule','next_run_at','replay_safe','delivery','history','outputs'];
  const optionalKeys = ['model','effort','provider_safety'];
  const job = value as unknown as SchedulerWireJob;
  if (job.job_type === 'mentor') {
    if (!exact(value, [...commonKeys,'job_type','mentor',...optionalKeys.filter(key => key in value)])) throw Error('shape');
    return { ...common(job, generatedAt), jobType: 'mentor', mentor: mentor(job.mentor, generatedAt) };
  }
  if (job.job_type !== undefined || !exact(value, [...commonKeys,'prompt_custody',...optionalKeys.filter(key => key in value),...(job.output === undefined ? [] : ['output'])])) throw Error('shape');
  return standard(job, generatedAt);
}
export function adaptScheduler(value: unknown): SchedulerData {
  if (!object(value) || !(exact(value, ['schema_version','scope','read_only','status','generated_at','health','provider_safety','jobs','warnings']) ||
      exact(value, ['schema_version','scope','read_only','status','generated_at','health','provider_safety','jobs','warnings','projection_state']))) throw Error('shape');
  const packet = value as unknown as SchedulerWirePacket;
  const health = value.health;
  if (packet.schema_version !== 1 || packet.scope !== 'local_codex_scheduler' || packet.read_only !== true || !utcTimestamp(packet.generated_at) ||
      !member(packet.status, ['ok', 'partial'] as const) || !(packet.projection_state === undefined || packet.projection_state === 'stale') ||
      !object(health) || !(exact(health, ['state','heartbeat_at','watchdog_healthy']) || exact(health, ['state','heartbeat_at','watchdog_healthy','heartbeat_age_seconds'])) ||
      !member(health.state, ['healthy', 'stale', 'unavailable'] as const) ||
      !(health.heartbeat_at === null || utcTimestamp(health.heartbeat_at)) ||
      !(health.watchdog_healthy === null || typeof health.watchdog_healthy === 'boolean') ||
      (health.heartbeat_age_seconds !== undefined && (typeof health.heartbeat_age_seconds !== 'number' || !Number.isFinite(health.heartbeat_age_seconds))) ||
      !Array.isArray(packet.jobs) || packet.jobs.length > 1000 || !Array.isArray(packet.warnings)) throw Error('shape');
  const declaredProviderSummary = providerSummary(packet.provider_safety);
  const degradedProviderDetails = packet.jobs.map(job => providerDetailDegraded(job, packet.generated_at));
  const degradedPromptCustody = packet.jobs.map(job => object(job) && job.job_type === undefined && promptCustodyDegraded(job.prompt_custody));
  const jobs = packet.jobs.map(job => adaptJob(job, packet.generated_at));
  const adaptedProviderSummary = summarizeProviderSafety(jobs);
  const providerSummaryMismatch = !sameProviderSummary(declaredProviderSummary, adaptedProviderSummary);
  const providerDetailIncomplete = degradedProviderDetails.some(Boolean);
  const warnings = packet.warnings.map(item => { if (!object(item) || !(exact(item, ['code']) || exact(item, ['code','job_id'])) || !text(item.code) || (item.job_id !== undefined && !text(item.job_id))) throw Error('shape'); return { code: item.code, ...(item.job_id ? { jobId: item.job_id } : {}) }; });
  if (providerSummaryMismatch) warnings.push({ code: 'PROVIDER_SAFETY_SUMMARY_MISMATCH' });
  degradedProviderDetails.forEach((degraded, index) => {
    const warning = { code: 'PROVIDER_SAFETY_UNAVAILABLE', jobId: jobs[index].id };
    if (degraded && !warnings.some(item => item.code === warning.code && item.jobId === warning.jobId)) warnings.push(warning);
  });
  degradedPromptCustody.forEach((degraded, index) => {
    if (degraded) warnings.push({ code: 'PROMPT_CUSTODY_UNAVAILABLE', jobId: jobs[index].id });
  });
  return { generatedAt: packet.generated_at, status: providerSummaryMismatch || providerDetailIncomplete || degradedPromptCustody.some(Boolean) ? 'partial' : packet.status, projectionState: packet.projection_state,
    health: { state: packet.health.state, heartbeatAt: packet.health.heartbeat_at, watchdogHealthy: packet.health.watchdog_healthy },
    providerSafety: adaptedProviderSummary, jobs, warnings };
}
