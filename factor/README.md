# Factor-mining integration

This component keeps external engines, project adapters, evaluation controls, runtime state and UI projection separate.

## Current status

RD-Agent and Qlib are **source-only**. Their pinned checkouts exist under ignored `factor/runtime/upstream/`; they have not been installed, imported, built, or executed. No historical factor metric from the shared ChatGPT thread has been reproduced locally yet.

Tracked provenance is in `upstream/sources.lock.json`. Verify without importing upstream code:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B factor/upstream/verify.py
```

Expected: `FACTOR_SOURCES_OK` with three profiles:

- RD-Agent `v1.0.0` (`484776c…`) for proposal/coding/feedback;
- Qlib `2fb9380…`, the revision pinned by RD-Agent `v1.0.0` in both its Dockerfile and environment builder;
- Qlib `v0.9.8` (`5435523…`) as a separate standalone compatibility candidate.

The two Qlib revisions must never share an environment, cache, Recorder store or result identity. The standalone candidate cannot replace RD-Agent's pinned revision without a separately recorded compatibility run.

## Intended boundaries

- `factor/runtime/`: ignored, untrusted upstream checkouts and later isolated build/runtime artifacts.
- `factor/upstream/`: tracked source identities, licenses and read-only verification.
- `factor/docker/`: scalable controller/executor policy. The lightweight GCP Cloud Run candidate is frozen-disabled; AWS remains superseded comparison evidence; no cloud runtime is provisioned.
- `factor/dataset/`: provider-free synthetic point-in-time contract, stable observation/evaluation identities, derived split fingerprints and deterministic materialization. It authenticates no real provider.
- `investment/factor_mining/rdagent_adapter/`: frozen v1 host-boundary contract plus fixture-only v2 authority/nonce/receipt binding. Neither path runs RD-Agent.
- `shared/qlib_bridge/`: project-owned Qlib subprocess/DTO boundary (deferred until an approved isolated Qlib environment exists).
- `tuning/factor_mining/`: deterministic experiment guard, frozen blocked admission policy, development-only authority, outcome-free evaluator receipts, overfitting quarantine/remediation and promotion controls.
- `shared/factor_mining/`: immutable RunManifest registry plus sanitized read-only projection.
- `ui/datasource/src/factorMining/`: sibling `/factor-mining` read-only view under localhost:7270.

Never import RD-Agent or Qlib into the datasource server/UI. Never deserialize upstream pickle artifacts in the host process. Generated factor code and downloaded datasets are untrusted inputs and must execute only in the eventual isolated runtime.

## Next acceptance step

The pre-outcome policy and synthetic PIT identities are frozen, and the fixture chain binds one local authority nonce through an outcome-free runner and evaluator receipt. The selected lightweight production candidate is GCP Cloud Run/Storage/KMS/Workflows and is frozen-disabled as `gcp-cloud-run-factor-mining-20261105-v1` by `factor/deployment/gcp-freeze-v1.json` (`593b5d60…7188d`); 60 architecture/provider files are pinned and any drift requires a new reviewed version. The separate activation scaffold validates the live freeze, models 101 inert Terraform resources with five purpose-separated signer identities, remains `apply_allowed:false`, and is itself frozen-disabled by manifest `1c31c6ca…c29a`; AWS is disabled comparison evidence. The next external step is account-owned Google billing/login/project/location input and disposable account-side conformance. No real RD-Agent→Qlib run, protected outcome, publication or Bucket Lock is authorized.
