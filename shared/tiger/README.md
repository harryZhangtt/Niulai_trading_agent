# Tiger read-only gateway

Shared infrastructure owns the leased credential lifecycle and query API.
`niulai-runtime/niulai_runtime/tiger.py` delegates to this package for compatibility
and report execution. The preserved `niulai/holdings/niulai_tiger.py` is an explicit,
privately staged SDK dependency. The snapshot and private archive remain intact.

| Module | Responsibility |
| --- | --- |
| `bridge.py` | Native context/policy validation, remote lease, restore/checkpoint, local lock and crash fence |
| `queries.py` | Request validation, account selection, complete requested reads and normalized private artifacts |
| `worker.py` | One leased query per isolated child; pipe-only service context |
| `__main__.py` | Hidden TTY input and portal process-group cleanup |
| `../market_data_mcp/adapters/tiger.mjs` | In-memory read-only MCP tools and bounded worker lifecycle |
| `../market_data_mcp/tiger-query.mjs` | Reuses `QueryPortal` with one attempt and no active host registration |

## Setup and use

Run from the workspace root. Reuse Python **3.12** and `tigeropen==3.8.0` from
[the Niulai runbook](../../docs/deployment/niulai.md), plus **Node >=22** and locked
npm dependencies from [the shared runbook](../../docs/deployment/shared-and-tuning.md).
No dependency pins or global installations are added. `shared/` must be on the
Python import path; commands run at the workspace root supply that path.
The launcher pins temporary files and Node's compile cache to
`.niulai-state/tmp/`; package caches remain in the documented local setup paths.

Provision `.niulai-state/config/tiger.json` as an owner-private **0600** regular
file with verified `project_id`, exact HTTPS `origin` and `owner_email`. Existing
policy values are retained. It contains no service bearer or broker token.
[config/tiger.example.json](config/tiger.example.json) describes the shape only;
its placeholders do not discover a service or grant access. Optional `taxonomy`
is only needed for reports.

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
  .niulai-state/.venv/bin/python -m shared.tiger \
  --tool snapshot --out "$PWD/.niulai-state/reports/tiger-UNIQUE-ATTEMPT"
```

Wait for hidden-input readiness. Supply a **fresh native Sites `get_site`
structured result for the configured project** through tool memory to hidden
stdin. Never put it in a shell command, environment, saved JSON, fixture or log.
The launcher validates the exact project, origin, owner and sole-owner audience,
then passes context through private pipes to Node and its Python worker. No HTTP
listener, Node credential file, browser login or host MCP registration is needed.
Python cannot independently obtain the host's Sites connection: this interactive
host adapter does not implement unattended service authentication.

| Tool | Arguments | Broker reads |
| --- | --- | --- |
| `positions` | Optional `security_types`: unique nonempty subset of `STK`, `OPT`, `FUT`, `FUND` | Account discovery and requested positions types |
| `assets` | `{}` | Account discovery and assets |
| `snapshot` | Same as positions | Account discovery, positions and assets |
| `market_snapshot` | Fixed roster-bound symbols, frozen contract hashes, as-of, field groups, currencies and corporate actions | Isolated QuoteClient reads; private raw files and sanitized receipt only |

Default types are `STK`, `OPT`, `FUT`. For a subset, pass
`--tool positions --args '{"security_types":["STK"]}'`. Account IDs, arbitrary
endpoints, orders and writes are rejected before credential acquisition. Exactly
one observed `STANDARD` account is required for account tools; ambiguity fails.
The additive `market_snapshot` calibration candidate branches before account
discovery, uses an isolated QuoteClient, rejects orders/trades/accounts/arbitrary
URLs and remains manual and unregistered. Transaction history and trading are not
exposed. Existing account read-scope validation is preserved.

Use a new output directory for each query. Stdout contains a sanitized receipt
and portal route. Private **0700** directories and **0600** files contain
`tiger_status.json`, `query.json` and requested `holdings.json`/`assets.json`.
Market calibration raw values and sampled identities remain private in
`market_raw.json`, `market_manifest.json` and `market_query.json`; the public
receipt contains only closed-schema counts, hashes and checkpoint/release state.
The envelope preserves source timestamps, decimal strings, unknown values and
coverage limits. Complete means all **requested** responses completed; it does
not establish whole-portfolio coverage or quote freshness. No cached fallback
substitutes for a failed read. Partial payloads remain private evidence and fail
the query; no successful envelope is written for them.

## Reliability and recovery

The existing remote private store is the single cross-runtime credential owner.
A local nonblocking lock prevents concurrent local use. Every SDK token save
checkpoints under the same lease, followed by a final committed checkpoint
requesting release. No independent refresh cache, consent flow or forced rotation
is added. A committed release request is not a separate lease-release receipt.

Only idempotent store acquire/checkpoint requests retry: three attempts, 15-second
timeouts, 1/2-second backoff, identical IDs and bytes. There is **one** portal/worker
attempt and no extra broker/OAuth retry. Deadlines are 100 seconds for the worker,
105 seconds for supervisor termination, 110/115 seconds for portal request/total
budgets and 125 seconds for the launcher. Termination escalates after 1.5 seconds;
launcher cleanup stops its process group. Slow providers may exceed these bounded
interactive budgets. The legacy direct/report CLI retains its longer deadline.

Uncertain acquisition, read, token persistence, interruption or checkpoint leaves
`.niulai-state/tiger/unresolved.json` and any private working profile. Later calls
stop before another lease. Preserve these files and reconcile with the existing
remote credential owner before removing a fence. Do not copy older tokens back,
retry through another route or assume consent expired. Definitive Sites 401/403
before acquisition does not leave an acquired-lease fence; obtain fresh native
service access. No recovery command guesses uncertain outcomes. The older cloud
task does not consult this local fence.

### Read-only owner acknowledgement diagnostic

`reconciliation.py` is a separate, manually invoked diagnostic. It cannot
acquire/release a lease, restore/read a profile, retire a fence, refresh a token or
query the broker. Its client contract is frozen in
[reconciliation-acceptance.md](reconciliation-acceptance.md); independent exact
Worker tests live in `tuning/trading_agent/reconciliation/`.
Offline proof receipts, temporary stores and Node caches stay in that component's
ignored `.runtime/` directory; they are not source fixtures or runtime credentials.
Do not invoke it against a new deployment without new exact-source no-write evidence.

The diagnostic is pinned to the recovered version-1 Worker source and saved
deployment. Obtain fresh native `get_site`, `get_site_version` and successful
`get_deployment_status` structured results for the configured project. An
authenticated host supplies exactly `{site, version, deployment}` through hidden
stdin, from tool memory. No bearer or source credential is saved. The original
checkpoint fence is read/hashed while the existing local bridge lock is held.

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
  .niulai-state/.venv/bin/python -m shared.tiger.reconciliation \
  --source .niulai-state/PATH-TO-EXACT-RECOVERED-WORKER/index.js \
  --out .niulai-state/reports/UNIQUE-READBACK
```

The source placeholder is not an installed file. Recover the exact existing Site
source through the supported Sites open-only helper, keep it owner-private, and
confirm its file SHA/commit and matching deployment before this command. The
helper's Git checkout may have 0644 source files even inside a private directory.
Stage an identical, newly owned 0600 Worker copy under `.niulai-state/` for this
diagnostic and verify the same SHA; preserve the retrieved checkout. The fence
and existing lock must also be owner-private regular files. Check permissions
before obtaining fresh service context. A rejected local preflight is not an
HTTP retry and must be retained separately.
The output directory must be new and its parent must already exist. A successful
readback is saved as `readback.json`; an unsuccessful invocation saves
only closed diagnostic fields in `readback-failure.json` in its newly owned output
directory. Existing reports are never replaced. Dependencies and
temporary paths are the same Python/stdlib environment as the gateway; no MCP,
listener, daemon, package or global configuration is added.

There are at most two HTTP requests: GET `/health`, then POST `/lease/checkpoint`
with only the original `commit_id` and `lease_id`. Each is attempted once, with a
15-second timeout, no redirects and a 64KiB body limit. The total post-input
deadline is 40 seconds. Health failure/uninitialized state skips the second
request. Responses are checked against closed scalar schemas; raw remote errors,
tokens, profile values and Site URLs are not output. The original fence/profile
are preserved even after an acknowledgement. Rollback is simply to stop using
this diagnostic; there are no changes to the active gateway or remote owner.

The recovered service retains only `last_commit`. Its idempotent branch checks
that commit ID before lease validation and reports release from the **current**
lease object. Therefore a matching acknowledgement recognizes the latest commit
only; it does not attest an original commit/lease tuple, historical release or
profile correctness. A rejected/unknown probe cannot prove the original commit
was absent. Lease expiry, a healthy service or a later revision never permits
automatic fence retirement. Remote historical commit readback is a remaining
recovery gap, not an implemented journal.

Remote encrypted custody remains the preferred sole credential owner. Current
native service access is host-provided, so it does not establish unattended
runtime access. The local working profile remains protected recovery evidence;
it is not an automatic failover credential owner. Do not add a competing local
refresh path after ambiguous remote persistence.

On 2026-11-16 the bounded live diagnostic made 2 HTTP requests without retries:
health reported initialized storage/no busy lease; the original commit-only
probe returned 409. The original fence remained byte-identical. This establishes
an available diagnostic route and unavailable original latest-commit recognition,
not broker authorization, historical commit absence or recovered holdings access.
The first local invocation rejected a 0644 source file before HTTP; an identical
0600 staged source corrected that preflight condition. The record is retained.
No broker query, credential write, fence retirement or new owner was performed.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
  .niulai-state/.venv/bin/python -m unittest discover -s shared/tiger/tests -v
node --test shared/market_data_mcp/tests/*.test.mjs
```

Offline checks cover request admission, audience/policy/path guards, partial reads,
concurrency, simulated rotation checkpoints, ambiguous commits, pipe secrecy,
malformed worker output and process cleanup. They do not prove live access.
On 2026-10-30 the gateway completed a live account snapshot, a fresh-process assets query
and a positions-only query, each with fresh native service context, real Tiger responses and
committed checkpoints. Receipts and data remain under `.niulai-state/reports/`;
account values stay out of source and docs. These runs prove current interactive
access and cold restoration, not continuous availability, actual token rotation
or unattended scheduler operation.


## Isolated market snapshot calibration candidate

`market_snapshot` is an offline-tested, manual calibration candidate. It accepts
exactly the frozen ordered calibration cohort of at most eight roster-bound US
symbols and binds the immutable selection document, validation receipt, cohort and
ordered-symbol hashes alongside calibration, promotion and roster hashes. Field groups, FX currencies and corporate-action types
are closed enums. Tiger SDK retries are disabled, the portal makes one attempt,
and uncertain outcomes retain the existing unresolved fence for reconciliation.

The QuoteClient branch never calls managed accounts or order methods. Yahoo is a
separate secondary cross-check and never replaces Tiger or establishes COMP
membership. Public receipts must use the closed schema in
`shared/research_sources/market_pilot.py`; raw provider values never leave the
private run root. A fixed-root private authorization ledger is atomically claimed
before StoreClient, credential lease or provider I/O. Success, failure, unresolved
outcome and interrupted claimed state remain consumed and reject replay; interrupted
claims require reconciliation. Promotion uses a separate authorization and requires
later explicit approval.
No active MCP registration, scheduler or production acceptance is established.


### Authorization issuance

Only the owner-controlled orchestrator may issue a calibration authorization, and
only after an explicit user approval record, the exact calibration-contract SHA
and the frozen cohort SHA have been independently checked. Query workers and MCP
tools must never call the issuance API automatically.

The issuer constructs the five-field receipt (`schema_version`, opaque
`authorization_id`, `calibration_contract_sha256`, `cohort_sha256`, `created_at`)
and calls `shared.tiger.authorization.create_authorization(workspace, receipt)`.
No credentials, account values or private paths belong in the receipt. The returned
public projection is checked for the same ID/hash and `unused` status before the
manual query is dispatched. Issuance proves only the user-authorized one-time
calibration scope; it does not prove provider availability, runtime acceptance or
promotion. A consumed or interrupted claim is never reissued or reset; reconcile
it under the existing private-state procedure.


### Selection hash semantics

Four hashes have distinct roles and must never be interchanged: the selection file
custody SHA binds stored bytes, the canonical-object SHA binds the private inline
`sample_selection` request, the calibration-cohort SHA binds the one-time
authorization, and the ordered-query-record SHA binds the actual requested symbols.
Offline custody validation checks the stored-file SHA. Before authorization claim or credential I/O, the provider gate checks the canonical-object, calibration-cohort and ordered-query-record hashes together with the frozen selection-contract and roster bindings.
