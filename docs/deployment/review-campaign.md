# Six-hour review/capture continuation

`shared.job_runtime.review_campaign` is a separate temporary controller for
parent-staged acquisition A/B trace diagnosis and pooled reviews. It does not
reactivate the old A–F implementation campaign, resume the parent app thread,
perform native web acquisition, edit the checkout, or promote research results.

Use the existing `.research-sources/.venv/bin/python`, whose pinned source
requirements include `jsonschema`. The smaller job-runtime environment does not
include that package. No dependency installation or production environment
change is part of this controller. The configured default Codex model/effort,
authentication home and single authentication lock remain unchanged. CLI tools,
web, apps and MCP stay disabled. The controller explicitly loads the mentor
policy/router and records that manual load; this is not automatic hook proof.

The parent stages immutable public input records, policy records and work packets
under `.niulai-state/reports/research-sources/runtime/acquisition-ab-now-20261102/continuation/`:

- `public-inputs/`: allowlisted public trace facts, source quotations or review
  packets; no credentials, account data, protected gold pool or other-arm output.
- `policies/`: closed parent-owned deterministic postconditions, excluded from
  the model prompt; owner ID `root:review_campaign_v1`.
- `work/`: `schema_version`, `work_id`, kind, role, objective, named input
  ArtifactRefs, closed output schema and postcondition ArtifactRef.
- `model-outputs/`: immutable verified scoped results. These are not semantic
  truth guarantees or accepted investment research.

Kinds are `trace_diagnosis`, `pooled_review_order1`, `pooled_review_order2` and
`regression_review`. Deduplication binds input hashes, policy hash, role and kind.
Work IDs/timestamps alone cannot create progress. Output schema validation,
authentic completed model receipt/hash and every parent postcondition must pass.
Policies support bounded equality/input binding, required diagnostic codes,
input-hash binding, exact quoted-span checks that reopen hash-bound original
source bytes, and nonempty rationale checks; they cannot execute code.

Create, enqueue and install only for an explicitly authorized campaign:

```sh
.research-sources/.venv/bin/python -m shared.job_runtime.review_campaign create --name NAME
.research-sources/.venv/bin/python -m shared.job_runtime.review_campaign enqueue --state ABSOLUTE_STATE --packet-ref ARTIFACT_REF_JSON
.research-sources/.venv/bin/python -m shared.job_runtime.review_campaign install --state ABSOLUTE_STATE
```

`status`, `tick` and `stop` accept the same `--state`. All private controller
configuration, queue pointers, Engine slots, model logs, process identities and
receipts remain under `.job-runtime/review-campaigns/NAME/`. `stop` writes a
cancellation request; the model adapter terminates its owned process group.

The absolute TTL is six hours. Twelve one-time opportunities begin 90 seconds
after creation, then every 30 minutes, with 90-second grace and no catch-up.
The temporary workspace-resident launchd plist checks every 30 seconds and
unloads its own label at expiry/terminal state; it creates no login link.
Empty queue checks make zero model calls. Limits are six actual model starts,
360 seconds per slice (also capped by the existing model profile), 1,800
cumulative model seconds and a 400,000 observed input+output token stop. Token
usage is checked between calls; one call may exceed the remainder. This is not a
provider billing cap. Unknown usage or result stops immediately without replay.
Two no-progress results, two matching failures, repeated output hash, clock
rollback, changed source/profile pins or an unfinished prior intent also stop.

Enabled primary ready/running/retry/unknown slots and imminent daily business
work make review yield. An interval schedule alone does not reserve the entire
host forever. Disabled historical unknown fault slots remain untouched/fenced;
they are not replayed or called reconciled. The shared auth lock still decides
actual cache ownership, and an occupied lock yields without consuming a model
start. Cooperative yielding is not zero shared-resource interference.

The trusted optional `process_observer(pid)` model context hook records PID,
process birth and unique attempt directory before continuing. Callback failure
kills/reaps the newly owned child. Restart recovery kills only a matching saved
identity, then preserves the unknown result fence. It does not kill by PID alone.

Before claiming acceptance, require a new future-triggered actual Codex session
to process real staged trace evidence, independent result/source-span readback,
actual slot/attempt/thread/timing and verified owner email. An old probe or this
runbook is not acceptance. Six-hour endurance remains unverified until observed;
the first success establishes only its recorded review/capture path.

The initial trace packet is staged from the registered manual-final cold/warm
NOW manifests and a new replay readback, plus the captured margin case whose
review passed while its original execution was blocked. Its parent-owned
postconditions reopen the original source receipt and text bytes to check the
exact quoted span. The worker sees only bounded public projections; queue and
policy artifact hashes identify the actual candidate. This packet establishes
review/capture behavior rather than a fresh acquisition result.


Runtime replacement after a dependency change uses version
`review-continuation-1.0.1`. The controller now pins its direct
`shared/research_sources/artifacts.py` dependency alongside the existing runtime
and mentor sources. A mismatched pin stops before scheduler/model dispatch.
The v1 future success remains historical evidence; it does not validate bytes
loaded after that success.

Stop and unload only the predecessor's own label before replacement. `create`
accepts `--predecessor-state PATH` only for a stopped-manual predecessor without
an unfinished attempt. It inherits the original absolute expiry and consumed
calls, model seconds and observed tokens, retaining the original global ceilings.
Only finite opportunities before that expiry are created. The config records
predecessor configuration/state hashes and inherited usage. A repeated real
trace packet may verify the changed runtime; label this candidate revalidation,
not new research progress. A new future worker and independent readback are
required for the replacement before acceptance email synchronization.
