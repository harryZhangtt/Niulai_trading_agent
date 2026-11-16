import type { ResilienceEvidenceWire } from './types';

export const completeEvidenceWire = {
  generated_at: '2030-02-03T04:05:06Z',
  status: 'partial',
  projection_state: 'stale',
  scheduler: { status: 'retry_wait', attempts: 2 },
  provider_safety: {
    latest_attempt: { phase: 'terminal', status: 'unknown' },
    delayed_until: '2030-02-03T04:10:00Z',
    delay_source: 'backoff',
    unknown_fence: true,
    replay_authorization: 'reconciliation_required',
  },
  mentor: {
    cycles: 4,
    no_progress: { used: 2, limit: 4 },
    repeated: { used: 2, limit: 3 },
    evidence_reset: false,
  },
  health: {
    heartbeat_age_seconds: 48,
    watchdog_healthy: true,
    last_tick_at: '2030-02-03T04:04:18Z',
    catch_up: 'coalesced',
  },
} satisfies ResilienceEvidenceWire;

export const resetEvidenceWire = {
  generated_at: '2030-02-03T04:05:06Z',
  status: 'ok',
  projection_state: 'current',
  scheduler: { status: 'ready', attempts: 0 },
  provider_safety: {
    latest_attempt: { phase: 'not_started', status: 'running' },
    unknown_fence: false,
    replay_authorization: 'not_applicable',
  },
  mentor: {
    cycles: 1,
    no_progress: { used: 0, limit: 4 },
    repeated: { used: 3, limit: 3 },
    evidence_reset: true,
  },
  health: {
    heartbeat_age_seconds: 0,
    watchdog_healthy: true,
  },
} satisfies ResilienceEvidenceWire;

export const missingEvidenceWire = {} satisfies ResilienceEvidenceWire;

export const unavailableEvidenceWire: ResilienceEvidenceWire | null = null;
