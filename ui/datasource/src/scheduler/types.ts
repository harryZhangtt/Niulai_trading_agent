import type { ResilienceEvidence } from '../scheduler-resilience-mvp';

export type Schedule =
  | { kind: 'daily'; timezone: string; times: string[]; grace_seconds: number }
  | { kind: 'interval'; seconds: number; grace_seconds?: number }
  | { kind: 'once'; at: string; grace_seconds: number }
  | { kind: 'sequence'; timestamps: string[]; grace_seconds: number };
export interface JobRun { id: string; scheduledAt: string; updatedAt: string; status: string; code: string; attempts: number }
export interface SavedMessage { id: string; subject: string; status: string; verified: boolean; createdAt: string; verifiedAt: string | null; kind: string }
export interface SchedulerOutput { id: string; subject: string; html: string; attachments: Array<{ name: string; type: string }> }
export type ProviderFailure =
  | 'none' | 'timeout' | 'connection_reset' | 'connection' | 'partial_response' | 'missing_terminal'
  | 'http' | 'auth' | 'config' | 'model' | 'policy' | 'local_config' | 'provider' | 'unknown';
export type ProviderSafety = { status: 'unavailable' } | {
  status: 'available'; provider: 'codex_cli' | 'claude_host';
  latestAttempt: null | {
    phase: 'not_started' | 'connecting' | 'submitted' | 'streaming' | 'terminal' | 'unavailable';
    submission: 'not_submitted' | 'definitely_submitted' | 'possibly_submitted' | 'unavailable';
    terminalProof: 'verified' | 'absent' | 'contradictory' | 'unavailable';
    status: 'running' | 'succeeded' | 'retryable' | 'failed' | 'unknown'; failure: ProviderFailure | 'unavailable';
  };
  delayedUntil: string | null; delaySource: 'retry_after' | 'backoff' | 'circuit' | null; retryReason: string | null;
  replayAuthorization: 'authorized' | 'reconciliation_required' | 'not_authorized' | 'not_applicable' | 'unavailable';
  circuit: { state: 'closed' | 'open' | 'half_open' | 'unavailable'; openUntil: string | null; probeUntil: string | null };
  unknownFence: boolean; queue: { depth: number; oldestDelayedAt: string | null };
};
export interface ProviderSafetySummary {
  status: 'not_applicable' | 'available' | 'partial' | 'unavailable'; jobs: number; availableJobs: number;
  unknownFences: number; delayedJobs: number; queueDepth: number;
  circuits: { closed: number; open: number; halfOpen: number; unavailable: number };
}
export interface SchedulerJobBase {
  id: string; title: string; description: string; enabled: boolean; schedule: Schedule; nextRunAt: string | null;
  model?: string; effort?: string; replaySafe: boolean; providerSafety?: ProviderSafety;
  delivery: { mode: string; nextSendAt: string | null; note: string; calendar?: string | null };
}
export type PromptCustody = { status: 'bound' | 'backfilled' | 'legacy_unbound' | 'unavailable'; attemptsBound: number };
export interface StandardJob extends SchedulerJobBase {
  jobType: 'standard'; history: JobRun[]; outputs: SavedMessage[]; promptCustody: PromptCustody;
  output?: SchedulerOutput;
}
export type GateState = 'verified' | 'failed' | 'not_verified';
export type EvaluationState = 'pending' | 'preserved' | 'not_required' | 'unverified' | 'inconclusive' | 'passed' | 'failed';
export interface MentorTruth {
  workOrder: { id: string; logicalSessionId: string; startsAt: string; endsAt: string; windowState: 'upcoming' | 'open' | 'expired'; acceptanceCriteriaTotal: number; requiredEventKinds: string[] };
  scheduler: { status: 'ready' | 'running' | 'retry_wait' | 'succeeded' | 'failed' | 'unknown' | 'missed' | 'coalesced'; code: string; attempts: number; dispatch: 'not_attempted' | 'definitely_not_dispatched' | 'possibly_dispatched' | 'confirmed_dispatched' };
  session: { status: 'active' | 'blocked_pending_effect' | 'completed' | 'failed' | 'cancelled'; revision: number };
  progress: { cycles: MentorBudget; providerThreads: MentorBudget; variants: MentorBudget; interventions: MentorBudget; reusedEvaluations: MentorBudget; pendingEffects: number };
  safeguards: { providerThreadMode: string; recordAllVariants: boolean; workerHoldoutAccess: false; requireNoPendingEffects: boolean; configuredReplaySafe: boolean; replayAuthorization: 'not_authorized' };
  gates: { futureWake: GateState; profileBinding: GateState; stopPropagation: GateState; modelTurn: GateState; journalCyclePostcondition: GateState; noDuplicateDispatch: GateState };
  evaluation: { attemptLedgerPreserved: boolean; baseline: EvaluationState; ablation: EvaluationState; holdout: EvaluationState; promotion: EvaluationState };
  resilience: ResilienceEvidence;
  runtimeAcceptance: { execution: 'pending' | 'running' | 'passed' | 'partial' | 'failed' | 'unverified'; acceptance: 'pending' | 'passed' | 'partial' | 'failed' | 'unverified'; modelTurn: 'completed' | 'started' | 'not_started' | 'unknown'; email: 'pending' | 'verified' | 'failed' | 'unknown' };
  recoveryTimeline: Array<{ event: 'scheduled' | 'attempt_started' | 'dispatch_failed' | 'operator_reconciled'; status: 'recorded' | 'failed' | 'resolved'; at: string }>;
}
export interface MentorBudget { used: number; limit: number }
export interface MentorJob extends SchedulerJobBase { jobType: 'mentor'; mentor: MentorTruth | { status: 'unavailable' } }
export type SchedulerJob = StandardJob | MentorJob;
export interface SchedulerData {
  generatedAt: string; status: 'ok' | 'partial'; projectionState?: 'stale';
  health: { state: 'healthy' | 'stale' | 'unavailable'; heartbeatAt: string | null; watchdogHealthy: boolean | null };
  providerSafety: ProviderSafetySummary; jobs: SchedulerJob[]; warnings: Array<{ jobId?: string; code: string }>;
}
