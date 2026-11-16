export type SchedulerWireProviderFailure =
  | 'none' | 'timeout' | 'connection_reset' | 'connection' | 'partial_response' | 'missing_terminal'
  | 'http' | 'auth' | 'config' | 'model' | 'policy' | 'local_config' | 'provider' | 'unknown';

export interface SchedulerWireProviderSafetySummary {
  status: 'not_applicable' | 'available' | 'partial' | 'unavailable';
  jobs: number;
  available_jobs: number;
  unknown_fences: number;
  delayed_jobs: number;
  queue_depth: number;
  circuits: { closed: number; open: number; half_open: number; unavailable: number };
}

export type SchedulerWireProviderSafety = { status: 'unavailable' } | {
  status: 'available';
  provider: 'codex_cli' | 'claude_host';
  latest_attempt: null | {
    phase: 'not_started' | 'connecting' | 'submitted' | 'streaming' | 'terminal' | 'unavailable';
    submission: 'not_submitted' | 'definitely_submitted' | 'possibly_submitted' | 'unavailable';
    terminal_proof: 'verified' | 'absent' | 'contradictory' | 'unavailable';
    status: 'running' | 'succeeded' | 'retryable' | 'failed' | 'unknown';
    failure: SchedulerWireProviderFailure | 'unavailable';
  };
  delayed_until: string | null;
  delay_source: 'retry_after' | 'backoff' | 'circuit' | null;
  retry_reason: 'PROVIDER_SUCCEEDED' | 'PROVIDER_OUTCOME_UNKNOWN' | 'PROVIDER_TERMINAL_FAILURE' | 'PERMANENT_LOCAL_FAILURE'
    | 'PROVIDER_RETRY_DENIED' | 'REPLAY_AUTHORITY_ABSENT' | 'HTTP_STATUS_NOT_RETRYABLE' | 'ATTEMPTS_EXHAUSTED'
    | 'PROVIDER_WAIT_INVALID' | 'PROVIDER_WAIT_EXCEEDS_MAX' | 'RETRY_DEADLINE_EXCEEDED' | 'RETRY_SCHEDULED'
    | 'PROCESS_EXITED_OUTCOME_UNKNOWN' | 'RECONCILIATION_ABSENT_RETRY' | null;
  replay_authorization: 'authorized' | 'reconciliation_required' | 'not_authorized' | 'not_applicable' | 'unavailable';
  circuit: { state: 'closed' | 'open' | 'half_open' | 'unavailable'; open_until: string | null; probe_until: string | null; probe_eligible: boolean };
  unknown_fence: boolean;
  queue: { depth: number; oldest_delayed_at: string | null };
};

export interface SchedulerWirePacket {
  schema_version: 1;
  generated_at: string;
  read_only: true;
  scope: 'local_codex_scheduler';
  status: 'ok' | 'partial';
  projection_state?: 'stale';
  health: { state: 'healthy' | 'stale' | 'unavailable'; heartbeat_at: string | null; watchdog_healthy: boolean | null };
  provider_safety: SchedulerWireProviderSafetySummary;
  jobs: unknown[];
  warnings: Array<{ job_id?: string; code: string }>;
}

export interface SchedulerWireResilience {
  generated_at: string;
  status: 'ok' | 'partial';
  projection_state: 'current' | 'stale' | 'unknown';
  scheduler: {
    status: 'ready' | 'running' | 'retry_wait' | 'succeeded' | 'failed' | 'unknown' | 'missed' | 'coalesced';
    attempts: number;
  };
  provider_safety: {
    latest_attempt: null | {
      phase: 'not_started' | 'connecting' | 'submitted' | 'streaming' | 'terminal' | 'unavailable';
      status: 'running' | 'succeeded' | 'retryable' | 'failed' | 'unknown';
    };
    delayed_until: string | null;
    delay_source: 'retry_after' | 'backoff' | 'circuit' | null;
    unknown_fence: boolean;
    replay_authorization: 'authorized' | 'reconciliation_required' | 'not_authorized' | 'not_applicable' | 'unavailable';
  };
  mentor: {
    cycles: number;
    no_progress: { used: number; limit: number };
    repeated: { used: number; limit: number };
    evidence_reset: boolean;
  };
  health: {
    heartbeat_age_seconds: number | null;
    watchdog_healthy: boolean | null;
  };
}

export interface SchedulerWireMentor {
  work_order: {
    id: string;
    logical_session_id: string;
    starts_at: string;
    ends_at: string;
    window_state: 'upcoming' | 'open' | 'expired';
    acceptance_criteria_total: number;
    required_event_kinds: string[];
  };
  scheduler: {
    status: 'ready' | 'running' | 'retry_wait' | 'succeeded' | 'failed' | 'unknown' | 'missed' | 'coalesced';
    code: string;
    attempts: number;
    dispatch: 'not_attempted' | 'definitely_not_dispatched' | 'possibly_dispatched' | 'confirmed_dispatched';
  };
  session: { status: 'active' | 'blocked_pending_effect' | 'completed' | 'failed' | 'cancelled'; revision: number };
  progress: {
    cycles: { used: number; limit: number };
    provider_threads: { used: number; limit: number };
    variants: { used: number; limit: number };
    interventions: { used: number; limit: number };
    reused_evaluations: { used: number; limit: number };
    pending_effects: number;
  };
  safeguards: {
    provider_thread_mode: string;
    record_all_variants: boolean;
    worker_holdout_access: false;
    require_no_pending_effects: boolean;
    configured_replay_safe: boolean;
    replay_authorization: 'not_authorized';
  };
  gates: {
    future_wake: 'verified' | 'failed' | 'not_verified';
    profile_binding: 'verified' | 'failed' | 'not_verified';
    stop_propagation: 'verified' | 'failed' | 'not_verified';
    model_turn: 'verified' | 'failed' | 'not_verified';
    journal_cycle_postcondition: 'verified' | 'failed' | 'not_verified';
    no_duplicate_dispatch: 'verified' | 'failed' | 'not_verified';
  };
  evaluation: {
    attempt_ledger_preserved: boolean;
    baseline: 'pending' | 'preserved' | 'not_required' | 'unverified' | 'inconclusive' | 'passed' | 'failed';
    ablation: 'pending' | 'preserved' | 'not_required' | 'unverified' | 'inconclusive' | 'passed' | 'failed';
    holdout: 'pending' | 'preserved' | 'not_required' | 'unverified' | 'inconclusive' | 'passed' | 'failed';
    promotion: 'pending' | 'preserved' | 'not_required' | 'unverified' | 'inconclusive' | 'passed' | 'failed';
  };
  resilience: SchedulerWireResilience;
  runtime_acceptance: {
    execution: 'pending' | 'running' | 'passed' | 'partial' | 'failed' | 'unverified';
    acceptance: 'pending' | 'passed' | 'partial' | 'failed' | 'unverified';
    model_turn: 'completed' | 'started' | 'not_started' | 'unknown';
    email: 'pending' | 'verified' | 'failed' | 'unknown';
  };
  recovery_timeline: Array<{ event: 'scheduled' | 'attempt_started' | 'dispatch_failed' | 'operator_reconciled'; status: 'recorded' | 'failed' | 'resolved'; at: string }>;
}

export interface SchedulerWireJob {
  id: string;
  title: string;
  description: string;
  enabled: boolean;
  schedule: unknown;
  next_run_at: string | null;
  replay_safe: boolean;
  model?: string;
  effort?: string;
  delivery: unknown;
  history: unknown[];
  outputs: unknown[];
  prompt_custody?: unknown;
  output?: unknown;
  job_type?: unknown;
  mentor?: SchedulerWireMentor | { status: 'unavailable' } | unknown;
  provider_safety?: SchedulerWireProviderSafety | unknown;
}
