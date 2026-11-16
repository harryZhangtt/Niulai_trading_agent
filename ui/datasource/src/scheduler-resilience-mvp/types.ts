export type EvidenceAvailability = 'recorded' | 'not-recorded' | 'unavailable' | 'unknown';

export type EvidenceSeverity = 'neutral' | 'positive' | 'info' | 'warning' | 'critical';

export interface EvidenceValue {
  readonly text: string;
  readonly availability: EvidenceAvailability;
  readonly severity: EvidenceSeverity;
}

export interface ResilienceEvidence {
  readonly snapshot: {
    readonly generatedAt: EvidenceValue;
    readonly status: EvidenceValue;
    readonly projectionFreshness: EvidenceValue;
  };
  readonly activeWork: {
    readonly schedulerStatus: EvidenceValue;
    readonly schedulerAttempts: EvidenceValue;
    readonly providerLatestPhase: EvidenceValue;
    readonly providerLatestStatus: EvidenceValue;
  };
  readonly recovery: {
    readonly mentorCycles: EvidenceValue;
    readonly noProgressCycles: EvidenceValue;
    readonly noProgressLimit: EvidenceValue;
    readonly repeatedCycles: EvidenceValue;
    readonly repeatedLimit: EvidenceValue;
    readonly evidenceReset: EvidenceValue;
    readonly retryDelay: EvidenceValue;
    readonly retrySource: EvidenceValue;
    readonly unknownFence: EvidenceValue;
    readonly replayAuthorization: EvidenceValue;
  };
  readonly hostTiming: {
    readonly heartbeatAge: EvidenceValue;
    readonly watchdog: EvidenceValue;
    readonly lastTick: EvidenceValue;
    readonly catchUp: EvidenceValue;
  };
}

/**
 * Reduced, read-only projection accepted by the adapter. Names remain snake_case
 * to match scheduler evidence. Every value is unknown until runtime-narrowed.
 */
export interface ResilienceEvidenceWire {
  readonly generated_at?: unknown;
  readonly status?: unknown;
  readonly projection_state?: unknown;
  readonly scheduler?: {
    readonly status?: unknown;
    readonly attempts?: unknown;
  } | null;
  readonly provider_safety?: {
    readonly latest_attempt?: {
      readonly phase?: unknown;
      readonly status?: unknown;
    } | null;
    readonly delayed_until?: unknown;
    readonly delay_source?: unknown;
    readonly unknown_fence?: unknown;
    readonly replay_authorization?: unknown;
  } | null;
  readonly mentor?: {
    readonly cycles?: unknown;
    readonly no_progress?: {
      readonly used?: unknown;
      readonly limit?: unknown;
    } | null;
    readonly repeated?: {
      readonly used?: unknown;
      readonly limit?: unknown;
    } | null;
    readonly evidence_reset?: unknown;
  } | null;
  readonly health?: {
    readonly heartbeat_age_seconds?: unknown;
    readonly watchdog_healthy?: unknown;
    readonly last_tick_at?: unknown;
    readonly catch_up?: unknown;
  } | null;
}

export interface ResiliencePanelProps {
  readonly evidence: ResilienceEvidence;
  readonly zone: string;
  readonly stale: boolean;
  readonly refreshing: boolean;
  readonly partial: boolean;
}
