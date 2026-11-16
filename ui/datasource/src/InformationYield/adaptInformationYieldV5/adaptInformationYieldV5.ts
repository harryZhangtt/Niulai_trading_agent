import type { InformationYieldV5WireResponse } from '../../types/informationYieldApiV5';
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
const CANONICAL_POLICY_SHA256 = 'b25d0e9dd7fd5d1db6f95c1114a179d0963d2bc55b7ef839227364e300df887f';
const GATE_AUTHORITY_SHA256 = '558c4add60096842836aa67472731785f869897bc662dcd873b740b08de16878';
const PRIVATE_KEY = /(?:^|_)(?:raw(?:_result)?|payload|prompt|credentials?|auth(?:entication|orization)?|token|secret|private|path|quote|exception|password|api_?key|access_?key)(?:$|_)/i;
const TOP_KEYS = ['wire_version', 'publication', 'view', 'evaluation_id', 'index_sha256', 'custody_sha256', 'result_sha256', 'verdict', 'counts', 'evidence', 'outcomes', 'populations', 'policy_gates', 'hard_failures', 'cases', 'selection', 'case', 'selected_arm', 'projection_state', 'read_only'] as const;
const GATE_NAMES = ['confirmation_cohort', 'richness_mean', 'richness_positive_cases', 'depth_mean', 'depth_positive_cases', 'case_delta_floor', 'issuer_loo', 'precision_delta', 'arm_wall_limit', 'case_wall_ratio', 'aggregate_wall_ratio', 'complete_trace_ratio', 'complete_pooled_review', 'zero_critical_unsupported', 'lineage', 'execution_custody', 'zero_hard_failures', 'unknown_semantics'] as const;

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function exact(value: Record<string, unknown>, keys: readonly string[]) {
  return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
function identifier(value: unknown): string | null { return typeof value === 'string' && ID.test(value) ? value : null; }
function hash(value: unknown): string | null { return typeof value === 'string' && SHA.test(value) ? value : null; }
function integer(value: unknown): number | null { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null; }
function finite(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  const object = record(value);
  return object ? Object.fromEntries(Object.keys(object).sort().map(key => [key, canonical(object[key])])) : value;
}
function same(left: unknown, right: unknown) { return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right)); }
function publicValue(value: unknown, depth = 0): boolean {
  if (depth > 8) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return value.length <= 512;
  if (Array.isArray(value)) return value.length <= 256 && value.every(item => publicValue(item, depth + 1));
  const object = record(value);
  return Boolean(object) && Object.keys(object!).length <= 128 && Object.entries(object!).every(([key, item]) => !PRIVATE_KEY.test(key) && publicValue(item, depth + 1));
}
function identifierArray(value: unknown, maximum = 128): string[] | null {
  if (!Array.isArray(value) || value.length > maximum) return null;
  const parsed = value.map(identifier);
  return parsed.some(item => item === null) || new Set(parsed).size !== parsed.length ? null : parsed as string[];
}
function observation(value: unknown): InformationYieldObservation | null {
  const object = record(value);
  if (!object) return null;
  if (exact(object, ['state', 'value', 'unit']) && object.state === 'known') {
    const parsed = finite(object.value); const unit = identifier(object.unit);
    return parsed !== null && unit ? { state: 'known', value: parsed, unit } : null;
  }
  if (exact(object, ['state', 'reason_code']) && object.state === 'unavailable') {
    const reasonCode = identifier(object.reason_code);
    return reasonCode ? { state: 'unavailable', reasonCode } : null;
  }
  return null;
}
const unavailable = (reasonCode: string): InformationYieldObservation => ({ state: 'unavailable', reasonCode });
function nullableInteger(value: unknown): number | null | undefined {
  if (value === null) return null;
  const parsed = integer(value); return parsed === null ? undefined : parsed;
}
function arm(value: unknown): InformationYieldArm | null {
  const object = record(value);
  if (!object || !exact(object, ['richness', 'depth', 'precision', 'wall_seconds', 'trace'])) return null;
  const richness = observation(object.richness); const depth = observation(object.depth);
  const precision = observation(object.precision); const wallSeconds = observation(object.wall_seconds);
  const trace = record(object.trace);
  if (!richness || !depth || !precision || !wallSeconds || !trace || !exact(trace, ['complete', 'credited', 'unjudged'])) return null;
  const parsedTrace = { complete: nullableInteger(trace.complete), credited: nullableInteger(trace.credited), unjudged: nullableInteger(trace.unjudged) };
  if (Object.values(parsedTrace).some(item => item === undefined)) return null;
  return { richness, depth, precision, wallSeconds, lineages: unavailable('NOT_PROJECTED_V5'),
    criticalUnsupported: unavailable('NOT_PROJECTED_V5'), trace: JSON.stringify(parsedTrace) };
}
function metric(value: unknown): InformationYieldMetric | null {
  const object = record(value);
  const obs = ['mean', 'median', 'minimum', 'maximum', 'range', 'total'] as const;
  const keys = [...obs, 'denominator', 'wins', 'ties', 'losses', 'leave_one_issuer_out'] as const;
  if (!object || !exact(object, keys) || !Array.isArray(object.leave_one_issuer_out) || object.leave_one_issuer_out.length !== 0) return null;
  const values = Object.fromEntries(obs.map(key => [key, observation(object[key])])) as Record<(typeof obs)[number], InformationYieldObservation | null>;
  if (obs.some(key => values[key] === null)) return null;
  const denominator = integer(object.denominator); const wins = integer(object.wins);
  const ties = integer(object.ties); const losses = integer(object.losses);
  if (denominator === null || wins === null || ties === null || losses === null || wins + ties + losses !== denominator) return null;
  return { mean: values.mean!, median: values.median!, minimum: values.minimum!, maximum: values.maximum!,
    range: values.range!, total: values.total!, denominator, wins, ties, losses, leaveOneIssuerOut: [] };
}
function caseRow(value: unknown): InformationYieldCase | null {
  const object = record(value);
  const keys = ['case_id', 'issuer_id', 'window_id', 'evidence_level', 'split', 'arm_order', 'request_sha256', 'fact_sha256', 'delta_r', 'delta_d', 'arms', 'hard_failure_codes'] as const;
  if (!object || !exact(object, keys)) return null;
  const id = identifier(object.case_id); const issuerId = identifier(object.issuer_id); const windowId = identifier(object.window_id);
  const requestSha256 = hash(object.request_sha256); const factSha256 = hash(object.fact_sha256);
  const deltaRichness = observation(object.delta_r); const deltaDepth = observation(object.delta_d);
  if (!id || !issuerId || !windowId || !requestSha256 || !factSha256 || !deltaRichness || !deltaDepth) return null;
  if (!['confirmation', 'development'].includes(String(object.evidence_level)) || !['untouched', 'development'].includes(String(object.split))) return null;
  if ((object.evidence_level === 'confirmation') !== (object.split === 'untouched')) return null;
  if (!Array.isArray(object.arm_order) || object.arm_order.length !== 2 || new Set(object.arm_order).size !== 2 || !object.arm_order.every(item => item === 'B0' || item === 'F')) return null;
  const arms = record(object.arms); if (!arms || !exact(arms, ['B0', 'F'])) return null;
  const b0 = arm(arms.B0); const f = arm(arms.F); const failureCodes = identifierArray(object.hard_failure_codes, 64);
  if (!b0 || !f || !failureCodes) return null;
  return { id, issuerId, subject: null, windowId, evidenceLevel: String(object.evidence_level), split: String(object.split),
    armOrder: object.arm_order[0] === 'B0' ? ['B0', 'F'] : ['F', 'B0'], requestSha256, factSha256,
    deltaRichness, deltaDepth, lineageDelta: unavailable('NOT_PROJECTED_V5'), arms: { B0: b0, F: f },
    hardFailures: failureCodes.map(code => ({ code, chainIds: [] })) };
}
function parsePopulation(value: unknown): { C: string[]; D: string[]; E: string[]; N: string[] } | null {
  const object = record(value); if (!object || !exact(object, ['C', 'D', 'E', 'N'])) return null;
  const C = identifierArray(object.C); const D = identifierArray(object.D); const E = identifierArray(object.E); const N = identifierArray(object.N);
  return C && D && E && N ? { C, D, E, N } : null;
}
function diagnostic(value: unknown): string | null { return publicValue(value) ? (typeof value === 'string' ? value : JSON.stringify(value)) : null; }

export interface ExpectedInformationYieldV5Selection { evaluation: string; caseId: string | null; arm: 'B0' | 'F' | null }

export function adaptInformationYieldV5(value: unknown, expected: ExpectedInformationYieldV5Selection): InformationYieldViewModel | null {
  if (!publicValue(value)) return null;
  const object = record(value);
  if (!object || !exact(object, TOP_KEYS) || object.wire_version !== 'information-yield-wire-5' || object.publication !== 'information-yield-v5' || object.read_only !== true) return null;
  if (object.evaluation_id !== expected.evaluation || (object.view !== 'summary' && object.view !== 'detail') || !['pass', 'reject', 'inconclusive'].includes(String(object.verdict))) return null;
  const indexSha256 = hash(object.index_sha256); const custodySha256 = hash(object.custody_sha256); const resultSha256 = hash(object.result_sha256);
  if (!indexSha256 || !custodySha256 || !resultSha256 || !['fresh', 'stale'].includes(String(object.projection_state))) return null;
  const counts = record(object.counts);
  if (!counts || !exact(counts, ['planned', 'confirmation', 'development'])) return null;
  const planned = integer(counts.planned); const confirmation = integer(counts.confirmation); const development = integer(counts.development);
  if (planned === null || confirmation === null || development === null || planned !== confirmation + development || confirmation !== 6) return null;
  const evidence = record(object.evidence);
  const evidenceKeys = ['context_sha256', 'fact_set_sha256', 'policy_sha256', 'gate_authority_sha256', 'source_closure_sha256', 'claim_limits', 'same_user_trust', 'same_user_limitations'] as const;
  if (!evidence || !exact(evidence, evidenceKeys) || evidence.same_user_trust !== 'integrity_and_nominal_issuance_only') return null;
  const evidenceHashes = evidenceKeys.slice(0, 5).map(key => hash(evidence[key]));
  const claimLimits = identifierArray(evidence.claim_limits); const limitations = identifierArray(evidence.same_user_limitations);
  if (evidenceHashes.some(item => item === null) || evidenceHashes[2] !== CANONICAL_POLICY_SHA256 || evidenceHashes[3] !== GATE_AUTHORITY_SHA256 || !claimLimits || !limitations || !same(limitations, ['no_malicious_same_user_resistance', 'no_remote_attestation', 'registry_and_self_hash_do_not_elevate_trust'])) return null;
  const populations = parsePopulation(object.populations); if (!populations || populations.N.length !== 0 || !same(populations.E, [...populations.C, ...populations.D])) return null;
  if (populations.C.length !== confirmation || populations.D.length !== development || new Set(populations.E).size !== populations.E.length) return null;
  const outcomes = record(object.outcomes); if (!outcomes || !exact(outcomes, ['richness', 'depth'])) return null;
  const richness = metric(outcomes.richness); const depth = metric(outcomes.depth);
  if (!richness || !depth || richness.denominator !== confirmation || depth.denominator !== confirmation) return null;
  if (!Array.isArray(object.policy_gates) || object.policy_gates.length !== 18) return null;
  const gates: InformationYieldGate[] = [];
  for (const [index, raw] of object.policy_gates.entries()) {
    const gate = record(raw); const keys = ['ordinal', 'name', 'population', 'decisive', 'population_case_ids', 'status', 'observed', 'threshold', 'numerator', 'denominator', 'case_results', 'reason_codes'] as const;
    if (!gate || !exact(gate, keys) || gate.ordinal !== index + 1 || gate.name !== GATE_NAMES[index]) return null;
    const population = index < 8 ? 'C' : 'E'; const decisive = index >= 11 && index <= 16;
    if (gate.population !== population || gate.decisive !== decisive || !same(gate.population_case_ids, populations[population])) return null;
    if (!['pass', 'fail', 'unknown', 'not_applicable'].includes(String(gate.status)) || !Array.isArray(gate.case_results) || !publicValue(gate.case_results)) return null;
    const reasons = identifierArray(gate.reason_codes, 64); const observed = diagnostic(gate.observed); const threshold = diagnostic(gate.threshold);
    if (!reasons || observed === null || threshold === null || !publicValue(gate.numerator) || !publicValue(gate.denominator)) return null;
    gates.push({ name: String(gate.name), status: gate.status as InformationYieldGate['status'], observed, threshold, reasonCodes: reasons });
  }
  const gateRows = object.policy_gates as Array<Record<string, unknown>>;
  const verdict = gateRows.some(gate => gate.decisive === true && gate.status === 'fail') ? 'reject'
    : gateRows.some(gate => gate.status === 'unknown') ? 'inconclusive'
      : gateRows.some(gate => gate.decisive === false && gate.status === 'fail') ? 'inconclusive'
        : gateRows.every(gate => gate.status === 'pass') ? 'pass' : 'inconclusive';
  if (object.verdict !== verdict) return null;
  if (!Array.isArray(object.cases) || object.cases.length > 64) return null;
  const cases = object.cases.map(caseRow); if (cases.some(item => item === null) || new Set(cases.map(item => item!.id)).size !== cases.length) return null;
  const selectedCase = object.case === null ? null : caseRow(object.case); const selectedArm = object.selected_arm === null ? null : arm(object.selected_arm);
  if (object.case !== null && !selectedCase || object.selected_arm !== null && !selectedArm) return null;
  const selection = record(object.selection); if (!selection || !exact(selection, ['case_id', 'arm'])) return null;
  const caseId = selection.case_id === null ? null : identifier(selection.case_id); const armId = selection.arm;
  if ((caseId === null) !== (selection.case_id === null) || armId !== null && armId !== 'B0' && armId !== 'F') return null;
  if (caseId !== expected.caseId || armId !== expected.arm || object.view !== (caseId === null ? 'summary' : 'detail')) return null;
  if (caseId === null && (selectedCase !== null || selectedArm !== null || cases.length !== populations.E.length || !same(cases.map(item => item!.id), populations.E))) return null;
  if (caseId !== null && (cases.length !== 0 || !selectedCase || selectedCase.id !== caseId)) return null;
  if (armId === null && selectedArm !== null || armId !== null && (!selectedArm || !selectedCase || !same(selectedArm, selectedCase.arms[armId]))) return null;
  const visibleCases = caseId === null ? cases as InformationYieldCase[] : [selectedCase!];
  const expectedFailures = visibleCases.flatMap(item => item.hardFailures.map(failure => ({ caseId: item.id, code: failure.code, chainIds: [] as string[] })));
  if (!Array.isArray(object.hard_failures) || object.hard_failures.length > 128) return null;
  const failures: InformationYieldViewModel['hardFailures'] = [];
  for (const raw of object.hard_failures) {
    const failure = record(raw); if (!failure || !exact(failure, ['case_id', 'code'])) return null;
    const failureCase = identifier(failure.case_id); const code = identifier(failure.code); if (!failureCase || !code) return null;
    failures.push({ caseId: failureCase, code, chainIds: [] });
  }
  if (!same(failures, expectedFailures) || failures.length > 0 && object.verdict !== 'reject') return null;
  const wire = object as unknown as InformationYieldV5WireResponse;
  return { view: wire.view, evaluationId: expected.evaluation, resultSha256, registrySha256: null, indexSha256,
    stale: wire.projection_state === 'stale', verdict: wire.verdict, counts: { planned, confirmation, development },
    evidence: { contextSha256: evidenceHashes[0]!, factSetSha256: evidenceHashes[1]!, policySha256: evidenceHashes[2]!,
      gateAuthoritySha256: evidenceHashes[3]!, sourceClosureSha256: evidenceHashes[4]!, summarySha256: null,
      custodySha256, claimLimits }, outcomes: { richness, depth }, gates, hardFailures: failures,
    cases: cases as InformationYieldCase[], selectedCase, selectedArm,
    selection: { caseId, arm: armId as 'B0' | 'F' | null, run: null, source: null } };
}
