# Isolated Codex business-tool capability check

This document records the supported integration path and the remaining evidence
needed before an unattended Niulai business job can use Gmail or Sites. It does
not enable tools, install a plugin, change permissions, query a broker or send mail.

## Established facts

The inspected Codex CLI is `0.165.0`. Its `plugin --help` exposes `add`, `list`,
`marketplace` and `remove`; `plugin list --help` supports `--json`. Its feature
catalog reports `apps`, `plugins`, and `remote_plugin` as stable. Official
documentation supports plugins in Codex CLI and says new CLI sessions can use
installed bundled tools and skills. The host sandbox/approval policy and the
external service's authorization still apply.

The workspace-local `.job-runtime/codex-home/plugins/cache/` contains installed
metadata for Gmail `0.1.10` and Sites `1.1.2`. Their manifests reference the native
app connector, rather than requiring a manually configured MCP URL:

| Plugin | App ID in inspected manifest |
| --- | --- |
| Gmail | `connector_2128aebfecb84f64a069897515042a44` |
| Sites | `connector_20205bf7d4e99a89d7154bb849718324` |

These app IDs are service metadata, not account credentials. Re-read the actual
installed `.app.json` on a new deployment; do not infer account access from a
cached manifest, tool title, feature flag, or a plugin listed as installed.

No live model or connector request was performed for this metadata inspection.
In particular, native Gmail/Sites tool availability and connected-account access
from an unattended `codex exec` process are not established by this document.

## Keep readiness and business profiles separate

`shared/job_runtime/model.py` intentionally disables apps, shell tools and web
search. It also treats unexpected tool activity as a policy violation. Keep that
readiness profile unchanged. A business executor needs a separate, reviewed
policy which enables only the required connectors/tools and verifies actual
side-effect receipts. Do not reinterpret model text as a Gmail send record or
Tiger read evidence.

`shared/job_runtime/business.py` implements this separate execution boundary.
Its profile adds explicit `phase`, `apps`, and `shell` capabilities to the shared
base model profile. `phase = "catalog"` requires shell disabled; business phase
allows state-writing shell execution only from a fresh private run directory.
The repository is not made a writable working root. The only additional writable
business directory is `.niulai-state/`. Both phases keep the same bounded
process-group cleanup and inherited authentication lock.

Prompt, raw JSONL tool events and stderr are handled in bounded memory pipes.
The adapter does not write them to files or request a last-message artifact;
ephemeral execution and disabled Rust logging prevent routine rollout/diagnostic
capture. Only allowlisted completion/thread/usage/tool-name metadata and validated
final JSON are returned. Opaque bearer/token-looking final output is rejected.
The adapter's synthetic tests verify that raw tool-result markers and stderr
do not appear in its retained artifacts or returned receipt. This implementation
does not itself establish live Gmail/Sites connection access.

The optional business-profile `approval_mode` is `never` by default or explicit
`automatic_review`. Catalog phase always requires `never`. Automatic review
uses the documented `--approve-for-me` flag, which selects `on-request` approvals
and the workspace-write sandbox. The executor omits the conflicting `--sandbox`
flag and does not override the approval policy with `never` in that mode.
It keeps the private working directory, restricted writable state and connector
allowlist. This per-invocation reviewer routing does not change global Gmail
permissions, force approval, or override managed restrictions.

With policy `never`, an action requiring approval cannot be sent to a reviewer.
Use automatic review only for a concrete user-authorized business action; retain
the reviewer decision and actual send/readback evidence. The executor extracts
only fixed approval-error codes and tool names from unambiguous tool-error
envelopes before discarding raw events. A model's blocked statement is not proof
that a send was rejected before dispatch. Existing `unknown` outbox records stay
unresolved until separately reconciled and are never reset for a retry.

Final-summary validation emits fixed field-specific codes without retaining
rejected values. `receipt.summary_parse_failure` appears only for that parsing
stage and records `code`, an allowlisted `field`, and a fixed `category`.
`format` is distinct from `sensitive_output`, `oversized_output`,
`rejected_fields`, and `boundary_violation`. The executor still returns failure;
it does not loosen enum guards or infer business success from a completed model
turn. Tool approval rejection and a model's blocked statement never set this
parsing flag. A business-specific caller may reconcile a formatting-only failure
against independently verified canonical artifacts, accepted outbox and exact
new mail readback. Such reconciliation is not an automatic send retry or a
general fallback for tool/security failures.

Use only the workspace-local Codex authentication home. Acquire its existing
`runtime.lock` nonblockingly before CLI/plugin operations that could refresh
authentication. Preserve the lock through the child process lifetime, as the
model adapter does. A busy lock is a deferral, not permission to copy credentials
or start a second independent refresh cache. Never reseed the auth cache after
an authentication failure without explicit recovery.

All probe prompts, logs, schemas, output, temporary files and SQLite state must
remain under `.job-runtime/`. Preserve the real `HOME`; set the documented
`CODEX_HOME` override to the already provisioned local authentication home.
Do not edit root `.codex/config.toml`, add market-data MCP entries, scrape browser
sessions, or derive a private app-server endpoint. The prior MCP stability gate
continues to apply.

## Commands and candidate overrides

Run the installed CLI's metadata command in the isolated environment to inspect
canonical installed plugin state. It is a read-only listing, not a connection
test. Run it under the same authentication lock used by the model executor:

```sh
CODEX_HOME="$PWD/.job-runtime/codex-home" \
TMPDIR="$PWD/.job-runtime/tmp" \
XDG_CACHE_HOME="$PWD/.job-runtime/cache" \
CODEX_SQLITE_HOME="$PWD/.job-runtime/sqlite" \
codex plugin list --json
```

The command above is a candidate for the operator to run; it was not executed by
the metadata investigator. Use an explicit verified `codex` binary path in a
service profile. Ensure all directories exist privately before invocation.
The actual process launcher must also set private `log_dir` and retain normal
timeout/process cleanup protections. Do not automatically install or connect
anything merely because listing reports a missing plugin.

For one catalog-only model probe, the documented overrides permit an isolated
process to keep all apps off by default and expose only Gmail and Sites:

```toml
# Per-invocation candidate overrides; not active workspace configuration.
[features]
apps = true
shell_tool = false
shell_snapshot = false

[apps._default]
enabled = false

[apps.connector_2128aebfecb84f64a069897515042a44]
enabled = true

[apps.connector_20205bf7d4e99a89d7154bb849718324]
enabled = true
```

Keep `web_search = "disabled"`, `mcp_servers = {}`, `--ignore-user-config`,
`--ephemeral`, `--sandbox read-only`, and explicit model/effort selection for that
catalog probe. This does not grant new third-party authorization. It is distinct
from globally changing app permissions. Unknown or rejected configuration must
fail closed, without retrying with broader access.

The catalog-only prompt must request only the loaded tool metadata. It must
forbid Gmail/Sites invocation, file/source reads, browsing, sends, environment
dumps, installation, connection flows and permission changes. When a supported
tool-metadata search surface is exposed, retain its actual returned names/schema
evidence. A model's invented list is insufficient. If no catalog surface exists,
record that limitation rather than guessing tool names or private APIs.

## From discovery to a business execution gate

After catalog discovery succeeds, derive exact canonical tool identifiers from
the observed catalog. The documented `apps.<id>.default_tools_enabled = false`
and `apps.<id>.tools.<tool>.enabled` overrides support a narrow tool allowlist.
Do not guess whether a connector's internal identifier is a display name,
namespaced action or model-visible wrapper name; verify each allowlisted action
through the supported host.

Separate subsequent acceptance gates are:

1. Read-only account metadata proves the expected Gmail identity through the
   actual CLI-connected Gmail tool. Do not read unrelated mail.
2. The actual Sites tool returns a fresh result for the exact private credential
   project. Enforce Niulai's owner-only audience and origin checks before any
   private-store call. Keep the bearer in tool/process memory.
3. A fresh broker read and confirmed credential checkpoint succeed without
   recreating consent or copying a second refresh cache. Source/read timestamps
   are retained privately.
4. One user-authorized business attempt atomically claims the immutable email
   payload, sends exactly once, records the actual returned message ID, and reads
   that exact new message back. Ambiguous outcomes remain blocked for reconciliation.
5. A real scheduled wake executes the same accepted path and preserves slot
   deduplication. A manual run is not evidence of scheduler timing or Mac wake.

Only the smallest required action set should be enabled for each stage. Keep
the historical exact-content resend, fresh source/report generation, model
completion, send acceptance, mailbox arrival and phone receipt as distinct claims.
Do not disable the existing production sender or claim full independence based
on a catalog probe. Update this document when actual connection/tool evidence
changes; keep account values and raw receipts in ignored private state.

## Official sources

- [Plugins](https://learn.chatgpt.com/docs/plugins)
- [CLI command reference](https://learn.chatgpt.com/docs/cli/reference)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)

The relevant documented settings are `features.apps`, `apps._default.enabled`,
`apps.<id>.enabled`, `apps.<id>.default_tools_enabled`, and
`apps.<id>.tools.<tool>.enabled`. Installed manifests and CLI help supplement
these sources; neither replaces a real connected-tool acceptance result.

## Current isolated execution evidence

The operator subsequently ran an isolated native tool-catalog check and an actual
Gmail profile query through the workspace-owned Codex CLI home. Both completed;
the profile check observed a real Gmail tool invocation. This establishes access
for those checked calls, not a completed scheduled business delivery. A separate
one-time full Niulai test allocation is under verification. It uses the business
executor with Gmail/Sites enabled, bounded private shell execution and no raw
tool-stream persistence. Readiness profiles remain unchanged.

The subsequent one-time scheduled business test completed real Sites/Tiger and
Gmail calls under automatic approval review. Gmail send and raw readback were
verified independently, including both PDFs and the full body. The first attempt
under never-ask policy remained blocked and its unknown outbox was not reset.
A separate authorized corrected request succeeded. Its final model-summary
format rejection was reconciled against actual delivery without another send.
Field-specific sanitized format diagnostics and trusted artifact postconditions
now distinguish this case from security, permission and transport failures.
