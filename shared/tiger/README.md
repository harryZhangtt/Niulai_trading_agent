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

Default types are `STK`, `OPT`, `FUT`. For a subset, pass
`--tool positions --args '{"security_types":["STK"]}'`. Account IDs, arbitrary
endpoints, orders and writes are rejected before credential acquisition. Exactly
one observed `STANDARD` account is required; ambiguity fails. Quotes, bars,
transaction history and trading are not exposed. Existing exact read-scope
validation is preserved; no wider consent is requested.

Use a new output directory for each query. Stdout contains a sanitized receipt
and portal route. Private **0700** directories and **0600** files contain
`tiger_status.json`, `query.json` and requested `holdings.json`/`assets.json`.
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

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
  .niulai-state/.venv/bin/python -m unittest discover -s shared/tiger/tests -v
node --test shared/market_data_mcp/tests/*.test.mjs
```

Offline checks cover request admission, audience/policy/path guards, partial reads,
concurrency, simulated rotation checkpoints, ambiguous commits, pipe secrecy,
malformed worker output and process cleanup. They do not prove live access.
On 2026-10-30 the gateway completed a live snapshot, a fresh-process assets query
and a positions-only query, each with fresh native service context, real Tiger responses and
committed checkpoints. Receipts and data remain under `.niulai-state/reports/`;
account values stay out of source and docs. These runs prove current interactive
access and cold restoration, not continuous availability, actual token rotation
or unattended scheduler operation.
