import type {
  EvidenceAvailability,
  EvidenceSeverity,
  EvidenceValue,
  ResilienceEvidence,
} from './types';

type Lookup =
  | { readonly kind: 'value'; readonly value: unknown }
  | { readonly kind: 'missing' }
  | { readonly kind: 'unavailable' };

const NOT_RECORDED: EvidenceValue = {
  text: 'Not recorded',
  availability: 'not-recorded',
  severity: 'neutral',
};

const UNAVAILABLE: EvidenceValue = {
  text: 'Unavailable',
  availability: 'unavailable',
  severity: 'neutral',
};

const UNKNOWN: EvidenceValue = {
  text: 'Unknown',
  availability: 'unknown',
  severity: 'neutral',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function lookup(root: unknown, path: readonly string[]): Lookup {
  if (!isRecord(root)) return { kind: 'unavailable' };

  let cursor: unknown = root;
  for (const key of path) {
    if (!isRecord(cursor)) return { kind: 'unavailable' };
    if (!Object.prototype.hasOwnProperty.call(cursor, key)) return { kind: 'missing' };
    cursor = cursor[key];
  }

  return cursor === null || cursor === undefined
    ? { kind: 'unavailable' }
    : { kind: 'value', value: cursor };
}

function fallback(result: Lookup): EvidenceValue | null {
  if (result.kind === 'missing') return NOT_RECORDED;
  if (result.kind === 'unavailable') return UNAVAILABLE;
  return null;
}

function recorded(text: string, severity: EvidenceSeverity = 'neutral'): EvidenceValue {
  return { text, availability: 'recorded', severity };
}

function textValue(root: unknown, path: readonly string[]): EvidenceValue {
  const result = lookup(root, path);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  if (result.kind !== 'value' || typeof result.value !== 'string') return UNAVAILABLE;

  const text = result.value.trim();
  if (!text) return UNAVAILABLE;
  if (text.toLowerCase() === 'unknown') return UNKNOWN;
  if (text.toLowerCase() === 'unavailable') return UNAVAILABLE;
  return recorded(text.replaceAll('_', ' '));
}

function nullableTextValue(root: unknown, path: readonly string[], noneText: string): EvidenceValue {
  if (!isRecord(root)) return UNAVAILABLE;
  let cursor: unknown = root;
  for (const key of path) {
    if (!isRecord(cursor)) return UNAVAILABLE;
    if (!Object.prototype.hasOwnProperty.call(cursor, key)) return NOT_RECORDED;
    cursor = cursor[key];
  }
  if (cursor === null) return recorded(noneText);
  if (typeof cursor !== 'string' || !cursor.trim()) return UNAVAILABLE;
  return recorded(cursor.trim().replaceAll('_', ' '));
}

function finiteNumber(result: Lookup): number | null {
  return result.kind === 'value'
    && typeof result.value === 'number'
    && Number.isFinite(result.value)
    && result.value >= 0
    ? result.value
    : null;
}

function finiteCount(result: Lookup): number | null {
  return result.kind === 'value'
    && typeof result.value === 'number'
    && Number.isSafeInteger(result.value)
    && result.value >= 0
    ? result.value
    : null;
}

function numberValue(
  root: unknown,
  path: readonly string[],
  suffix = '',
  severity: EvidenceSeverity = 'neutral',
): EvidenceValue {
  const result = lookup(root, path);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  const value = finiteNumber(result);
  return value === null ? UNAVAILABLE : recorded(`${value}${suffix}`, severity);
}

function countValue(
  root: unknown,
  path: readonly string[],
  severity: EvidenceSeverity = 'neutral',
): EvidenceValue {
  const result = lookup(root, path);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  const value = finiteCount(result);
  return value === null ? UNAVAILABLE : recorded(`${value}`, severity);
}

function booleanValue(
  root: unknown,
  path: readonly string[],
  trueText: string,
  falseText: string,
  trueSeverity: EvidenceSeverity = 'neutral',
  falseSeverity: EvidenceSeverity = 'neutral',
): EvidenceValue {
  const result = lookup(root, path);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  if (result.kind !== 'value' || typeof result.value !== 'boolean') return UNAVAILABLE;
  return recorded(result.value ? trueText : falseText, result.value ? trueSeverity : falseSeverity);
}

function projectionValue(root: unknown): EvidenceValue {
  const result = lookup(root, ['projection_state']);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  if (result.kind !== 'value' || typeof result.value !== 'string') return UNAVAILABLE;

  const state = result.value.trim().toLowerCase();
  if (state === 'stale') return recorded('Stale', 'warning');
  if (state === 'current') return recorded('Current', 'positive');
  if (state === 'unknown') return UNKNOWN;
  return UNAVAILABLE;
}

function replayAuthorizationValue(root: unknown): EvidenceValue {
  const result = lookup(root, ['provider_safety', 'replay_authorization']);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  if (result.kind !== 'value' || typeof result.value !== 'string') return UNAVAILABLE;
  const state = result.value.trim().toLowerCase();
  if (state === 'unknown') return UNKNOWN;
  if (state === 'reconciliation_required') return recorded('reconciliation required', 'critical');
  if (state === 'not_authorized') return recorded('not authorized', 'warning');
  if (state === 'authorized') return recorded('authorized', 'positive');
  if (state === 'not_applicable') return recorded('not applicable');
  return state ? recorded(state.replaceAll('_', ' ')) : UNAVAILABLE;
}

function noProgressSeverity(used: number | null, limit: number | null): EvidenceSeverity {
  if (used === null) return 'neutral';
  if (used === 0) return 'positive';
  if (limit !== null && limit > 0 && used >= limit) return 'critical';
  if (limit !== null && limit > 0 && used >= limit / 2) return 'warning';
  return 'info';
}

function repeatedSeverity(used: number | null, limit: number | null, evidenceReset: boolean | null): EvidenceSeverity {
  if (used === null) return 'neutral';
  if (evidenceReset === true) return 'positive';
  if (used === 0) return 'positive';
  if (limit !== null && limit > 0 && used >= limit) return 'critical';
  if (used >= 2) return 'warning';
  return 'info';
}

function countWithSeverity(
  root: unknown,
  path: readonly string[],
  severity: EvidenceSeverity,
): EvidenceValue {
  return countValue(root, path, severity);
}

function evidenceResetValue(root: unknown): EvidenceValue {
  const result = lookup(root, ['mentor', 'evidence_reset']);
  const unavailable = fallback(result);
  if (unavailable) return unavailable;
  if (result.kind !== 'value' || typeof result.value !== 'boolean') return UNAVAILABLE;
  return recorded(result.value ? 'Reset recorded' : 'No reset recorded', result.value ? 'positive' : 'neutral');
}

function lookupBoolean(root: unknown, path: readonly string[]): boolean | null {
  const result = lookup(root, path);
  return result.kind === 'value' && typeof result.value === 'boolean' ? result.value : null;
}

/** Pure, total conversion from untrusted reduced wire evidence to render-safe UI evidence. */
export function adaptResilience(wire: unknown): ResilienceEvidence {
  const noProgressUsed = finiteCount(lookup(wire, ['mentor', 'no_progress', 'used']));
  const noProgressLimit = finiteCount(lookup(wire, ['mentor', 'no_progress', 'limit']));
  const repeatedUsed = finiteCount(lookup(wire, ['mentor', 'repeated', 'used']));
  const repeatedLimit = finiteCount(lookup(wire, ['mentor', 'repeated', 'limit']));
  const evidenceReset = lookupBoolean(wire, ['mentor', 'evidence_reset']);

  return {
    snapshot: {
      generatedAt: textValue(wire, ['generated_at']),
      status: textValue(wire, ['status']),
      projectionFreshness: projectionValue(wire),
    },
    activeWork: {
      schedulerStatus: textValue(wire, ['scheduler', 'status']),
      schedulerAttempts: countValue(wire, ['scheduler', 'attempts']),
      providerLatestPhase: textValue(wire, ['provider_safety', 'latest_attempt', 'phase']),
      providerLatestStatus: textValue(wire, ['provider_safety', 'latest_attempt', 'status']),
    },
    recovery: {
      mentorCycles: countValue(wire, ['mentor', 'cycles']),
      noProgressCycles: countWithSeverity(
        wire,
        ['mentor', 'no_progress', 'used'],
        noProgressSeverity(noProgressUsed, noProgressLimit),
      ),
      noProgressLimit: countValue(wire, ['mentor', 'no_progress', 'limit']),
      repeatedCycles: countWithSeverity(
        wire,
        ['mentor', 'repeated', 'used'],
        repeatedSeverity(repeatedUsed, repeatedLimit, evidenceReset),
      ),
      repeatedLimit: countValue(wire, ['mentor', 'repeated', 'limit']),
      evidenceReset: evidenceResetValue(wire),
      retryDelay: nullableTextValue(wire, ['provider_safety', 'delayed_until'], 'No retry scheduled'),
      retrySource: nullableTextValue(wire, ['provider_safety', 'delay_source'], 'No retry source'),
      unknownFence: booleanValue(
        wire,
        ['provider_safety', 'unknown_fence'],
        'Outcome unknown; replay fenced',
        'No unknown fence recorded',
        'critical',
        'positive',
      ),
      replayAuthorization: replayAuthorizationValue(wire),
    },
    hostTiming: {
      heartbeatAge: numberValue(wire, ['health', 'heartbeat_age_seconds'], ' s'),
      watchdog: booleanValue(wire, ['health', 'watchdog_healthy'], 'Healthy', 'Unhealthy'),
      lastTick: textValue(wire, ['health', 'last_tick_at']),
      catchUp: textValue(wire, ['health', 'catch_up']),
    },
  };
}

export function evidenceAvailabilityLabel(availability: EvidenceAvailability): string {
  switch (availability) {
    case 'recorded': return 'Recorded';
    case 'not-recorded': return 'Not recorded';
    case 'unavailable': return 'Unavailable';
    case 'unknown': return 'Unknown';
  }
}
