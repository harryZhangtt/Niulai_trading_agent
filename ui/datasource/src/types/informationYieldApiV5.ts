export type InformationYieldV5ArmIdWire = 'B0' | 'F';
export type InformationYieldV5GateStatusWire = 'pass' | 'fail' | 'unknown' | 'not_applicable';
export type InformationYieldV5ObservationWire =
  | { state: 'known'; value: number; unit: string }
  | { state: 'unavailable'; reason_code: string };

export interface InformationYieldV5TraceWire {
  complete: number | null;
  credited: number | null;
  unjudged: number | null;
}
export interface InformationYieldV5ArmWire {
  richness: InformationYieldV5ObservationWire;
  depth: InformationYieldV5ObservationWire;
  precision: InformationYieldV5ObservationWire;
  wall_seconds: InformationYieldV5ObservationWire;
  trace: InformationYieldV5TraceWire;
}
export interface InformationYieldV5CaseWire {
  case_id: string;
  issuer_id: string;
  window_id: string;
  evidence_level: 'confirmation' | 'development';
  split: 'untouched' | 'development';
  arm_order: [InformationYieldV5ArmIdWire, InformationYieldV5ArmIdWire];
  request_sha256: string;
  fact_sha256: string;
  delta_r: InformationYieldV5ObservationWire;
  delta_d: InformationYieldV5ObservationWire;
  arms: { B0: InformationYieldV5ArmWire; F: InformationYieldV5ArmWire };
  hard_failure_codes: string[];
}
export interface InformationYieldV5MetricWire {
  mean: InformationYieldV5ObservationWire;
  median: InformationYieldV5ObservationWire;
  minimum: InformationYieldV5ObservationWire;
  maximum: InformationYieldV5ObservationWire;
  range: InformationYieldV5ObservationWire;
  total: InformationYieldV5ObservationWire;
  denominator: number;
  wins: number;
  ties: number;
  losses: number;
  leave_one_issuer_out: [];
}
export interface InformationYieldV5GateWire {
  ordinal: number;
  name: string;
  population: 'C' | 'E';
  decisive: boolean;
  population_case_ids: string[];
  status: InformationYieldV5GateStatusWire;
  observed: unknown;
  threshold: unknown;
  numerator: unknown;
  denominator: unknown;
  case_results: unknown[];
  reason_codes: string[];
}
export interface InformationYieldV5WireResponse {
  wire_version: 'information-yield-wire-5';
  publication: 'information-yield-v5';
  view: 'summary' | 'detail';
  evaluation_id: string;
  index_sha256: string;
  custody_sha256: string;
  result_sha256: string;
  verdict: 'pass' | 'reject' | 'inconclusive';
  counts: { planned: number; confirmation: number; development: number };
  evidence: {
    context_sha256: string;
    fact_set_sha256: string;
    policy_sha256: string;
    gate_authority_sha256: string;
    source_closure_sha256: string;
    claim_limits: string[];
    same_user_trust: 'integrity_and_nominal_issuance_only';
    same_user_limitations: string[];
  };
  outcomes: { richness: InformationYieldV5MetricWire; depth: InformationYieldV5MetricWire };
  populations: { C: string[]; D: string[]; E: string[]; N: [] };
  policy_gates: InformationYieldV5GateWire[];
  hard_failures: Array<{ case_id: string; code: string }>;
  cases: InformationYieldV5CaseWire[];
  selection: { case_id: string | null; arm: InformationYieldV5ArmIdWire | null };
  case: InformationYieldV5CaseWire | null;
  selected_arm: InformationYieldV5ArmWire | null;
  projection_state: 'fresh' | 'stale';
  read_only: true;
}
