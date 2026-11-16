export type FactorMiningStatus = 'planned' | 'running' | 'succeeded' | 'failed' | 'timed_out' | 'cancelled' | 'unknown';
export interface FactorMiningStage { id: string; status: string; attempts: number; receiptSha256: string | null; failureCode: string | null }
export interface FactorMiningFactor { id: string; family: string; formulaSha256: string | null; status: string; metrics: Record<string, number> }
export interface FactorMiningGate { id: string; dimension: string; status: string; reasonCode: string | null; evidenceSha256: string | null }
export interface FactorMiningArtifact { id: string; kind: string; sha256: string; sizeBytes: number }
export type FactorPerformanceSubject =
  | { kind: 'standalone'; factorIds: [string]; omittedFactorId: null }
  | { kind: 'combination'; factorIds: string[]; omittedFactorId: null }
  | { kind: 'leave_one_out'; factorIds: string[]; omittedFactorId: string };
export interface FactorPerformanceProvenance { origin: string; evidence: string; evidenceSha256: string | null }
export interface FactorPerformanceContext {
  subject: FactorPerformanceSubject;
  metricId: string | null;
  estimateUnit: string | null;
  period: { id: string; start: string; end: string } | null;
  baselineId: string | null;
  provenance: FactorPerformanceProvenance;
}
export type FactorPerformance =
  | (FactorPerformanceContext & {
      state: 'available'; id: string; metricId: string; estimateUnit: string;
      pointEstimate: number;
      uncertainty: { kind: string; lower: number; upper: number; level: number | null };
      sample: { size: number; unit: string };
      period: { id: string; start: string; end: string };
      baselineId: string;
      provenance: FactorPerformanceProvenance & { evidenceSha256: string };
    })
  | (FactorPerformanceContext & { state: 'unavailable'; id: string; reasonCode: string });
export type FactorPerformanceState = 'available' | 'not_published' | 'withheld_fixture' | 'legacy_not_recorded';
export interface FactorMiningRun {
  id: string; revision: number; manifestSha256: string; manifestSchemaVersion: 1 | 2; createdAt: string; status: FactorMiningStatus;
  provenanceOrigin: string; provenanceEvidence: string; adapterVersion: string; qlibProfile: string;
  protocolSha256: string | null; datasetSnapshotSha256: string | null;
  stages: FactorMiningStage[]; factors: FactorMiningFactor[]; gates: FactorMiningGate[];
  performanceState: FactorPerformanceState; performanceLoaded: boolean; performance: FactorPerformance[];
  failures: Array<{ code: string; stageId: string }>; wallSeconds: number; cpuSeconds: number;
  peakRssBytes: number; cacheHit: boolean; limitations: string[]; artifactCount: number;
  artifacts: FactorMiningArtifact[];
}
export interface FactorMiningViewModel {
  generatedAt: string; status: 'ok' | 'partial' | 'empty'; stale: boolean;
  runs: FactorMiningRun[]; warnings: Array<{ runId: string; code: string }>;
}
