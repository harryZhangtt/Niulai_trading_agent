export type InformationYieldObservation =
  | { state: 'known'; value: number; unit: string }
  | { state: 'unavailable'; reasonCode: string }
  | { state: 'not_applicable'; reasonCode: string };
export interface InformationYieldMetric {
  mean: InformationYieldObservation; median: InformationYieldObservation; minimum: InformationYieldObservation;
  maximum: InformationYieldObservation; range: InformationYieldObservation; total: InformationYieldObservation;
  denominator: number; wins: number; ties: number; losses: number;
  leaveOneIssuerOut: Array<{ issuerId: string; mean: number | null }>;
}
export interface InformationYieldArm {
  richness: InformationYieldObservation; depth: InformationYieldObservation; precision: InformationYieldObservation;
  wallSeconds: InformationYieldObservation; lineages: InformationYieldObservation; criticalUnsupported: InformationYieldObservation;
  trace: string;
}
export interface InformationYieldCase {
  id: string; issuerId: string; subject: string | null; windowId: string; evidenceLevel: string; split: string;
  armOrder: ['B0', 'F'] | ['F', 'B0']; requestSha256: string; factSha256: string;
  deltaRichness: InformationYieldObservation; deltaDepth: InformationYieldObservation; lineageDelta: InformationYieldObservation;
  arms: { B0: InformationYieldArm; F: InformationYieldArm };
  hardFailures: Array<{ code: string; chainIds: string[] }>;
}
export interface InformationYieldGate { name: string; status: 'pass'|'fail'|'unknown'|'not_applicable'; observed: string; threshold: string; reasonCodes: string[] }
export interface InformationYieldViewModel {
  view: 'summary'|'detail'; evaluationId: string; resultSha256: string; registrySha256: string | null; indexSha256?: string; stale: boolean;
  verdict: 'pass'|'reject'|'inconclusive'; counts: { planned: number; confirmation: number; development: number };
  evidence: { contextSha256: string; factSetSha256: string; policySha256: string; sourceClosureSha256: string; summarySha256: string | null; custodySha256?: string; gateAuthoritySha256?: string; claimLimits: string[] };
  outcomes: { richness: InformationYieldMetric; depth: InformationYieldMetric };
  gates: InformationYieldGate[]; hardFailures: Array<{ caseId: string; code: string; chainIds: string[] }>;
  cases: InformationYieldCase[]; selectedCase: InformationYieldCase | null; selectedArm: InformationYieldArm | null;
  selection: { caseId: string | null; arm: 'B0'|'F'|null; run: string | null; source: string | null };
}
export type InformationYieldErrorKind = 'permission_denied'|'not_found'|'conflict'|'timeout'|'unavailable'|'schema_invalid';
