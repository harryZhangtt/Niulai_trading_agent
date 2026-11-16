# Trusted real-data and runtime boundary for factor mining

**Status:** IN PROGRESS — 2026-11-05; synthetic policy/data/authority/runner/evaluator lineage is accepted for fixture-only structure. Trusted external authority, real PIT evidence, isolated engines and every scientific/publication claim remain blocked.

## Objective

Replace the remaining synthetic trust assumptions with explicit, independently testable contracts for external authority, real point-in-time source attestation and prior-outcome exposure/fresh-split planning. Then admit exactly one development-only RD-Agent→Qlib E2E before baseline reproduction. No protected outcome is accessed in this plan until every authority, data, runtime and maturity gate is satisfied.

## Observed problem, benefit and minimum useful change

The local fixture chain now prevents relabeling and replay inside its narrow synthetic scope, but it is deletable/reprovisionable and authenticates no real provider, signer, runner, evaluator or protected custodian. A real run would therefore allow caller-supplied trust to masquerade as admission evidence.

The minimum useful next capability is not a live experiment. It is three provider-neutral contracts with fail-closed conformance tests:

1. trusted authority port and disabled deployment profile;
2. real-source inventory/attestation intake without downloading outcome data;
3. immutable outcome-exposure ledger plus fresh chronological split planner.

These contracts reduce integration uncertainty while preserving all current blockers. They do not establish that a provider, backend or signer is accepted.

## Accepted deliverables

- A versioned trusted-authority port separating durable checkpoint storage, signatures/key policy, recovery and current authorization lookup. All real methods fail closed until an accepted deployment profile supplies every dependency.
- A conformance harness covering checkpoint rollback/reset, key rotation/revocation, copied authority identities, stale authorization, unknown outcomes and purpose-specific publication.
- A strict real-source inventory and attestation-request contract for DFII5, BAMLC0A0CM, DFF, SPY and ONEQ inputs: provider/product/version, license/retention, authority/acquisition receipt, authenticated availability, revisions, security master/calendar, corporate actions, costs/cash and missingness.
- No credentials, downloaded values, private identifiers or protected labels in tracked records. Candidate sources remain `unverified` until separate authorized acquisition and receipt verification.
- A `T_seen` exposure ledger recording every known raw/summary/outcome exposure by immutable evidence reference and computing the conservative latest exposure cutoff without storing outcomes.
- A fresh-split planner deriving earliest possible validation/protected origins from `T_seen`, horizon, purge, embargo, requested origin counts and calendar identity. Insufficient coverage returns `inconclusive_awaiting_fresh_data`; it never backfills a protected split.
- An integration contract binding authority profile, source-attestation root, exposure-ledger root, frozen policy SHA and dataset identity into a non-sealable readiness record.
- Updated factor runbook, setup inventory and durable mentor handoff with exact tested/non-tested claims.

## Anti-overfitting invariants

- The inspected recent-three-year history remains development-only.
- New experiment/family IDs, paths, packaging, split names, models or sessions cannot reset the evaluation-population budget.
- `T_seen` is monotonic: new exposure may move it later; no operation moves it earlier or deletes history.
- Split membership is derived from attested calendar/universe/label-roster identities; no caller-supplied split hash is authoritative.
- Validation starts only after `T_seen + 126-session purge`; protected starts only after validation maturity plus 126-session purge and 21-session embargo.
- One candidate, one confirmatory variant, one protected use/look. Inconclusive consumes the protected population.
- A runner nonce is claimed before work. Unknown outcomes remain fenced.
- Metrics, triggers and verdicts come only from a trusted evaluator and independent receipt over the same evidence root.
- Performance, combination, EV and Kelly publication each require a current purpose-specific authorization; quarantine/revocation blocks future use.
- Missing evidence is Inconclusive or Blocked, never Pass. Fixture success is never factor-quality evidence.

## Architecture and ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| `tuning/factor_mining/trusted_authority/` | ports, strict deployment profile, conformance fixtures | credentials, active backend config, local fixture authority history |
| `factor/source_inventory/` | source/license/availability/retention attestations and readiness | market values, labels, credentials, provider execution |
| `tuning/factor_mining/exposure/` | monotonic `T_seen` ledger and fresh-split planning | outcome values, performance summaries, split publication |
| existing `factor/dataset/` | canonical PIT identities/materialization | acquisition or authority selection |
| existing admission authority/runner/evaluator | synthetic structural lineage | production trust or protected outcomes |
| later Linux runtime | isolated RD-Agent/Qlib execution | data truth, admission, UI or publication |

## Parallel file ownership for the first slice

- Authority agent: new files only under `tuning/factor_mining/trusted_authority/**`.
- Source agent: new files only under `factor/source_inventory/**`.
- Exposure agent: new files only under `tuning/factor_mining/exposure/**`.
- Main orchestrator: integration review, shared documentation, setup inventory and cross-contract tests after the three owners finish.

No parallel agent may edit existing guard, dataset, authority, adapter, evaluator, manifest, UI, setup or shared documentation files during its first pass.

## Phases

### Phase 0: Preserve accepted synthetic boundary
**Status:** complete

- Frozen admission policy: `d010b96585994ba2bc712ba96d580cbc2cd669b03bbf41eaeee2b855c53c0b9f`.
- Synthetic PIT contract and anti-relabel identities accepted.
- Development-only authority plus atomic nonce, outcome-free runner/evaluator and publication refusal accepted.
- Current UI is read-only and live registry remains empty.

### Phase 1: Provider-neutral trust and freshness contracts
**Status:** complete

- Implement the three parallel contracts and adversarial tests.
- Bind their readiness outputs without enabling any external backend or provider.
- Require explicit `blocked`/`unverified` status and null deployment identities.

Gate: all deterministic/adversarial suites pass; independent review finds no surviving defect within the blocked-contract claims.

### Phase 2: Select and provision external trust dependencies
**Status:** in_progress — GCP candidate frozen-disabled as `gcp-cloud-run-factor-mining-20261105-v1`; account provisioning and conformance remain pending

Decisions requiring owner authorization:

- durable checkpoint service/storage and rollback guarantees;
- signing algorithm, key custody, rotation/revocation and recovery owners;
- accepted runner/evaluator/independent-check identities;
- publication authorization service;
- real data providers/products/licenses/retention for every series;
- protected-label custodian and private capability path;
- accepted Linux execution platform.

Gate: deployment profile contains verified receipts/identities and no unresolved P0 blocker. Candidate config remains separate and disabled until accepted; do not hot-enable MCP or runtime services.

### Phase 3: Acquire and attest real PIT evidence
**Status:** pending

- Acquire only authorized sources through existing bounded acquisition contracts.
- Preserve raw/version/first-observed/available-at identities and license/retention receipts.
- Build stable observation, label-roster/commitment, feature and evaluation-population identities.
- Compute `T_seen` from the exposure ledger and derive fresh chronological memberships.

Gate: two cache-cold builds in different roots yield identical normalized identities; independent validator recomputes every public root; protected values remain private.

### Phase 4: Accepted isolated development E2E
**Status:** pending

- Finish hash-complete multiarch images, provider proxy and Linux runner acceptance.
- Seal one development-only request against the frozen policy and attested dataset.
- Run one RD-Agent proposal/coding step and one Qlib materialization/replay inside the accepted isolation.
- Publish implementation receipts only; no protected metric or promotion.

Gate: exact request/receipt/artifact reconciliation, clean cancellation/failure injection, two cache-cold deterministic runs, and future scheduled runtime/email acceptance if the change qualifies as major runtime behavior.

### Phase 5: Baseline reproduction
**Status:** pending

- Reproduce individual factors, joint signal, matched-exposure baseline, ablations, costs/cash/lags and account decisions on development evidence.
- Reconcile old share-reported metrics as discrepancies, not ground truth.

Gate: deterministic same-data/same-config replay and explicit predictive/economic verdict separation. No protected access.

### Phase 6: Fresh validation and protected confirmation
**Status:** pending

- Wait for all prescribed fresh origins and label maturity.
- Execute the single locked validation and terminal protected read through trusted receipts.
- Record Pass, Fail, Inconclusive or Quarantined. Stop after the terminal read.

Gate: complete evaluator/independent receipts, all triggers present, one protected use consumed and purpose-specific publication authorization. Pass permits a separate sizing protocol only; EV/Kelly remain separately gated.

## Acceptance evidence

- Canonical schemas/hashes and type-exact validators.
- Cross-process race, rollback, replay, symlink/path, stale checkpoint, revocation and unknown-outcome tests.
- Authority conformance against at least one accepted external backend before activation.
- Source inventory rejects unknown license/availability/retention for real use.
- Exposure ledger is append-only, monotonic and outcome-free.
- Split planner tests exact session calendars, maturity, purge/embargo, insufficient coverage and alias/repackaging attacks.
- No tracked credential/private path/outcome/metric leakage.
- Setup audit refresh/check only after all concurrent setup-sensitive hashes stabilize.
- Major runtime acceptance remains future-scheduled and email-synchronized; local tests never substitute for it.

## Explicit nonclaims

This plan selects and freezes a disabled GCP architecture and provider route but does not provision a billing account, project, backend, signer, provider entitlement or custodian. It does not authenticate historical data, run RD-Agent/Qlib, reproduce a baseline, evaluate a protected split, demonstrate alpha or authorize performance, EV or Kelly publication.

## Errors encountered

| Error | Resolution |
| --- | --- |
| Prior local authority could be reset by choosing/deleting a state root | Kept it development-only and made externally durable authority a mandatory Phase 2 dependency. |
| Synthetic runner initially read label-value artifacts while claiming no outcomes | Removed dataset reads from runner; authority attestation now precedes an outcome-free fixed worker. |
| Concurrent runners could execute before terminal-record race resolution | Added atomic nonce claim before work; unknown claims remain permanently fenced. |

## Next step

Phase 1 and the Phase 2 offline architecture/activation scopes are frozen-disabled by manifests `593b5d60…7188d` and `1c31c6ca…c29a`. Obtain the account-owned Google billing/login/project-prefix/location inputs, instantiate a disposable synthetic environment with APIs/resources still bounded, and collect account-side conformance receipts. Keep runtime invocation, publication and irreversible Bucket Lock disabled until the frozen gates and explicit owner approval clear.
