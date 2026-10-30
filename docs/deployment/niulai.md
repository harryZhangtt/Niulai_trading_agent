# Niulai runtime deployment and migration

This guide covers `niulai-runtime/`, its explicit dependency on the preserved
`niulai/` source snapshot, and private `.niulai-state/`. For shared model,
scheduler, host supervision and retry infrastructure, use
[the job-runtime guide](job-runtime.md). Do not put those shared concerns into
Niulai's holdings or investment-research modules.

## What can be redeployed today

| Component | Implemented boundary | Deployment limitation |
| --- | --- | --- |
| `config.py`, `scheduler.py` | Recipient, NY timezone/slots, XNYS calendar, manual/production admission | Admission does not wake a process or verify scheduler ownership |
| `wake.py`, `job_adapter.py` | Readiness-only admission for a shared scheduler allocation | No source collection or email sending |
| `tiger.py` / `shared/tiger/` | Compatibility/report CLI and shared credential/query gateway | Requires a fresh authenticated native Sites result per invocation |
| `delivery.py` | Immutable MIME payload, atomic outbox claim, accepted/unknown/readback states | No standalone Gmail OAuth or SMTP transport |
| `replay.py` | Explicit manual resend and exact-content Gmail verification | Host must invoke the connected Gmail tool; historical payload is reused |
| Preserved holdings pipeline | Fresh source collection, calculations, HTML and PDF | Requires private taxonomy and authorized broker/source access |

A one-time full scheduled portfolio email has been verified through the separate
Codex business executor. A standalone Python Gmail OAuth sender and recurring
production-email cutover remain unimplemented.
The checked-in `jobs/daily-readiness.json` is a readiness allocation, not a
production-mail allocation. Its enabled flag does not prove that a scheduler is
installed. Inspect actual host status and durable run receipts separately.

A Codex-triggered resend from a locally materialized message does not invoke the
old Work task, but its report content is historical. A fresh Tiger run performs
new broker reads through the shared private credential store. Neither observation
establishes a fully independent, unattended replacement for the original workflow.

## Files and ownership

| Location | How to provision or move it |
| --- | --- |
| `niulai/`, `niulai-runtime/`, `shared/tiger/`, `shared/market_data_mcp/` | Deploy together from the same reviewed source revision |
| `niulai-private/` | Preserve as the original private archive; do not treat it as mutable runtime state or ship it with source |
| `.niulai-state/config/` | Recreate owner-private policy files from verified account/service metadata |
| `.niulai-state/databases/` | Transfer a consistent, access-controlled backup of the delivery ledger at cutover |
| `.niulai-state/reports/` | Private report/evidence artifacts; migrate only when explicitly needed |
| `.niulai-state/tiger/` | Working profiles, locks and unresolved-operation fences; reconcile before moving or deleting |
| `.niulai-state/.venv*`, `python/`, `bin/`, `.cache/`, `tmp/` | Rebuild on the target host; environments and managed-interpreter symlinks are not portable artifacts |
| `.job-runtime/` | Separate shared scheduler/model runtime state, documented in the shared guide |

The active workspace rules require runtime state to remain inside this workspace,
excluded from Git. Older archive guidance describing external credential directories
is historical; it does not authorize new writes outside the current workspace.
Private directories use mode `0700`, private files `0600`, and the owning user
must match the process account. Use an encrypted local disk. Do not put active
credential profiles in source, fixtures, Library reports, cloud sync or public logs.

## Recreate the local dependency environment

The currently exercised toolchain is Python `3.12.16` and the workspace-local
`uv` bootstrap `0.13.6`. Direct application dependencies are pinned through
`niulai-runtime/requirements.txt` to `niulai/holdings/requirements.txt`:

| Package | Direct pin |
| --- | --- |
| `tigeropen` | `3.8.0` |
| `exchange-calendars` | `4.11.2` |
| `pandas` | `2.2.3` |
| `reportlab` | `4.4.9` |
| `cryptography` | `50.0.2` |

These direct pins are not a complete transitive hash lock. A private resolved
package listing records what was installed; it does not guarantee identical
future resolution or wheels on another OS/architecture. Generate and validate a
platform-appropriate lock before claiming a reproducible production deployment.
Keep the supplied fonts and their license with the holdings rendering code.

From the workspace root, using an already available Python capable of creating a
venv, the following rebuilds dependencies without global package installation:

```sh
umask 077
mkdir -p .niulai-state/tmp .niulai-state/.cache/pip .niulai-state/.cache/uv \
  .niulai-state/python .niulai-state/bin .niulai-state/config \
  .niulai-state/reports .niulai-state/databases .niulai-state/logs
chmod 700 .niulai-state

export TMPDIR="$PWD/.niulai-state/tmp"
export PIP_CACHE_DIR="$PWD/.niulai-state/.cache/pip"
export UV_CACHE_DIR="$PWD/.niulai-state/.cache/uv"
export UV_PYTHON_INSTALL_DIR="$PWD/.niulai-state/python"
export UV_PYTHON_BIN_DIR="$PWD/.niulai-state/bin"

python3 -m venv .niulai-state/.venv-bootstrap
.niulai-state/.venv-bootstrap/bin/python -m pip install \
  --disable-pip-version-check --no-cache-dir uv==0.13.6
.niulai-state/.venv-bootstrap/bin/uv python install 3.12.16
.niulai-state/.venv-bootstrap/bin/uv venv --python 3.12.16 .niulai-state/.venv
.niulai-state/.venv-bootstrap/bin/uv pip install \
  --python .niulai-state/.venv/bin/python -r niulai-runtime/requirements.txt
```

Set both managed-interpreter directories explicitly: omitting
`UV_PYTHON_BIN_DIR` can create an executable link outside the workspace. These
exports apply only to the current shell; do not add them to a shell profile.
Do not replace an existing live environment or credential directory in place.
Stage and validate a new environment before selecting it for production.

## Provision policy and private metadata

Start from `niulai-runtime/config/runtime.example.json`. Its placeholders are
deliberately invalid. Save the completed policy below `.niulai-state/config/`
with private permissions. Obtain the recipient from the authenticated Gmail
profile, the existing production identity from verified task metadata, and
the expected scheduler owner from the selected deployment. Do not infer these
from archived scheduler IDs or copy a manual-test identity into production.

Preserve `America/New_York`, the existing `13:00`/`19:00` slots, the `60` minute
grace and actual `XNYS` calendar. Calendar lookup failures remain failures.
Keep `production_enabled: false` for installation and manual acceptance.
Use a separate dry-run policy for readiness; `wake.py` rejects manual-test or
production policies. Job allocation stays in `niulai-runtime/jobs/`; shared
model choice/retry/host policy stays in the shared runtime configuration.

Fresh report rendering needs an authorized private taxonomy file, selected by
the Tiger policy's `taxonomy` path. It is excluded from Git because it is
account-derived. Provision it through the approved private transfer route;
never replace a missing taxonomy with invented classifications or copy private
account data into a test fixture.

The private Tiger policy contains only verified `project_id`, exact HTTPS
`origin`, `owner_email`, and optional absolute workspace `taxonomy` path. Those
values must be rechecked on the target host. Source placeholders are not service
discovery and must not be used as endpoints.

## Tiger credential ownership and retries

For company research source selection and completion, the maintained
[`investment.research` entry points](../../investment/research/README.md) compose
a separately frozen evidence contract with the preserved Niulai finalization and
completion validators. Source acquisition lives in `shared/research_sources/`.
Deploy those sources together for new gated research; this does not modify the
original cloud task or the holdings/email sender.

The canonical bridge and tests live in `shared/tiger/`; the runtime CLI delegates
there. The [shared runbook](../../shared/tiger/README.md) documents the isolated MCP
query entry, using existing Node >=22 portal dependencies and this Python SDK
environment. It adds no dependency pins, listener, host registration or OAuth
cache. Use new private output paths. Complete requested reads are required;
partial responses fail while retaining private evidence. Broker retries stay zero.

The current bridge does not seed credentials or perform new consent. An
authenticated host obtains a fresh native Sites result for the exact private
project and passes that structured result through hidden TTY stdin. The bridge
checks the active owner identity, custom access, sole-owner audience, exact
origin, and absence of extra editors/groups/visitors before requesting a lease.
The native bearer remains in memory; do not save it as a scheduler secret or
put it in shell arguments, environment dumps or chat.

The remote private store coordinates the refresh owner. The official SDK keeps
the existing narrow read scope, rotates tokens as needed, and checkpoints token
persistence back to that same store. Do not create a second independent refresh
cache for the same transferred grant. A local lock serializes local bridge runs;
it does not replace the remote lease or control the older cloud task.

| Failure | Existing behavior |
| --- | --- |
| Transient private-store request | At most three attempts with bounded timeout/backoff and identical idempotency identifiers/body |
| Sites authorization rejection | No automatic repeated request; obtain fresh authorized native service access through the supported host |
| OAuth/broker uncertainty | No added blind broker-refresh retry or automatic reauthorization |
| Unconfirmed checkpoint or read outcome | Preserve the private profile and unresolved fence; stop for reconciliation |
| Verified broker grant rejection/expiry/revocation | Interactive owner reauthorization may be required; never request secrets pasted into chat |

The cloud task does not consult the local crash fence. Reconcile the remote
lease and any retained rotated profile before another owner proceeds. Do not
delete the fence or reseed old tokens to clear an error. A missing local directory
or failed Sites request is not evidence that the broker grant expired.
[Tiger documents a maximum OAuth authorization lifetime](https://docs-en.itigerup.com/docs/authentication);
refresh persistence reduces unnecessary login requests but does not make consent
permanent. Do not change authentication method or broaden scope to evade expiry.

For the actual TTY invocation and cold-restoration sequence, follow
[the operator procedure](../../niulai-runtime/docs/operator.md) and
[Tiger bridge details](../../niulai-runtime/docs/tiger.md). New output directories
must be private workspace paths. A partial report remains partial, with source
timestamps and unknown values preserved.

## Gmail, content parity and independent delivery

Python does not inherit the host's connected Gmail capability. The current
operator sequence validates the live Gmail profile, atomically claims the
prepared outbox payload, invokes the connected Gmail tool once, records its
actual immutable message ID, and reads that exact message back. See
[delivery semantics](../../niulai-runtime/docs/delivery.md).

The concurrent `niulai_runtime.e2e_delivery` helper provides manual-test outbox
prepare/claim/receipt/readback actions. It requires `manual_test` with production
disabled and still relies on the host for the actual authorized Gmail operation.
Its source presence is not activation or delivery evidence. This helper is outside
the Tiger query acceptance recorded by the shared gateway.

The exact-content replay uses a locally materialized original HTML body and two
actual PDF byte attachments. It does not collect fresh prices or holdings and
cannot complete a production slot. A changed test subject is an explicit
exception to subject parity; body and decoded PDF parity still require matching
hashes. The local resend can be independent of invoking the old Work task while
still reusing its historical report content.

Never interpret a claim, timeout, stale message with identical content, search
snippet or model statement as a new send receipt. `sending` and `unknown` entries
are not eligible for automatic resend. Verify the newly returned Gmail ID,
recipient, subject, full HTML and both attachments; exclude the source/older
same-content messages. Mailbox arrival and phone notification receipt are
separate facts.

A fully standalone deployment still needs its own supported Gmail authentication
and transport adapter, plus an unattended way to obtain fresh authorized broker
service access. Until those are implemented and tested, do not label the existing
connected-tool path a zero-dependency production replacement.

## Acceptance and cutover

Run the component tests using the rebuilt environment:

```sh
PYTHONPATH=niulai-runtime PYTHONDONTWRITEBYTECODE=1 \
TMPDIR="$PWD/.niulai-state/tmp" .niulai-state/.venv/bin/python \
  -m unittest discover -s niulai-runtime/tests -v
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/tmp" \
  .niulai-state/.venv/bin/python -m unittest discover -s shared/tiger/tests -v
```

Then separately verify private-policy rejection, actual-calendar admission,
fresh broker reads in two independent processes, confirmed credential commits,
fresh report generation with explicit gaps, and one authorized email with exact
readback. A successful credential checkpoint does not itself prove that a token
rotation occurred. Synthetic tests and manual sends do not establish an actual
unattended due-slot run. Keep per-run evidence in private state, not this guide;
never freeze real holdings counts, values, addresses or message IDs into docs.

Before a production switch, verify a replacement execution host and complete
fresh data/report/delivery interfaces. Import and reconcile previous per-channel
delivery records, then verify the old sender is disabled immediately before the
replacement sender is enabled. Preserve immutable IDs and slot dedup across
code/config revisions. Do not run two production senders to test the migration.

Rollback must keep the delivery ledger and uncertain outcomes. Disabling a
replacement scheduler does not authorize replaying its last slot through the
old workflow. Reconcile that slot first. Reinstalling packages or regenerating
host configuration must never reset credentials, outbox history or admission IDs.

## Keep this guide synchronized

Changes to Niulai dependency pins, policy schema, job allocation, broker/store
protocol, retry rules, state paths, Gmail transport, or cutover gates must update
this guide and the relevant component instructions in the same change. Re-run
the affected tests and record actual acceptance evidence privately. Update the
shared runtime guide when the change affects common wake/model/host behavior.
Documentation must distinguish implemented, configured, installed, and verified
states; a proposed or checked-in configuration is never an activation receipt.

## One-time full scheduled test

`e2e_prepare.py` retrieves public sources anew for the latest completed XNYS
session in a second private cloned database. `e2e_delivery.py` uses a separate
manual-test policy and durable delivery key; it never completes production slots.
`jobs/scheduled-e2e-prompt.md` orchestrates fresh Tiger collection, full price
reporting, two PDF attachments, one Gmail send and exact raw-message readback.
This allocation is one-time, non-replay-safe and separate from readiness. Its
existence is not evidence that it passed or that production mail was cut over.
The price cutoff is session close plus one minute, explicitly historical;
weekend calendar bounds are clamped to actual XNYS sessions.

The full-test delivery guard now owns canonical composition. It pins every
source/PDF and composer hash in a private integrity manifest, rejects any body
or attachment change, and uses a component completion adapter to require an
accepted-and-readback-verified outbox entry with fresh holdings after the due
time. A blocked/unknown record is never reset automatically. A separately
authorized corrective test uses its own request ID and output directory.

## Verified full-path boundary and summary reconciliation

The installed launchd scheduler has completed a one-time path through Codex CLI,
native Sites credential access, real Tiger holdings/assets reads, fresh retrieval
of last-completed-session prices, full report/PDF composition, native Gmail send
and exact raw-message verification. The supervising host separately verified
the mailbox bytes. This establishes the tested path with explicit partial data;
it does not establish daily production cutover or future service availability.

A model-summary enum error after actual delivery is not permission to resend.
The engine can record operator-verified delivery for a narrow final-format
false-negative, preserving the original failed attempt and adding an immutable
reconciliation row. Future automatic completion may use a trusted component
postcondition only for harmless summary-format failures after completed transport,
with no tool rejection and real canonical/outbox/readback evidence. Security
rejections, approval denials and unknown outcomes cannot take this path.
