import type {
  InformationYieldFailureWire,
  InformationYieldGateCaseResultWire,
  InformationYieldGateDiagnosticWire,
  InformationYieldTopFailureWire,
  InformationYieldTraceWire,
  InformationYieldWireResponse,
} from '../../types/informationYieldApi';
import type {
  InformationYieldArm,
  InformationYieldCase,
  InformationYieldGate,
  InformationYieldMetric,
  InformationYieldObservation,
  InformationYieldViewModel,
} from '../viewModels';

const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const SHA = /^[a-f0-9]{64}$/;
const TOP_LEVEL_KEYS = ['schema_version', 'view', 'evaluation_id', 'registry_sha256', 'result_sha256', 'verdict', 'counts', 'evidence', 'outcomes', 'policy_gates', 'hard_failures', 'cases', 'selection', 'case', 'selected_arm', 'projection_state', 'read_only'] as const;
const CASE_RESULT_KEYS = ['B0', 'F', 'arm', 'case_id', 'chain_ids', 'code', 'complete', 'count', 'credited', 'delta', 'delta_d', 'delta_r', 'issuer_id', 'matched', 'mean', 'metadata_known', 'pooled', 'ratio', 'reviewed', 'status', 'unjudged'] as const;

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function exact(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function allowed(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).every(key => keys.includes(key));
}
function identifier(value: unknown): string | null {
  return typeof value === 'string' && ID.test(value) ? value : null;
}
function sha256(value: unknown): string | null {
  return typeof value === 'string' && SHA.test(value) ? value : null;
}
function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}
function integer(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
function nullableFinite(value: unknown): number | null | undefined {
  if (value === null) return null;
  const parsed = finite(value);
  return parsed === null ? undefined : parsed;
}
function nullableInteger(value: unknown): number | null | undefined {
  if (value === null) return null;
  const parsed = integer(value);
  return parsed === null ? undefined : parsed;
}
function identifierArray(value: unknown, maximum = 128): string[] | null {
  if (!Array.isArray(value) || value.length > maximum) return null;
  const parsed = value.map(identifier);
  return parsed.some(item => item === null) ? null : parsed as string[];
}
function shaArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > 128) return null;
  const parsed = value.map(sha256);
  return parsed.some(item => item === null) ? null : parsed as string[];
}
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  const object = record(value);
  return object ? Object.fromEntries(Object.keys(object).sort().map(key => [key, canonical(object[key])])) : value;
}
function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

function observation(value: unknown): InformationYieldObservation | null {
  const object = record(value);
  if (!object) return null;
  if (exact(object, ['state', 'value', 'unit']) && object.state === 'known') {
    const parsedValue = finite(object.value);
    const unit = identifier(object.unit);
    return parsedValue !== null && unit ? { state: 'known', value: parsedValue, unit } : null;
  }
  if (exact(object, ['state', 'reason_code']) && (object.state === 'unavailable' || object.state === 'not_applicable')) {
    const reasonCode = identifier(object.reason_code);
    return reasonCode ? { state: object.state, reasonCode } : null;
  }
  return null;
}

function trace(value: unknown): InformationYieldTraceWire | null {
  const object = record(value);
  const keys = ['complete', 'credited', 'reviewed_complete', 'pooled_total', 'rejected', 'unjudged'] as const;
  if (!object || !exact(object, keys)) return null;
  const parsed = Object.fromEntries(keys.map(key => [key, nullableInteger(object[key])])) as Record<(typeof keys)[number], number | null | undefined>;
  return keys.some(key => parsed[key] === undefined) ? null : parsed as InformationYieldTraceWire;
}

function arm(value: unknown): InformationYieldArm | null {
  const object = record(value);
  const keys = ['richness', 'depth', 'precision', 'wall_seconds', 'lineages', 'critical_unsupported', 'trace'] as const;
  if (!object || !exact(object, keys)) return null;
  const richness = observation(object.richness);
  const depth = observation(object.depth);
  const precision = observation(object.precision);
  const wallSeconds = observation(object.wall_seconds);
  const lineages = observation(object.lineages);
  const criticalUnsupported = observation(object.critical_unsupported);
  const parsedTrace = trace(object.trace);
  return richness && depth && precision && wallSeconds && lineages && criticalUnsupported && parsedTrace
    ? { richness, depth, precision, wallSeconds, lineages, criticalUnsupported, trace: JSON.stringify(parsedTrace) }
    : null;
}

function failure(value: unknown, topLevel: false): InformationYieldFailureWire | null;
function failure(value: unknown, topLevel: true): InformationYieldTopFailureWire | null;
function failure(value: unknown, topLevel: boolean): InformationYieldFailureWire | InformationYieldTopFailureWire | null {
  const object = record(value);
  const keys = topLevel ? ['case_id', 'code', 'chain_ids'] : ['code', 'chain_ids'];
  if (!object || !exact(object, keys)) return null;
  const code = identifier(object.code);
  const chainIds = shaArray(object.chain_ids);
  if (!code || !chainIds || chainIds.length === 0 || new Set(chainIds).size !== chainIds.length) return null;
  if (!topLevel) return { code, chain_ids: chainIds };
  const caseId = identifier(object.case_id);
  return caseId ? { case_id: caseId, code, chain_ids: chainIds } : null;
}

function metric(value: unknown): InformationYieldMetric | null {
  const object = record(value);
  const observationKeys = ['mean', 'median', 'minimum', 'maximum', 'range', 'total'] as const;
  const keys = [...observationKeys, 'denominator', 'wins', 'ties', 'losses', 'leave_one_issuer_out'] as const;
  if (!object || !exact(object, keys)) return null;
  const values = Object.fromEntries(observationKeys.map(key => [key, observation(object[key])])) as Record<(typeof observationKeys)[number], InformationYieldObservation | null>;
  if (observationKeys.some(key => values[key] === null)) return null;
  const denominator = integer(object.denominator);
  const wins = integer(object.wins);
  const ties = integer(object.ties);
  const losses = integer(object.losses);
  if (denominator === null || wins === null || ties === null || losses === null || wins + ties + losses !== denominator) return null;
  if (!Array.isArray(object.leave_one_issuer_out) || object.leave_one_issuer_out.length > 64) return null;
  const leaveOneIssuerOut: InformationYieldMetric['leaveOneIssuerOut'] = [];
  for (const item of object.leave_one_issuer_out) {
    const row = record(item);
    if (!row || !exact(row, ['issuer_id', 'mean'])) return null;
    const issuerId = identifier(row.issuer_id);
    const mean = nullableFinite(row.mean);
    if (!issuerId || mean === undefined) return null;
    leaveOneIssuerOut.push({ issuerId, mean });
  }
  return {
    mean: values.mean!, median: values.median!, minimum: values.minimum!, maximum: values.maximum!, range: values.range!, total: values.total!,
    denominator, wins, ties, losses, leaveOneIssuerOut,
  };
}

function gateCaseResult(value: unknown): InformationYieldGateCaseResultWire | null {
  const object = record(value);
  if (!object || !allowed(object, CASE_RESULT_KEYS)) return null;
  const output: InformationYieldGateCaseResultWire = {};
  for (const [key, raw] of Object.entries(object)) {
    if (key === 'B0' || key === 'F' || ['delta', 'delta_d', 'delta_r', 'mean', 'ratio'].includes(key)) {
      const parsed = nullableFinite(raw);
      if (parsed === undefined) return null;
      Object.assign(output, { [key]: parsed });
    } else if (['complete', 'credited', 'pooled', 'reviewed', 'unjudged'].includes(key)) {
      const parsed = nullableInteger(raw);
      if (parsed === undefined) return null;
      Object.assign(output, { [key]: parsed });
    } else if (key === 'count') {
      const parsed = integer(raw);
      if (parsed === null) return null;
      output.count = parsed;
    } else if (key === 'arm') {
      if (raw !== 'B0' && raw !== 'F') return null;
      output.arm = raw;
    } else if (key === 'case_id' || key === 'code' || key === 'issuer_id') {
      const parsed = identifier(raw);
      if (!parsed) return null;
      Object.assign(output, { [key]: parsed });
    } else if (key === 'chain_ids') {
      const parsed = shaArray(raw);
      if (!parsed) return null;
      output.chain_ids = parsed;
    } else if (key === 'matched' || key === 'metadata_known') {
      if (typeof raw !== 'boolean') return null;
      Object.assign(output, { [key]: raw });
    } else if (key === 'status') {
      if (!['pass', 'fail', 'unknown', 'not_applicable'].includes(String(raw))) return null;
      output.status = raw as InformationYieldGateCaseResultWire['status'];
    } else return null;
  }
  return output;
}

function orders(value: unknown): { B0_first: number; F_first: number } | null {
  const object = record(value);
  if (!object || !exact(object, ['B0_first', 'F_first'])) return null;
  const b0 = integer(object.B0_first);
  const f = integer(object.F_first);
  return b0 !== null && f !== null ? { B0_first: b0, F_first: f } : null;
}

function diagnostic(value: unknown): InformationYieldGateDiagnosticWire | undefined {
  if (value === null || typeof value === 'boolean') return value;
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined;
  if (typeof value === 'string') return value.length <= 256 ? value : undefined;
  if (Array.isArray(value)) {
    if (value.length > 128) return undefined;
    const parsed: Array<string | number | boolean | null | InformationYieldGateCaseResultWire> = [];
    for (const item of value) {
      if (item === null || typeof item === 'boolean') parsed.push(item);
      else if (typeof item === 'number' && Number.isFinite(item)) parsed.push(item);
      else if (typeof item === 'string' && item.length <= 256) parsed.push(item);
      else {
        const result = gateCaseResult(item);
        if (!result) return undefined;
        parsed.push(result);
      }
    }
    return parsed;
  }
  const object = record(value);
  if (!object) return undefined;
  if (exact(object, ['count', 'distinct', 'orders'])) {
    const count = integer(object.count);
    const parsedOrders = orders(object.orders);
    return count !== null && typeof object.distinct === 'boolean' && parsedOrders ? { count, distinct: object.distinct, orders: parsedOrders } : undefined;
  }
  if (exact(object, ['count', 'orders'])) {
    const count = integer(object.count);
    const parsedOrders = orders(object.orders);
    return count !== null && parsedOrders ? { count, orders: parsedOrders } : undefined;
  }
  if (exact(object, ['aggregate', 'case'])) {
    const aggregate = finite(object.aggregate);
    const caseValue = finite(object.case);
    return aggregate !== null && caseValue !== null ? { aggregate, case: caseValue } : undefined;
  }
  return undefined;
}

function diagnosticText(value: InformationYieldGateDiagnosticWire): string {
  return typeof value === 'string' ? value : JSON.stringify(value);
}

function pair(value: unknown): number | null | [number, number] | undefined {
  if (value === null) return null;
  const scalar = finite(value);
  if (scalar !== null) return scalar;
  if (!Array.isArray(value) || value.length !== 2) return undefined;
  const left = finite(value[0]);
  const right = finite(value[1]);
  return left !== null && right !== null ? [left, right] : undefined;
}

function gate(value: unknown): InformationYieldGate | null {
  const object = record(value);
  const keys = ['name', 'status', 'observed', 'threshold', 'numerator', 'denominator', 'case_results', 'reason_codes'] as const;
  if (!object || !exact(object, keys)) return null;
  const name = identifier(object.name);
  if (!name || !['pass', 'fail', 'unknown', 'not_applicable'].includes(String(object.status))) return null;
  const observed = diagnostic(object.observed);
  const threshold = diagnostic(object.threshold);
  const numerator = pair(object.numerator);
  const denominator = pair(object.denominator);
  if (observed === undefined || threshold === undefined || numerator === undefined || denominator === undefined) return null;
  if (!Array.isArray(object.case_results) || object.case_results.length > 128) return null;
  for (const item of object.case_results) {
    if (typeof item === 'string') {
      if (!identifier(item)) return null;
    } else if (!gateCaseResult(item)) return null;
  }
  const reasonCodes = identifierArray(object.reason_codes, 16);
  return reasonCodes ? { name, status: object.status as InformationYieldGate['status'], observed: diagnosticText(observed), threshold: diagnosticText(threshold), reasonCodes } : null;
}

function caseRow(value: unknown): InformationYieldCase | null {
  const object = record(value);
  const keys = ['case_id', 'issuer_id', 'subject', 'window_id', 'evidence_level', 'split', 'arm_order', 'request_sha256', 'fact_sha256', 'delta_r', 'delta_d', 'lineage_delta', 'arms', 'hard_failures'] as const;
  if (!object || !exact(object, keys)) return null;
  const caseId = identifier(object.case_id);
  const issuerId = identifier(object.issuer_id);
  const subject = identifier(object.subject);
  const windowId = identifier(object.window_id);
  const requestSha256 = sha256(object.request_sha256);
  const factSha256 = sha256(object.fact_sha256);
  const deltaRichness = observation(object.delta_r);
  const deltaDepth = observation(object.delta_d);
  const lineageDelta = observation(object.lineage_delta);
  if (!caseId || !issuerId || !subject || !windowId || !requestSha256 || !factSha256 || !deltaRichness || !deltaDepth || !lineageDelta) return null;
  if (object.evidence_level !== 'confirmation' && object.evidence_level !== 'development') return null;
  if (object.split !== 'untouched' && object.split !== 'development') return null;
  if (!Array.isArray(object.arm_order) || object.arm_order.length !== 2 || !object.arm_order.every(item => item === 'B0' || item === 'F') || new Set(object.arm_order).size !== 2) return null;
  const armsObject = record(object.arms);
  if (!armsObject || !exact(armsObject, ['B0', 'F'])) return null;
  const b0 = arm(armsObject.B0);
  const f = arm(armsObject.F);
  if (!b0 || !f || !Array.isArray(object.hard_failures) || object.hard_failures.length > 128) return null;
  const hardFailures: InformationYieldCase['hardFailures'] = [];
  const failureKeys = new Set<string>();
  for (const item of object.hard_failures) {
    const parsed = failure(item, false);
    if (!parsed) return null;
    const key = JSON.stringify([parsed.code, [...parsed.chain_ids].sort()]);
    if (failureKeys.has(key)) return null;
    failureKeys.add(key);
    hardFailures.push({ code: parsed.code, chainIds: parsed.chain_ids });
  }
  const armOrder: ['B0', 'F'] | ['F', 'B0'] = object.arm_order[0] === 'B0' ? ['B0', 'F'] : ['F', 'B0'];
  return {
    id: caseId,
    issuerId,
    subject,
    windowId,
    evidenceLevel: object.evidence_level,
    split: object.split,
    armOrder,
    requestSha256,
    factSha256,
    deltaRichness,
    deltaDepth,
    lineageDelta,
    arms: { B0: b0, F: f },
    hardFailures,
  };
}

export interface ExpectedInformationYieldSelection {
  evaluation: string;
  caseId: string | null;
  arm: 'B0' | 'F' | null;
  run: string | null;
  source: string | null;
}

export function adaptInformationYield(value: unknown, expected: ExpectedInformationYieldSelection): InformationYieldViewModel | null {
  const object = record(value);
  if (!object || !exact(object, TOP_LEVEL_KEYS)) return null;
  if (object.schema_version !== 1 || object.read_only !== true || (object.view !== 'summary' && object.view !== 'detail')) return null;
  if (object.evaluation_id !== expected.evaluation || !['pass', 'reject', 'inconclusive'].includes(String(object.verdict))) return null;
  const resultSha256 = sha256(object.result_sha256);
  const registrySha256 = sha256(object.registry_sha256);
  if (!resultSha256 || !registrySha256 || (object.projection_state !== 'fresh' && object.projection_state !== 'stale')) return null;

  const counts = record(object.counts);
  if (!counts || !exact(counts, ['planned', 'confirmation', 'development'])) return null;
  const planned = integer(counts.planned);
  const confirmation = integer(counts.confirmation);
  const development = integer(counts.development);
  if (planned === null || confirmation === null || development === null || confirmation + development !== planned) return null;

  const evidence = record(object.evidence);
  const evidenceKeys = ['context_sha256', 'fact_set_sha256', 'policy_sha256', 'source_closure_sha256', 'summary_sha256', 'claim_limits'] as const;
  if (!evidence || !exact(evidence, evidenceKeys)) return null;
  const hashes = evidenceKeys.slice(0, 5).map(key => sha256(evidence[key]));
  const claimLimits = identifierArray(evidence.claim_limits, 128);
  if (hashes.some(hash => hash === null) || !claimLimits) return null;

  const outcomes = record(object.outcomes);
  if (!outcomes || !exact(outcomes, ['richness', 'depth'])) return null;
  const richness = metric(outcomes.richness);
  const depth = metric(outcomes.depth);
  if (!richness || !depth) return null;

  if (!Array.isArray(object.policy_gates) || object.policy_gates.length > 64) return null;
  const gates = object.policy_gates.map(gate);
  if (gates.some(item => item === null)) return null;

  if (!Array.isArray(object.cases) || object.cases.length > 64) return null;
  const cases = object.cases.map(caseRow);
  if (cases.some(item => item === null) || new Set(cases.map(item => item!.id)).size !== cases.length) return null;

  const selectedCase = object.case === null ? null : caseRow(object.case);
  const selectedArm = object.selected_arm === null ? null : arm(object.selected_arm);
  if (object.case !== null && !selectedCase || object.selected_arm !== null && !selectedArm) return null;

  const selection = record(object.selection);
  if (!selection || !exact(selection, ['case_id', 'arm', 'run', 'source'])) return null;
  const caseId = selection.case_id === null ? null : identifier(selection.case_id);
  const selectedArmId = selection.arm === null ? null : selection.arm;
  const run = selection.run === null ? null : identifier(selection.run);
  const source = selection.source === null ? null : identifier(selection.source);
  if (caseId === null && selection.case_id !== null || selectedArmId !== null && selectedArmId !== 'B0' && selectedArmId !== 'F' || run === null && selection.run !== null || source === null && selection.source !== null) return null;
  if (caseId !== expected.caseId || selectedArmId !== expected.arm || run !== expected.run || source !== expected.source) return null;
  if (object.view !== (expected.caseId === null ? 'summary' : 'detail')) return null;
  if (object.view === 'detail' && (!selectedCase || selectedCase.id !== expected.caseId) || object.view === 'summary' && selectedCase) return null;
  if (expected.arm === null && selectedArm !== null || expected.arm !== null && (!selectedArm || !selectedCase || !same(selectedArm, selectedCase.arms[expected.arm]))) return null;

  const visibleCases = object.view === 'summary' ? cases : selectedCase ? [selectedCase] : [];
  const expectedFailures: InformationYieldViewModel['hardFailures'] = [];
  const expectedFailureKeys = new Set<string>();
  for (const item of visibleCases) {
    for (const itemFailure of item!.hardFailures) {
      const row = { caseId: item!.id, code: itemFailure.code, chainIds: [...itemFailure.chainIds].sort() };
      const key = JSON.stringify(row);
      if (expectedFailureKeys.has(key)) return null;
      expectedFailureKeys.add(key);
      expectedFailures.push(row);
    }
  }
  expectedFailures.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));

  if (!Array.isArray(object.hard_failures) || object.hard_failures.length > 128) return null;
  const failures: InformationYieldViewModel['hardFailures'] = [];
  const failureKeys = new Set<string>();
  for (const item of object.hard_failures) {
    const parsed = failure(item, true);
    if (!parsed) return null;
    const row = { caseId: parsed.case_id, code: parsed.code, chainIds: [...parsed.chain_ids].sort() };
    const key = JSON.stringify(row);
    if (failureKeys.has(key)) return null;
    failureKeys.add(key);
    failures.push(row);
  }
  failures.sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  if (!same(failures, expectedFailures) || failures.length > 0 && object.verdict !== 'reject') return null;

  const wire = object as unknown as InformationYieldWireResponse;
  return {
    view: wire.view,
    evaluationId: expected.evaluation,
    resultSha256,
    registrySha256,
    stale: wire.projection_state === 'stale',
    verdict: wire.verdict,
    counts: { planned, confirmation, development },
    evidence: {
      contextSha256: hashes[0]!,
      factSetSha256: hashes[1]!,
      policySha256: hashes[2]!,
      sourceClosureSha256: hashes[3]!,
      summarySha256: hashes[4]!,
      claimLimits,
    },
    outcomes: { richness, depth },
    gates: gates as InformationYieldGate[],
    hardFailures: failures,
    cases: cases as InformationYieldCase[],
    selectedCase,
    selectedArm,
    selection: { caseId, arm: selectedArmId as 'B0' | 'F' | null, run, source },
  };
}
