# Factor-mining research and observability

## Current status

The local factor-mining capability is **source-only plus frozen-disabled GCP architecture and synthetic boundary verification**:

- RD-Agent `v1.0.0` is pinned at `484776c…`.
- Qlib is separately pinned at RD-Agent's required `2fb9380…`; Qlib `v0.9.8` is a standalone compatibility candidate and must not replace it silently.
- Full upstream checkouts live under ignored `factor/runtime/upstream/`; pinned commit objects are hydrated and pass `git fsck --full`, while tracked identities, trees, file counts and license hashes live in `factor/upstream/sources.lock.json`.
- No RD-Agent/Qlib package is installed or imported, no real factor loop has run, and no historical factor result has been reproduced locally.
- The immutable run registry is private under `factor/runtime/registry/`. It is currently empty by design; product routes never seed fixture data.

Unmodified RD-Agent `fin_factor` is not upstream-faithful on this macOS arm64 host. The pinned path requires Docker or Conda, later forces `QTDockerEnv`, and uses GNU `timeout`; this host has none of those. Do not substitute the existing Python 3.12 environment, Qlib v0.9.8, Homebrew/global state, Rosetta or PATH shims and call it RD-Agent execution.

The selected lightweight production candidate is GCP Cloud Run Jobs with Cloud Storage, Cloud KMS and Workflows, separated across control, execution and custody projects. Architecture/provider contracts are frozen-disabled as `gcp-cloud-run-factor-mining-20261105-v1` by `factor/deployment/gcp-freeze-v1.json` (SHA-256 `593b5d6078ff6bdcb8d4777ae7123ae754a373b55b4e47433a5e9acd7ba7188d`). The independently reviewed activation scaffold in `factor/deployment/gcp_activation/` validates that live freeze, emits 101 Terraform-JSON resources with literal `count:0`, keeps `apply_allowed=false`, uses five distinct purpose signer identities and places separately receipt-gated Bucket Lock last. It is separately frozen-disabled as `gcp-factor-activation-20261105-v1` by `factor/deployment/gcp-activation-freeze-v1.json` (SHA-256 `1c31c6ca4680a9272bed68cdf74376b4819654beb1260b2d7addbcc14f30c29a`). No Google account, billing project, credential, API, image or resource has been accessed or created. AWS and the generic Docker runner remain disabled comparison evidence, not the activation path.

## Boundaries

| Component | Responsibility |
| --- | --- |
| `factor/upstream/` | Read-only verification of pinned public sources and licenses |
| `factor/dataset/` | Synthetic PIT source/calendar/universe/vintage/label-roster contract and stable anti-relabel identities; no real provider claim |
| `tuning/factor_mining/` | Frozen blocked policy, historical guard, development-only authority, fixture evaluator receipts, global budgets, quarantine/remediation and promotion rules |
| `shared/factor_mining/manifest.py` | Immutable, content-addressed RunManifest v1/v2 registry; v1 stays frozen and v2 adds structured performance evidence |
| `investment/factor_mining/rdagent_adapter/` | Frozen v1 subprocess boundary plus v2 fixed outcome-free authority/nonce/receipt contract; no RD-Agent execution |
| `shared/factor_mining/projection.py` | Bounded, redacted, read-only manifest projection |
| `ui/datasource/src/factorMining/` | Read-only `/factor-mining` page; no run/retry/promote/edit actions |

Generated code is untrusted and is not accepted by the synthetic runner. The current runner executes only its fixed repository-owned fixture worker and verifies process-group cleanup; it is not an OS sandbox or future upstream worker. Child state is removed, verified artifacts are copied into host evidence paths, and only sanitized host receipts remain.

## Deterministic overfitting guard

Before any outcomes are viewed, seal a protocol that fixes the hypothesis, financial mechanism, point-in-time snapshot, chronological splits, factor transformations, model/execution, purge/embargo, matched baseline, multiplicity family/method/alpha, global variant cap, stopping rule, promotion gates and overfitting triggers.

The append-only ledger rejects hidden semantic retries, family-contract changes, protected-holdout reuse and unsupported EV/Kelly publication across process/session/model changes. A firing trigger quarantines evidence even after promotion. Continued research requires a parent-linked remediation protocol with a protected split unused by any ancestor; the original result remains quarantined.

See `tuning/factor_mining/README.md`. Guard state belongs under an ignored `runtime/` directory.

The initial pre-outcome policy is frozen at `tuning/factor_mining/admission_policy/initial-confirmatory-policy.json` (`d010b965…c0b9f`) but remains `draft_blocked` and non-sealable. The synthetic PIT builder derives observation-set, label-commitment, feature-snapshot, evaluation-population and split identities rather than trusting caller hashes. A development-only authority binds those identities to an atomically claimed one-time nonce, fixed outcome-free runner receipt and outcome-free evaluator receipt. Local atomic writes now separate pre-effect failure from `AUTHORITY_WRITE_DURABILITY_UNKNOWN`, retain intended bytes/hash/destination, reconcile exact landed event/checkpoint bytes before retry after link, replace or parent-fsync uncertainty, and recover exactly one valid chained event orphan under the authority lock after pre-effect checkpoint failure. This local chain is explicitly not production authority: hostile same-user process authenticity, externally durable checkpoints, trusted signers/recovery, real runner/evaluator/independent-check policies, protected-label custody and purpose-specific publication authorization remain unresolved. Deleting and reprovisioning the local fixture is not a valid budget reset or real-data workflow.

Provider-neutral Phase1 contracts define the trust boundary: `trusted_authority/` has candidate-disabled profiles and synthetic conformance harnesses; `factor/source_inventory/` keeps proposed input roles blocked behind exact entitlement, PIT and retention attestations; `exposure/` stores outcome-free semantic exposure references, derives subjects from the inventory's canonical entry/provider-route semantics, converts malformed inventory, enum shapes and filesystem failures into stable sanitized `ExposureError`, reconciles exact event/head bytes after `EXPOSURE_WRITE_DURABILITY_UNKNOWN`, derives monotonic `T_seen`, and emits only `blocked_nonsealable` fresh-split readiness. The selected GCP subprofiles bind create-only checkpoint chains, five purpose keys, independent evaluator/checker/two-approval publication, separate Cloud Run Jobs, restricted executor egress and exact-version aggregate outputs. These remain offline structural contracts: they cannot authenticate a provider, make a local ledger authoritative, provision GCP or permit a real run.

## Local read-only UI

The shared app exposes:

- `GET /api/factor-mining`
- `GET /api/factor-mining?run=<run-id>`
- `GET /api/factor-mining?run=<run-id>&manifest=<sha256>`
- <http://localhost:7270/factor-mining>

This route shares the Figma-derived research-operations chrome and tokens from
`ui/datasource/DESIGN.md` while retaining Factor mining's own adapter, request
state, view models and CSS modules. Mobile exact-performance rows keep the same
metric, unit, interval, sample, period, baseline and provenance fields as the
desktop table; reflow is presentation only. The real empty registry continues to
show `No run evidence` across the workflow rather than seeded charts or rankings.
See `ui/datasource/design-qa.md` for the cross-page visual and responsive record.

Only run IDs and immutable manifest hashes are accepted. Host/Origin and GET/HEAD-only controls are inherited from the existing loopback server. The API uses the existing project-local Python 3.12 environment to run the standard-library projection only; it does not import RD-Agent or Qlib. Requests have the existing 8-second/2MB/pending/singleflight/cache bounds and stale-last-good behavior.

The page distinguishes implementation, predictive, economic and publication gates; displays reported-vs-reproduced provenance, stages, resources, factors, failures, limitations and immutable artifact identities; and never returns artifact paths. Synthetic fixtures are visibly labelled, scalar fixture metrics are suppressed, and predictive/economic/publication gates remain withheld.

RunManifest v2 adds bounded structured performance records for standalone factors, combinations and leave-one-out observations. Available records require explicit metric/unit, point estimate, uncertainty method and bounds, sample definition, period, baseline and a same-manifest evaluation-artifact hash. The detail page groups only comparable metric/unit/period/baseline records on one point-and-interval axis and always provides an exact table equivalent. Missing, legacy, fixture-withheld and explicitly unavailable evidence render as different states; no absent number becomes zero. RunManifest v1 identities and validation remain unchanged, and legacy scalar values are never converted into uncertainty-bearing chart records.

Do not iframe the pinned upstreams into this page. Qlib has no native operational browser UI. RD-Agent's Streamlit surface reads path-selected traces, while its Vue/Flask surface is a privileged execution console that can upload inputs and start or stop jobs. The bounded native projection remains canonical. A future accepted isolated runtime may expose separately authenticated top-level operator deep links; token-bearing URLs and arbitrary upstream URLs must not enter manifests or frontend state.

After server code changes, stop the verified owning foreground process and restart it from the workspace root:

```sh
pnpm -w run dev
```

A matching current process is reused; an old or foreign process is never killed automatically. `pnpm -w run dev:status` verifies the current fingerprint. The registry can be truthfully empty.

## Verification

From the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B factor/upstream/verify.py
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m factor.docker.verify
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s factor/dataset/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tuning/factor_mining/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tuning/factor_mining/admission_policy/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s tuning/factor_mining/admission_authority/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s tuning/factor_mining/evaluator/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s tuning/factor_mining/trusted_authority/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s tuning/factor_mining/trusted_authority/gcp/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s factor/docker/gcp/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s factor/source_inventory/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest factor.deployment.tests.test_gcp_freeze -v
python3 -B -m factor.deployment.gcp_freeze
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s factor/deployment/gcp_activation/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s tuning/factor_mining/exposure/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s shared/factor_mining/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s investment/factor_mining/rdagent_adapter/tests -v
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover -s investment/factor_mining/rdagent_adapter/v2/tests -v
node --test ui/datasource/tests/*.test.mjs
pnpm --dir ui/datasource run build
PLAYWRIGHT_BROWSERS_PATH="$PWD/ui/runtime/browsers" \
  ui/verification/node_modules/.bin/playwright test \
  -c ui/datasource/playwright.config.mjs
python3 -B shared/setup_audit.py --check
```

Verified locally on the current tree: 3 pinned-source tests; 6 blocked-Docker comparison tests; 32 synthetic PIT dataset tests; 31 historical guard tests; 8 frozen admission-policy tests; 19 development-authority tests; 13 runner-v2 tests; 8 evaluator/integration tests; 10 provider-neutral authority-port tests; 8 GCP authority tests; 8 GCP Cloud Run/output tests; 29 source-inventory/PIT/total-return tests; 4 GCP freeze-validator tests; 11 disabled activation/IaC tests; 23 exposure/freshness tests; 21 manifest tests; 7 projection tests; and the existing adapter/server/UI suites. The frozen GCP architecture suite passed 49/49 and the activation scaffold passed 11/11; independent adversarial reviews found no surviving defect within those selected-disabled claims. These are structural/offline results, not account-side conformance or runtime acceptance. Browser artifacts remain ignored under `ui/runtime/`.

The 2026-11-07 O1 security correction passed 19/19 development-authority tests and 23/23 exposure/freshness tests with `ResourceWarning` promoted to error; the transitive runner-v2 and evaluator suites also passed 13/13 and 8/8. Frozen identities for this result are authority policy `ed5ab71c758489d8e3c3917794a80054abe5c31d5885fc8c808b5535986c0d81`, authority genesis `e13a6f0d6c55d7a482dfaeb85657406df2418e72850015a3950cfca724693ce5`, authority implementation `236464fef3ebcc60015923622065c0ac1493ae9f3f2ddad04f78acf271ee7fea`, transitive runner implementation `6cd7ee81abe53bfc06c5e3918710730a191141f4eb80723f383ca35a4ead5989`, transitive evaluator implementation `d2f706f416a6ac5ae8a17de0e03cf8fceada4b0812cdb07228edef81e225ecf3`, source-inventory semantic identity `fd9526a7ac297d0a0803d250bf7b01420397c90b547a58112adf1f1363907f19`, and exposure contract file SHA-256 `59b2679ccf30f52af5c366d3ec362e4126b3e152355ec4620414f63de35182e4`. Authority remains `development-only-blocked`; exposure remains `blocked_nonsealable`. These hashes and local fault injections do not establish hostile same-user process authenticity, external durability, protected-data custody, provider activation, factor activation or runtime acceptance.

Final live readback on 2026-11-04 reports the verified localhost:7270 workspace server as `ready` and `read_only`. `GET /api/factor-mining` returned the actual fresh empty registry (`status:"empty"`, no runs or warnings), and `/factor-mining` served the Vite application shell. This proves live empty-route activation only; structured performance rendering remains browser-fixture evidence until a real sanitized RunManifest v2 is published.

The 2026-11-05 visual/responsive pass verified all 17 Factor browser cases inside
the 64-case combined suite, including 320px with 200% text, exact run identities,
late-response isolation, detail polling, stale/partial states, mobile Back focus
and the real empty registry. The exact performance table reflows into labelled
mobile rows while preserving every metric, interval, sample, period, baseline and
evidence field. Focused 1440/390/320 captures and loading/error/stale fixtures are
under `ui/runtime/factor-mobile-audit-20261105/`. These are UI fixture and empty-
registry checks, not real factor-performance or admission evidence.

## Research status

No factor currently qualifies for a recession-entry, positive-EV buy, or position-size decision. Share-reported results remain unverified: forecast gains did not consistently improve post-cost wealth, confidence intervals crossed zero, and recent effective sample size/multiplicity were inadequate. EV and half-Kelly remain withheld until a point-in-time baseline is locally reproduced and a protected economic gate passes.

### Probability authority provider-free experiment (2026-11-07)

A standalone experiment under `tuning/probability_guard_experiment/` tests a process-owned issuance/evidence chronology and MACed receipts. It passed its bounded synthetic falsifier matrix and independent review, but has no durable key management, hostile same-user security, crash recovery, protected production cohort or L3/L4/factor authorization. O0 blocked remains the default.
