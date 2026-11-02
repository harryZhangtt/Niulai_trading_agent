export type Scalar = string | number | boolean | null;
export type Metrics = Record<string, number | null>;
export type Details = Record<string, unknown>;

export interface MetricDefinition {
  label?: string;
  unit?: string;
  aggregation?: string;
  caveat?: string;
}

export interface AggregateMetric {
  sum: number | null;
  mean: number | null;
  known: number;
  unknown: number;
  denominator: number;
  unit?: string;
}

export interface Source {
  id: string;
  title: string;
  url: string | null;
  subject: string;
  scope: string;
  content_access: string;
  source_sha256: string | null;
  version_sha256: string | null;
  timestamps: {
    published_at: string | null;
    available_at: string | null;
    fetched_at: string | null;
    recorded_at: string | null;
  };
  labels: {
    publisher_kind: string | null;
    perspectives: string[];
    document_type: string | null;
    topics: string[];
    epistemic_status: string | null;
    annotation_status: string | null;
    policy_version: string | null;
    provenance_status: string | null;
    persistence?: string | null;
  };
  run_ids: string[];
  batch_ids?: string[];
  collection_ids?: string[];
  limitations: string[];
  temporal?: Details | null;
  temporal_checks?: Details[];
  local_preview?: {
    status: 'available' | 'missing';
    content_scope: string;
    origin: string;
    filename: string;
    text: string;
    truncated: boolean;
    redacted_fields: number;
    document_sha256: string | null;
    declared_document_sha256: string | null;
    document_bytes: number | null;
    declared_document_bytes: number | null;
    preview_sha256: string | null;
    frozen_at: string | null;
    original_availability: null;
    canonical_byte_identity_verified: false;
    reason_codes: string[];
  } | null;
}

export interface TemporalSourceDecision extends Details {
  source_sha256: string;
  cutoff: string | null;
  status: 'eligible' | 'blocked' | 'unknown' | 'qualified_reconstruction';
  worker_visible: boolean | null;
  reason_codes: string[];
  basis: string | null;
  view: 'reviewer_diagnostic';
}

export interface RunTemporal extends Details {
  cutoff: string | null;
  status: 'guarded' | 'not_evaluated' | 'unverified';
  execution_id: string | null;
  report_sha256: string;
  diagnostic_sha256: string | null;
  semantics: 'run_bound_diagnostic';
  reason_codes: string[];
  source_decisions: TemporalSourceDecision[];
}

export interface Run {
  id: string;
  execution_id: string | null;
  query: string;
  pipeline_id: string | null;
  pipeline_version: string | null;
  config_sha256: string | null;
  status: string;
  scope: string;
  started_at: string | null;
  finished_at: string | null;
  script_versions: Array<{ id: string; sha256: string | null }>;
  phases: Array<{ id: string; status: string; mode: string | null; action: string | null }>;
  metrics: Metrics;
  source_ids: string[];
  temporal?: RunTemporal | null;
  output?: RunOutput | null;
}

export interface RunOutput {
  summary: string;
  catalog_sha256: string;
  questions: Array<{ id: string; facet: string; question: string; priority: 'required' | 'optional' | 'exploration' }>;
  observations: Array<{ source_sha256: string; quote: string; epistemic_status: string; topics: string[] }>;
  annotation_status: 'provisional';
  scope: 'not_semantic_admission';
}

export interface AcquisitionAttempt {
  ordinal: number | null;
  capability: string;
  status: string;
  route: string | null;
  fetch_key_sha256: string | null;
  fetch_executed: boolean | null;
  cache_hit: boolean | null;
  reasons: string[];
  started_at: string | null;
  finished_at: string | null;
  receipt_sha256: string;
  action_execution_sha256: string | null;
}

export interface AcquisitionRequirement {
  id: string;
  subject: string;
  status: string;
  source_id: string | null;
  route: string | null;
  cache_hit: boolean | null;
  reasons: string[];
  elapsed_seconds: number | null;
  attempts: AcquisitionAttempt[];
  receipt_sha256: string;
}

export interface AcquisitionBatch {
  id: string;
  execution_id: string;
  batch_id: string;
  query: string | null;
  subjects: string[];
  version: string;
  status: string;
  scope: string;
  manifest_sha256: string;
  config_sha256: string;
  capability_catalog_sha256: string | null;
  script_versions: Array<{ id: string; sha256: string | null }>;
  started_at: string | null;
  finished_at: string | null;
  metrics: Metrics;
  metrics_scope: 'whole_batch';
  counting_unit: 'adapter_dispatch';
  http_requests: null;
  configuration: {
    budget: { deadline_seconds: number | null; max_workers: number | null; max_provider_calls: number | null };
    requirements: Array<{
      id: string;
      subject: string;
      access: string;
      routes: Array<{ capability: string; parameters: { url?: string | null; paper_id?: string | null; query?: string | null } }>;
      max_attempts: number | null;
      cache_max_age_seconds: number | null;
      timeout_seconds: number | null;
    }>;
  };
  requirements: AcquisitionRequirement[];
  requirements_scope: 'requested_subject';
  source_ids: string[];
  sources: Source[];
  retention: RetentionCounts & { snapshots: string; cache_is_disposable_index: boolean; scope: string };
  limitations: string[];
}

export interface RetentionCounts {
  manifest_receipts: number;
  configuration_receipts: number;
  requirement_receipts: number;
  attempt_receipts: number;
  source_receipts: number;
  observation_receipts: number;
}

export interface BatchCounts {
  registered: number;
  total: number;
  unavailable_batches: number;
  by_status: Record<string, number>;
  scope: string;
  counting_unit: string;
  http_requests: null;
  counts: Record<string, number>;
}

export interface Cohort {
  id: string;
  scope: string;
  denominator: number;
  metrics: Record<string, AggregateMetric>;
  unknowns: unknown;
}

export interface Comparison {
  id: string;
  title: string;
  scope: string;
  status: string;
  conclusion?: {
    status: string;
    runtime_counts: Record<string, number>;
    noncompleted_executions: number;
    review_order_known: number;
    preference_disagreements: number;
    score_disagreements: number;
    scope: string;
  };
  arms: Array<{ id: string; status: string; denominator: number; metrics: Record<string, AggregateMetric>; errors?: string[]; receipt_sha256?: string | null; expected_cases?: number; graded_cases?: number; denominator_scope?: string }>;
  rows: Array<{
    case_id: string;
    A: ComparisonArmResult;
    B: ComparisonArmResult;
    differences: Metrics;
    review_order?: {
      status: string;
      preferences: string[];
      preference_consistent: boolean | null;
      score_consistent: boolean | null;
      score_disagreements: string[];
      scope?: string;
    };
  }>;
  limitations: string[];
  acquisition?: AcquisitionComparison;
}

export interface AcquisitionComparison {
  report_sha256: string;
  baseline_sha256: string;
  contract_sha256: string;
  scope: string;
  sensitivity_excluding_anonymous: Record<string, number>;
  tasks: Array<{ id: string; question: string; required_facets: number; A: number; B: number }>;
  reviews: {
    count: number; replicate_metrics_equal: boolean; units_reviewed: number; unique_observations: number;
    unique_documents: number; answer_bearing_pool: number; freshness_disagreements: number;
    unique_freshness_disagreements: number; unknown_first_availability: number;
    unique_unknown_first_availability: number; receipt_sha256s: string[];
  };
  collections: NativeCollection[];
  capture_counts: { instances: number; search_metadata: number; document_instances: number; unique_document_bodies: number };
}

export interface NativeCollection {
  arm: string; execution_id: string; status: string; review_status: string; backend: string;
  cohort: string; cutoff: string | null; started_at: string | null; finished_at: string | null;
  collection_sha256: string; config_sha256: string; baseline_sha256: string; query: string | null;
  cache_enabled: boolean; budget: Metrics; metrics: Metrics;
  native_callbacks: number;
  financial_context_period: string | null;
  cache_outcomes: { misses: number; published_captures: number; hits: number; fallbacks: number };
  sources: Source[]; units_total: number; units_truncated: number;
  units: Array<{
    id: string; unit_sha256: string; claim: string | null; quote: string | null; quote_truncated: boolean;
    source_id: string; source_sha256: string; supported: boolean | null; answer_bearing: boolean | null;
    novelty_kind: string; tasks: string[]; epistemic_status: string | null; period: string | null;
    unit: string | null; lineage: string | null; freshness: string[]; first_verified_available_at: string | null;
    annotation_status: 'provisional'; limitations: string[];
  }>;
}

export interface ComparisonArmResult {
  status: string;
  review_status?: string;
  runtime_status?: string;
  pipeline_status?: string;
  pipeline_reason?: string | null;
  pipeline_report_sha256?: string;
  case_result_sha256?: string;
  execution_id?: string | null;
  metrics: Metrics;
  summary?: CapturedSummary | null;
}

export interface CapturedSummary {
  incremental_contribution: string | null;
  economic_inference: string | null;
  unproved_links: string[];
}

export interface DatasourceResponse {
  schema_version: 1;
  generated_at: string;
  snapshot_id: string;
  status: 'ok' | 'partial' | 'unavailable';
  warnings: Array<{ code: string; count: number }>;
  subject: string;
  pagination: { offset: number; limit: number; total_sources: number; total_runs: number; total_batches?: number; total_native_collections?: number; next_offset: number | null };
  metric_definitions?: Record<string, MetricDefinition>;
  sources: Source[];
  runs: Run[];
  batches?: AcquisitionBatch[];
  aggregates: { cohorts: Cohort[]; unknowns: unknown; batch_counts?: BatchCounts; retention_counts?: RetentionCounts & { scope: string; snapshots: string; cache_is_disposable_index: boolean } };
  comparisons: Comparison[];
  temporal?: Details | null;
}
