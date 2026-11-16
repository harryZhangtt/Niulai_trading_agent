# Storage Governance MVP

## Status and scope

The provider-free Storage Governance MVP is implemented in
`shared/storage_governance/` using only the Python standard library. Its current
scope is a strict source-controlled registry, one retained `WorkspaceSnapshot`
opened by `open_registry_snapshot`, a bounded read-only metadata audit, an
advisory retention planner, and fd-relative atomic private report publication
through that same snapshot. It is not a storage provider,
database migration, retention executor, daemon, scheduler job, or single
persistence plane.

Implementation and hardened contract tests exist. A historical private metadata
audit exists at `.job-runtime/storage-governance/audit-20261112.json` (mode
`0600`, SHA-256
`ba8b760b8bc1233d06ca10c8fc8c7d90e0bbd56c0a8b5a8a7299331cbce50907`); its
planner recorded `performed: false`. It is pre-quarantine evidence, not acceptance
of the quarantined state. This documentation task ran no new audit, created no
report, and performed no archive, deletion, retention, permission, provider, or
scheduled-runtime action. The CLI remains inert until an operator invokes it.
Registry status is descriptive:
`current` does not prove existence or audit completion, `planned` does not grant
write or authority status, and `unverified` routes to manual review.

## Roles and ownership

A store may have one or more ordered roles, subject to the registry contract:

- **authority**: canonical state for the declared owner's domain. Authority may
  not coexist with cache or projection, may not appear on a planned or unverified
  store, and may derive only from sources owned by the same owner. That ownership
  rule is checked across the full transitive derivation graph, not just direct
  parents.
- **evidence**: retained records that support audit, evaluation, delivery,
  research, or runtime claims. Evidence is not automatically an authority.
- **cache**: rebuildable, non-authoritative state. A cache finding can only lead
  to advisory review; the MVP does not clear it.
- **credential**: the private location owned by a credential lifecycle. The
  registry stores metadata and relative references only, never credential values.
  Credential stores must be restricted, use the credential retention class, and
  declare generated mode `0600`.
- **reference**: definitions, policies, corpora, or operator inputs consulted by
  another component. A reference is not promoted to authority by being read.
- **projection**: generated or derived state for consumption or display. A
  projection cannot share the authority role.

There is deliberately **no single persistence plane**. Each component keeps its
own authority, writer model, durability, backup unit, retention class, and owner.
The registry describes those boundaries and derivations; it does not copy,
centralize, migrate, or mediate writes to the registered stores.

## Factual registry

`shared/storage_governance/registry.json` is the source-controlled Registry v1.
It currently records these factual roots; paths are workspace-relative logical
references, not portable private payloads:

| Store | Root | Status | Roles | Owner |
| --- | --- | --- | --- | --- |
| `scheduler-ledger` | `.job-runtime/engine/schedule.sqlite` | current | authority, evidence | `job-runtime-scheduler` |
| `delivery-outbox` | `.niulai-state/databases/outbox.sqlite` | current | authority, evidence | `delivery-runtime` |
| `evaluation-definitions` | `tuning/evals` | current | evidence, reference | `tuning` |
| `evaluation-evidence` | `.job-runtime/evaluations` | unverified | evidence | `tuning` |
| `knowledge-corpus` | `mentor/references/llm-engineering` | current | reference | `mentor` |
| `agent-memory` | `agent-memory` | unverified external | reference | `agent-memory-host` |
| `investment-alerts-input` | `.niulai-state/daily-inputs/current/alerts.json` | current | authority, reference | `investment-daily-policy` |
| `investment-alert-runtime` | `.niulai-state/daily-inputs/current/alerts.sqlite` | current | authority, evidence | `investment-alert-runtime` |
| `investment-daily-prices` | `.niulai-state/databases/daily-prices.sqlite` | current | authority, evidence | `investment-daily-prices` |
| `investment-research-evidence` | `.niulai-state/reports/investment-research` | unverified | evidence | `investment-research` |
| `factor-registry` | `factor/runtime/registry` | planned | evidence, reference | `factor-mining` |
| `job-runtime-credentials` | `.job-runtime/credentials` | current | credential | `job-runtime` |
| `market-data-credentials` | `.market-data-mcp/credentials` | current | credential | `market-data-adapter` |
| `market-data-schwab-credentials` | `.market-data-mcp/credentials.json` | current | credential | `market-data-adapter` |
| `ui-artifacts` | `ui/artifacts` | unverified | evidence | `ui` |
| `ui-runtime-cache` | `ui/runtime` | unverified | evidence, cache, projection | `ui` |

The registry has 16 stores in the quarantined state: 10 current workspace, 1
planned workspace, 4 unverified workspace, and 1 external unverified store. The
factor registry is planned and intentionally non-authoritative. The legacy Schwab
`credentials.json` file is separately registered alongside the credential
directory because the market-data manager still uses both roots. The three
evidence stores `evaluation-evidence`, `investment-research-evidence`, and
`ui-artifacts` are unverified with `manual_review` retention under the selected
permission quarantine. `ui/runtime` remains a separate unverified mixed
evidence/cache/projection store with `manual_review` retention—not a simple
rebuildable cache. The external agent-memory store remains unverified, externally
managed, non-authoritative, and outside the workspace scan.

## Evidence-permission quarantine

The user selected quarantine and owner review instead of bulk remediation. The
historical metadata aggregates were:

| Store | Files / directories / bytes | Historical mode observation |
| --- | --- | --- |
| `evaluation-evidence` | 50 / 21 / 9,336,393 | 30 files `0644`, 20 files `0600`; directories/root `0700` |
| `investment-research-evidence` | 461 / 60 / 4,288,202 | 5 files `0644`, 456 files `0600`; directories/root `0700` |
| `ui-artifacts` | 129 / 1 / 15,207,193 | files `0644`; directories/root `0755` |

All entries in that bounded observation had uid `501`; the report recorded zero
scan errors, symlinks, or truncation. These aggregate observations are historical,
not a current scan. Exact affected entries and payloads are intentionally omitted
from source documentation.

Do not bulk `chmod`, move, delete, archive, or automatically remediate these
stores. Each owner must privately inventory exact affected entries, classify
private evidence versus explicitly public-safe artifacts, and first ensure future
private writers create exact-`0600` files under exact-`0700` directories. Any
historical migration requires a private backup and manifest, a finite disabled/
dry-run-first candidate, identity and permission readback, tested rollback,
unknown-outcome reconciliation, and explicit owner review. Public-safe UI output
requires a separate owner-approved publication contract; current readability is
not approval. See the
[evidence-permission quarantine plan](../plans/storage-governance-evidence-permissions.md)
for owner-specific steps and acceptance gates.

The validator rejects unknown or duplicate fields, duplicate identifiers and
roots, malformed JSON constants or duplicate keys, absolute/private/non-normalized
roots, invalid roles or permissions, planned/unverified authority, unknown or
cyclic derivations, and direct or transitive cross-owner authority. Registry
loading opens every workspace/registry path component with no-follow descriptor
operations, reads the already-opened regular-file descriptor under a 1 MiB bound,
and rejects identity, size, or modification changes during the read. The retained
workspace descriptor and device/inode identity survive registry read, every store
scan, and CLI report publication; verification before/between phases fails closed
if the caller-visible path is retargeted. A path swap does not redirect the bytes
being validated.

Registry strings are screened for private absolute paths and several common
credential shapes, including private-key markers, key/token prefixes such as
`gho_`, Google-style `AIza`, Slack-style `xapp-`, JWT-like values,
authorization/cookie headers, and credential-bearing URLs. This finite list is a
bounded defense-in-depth screen, **not exhaustive secret detection or DLP**. The
registry contract still requires metadata and references only; a string passing
the patterns is not evidence that it is safe to store.

## Future-writer hardening status

The three selected stores remain `unverified` with `manual_review` retention,
and the owner migration plan above is unchanged. The following source contracts
reduce future drift but do not normalize history or satisfy the migration and
post-migration audit gates:

- **Evaluation evidence:** every normalized future `run_codex` target beneath
  `.job-runtime/evaluations/`, including `..` aliases, fails before launch with
  `MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE` until strict containment
  exists. Future child umask, parent `fchmod`, and held-descriptor output checks
  are implemented, but generic non-evaluation paths still have detached-
  descendant risk and are not promoted.
- **Investment research:** future writes use descriptor-bound private
  directories, private temporary files, content-addressed immutable artifacts
  and one authoritative completion pointer at exact `0700`/`0600`. Existing
  permissive CAS entries fail closed; post-effect durability failures raise
  `PublicationOutcomeUnknown` for reconciliation; buffered producer output and
  final source-coverage revalidation protect publication. Historical evidence
  is unchanged. SQLite coverage is limited to a newly created primary file, not
  existing databases or sidecars.
- **UI artifacts:** the ignored confidential quarantine has a historical real
  root at `0755`, so the future publisher fails closed there unless the UI owner
  separately establishes its required exact-`0700` namespace. It only creates
  new paths under `ui/artifacts/future-private-v1/` from bounded stdin or stable
  exact-`0600` staging files. It never replaces an existing leaf; post-link
  failures return `outcome_unknown_reconcile_required` and require reconciliation
  before any new attempt. Public publishing is not implemented.

These are implemented/provider-free source and focused-test claims, not runtime
acceptance. No future-triggered scheduled session, owner migration, verified
email, or post-migration audit has accepted any of the three stores.

## Metadata-only bounded audit

The audit reads the registry and filesystem metadata only. It does not read a
registered file descriptor's payload, connect to SQLite, deserialize payloads,
contact a provider, or inspect an external store. The sanitized store-level result
contains the store identifier, existence/root type, file/directory/other counts,
aggregate bytes, permission categories, symlink indicators, sanitized scan-error
counts, SQLite sidecar metadata, truncation state, role classifications,
status/retention class, and metadata-evaluable migration-trigger observations.
Permission findings include owner mismatch and type-specific owner mismatch, plus
an exact generated-mode mismatch for regular files whose registry entry declares
`generated_file_mode`. It omits filenames, physical report paths, payloads, and
raw exception text.

Traversal is descriptor-relative and no-follow from the retained workspace
snapshot at the registered root and below it. The snapshot is verified before
each store and after the scan set. Directories are visited depth-first after
closing each `scandir` iterator, so only descriptors along the active depth path
remain open. Errors are classified
by errno: `ELOOP`/`ENOTDIR` as symlink-or-race, `EACCES`/`EPERM` as unreadable,
`EMFILE` as resource limit, and other errors as a sanitized other/scan-error
finding. Unreadable, resource-limited, and other failures truncate the scan rather
than being reported as complete.

For a registered SQLite file, the scanner also stats only the exact sibling names
`-journal`, `-wal`, and `-shm` relative to the held parent descriptor. It records
bounded counts, aggregate bytes, permissions, symlink indicators, and sanitized
error counts, and includes regular sidecar sizes in store totals. It never opens
or reads the database or sidecar contents; a lookalike such as `.sqlite.wal` is not
an exact sidecar.

Per-store defaults are 10,000 examined entries, depth 20, and 1 TiB aggregate
bytes; all limits must be positive and can be lowered on the CLI. Reaching a bound
marks the scan truncated. Missing roots, external or unverified stores, symlinks,
permission/error findings, or truncated scans route to manual review.

Migration-trigger observations are metric-specific and tri-state. `exists` and
`missing` are evaluable whenever `exists` is an actual boolean. `scan_truncated`
is evaluable for an inspected workspace snapshot. A positive symlink or permission
finding remains evaluable on an incomplete inspected snapshot, but a negative
symlink or permission result requires a complete inspected snapshot. File count
and aggregate bytes also require a complete inspected snapshot. Here, complete
means known-present, non-error/non-symlink root with no truncation; external and
workspace-unverified stores are uninspected, so their scan-derived metrics remain
`observed: null` with `not_evaluable_from_metadata`.

## Advisory planner and zero-delete boundary

The planner emits only `retain`, `archive`, `rebuildable-cache-review`, or
`manual-review`, always with `performed: false`. A `manual_review` retention class
or any status other than `current` is routed to `manual-review` before other
classification rules. `archive` is a recommendation, not an archive operation. Neither the auditor nor planner deletes, moves,
archives, truncates, rewrites, or changes permissions on any registered store.
Contract tests fence mutating filesystem calls and verify that source data remains.

The only supported mutation is optional report publication. Report writing may
atomically replace the operator-selected report filename and may clean up its own
incomplete temporary file after an error; this is outside the registered-store
retention plane. Replacing a report path does not chmod or mutate a prior symlink
or hardlink target. No command that executes a retention action exists in this MVP.

## Private reports and modes

The CLI combines the metadata audit and advisory plan, then atomically writes one
JSON report beneath:

```text
.job-runtime/storage-governance/<simple-name>.json
```

Publication reuses the retained workspace snapshot and is bound to held
descriptors for the workspace, `.job-runtime`, and `storage-governance`
directories. The workspace must be the retained real directory, owned by the
current user, and not group- or world-writable; ordinary owner-controlled `0755`
is accepted. `.job-runtime` and `storage-governance` must each be real,
owner-owned, exact-`0700` directories. No-follow opens and repeated
path-to-descriptor identity checks detect symlink or retarget races before and
after replacement. The temporary report is exclusively created fd-relative as an
owner-owned regular file with mode `0600` and one hard link. The final
`os.replace` uses the held output descriptor for both source and destination,
followed by directory fsync and another chain check.

Output names must be simple `.json` basenames without control characters. A failed
scan or validation happens before publication; a failed publish removes its own
temporary file and leaves no partial JSON result. Cleanup attempts every held
report and owned-snapshot descriptor. If work already failed, cleanup errors are
suppressed so the primary error is preserved; without a primary error, the first
cleanup failure is surfaced. Treat generated reports as
private runtime state: do not commit, copy into setup inventory, or paste into
documentation.

## Commands

Run from the workspace root. Registry validation is side-effect free:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -c \
  'from pathlib import Path; from shared.storage_governance import load_registry; root=Path.cwd(); load_registry(root / "shared/storage_governance/registry.json", root)'
```

Run the focused standard-library tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s shared/storage_governance/tests -p 'test_*.py' -v
```

An explicitly authorized operator can generate a real private metadata report and
advisory plan with the following command. This performs no retention action, but
it enumerates metadata across registered workspace roots and writes private
runtime state. The CLI retains one snapshot across registry read, audit, plan, and
publication. The historical 2026-11-12 report is pre-quarantine evidence; this
documentation task intentionally did not run this command or create a new report:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m shared.storage_governance.audit \
  --registry shared/storage_governance/registry.json \
  --workspace "$PWD" \
  --output-name audit.json \
  --max-files 10000 \
  --max-depth 20 \
  --max-bytes 1099511627776
```

The CLI returns `0` on publication success. Invalid registry, bounds, output name,
path/mode/owner errors, or supported I/O failures return `2` with the sanitized
message `storage governance audit failed`; no sensitive exception is printed.
Programmatic validation raises a stable `RegistryError` code for contract
violations.

## Recovery

1. Do not infer success from an old report. Confirm the CLI exit status and the
   intended private report name.
2. For registry failures, repair the source-controlled metadata rather than the
   private store, then rerun side-effect-free registry validation and focused tests.
3. For missing, permission, symlink/race, scan-error, truncation, external, or
   unverified findings, preserve the store and investigate with its owner. Do not
   turn `not_evaluable_from_metadata` into a negative observation.
4. For report publication failure, verify that the workspace is real,
   current-user-owned, and not group/world writable (`0755` is acceptable), while
   `.job-runtime` and the fixed output directory are owner-owned exact-`0700`.
   Reconcile any prior complete report before retrying the same name; do not work
   around snapshot or descriptor-binding failures with symlinks.
5. For a quarantined evidence store, fence any unknown migration outcome and
   reconcile its private manifest before retry. Preserve the original and private
   backup until exact entry identity, content hash/size, owner, type, and mode are
   read back. A failed rollback leaves that store `unverified`/`manual_review`.
6. Do not remove an evidence-permission quarantine until the owner has approved a
   complete private inventory and classification, future-writer `0600`/`0700`
   tests, private backup/manifest, bounded canary, exact readback, and rollback
   drill. A separately authorized post-migration audit is required; the historical
   report cannot satisfy that acceptance gate.
7. Retention advice requires a separately designed, reviewed, and authorized
   executor. Never translate an advisory `archive` or cache review into deletion
   by hand without owner-specific backup, authority, and recovery checks.

## Staged scaling guidance

Scale only after measuring a real workload or failure mode:

1. Keep **local SQLite** while execution is single-host and writes can be
   serialized or coordinated locally. SQLite documents its serverless/local fit
   and the cases where a client/server database is preferable:
   [Appropriate Uses For SQLite](https://www.sqlite.org/whentouse.html).
2. Move an owning store—not the whole registry—to **PostgreSQL** when measured
   multi-writer or multi-host requirements exceed the local SQLite design. Use
   PostgreSQL's official high-availability and replication guidance to design and
   test the actual topology:
   [High Availability, Load Balancing, and Replication](https://www.postgresql.org/docs/current/high-availability.html).
3. Add **object storage** only for immutable large artifacts whose measured size,
   transfer, or retention needs no longer fit local durable files. Keep authority,
   manifests, content identity, and publication fencing explicit; a bucket is not
   automatically the metadata authority.
4. Add a **queue** only for measured fan-out or backpressure. A queue does not
   become the authority, evidence ledger, or unknown-outcome reconciliation store.
5. Add a **durable workflow engine** only after long-lived execution demonstrates
   a checkpoint, retry, compensation, or recovery burden that local orchestration
   cannot safely carry. Temporal's workflow documentation describes the durable
   execution model; adopting it would still require a bounded provider-free
   experiment and separate runtime acceptance:
   [Temporal Workflows](https://docs.temporal.io/workflows).

These are migration triggers, not deployed dependencies. PostgreSQL, object
storage, a queue, and Temporal are planned options only; none is configured,
provisioned, or verified by this MVP.
