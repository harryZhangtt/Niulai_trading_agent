# Codex execution adapter

`model.run_codex(profile, prompt, workspace, run_dir, context=None)` executes one
explicit model profile and returns `status`, a stable diagnostic `code`, and a
transport receipt. It does not schedule, retry, select a fallback, send email,
or load job-specific policy. The engine decides whether a classified failure is
eligible for a later retry according to job replay safety and central limits.

Required profile fields are `codex_bin`, `model`, `effort`, `timeout_seconds`,
and `auth_home`. An optional `max_output_bytes` bounds captured output. The
workspace-local authentication home must already contain an owner-private
`auth.json`. Provisioning this directory is a separate authorized operation;
the adapter never copies credentials or falls back to the user's global cache.
One nonblocking file lock serializes access/refresh of this authentication home.
The locked descriptor is inherited by the Codex child, so a scheduler-parent
crash does not free the cache for another invocation while that child still lives.
An expired/rejected grant is a permanent authentication failure, not a request
to reset credentials or switch authentication methods automatically.

The supported `CODEX_HOME` override places Codex's authentication and private
state under `.job-runtime/`; `--ignore-user-config`, `--ephemeral`, and explicit
SQLite/cache/temp paths keep this execution isolated from global settings. The
adapter preserves the user's actual `HOME`. Command, app and web tools are
disabled, the filesystem sandbox is read-only, and shell/environment overrides
are built as an argument list with no shell interpolation. Prompt bytes stream
only through an anonymous stdin pipe; no prompt file is created. The v2 entry
accepts exact `bytes` only; the central service owns prompt-lease reading and
binding verification before this boundary. The legacy v1 entry may still accept
a string, but encodes it directly into the same bounded internal byte chunks.
Codex history persistence is explicitly disabled.

All attempts use fresh private directories. An exit code of zero and a model's
own success statement are insufficient: success requires a parsed real
`turn.completed` event and a nonempty final response. Actual usage and thread ID
are recorded when emitted by the CLI. `requested_model` is the enforced CLI
selection; `observed_model` stays null unless the event stream independently
supplies it. A different observed model or unexpected tool activity fails the
attempt. The optional context `response_schema` is passed to Codex's structured
output option; `cancel_event` supports cooperative service shutdown.

Timeout, output overflow, partial/EPIPE delivery and cancellation terminate the
invocation process group and retain an `unknown` outcome. The adapter never
automatically resubmits these runs. Known transient provider/network failures are
classified `retryable`; known auth/config/model errors are `failed`. Raw stdout,
stderr and provider events are bounded in memory and are neither persisted nor
embedded in the public diagnostic receipt. V2 uses one owner-private, exclusive
final-output file only while the normalizer's descriptor resolver needs it. A
known terminal result removes that file and fsyncs its directory; an unknown or
cleanup-uncertain outcome retains private attempt custody and exposes only the
fixed `retained_unknown` disposition, never a path, reference or digest.

The installed readiness profile intentionally has no business side effects:
shell, app/connector and web tools are disabled. It can verify that a scheduled
model turn completes, but cannot send a portfolio email or operate Tiger by
itself. Business actions require separate explicit adapters and ownership gates;
model text is never a substitute for their actual transport receipts.

Official references:

- [Non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference)
- [Environment variables](https://learn.chatgpt.com/docs/config-file/environment-variables)

Offline tests use synthetic executables and fake authentication files entirely
within workspace `.job-runtime/tests/`. They never invoke a live model or inspect
the user's credentials. Live wake/model availability must be verified separately.
