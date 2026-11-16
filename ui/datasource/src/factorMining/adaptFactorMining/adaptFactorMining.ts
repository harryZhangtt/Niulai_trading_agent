import type { FactorMiningWireResponse } from '../../types/factorMiningApi';
import type { FactorMiningArtifact, FactorMiningFactor, FactorMiningGate, FactorMiningRun, FactorMiningStage, FactorMiningStatus, FactorMiningViewModel, FactorPerformance, FactorPerformanceState, FactorPerformanceSubject } from '../viewModels';

const idPattern = /^[a-z0-9][a-z0-9_.-]{0,95}$/;
const shaPattern = /^[a-f0-9]{64}$/;
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const runStatuses = new Set(['planned', 'running', 'succeeded', 'failed', 'timed_out', 'cancelled']);
function record(value: unknown): Record<string, unknown> | null { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null; }
function text(value: unknown, maximum = 1000): string | null { return typeof value === 'string' && value.length <= maximum ? value : null; }
function id(value: unknown): string | null { const result = text(value, 96); return result && idPattern.test(result) ? result : null; }
function sha(value: unknown): string | null { return typeof value === 'string' && shaPattern.test(value) ? value : null; }
function optionalSha(value: unknown): string | null | undefined { return value === null ? null : sha(value) ?? undefined; }
function finite(value: unknown): number | null { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
function integer(value: unknown): number | null { return typeof value === 'number' && Number.isSafeInteger(value) ? value : null; }
function date(value: unknown): string | null { const result = text(value, 10); if (!result || !datePattern.test(result)) return null; const parsed = new Date(`${result}T00:00:00Z`); return Number.isFinite(parsed.getTime()) && parsed.toISOString().startsWith(result) ? result : null; }
function nullableId(value: unknown): string | null | undefined { return value === null ? null : id(value) ?? undefined; }

function stage(value: unknown): FactorMiningStage | null {
  const item = record(value); if (!item) return null;
  const stageId = id(item.id); const status = id(item.status); const attempts = integer(item.attempt_count);
  const receipt = optionalSha(item.receipt_sha256); const failure = item.failure_code === null ? null : id(item.failure_code);
  if (!stageId || !status || attempts == null || attempts < 0 || receipt === undefined || failure === undefined) return null;
  return { id: stageId, status, attempts, receiptSha256: receipt, failureCode: failure };
}

function factor(value: unknown): FactorMiningFactor | null {
  const item = record(value); if (!item) return null;
  const factorId = id(item.id); const family = id(item.family); const status = id(item.status);
  const formula = optionalSha(item.formula_sha256); const rawMetrics = record(item.metrics);
  if (!factorId || !family || !status || formula === undefined || !rawMetrics || Object.keys(rawMetrics).length > 64) return null;
  const metrics: Record<string, number> = {};
  for (const [key, value] of Object.entries(rawMetrics)) { const metric = finite(value); if (!idPattern.test(key) || metric == null) return null; metrics[key] = metric; }
  return { id: factorId, family, status, formulaSha256: formula, metrics };
}

function gate(value: unknown): FactorMiningGate | null {
  const item = record(value); if (!item) return null;
  const gateId = id(item.id); const dimension = id(item.dimension); const status = id(item.status);
  const reason = item.reason_code === null ? null : id(item.reason_code); const evidence = optionalSha(item.evidence_sha256);
  if (!gateId || !dimension || !status || reason === undefined || evidence === undefined) return null;
  return { id: gateId, dimension, status, reasonCode: reason, evidenceSha256: evidence };
}

function artifact(value: unknown): FactorMiningArtifact | null {
  const item = record(value); if (!item) return null;
  const artifactId = id(item.id); const kind = id(item.kind); const identity = sha(item.sha256); const size = integer(item.size_bytes);
  if (!artifactId || !kind || !identity || size == null || size <= 0) return null;
  return { id: artifactId, kind, sha256: identity, sizeBytes: size };
}

function subject(value: unknown, factorIds: Set<string>): FactorPerformanceSubject | null {
  const item = record(value); if (!item || !Array.isArray(item.factor_ids) || item.factor_ids.length > 128) return null;
  const ids = item.factor_ids.map(id); if (!ids.every(Boolean)) return null;
  const members = ids as string[]; if (new Set(members).size !== members.length || members.some(member => !factorIds.has(member))) return null;
  const kind = item.kind; const omitted = nullableId(item.omitted_factor_id); if (omitted === undefined) return null;
  if (kind === 'standalone' && members.length === 1 && omitted === null) return { kind, factorIds: members as [string], omittedFactorId: null };
  if (kind === 'combination' && members.length >= 2 && omitted === null) return { kind, factorIds: members, omittedFactorId: null };
  if (kind === 'leave_one_out' && members.length >= 1 && omitted && factorIds.has(omitted) && !members.includes(omitted)) return { kind, factorIds: members, omittedFactorId: omitted };
  return null;
}

function performance(value: unknown, factorIds: Set<string>, origin: string, evidence: string): FactorPerformance | null {
  const item = record(value); if (!item) return null;
  const performanceId = id(item.id); const performanceSubject = subject(item.subject, factorIds);
  const availability = item.availability; const metricId = nullableId(item.metric_id); const estimateUnit = nullableId(item.estimate_unit);
  const baselineId = nullableId(item.baseline_id); const evidenceSha256 = optionalSha(item.evidence_sha256);
  if (!performanceId || !performanceSubject || metricId === undefined || estimateUnit === undefined || baselineId === undefined || evidenceSha256 === undefined) return null;
  const rawPeriod = item.period === null ? null : record(item.period); let period: { id: string; start: string; end: string } | null = null;
  if (rawPeriod) { const periodId = id(rawPeriod.id); const start = date(rawPeriod.start); const end = date(rawPeriod.end); if (!periodId || !start || !end || start >= end) return null; period = { id: periodId, start, end }; }
  else if (item.period !== null) return null;
  const provenance = { origin, evidence, evidenceSha256 };
  if (availability === 'unavailable') {
    const reasonCode = id(item.reason_code);
    if (!reasonCode || item.point_estimate !== null || item.uncertainty !== null || item.sample !== null || evidenceSha256 !== null) return null;
    return { state: 'unavailable', id: performanceId, subject: performanceSubject, reasonCode, metricId, estimateUnit, period, baselineId, provenance };
  }
  if (availability !== 'available' || origin === 'synthetic_fixture' || item.reason_code !== null || !metricId || !estimateUnit || !period || !baselineId || !evidenceSha256) return null;
  const pointEstimate = finite(item.point_estimate); const rawUncertainty = record(item.uncertainty); const rawSample = record(item.sample);
  if (pointEstimate == null || !rawUncertainty || !rawSample) return null;
  const uncertaintyKind = id(rawUncertainty.kind); const lower = finite(rawUncertainty.lower); const upper = finite(rawUncertainty.upper);
  const level = rawUncertainty.level === null ? null : finite(rawUncertainty.level);
  const sampleSize = integer(rawSample.size); const sampleUnit = id(rawSample.unit);
  if (!uncertaintyKind || lower == null || upper == null || lower > upper || (level !== null && (level <= 0 || level >= 1)) || sampleSize == null || sampleSize <= 0 || !sampleUnit) return null;
  return { state: 'available', id: performanceId, subject: performanceSubject, metricId, estimateUnit, pointEstimate,
    uncertainty: { kind: uncertaintyKind, lower, upper, level }, sample: { size: sampleSize, unit: sampleUnit },
    period, baselineId, provenance: { origin, evidence, evidenceSha256 } };
}

function inferredPerformanceState(
  raw: unknown,
  schemaVersion: 1 | 2,
  origin: string,
  loaded: boolean,
  observations: FactorPerformance[],
): FactorPerformanceState | null {
  const value = raw === undefined ? null : id(raw);
  if (raw !== undefined && !value) return null;
  if (schemaVersion === 1) {
    if (loaded) return null;
    const expected = origin === 'synthetic_fixture' ? 'withheld_fixture'
      : origin === 'reported_external' ? 'legacy_reported_unverified'
      : 'legacy_reproduced_hash_bound';
    if (value !== null && value !== expected && value !== 'legacy_not_recorded') return null;
    return origin === 'synthetic_fixture' ? 'withheld_fixture' : 'legacy_not_recorded';
  }
  if (origin === 'synthetic_fixture') {
    if (value !== 'withheld_fixture') return null;
    return 'withheld_fixture';
  }
  const availableState = origin === 'reported_external' ? 'available_unverified' : 'available_hash_bound';
  if (value === null || ![availableState, 'unavailable', 'not_published'].includes(value)) return null;
  if (loaded) {
    const expected = observations.length === 0 ? 'not_published'
      : observations.some(observation => observation.state === 'available') ? availableState
      : 'unavailable';
    if (value !== expected) return null;
    return expected === 'not_published' ? 'not_published' : 'available';
  }
  return value === 'not_published' ? 'not_published' : 'available';
}

function run(value: unknown): FactorMiningRun | null {
  const item = record(value); if (!item) return null;
  const runId = id(item.id); const revision = integer(item.revision); const manifestSha256 = sha(item.manifest_sha256);
  const manifestSchemaVersion = item.manifest_schema_version === undefined ? 1 : integer(item.manifest_schema_version);
  const createdAt = text(item.created_at, 80); const rawStatus = text(item.status, 32);
  const provenance = record(item.provenance); const engine = record(item.engine); const resources = record(item.resources);
  const protocolSha256 = optionalSha(item.protocol_sha256); const datasetSnapshotSha256 = optionalSha(item.dataset_snapshot_sha256);
  if (!runId || revision == null || revision < 1 || !manifestSha256 || (manifestSchemaVersion !== 1 && manifestSchemaVersion !== 2) || !createdAt || !rawStatus || !provenance || !engine || !resources || protocolSha256 === undefined || datasetSnapshotSha256 === undefined) return null;
  const provenanceOrigin = id(provenance.origin); const provenanceEvidence = id(provenance.evidence);
  const adapterVersion = id(engine.adapter_version); const qlibProfile = id(engine.qlib_profile);
  const wallSeconds = finite(resources.wall_seconds); const cpuSeconds = finite(resources.cpu_seconds); const peakRssBytes = integer(resources.peak_rss_bytes);
  const provenancePair = `${provenanceOrigin}/${provenanceEvidence}`;
  if (!provenanceOrigin || !provenanceEvidence || !['reported_external/unverified', 'reproduced_local/hash_bound', 'synthetic_fixture/fixture_only'].includes(provenancePair) ||
      (provenanceOrigin === 'reproduced_local' && (!protocolSha256 || !datasetSnapshotSha256)) ||
      !adapterVersion || !qlibProfile || wallSeconds == null || cpuSeconds == null || peakRssBytes == null || typeof resources.cache_hit !== 'boolean') return null;
  const map = <T>(raw: unknown, maximum: number, adapt: (item: unknown) => T | null): T[] | null => {
    if (!Array.isArray(raw) || raw.length > maximum) return null;
    const result = raw.map(adapt); return result.every(Boolean) ? result as T[] : null;
  };
  const stages = map(item.stages, 64, stage); const parsedFactors = map(item.factors, 128, factor); const gates = map(item.gates, 128, gate); const artifacts = map(item.artifacts ?? [], 256, artifact);
  if (!stages || !parsedFactors || !gates || !artifacts || !Array.isArray(item.failures) || item.failures.length > 128 || !Array.isArray(item.limitations) || item.limitations.length > 64) return null;
  const factors = provenanceOrigin === 'synthetic_fixture' ? parsedFactors.map(value => ({ ...value, metrics: {} })) : parsedFactors;
  const knownFactorIds = new Set(factors.map(value => value.id));
  const performanceLoaded = item.performance !== undefined;
  const performanceRecords = performanceLoaded
    ? map(item.performance, 256, value => performance(value, knownFactorIds, provenanceOrigin, provenanceEvidence))
    : [];
  if (!performanceRecords || new Set(performanceRecords.map(value => value.id)).size !== performanceRecords.length) return null;
  const availableHashes = new Set(artifacts.filter(value => value.kind === 'evaluation').map(value => value.sha256));
  if (performanceRecords.some(value => value.state === 'available' && !availableHashes.has(value.provenance.evidenceSha256))) return null;
  const performanceState = inferredPerformanceState(item.performance_state, manifestSchemaVersion, provenanceOrigin, performanceLoaded, performanceRecords);
  if (!performanceState || (performanceState === 'withheld_fixture' && provenanceOrigin !== 'synthetic_fixture')) return null;
  const failures: Array<{ code: string; stageId: string }> = [];
  for (const raw of item.failures) { const failure = record(raw); const code = id(failure?.code); const stageId = id(failure?.stage_id); if (!code || !stageId) return null; failures.push({ code, stageId }); }
  const limitations: string[] = [];
  for (const raw of item.limitations) { const limitation = text(raw, 1000); if (!limitation) return null; limitations.push(limitation); }
  const artifactCount = integer(item.artifact_count); if (artifactCount == null || artifactCount < artifacts.length) return null;
  return { id: runId, revision, manifestSha256, manifestSchemaVersion, createdAt,
    status: (runStatuses.has(rawStatus) ? rawStatus : 'unknown') as FactorMiningStatus,
    provenanceOrigin, provenanceEvidence, adapterVersion, qlibProfile, protocolSha256, datasetSnapshotSha256,
    stages, factors, gates, performanceState, performanceLoaded, performance: performanceRecords, failures, wallSeconds, cpuSeconds, peakRssBytes,
    cacheHit: resources.cache_hit, limitations, artifactCount, artifacts };
}

export function adaptFactorMining(value: FactorMiningWireResponse): FactorMiningViewModel | null {
  const root = record(value); if (!root || root.schema_version !== 1 || root.scope !== 'factor_mining' || root.read_only !== true) return null;
  const generatedAt = text(root.generated_at, 80); const status = root.status;
  if (!generatedAt || !['ok', 'partial', 'empty'].includes(String(status)) || !Array.isArray(root.runs) || root.runs.length > 100 || !Array.isArray(root.warnings) || root.warnings.length > 1000) return null;
  const runs = root.runs.map(run); if (!runs.every(Boolean)) return null;
  if (status === 'empty' && runs.length !== 0 || status === 'ok' && runs.length === 0
    || new Set(runs.map(item => item!.id)).size !== runs.length) return null;
  if (root.projection_state !== undefined && !['fresh', 'stale'].includes(String(root.projection_state))) return null;
  const warnings: Array<{ runId: string; code: string }> = [];
  for (const raw of root.warnings) { const runId = id(record(raw)?.run_id); const code = id(record(raw)?.code); if (!runId || !code) return null; warnings.push({ runId, code }); }
  return { generatedAt, status: status as FactorMiningViewModel['status'], stale: root.projection_state === 'stale', runs: runs as FactorMiningRun[], warnings };
}
