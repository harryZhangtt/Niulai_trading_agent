export interface FactorMiningWireArtifact { id: unknown; kind: unknown; sha256: unknown; size_bytes: unknown }
export interface FactorMiningWireStage { id: unknown; status: unknown; attempt_count: unknown; receipt_sha256: unknown; failure_code: unknown }
export interface FactorMiningWireFactor { id: unknown; family: unknown; formula_sha256: unknown; status: unknown; metrics: unknown }
export interface FactorMiningWireGate { id: unknown; dimension: unknown; status: unknown; reason_code: unknown; evidence_sha256: unknown }
export interface FactorMiningWirePerformance {
  id: unknown; subject: unknown; availability: unknown; reason_code: unknown; metric_id: unknown;
  estimate_unit: unknown; point_estimate: unknown; uncertainty: unknown; sample: unknown;
  period: unknown; baseline_id: unknown; evidence_sha256: unknown;
}
export interface FactorMiningWireRun {
  id: unknown; revision: unknown; manifest_sha256: unknown; manifest_schema_version?: unknown;
  created_at: unknown; status: unknown; provenance: unknown; engine: unknown;
  protocol_sha256: unknown; dataset_snapshot_sha256: unknown;
  stages: unknown; factors: unknown; gates: unknown; failures: unknown; resources: unknown;
  limitations: unknown; artifact_count: unknown; artifacts?: unknown;
  performance_state?: unknown; performance?: unknown;
}
export interface FactorMiningWireResponse {
  schema_version: unknown; generated_at: unknown; read_only: unknown; scope: unknown;
  status: unknown; projection_state: unknown; runs: unknown; warnings: unknown;
}
