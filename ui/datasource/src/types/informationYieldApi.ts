export type InformationYieldArmIdWire = 'B0' | 'F';
export type InformationYieldGateStatusWire = 'pass' | 'fail' | 'unknown' | 'not_applicable';

export type InformationYieldObservationWire =
  | { state: 'known'; value: number; unit: string }
  | { state: 'unavailable' | 'not_applicable'; reason_code: string };

export interface InformationYieldTraceWire {
  complete: number | null;
  credited: number | null;
  reviewed_complete: number | null;
  pooled_total: number | null;
  rejected: number | null;
  unjudged: number | null;
}

export interface InformationYieldArmWire {
  richness: InformationYieldObservationWire;
  depth: InformationYieldObservationWire;
  precision: InformationYieldObservationWire;
  wall_seconds: InformationYieldObservationWire;
  lineages: InformationYieldObservationWire;
  critical_unsupported: InformationYieldObservationWire;
  trace: InformationYieldTraceWire;
}

export interface InformationYieldFailureWire {
  code: string;
  chain_ids: string[];
}

export interface InformationYieldTopFailureWire extends InformationYieldFailureWire {
  case_id: string;
}

export interface InformationYieldCaseWire {
  case_id: string;
  issuer_id: string;
  subject: string;
  window_id: string;
  evidence_level: 'confirmation' | 'development';
  split: 'untouched' | 'development';
  arm_order: [InformationYieldArmIdWire, InformationYieldArmIdWire];
  request_sha256: string;
  fact_sha256: string;
  delta_r: InformationYieldObservationWire;
  delta_d: InformationYieldObservationWire;
  lineage_delta: InformationYieldObservationWire;
  arms: { B0: InformationYieldArmWire; F: InformationYieldArmWire };
  hard_failures: InformationYieldFailureWire[];
}

export interface InformationYieldLeaveOneOutWire {
  issuer_id: string;
  mean: number | null;
}

export interface InformationYieldMetricWire {
  mean: InformationYieldObservationWire;
  median: InformationYieldObservationWire;
  minimum: InformationYieldObservationWire;
  maximum: InformationYieldObservationWire;
  range: InformationYieldObservationWire;
  total: InformationYieldObservationWire;
  denominator: number;
  wins: number;
  ties: number;
  losses: number;
  leave_one_issuer_out: InformationYieldLeaveOneOutWire[];
}

export interface InformationYieldGateCaseResultWire {
  B0?: number | null;
  F?: number | null;
  arm?: InformationYieldArmIdWire;
  case_id?: string;
  chain_ids?: string[];
  code?: string;
  complete?: number | null;
  count?: number;
  credited?: number | null;
  delta?: number | null;
  delta_d?: number | null;
  delta_r?: number | null;
  issuer_id?: string;
  matched?: boolean;
  mean?: number | null;
  metadata_known?: boolean;
  pooled?: number | null;
  ratio?: number | null;
  reviewed?: number | null;
  status?: InformationYieldGateStatusWire;
  unjudged?: number | null;
}

export interface InformationYieldOrdersWire {
  B0_first: number;
  F_first: number;
}

export type InformationYieldGateDiagnosticWire =
  | string
  | number
  | boolean
  | null
  | Array<string | number | boolean | null | InformationYieldGateCaseResultWire>
  | { count: number; distinct: boolean; orders: InformationYieldOrdersWire }
  | { count: number; orders: InformationYieldOrdersWire }
  | { aggregate: number; case: number };

export interface InformationYieldGateWire {
  name: string;
  status: InformationYieldGateStatusWire;
  observed: InformationYieldGateDiagnosticWire;
  threshold: InformationYieldGateDiagnosticWire;
  numerator: number | null | [number, number];
  denominator: number | null | [number, number];
  case_results: Array<string | InformationYieldGateCaseResultWire>;
  reason_codes: string[];
}

export interface InformationYieldCountsWire {
  planned: number;
  confirmation: number;
  development: number;
}

export interface InformationYieldEvidenceWire {
  context_sha256: string;
  fact_set_sha256: string;
  policy_sha256: string;
  source_closure_sha256: string;
  summary_sha256: string;
  claim_limits: string[];
}

export interface InformationYieldSelectionWire {
  case_id: string | null;
  arm: InformationYieldArmIdWire | null;
  run: string | null;
  source: string | null;
}

export interface InformationYieldWireResponse {
  schema_version: 1;
  view: 'summary' | 'detail';
  evaluation_id: string;
  registry_sha256: string;
  result_sha256: string;
  verdict: 'pass' | 'reject' | 'inconclusive';
  counts: InformationYieldCountsWire;
  evidence: InformationYieldEvidenceWire;
  outcomes: { richness: InformationYieldMetricWire; depth: InformationYieldMetricWire };
  policy_gates: InformationYieldGateWire[];
  hard_failures: InformationYieldTopFailureWire[];
  cases: InformationYieldCaseWire[];
  selection: InformationYieldSelectionWire;
  case: InformationYieldCaseWire | null;
  selected_arm: InformationYieldArmWire | null;
  projection_state: 'fresh' | 'stale';
  read_only: true;
}
