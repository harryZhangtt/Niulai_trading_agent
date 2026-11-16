# Evidence-permission quarantine and owner review plan

**Status:** QUARANTINED / MANUAL REVIEW — 2026-11-13. The user selected `unverified` status and `manual_review` retention for the three affected evidence stores. No bulk permission change, move, deletion, or automatic remediation is authorized.

## Decision, observed problem, and minimum useful change

A bounded historical metadata audit identified mixed or public-readable file modes in three evidence stores. The minimum safe response is a documentation and registry quarantine that removes any assumption that these stores are verified while each owning component prepares a private, reversible migration proposal. This preserves evidence and prevents a broad `chmod`, move, or delete operation from destroying provenance or making a public-safe artifact private without owner review.

The historical report is private runtime evidence at `.job-runtime/storage-governance/audit-20261112.json`, mode `0600`, with SHA-256 `ba8b760b8bc1233d06ca10c8fc8c7d90e0bbd56c0a8b5a8a7299331cbce50907`. Its advisory planner recorded `performed: false`. It is **pre-quarantine evidence**, not proof that the quarantined registry state or any later migration has been accepted. This documentation task did not run a new audit, create or replace a report, execute a retention action, or inspect file contents.

## Sanitized observed metadata

Only aggregate metadata is recorded here. Exact paths below each registered root, filenames, payloads, and a per-entry permission list remain private.

| Store / owner | Historical aggregate observation | Quarantine state |
| --- | --- | --- |
| `evaluation-evidence` / `tuning` | 50 files, 21 directories, 9,336,393 bytes; 30 files at `0644`, 20 files at `0600`; root/directories `0700` | `unverified`; `manual_review` |
| `investment-research-evidence` / `investment-research` | 461 files, 60 directories, 4,288,202 bytes; 5 files at `0644`, 456 files at `0600`; root/directories `0700` | `unverified`; `manual_review` |
| `ui-artifacts` / `ui` | 129 files, 1 directory, 15,207,193 bytes; files `0644`; root/directories `0755` | `unverified`; `manual_review` |

All observed entries had uid `501`. The bounded historical scan recorded zero scan errors, zero symlinks, and no truncation. Those observations apply only to that report's snapshot and do not authorize remediation or establish current state.

## Quarantine boundary

- Preserve all three stores in place. Do not bulk `chmod`, move, delete, archive, copy into source, or publish a normalized replacement.
- Treat the stores as unverified evidence with `manual_review` retention. They are not authority stores, and the quarantine does not transfer ownership.
- Require every future writer for private evidence to create regular files at exact mode `0600` and private directories at exact mode `0700`, including temporary and final publication paths. A writer change must be independently tested before it can prevent future drift.
- A genuinely public-safe UI artifact must be explicitly classified and published through a separate owner-approved public contract. Existing evidence is not made public-safe merely because it has mode `0644` or resides under a `0755` directory.
- Exact affected-entry inventories, backup manifests, and migration manifests are private runtime state. Store them in an owner-controlled `0700` directory with regular files at `0600`; do not add them to documentation, source control, command arguments, or logs.
- The storage-governance auditor and planner remain advisory. There is no automatic remediation path.

## Owner-specific work

Each owner must complete the same bounded contract independently; one owner's approval or successful canary does not approve another store.

### Tuning owner: `evaluation-evidence`

1. Privately inventory the exact entries whose observed or current mode differs from the intended private-evidence contract. Bind the inventory to the store root, capture time, entry identity, size, mode, owner, and content hash where safe, without reading protected holdout semantics for classification.
2. Classify each entry as private evaluation evidence or an explicitly public-safe artifact. Escalate ambiguous items; do not infer public safety from `0644`.
3. Confirm and test every active writer, temporary-file path, and final publication path for `0600` files and `0700` directories before proposing historical normalization.
4. Create a private backup and immutable private manifest, then prepare a finite migration candidate containing only owner-approved entries. The candidate must default to dry-run and reject unknown, changed, symlinked, missing, or out-of-root entries.
5. Exercise bounded canary, exact readback, and rollback. The tuning owner reviews the private inventory, classification, manifest, results, and residual exceptions before any status change.

### Investment-research owner: `investment-research-evidence`

1. Privately inventory exact affected entries while preserving research evidence identity, source coverage, finalization records, and immutable accepted artifacts.
2. Classify each entry as private research evidence or explicitly public-safe output. Public-safe classification requires the investment-research owner's review; a report's current readability is not approval.
3. Confirm maintained research finalization and all other active writers create private directories at `0700` and files at `0600`, including failure and retry paths.
4. Create a private backup and manifest before a finite, dry-run-first migration candidate. Reject changed identity/hash, unknown delivery or finalization state, symlinks, missing entries, and entries outside the sealed inventory.
5. Prove byte/hash preservation, exact permission readback, and rollback on a bounded canary. The investment-research owner must review any effect on completion/finalization evidence before authorization.

### UI owner: `ui-artifacts`

1. Privately inventory exact entries and classify each as private browser/acceptance evidence or a deliberately public-safe artifact.
2. Do not normalize the entire tree blindly. Private evidence moves only through a reviewed candidate to `0700` directories and `0600` files. Public-safe artifacts require a separate publication boundary and explicit owner approval rather than an in-place exception inferred from current modes.
3. Update and test all artifact writers, temporary paths, screenshot/trace exporters, and directory creators to use the selected private or separately approved public contract.
4. Create a private backup and manifest, then seal a bounded candidate to the approved entry identities. Reject changed, unknown, symlinked, missing, or out-of-root entries.
5. Prove visual/consumer usability where relevant, byte/hash preservation, exact permission readback, and rollback on a bounded canary. The UI owner reviews classifications and residual public-safe exceptions.

## Current future-writer controls (not migration acceptance)

The owner plan and quarantine disposition remain unchanged after future-writer
hardening:

- Tuning now fails every normalized future `.job-runtime/evaluations/...`
  `run_codex` request before launch with
  `MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE`. Strict containment is not
  active; generic non-evaluation invocations retain detached-descendant risk.
- Investment research now has descriptor-bound exact-`0700`/`0600` future
  artifact publication, immutable CAS plus one authoritative pointer, unknown-
  outcome fencing, buffered producer validation and final source-coverage
  revalidation. Existing permissive CAS files are rejected. Historical evidence
  and existing SQLite databases/sidecars are outside this hardening claim.
- UI now has a create-only private publisher for
  `ui/artifacts/future-private-v1/...`, using stdin or stable exact-`0600`
  staging. The real historical `ui/artifacts` root remains `0755`, so default
  publication fails closed. No replacement or public publication path exists; a
  post-link failure requires reconciliation and no blind retry.

Passing source tests for these controls is provider-free implementation evidence
only. It does not complete private inventory/classification, backup, migration
canary, rollback, owner review, future scheduled/email acceptance or a new audit.
All three stores therefore remain `unverified`/`manual_review`.

## Migration candidate contract

A future candidate is a separate implementation owned by the applicable component, not by this documentation task.

- **Input:** one owner-approved private inventory and classification, bound to exact root and entry identities.
- **Output:** a private result manifest recording attempted entries, before/after modes, unchanged content identities, skipped/rejected entries, errors, and rollback outcome.
- **Side effects:** only the finite approved entries for one owner; no cross-store batch, move, deletion, retention, or payload rewrite.
- **Failure behavior:** stop on drift, ambiguity, symlink, owner mismatch, hash/identity mismatch, backup failure, readback failure, or unknown outcome. Preserve diagnostic and recovery access without retrying a possibly completed mutation.
- **Activation:** disabled/dry-run by default. A separate explicit owner authorization is required for each store and each bounded batch.

## Recovery and rollback

1. Fence an unknown outcome. Reconcile the private result manifest and filesystem metadata before any retry.
2. Preserve the original store and private backup until owner acceptance. Never use the historical audit report itself as a restoration payload.
3. Roll back only the attempted finite batch from its sealed before-state manifest. Read back entry identity, content hash/size, owner, type, and exact mode after rollback.
4. If rollback cannot restore an entry exactly, keep the store `unverified`/`manual_review`, stop further batches, preserve both manifests, and escalate to the owning component.
5. Keep prompts, task notifications, read-only diagnosis, and recovery available throughout any future migration. A permission migration must not block recovery access to its own manifest or backup.

## Acceptance gates

No store may leave quarantine until its owner records all of the following:

1. A complete private exact-entry inventory with no scan errors, symlinks, truncation, unknown entries, or unresolved identity drift.
2. Explicit owner-approved classification of every affected entry as private evidence or separately public-safe artifact.
3. Tests and observed readback showing every future private writer creates `0600` files and `0700` directories on success, failure, retry, and atomic replacement paths.
4. A restorable private backup and immutable private manifest created before mutation.
5. A dry-run whose sealed set exactly matches the approved inventory, followed by a bounded canary with no payload/content-identity change.
6. Exact post-change readback of type, owner, mode, size/hash, writer behavior, and relevant consumer usability.
7. A tested rollback from the canary and reconciliation of any unknown outcome before replay.
8. Owner review of results and residual exceptions, followed by a separate explicit authorization for any remaining batches.
9. Side-effect-free registry validation and applicable component tests. If a future migration changes a major runtime capability, its intended future-triggered scheduled session and verified email acceptance remain separately required.
10. A new post-migration metadata audit and advisory report only when separately authorized. The pre-quarantine report cannot satisfy this gate.

Until all gates pass for a store, its only allowed claim is: quarantined, unverified, retained for manual review, and not automatically remediated.

## Expected registry state

The expected final registry count after applying this quarantine is 16 total stores: 10 current workspace stores, 1 planned workspace store, 4 unverified workspace stores, and 1 external unverified store. The three stores in this plan account for the increase from one to four unverified workspace stores.
