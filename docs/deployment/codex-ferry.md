# Optional Codex OpenAI and Ferry routes

User-authorized personal routing change, 2026-11-15. This is an explicit exception
for the user's Codex client route configuration; it does not install a proxy,
change global hooks, restart shared daemons or activate a production scheduler.

## Native defaults and opt-in profile

The base `~/.codex/config.toml` uses built-in `model_provider = "openai"` with the
previous official default `gpt-6.1-sol` and preserved `xhigh` effort. It has no
custom OpenAI endpoint or global Ferry model-catalog override. This means the
built-in OpenAI transport, using the existing native login; it is not a promise
that every OpenAI backend uses the public API hostname.

The existing `[model_providers.ferry]` definition and unrelated MCP, hooks,
permissions, model-summary and UI settings remain unchanged. The separate
`~/.codex/ferry.config.toml` contains only the Ferry provider/model selection and
the existing Ferry model-catalog path. Selecting the profile opts into Ferry:

```sh
codex
codex --profile ferry
codex --profile ferry --model ferry-gpt-5-6-sol-max
```

The first uses OpenAI. The others use the existing loopback Ferry Responses
endpoint. The profile's default model is `ferry-gpt-6-1-sol`; its effort inherits
`xhigh`. Names must match the installed gateway's catalog. A profile is selected
at session startup; changing only a model name inside a session does not imply
a provider switch. Existing sessions may retain their saved provider, so begin
a fresh session to establish the intended route. No default model upgrade was
part of this routing repair.

Codex 0.134.0 and later uses separate `<name>.config.toml` files for profiles,
not `[profiles.<name>]` tables. The local CLI checked here is 0.169.0. The older
running application host is a separate runtime and was not restarted.

## Why the coexistence configuration was confusing

Ferry's `--with-chatgpt` configuration intentionally keeps `model_provider =
"ferry"` and `requires_openai_auth = true`. It can forward ordinary OpenAI models
to ChatGPT/OpenAI while serving `ferry-` models through TRAE. Both still enter the
local Ferry gateway first, so Ferry availability affects either route. This is
valid coexistence, not inherently a mismatched configuration.

The user chose native OpenAI defaults plus an explicit Ferry profile to remove
that gateway dependency for ordinary Codex sessions. Do not reapply a full
`ferry config codex --with-chatgpt` block over the base config as an incidental
setup step. `ferry config` prints a proposal; it is not permission to replace
existing settings. No evidence identifies an A/B test as the writer of the old
user-level configuration. Repository evaluation occurrences of official model
names alone do not prove global configuration mutation.

For diagnosis, `GET /v1/responses` returns Unknown route because inference uses
POST. An invalid-JSON POST returned the parser's HTTP 400, confirming that the
POST route existed. A separate actual Ferry-prefixed Responses request completed
HTTP 200 with the requested `OK`, and a fresh native child-agent turn returned
`ROUTING_OK`. The earlier native child failure was `Could not reach ChatGPT`,
which shows an attempted upstream official forwarding path, not proof that POST
was absent. Installed Ferry CLI 0.1.119 and running daemon 0.1.117 differed during
inspection; that difference alone does not establish the cause. The daemon was
not restarted or upgraded during repair.

Claude's existing connection was inspected separately: its loopback base URL,
`claude-` catalog model, local placeholder and gateway discovery matched the
documented Ferry route. No Claude settings were changed. Ordinary Anthropic
models and OAuth forwarding are a different protocol from Codex's provider
selection; do not apply Codex profile rules to Claude blindly.

## Verification and rollback

Before activation, the candidate was staged in an owner-private workspace
directory. Native default configuration parsing and Ferry-profile local prompt
construction passed without inference. The exact original bytes were restored
on a disposable copy to rehearse rollback. A profile is supported on runtime
commands; passing `--profile` to `app-server --print-startup-config` was rejected
and was replaced with the supported `debug prompt-input` validation. Failed
validation attempts remain in private evidence.

Owned backups and receipts remain below
`.job-runtime/ferry-route-recovery-*/` and `.job-runtime/ferry-route-split-*/`.
Never publish their full configuration bytes or copy credentials into docs.
Rollback must compare the current config/profile hashes to the owned applied
receipt, reconcile later edits, restore the exact previous base, and remove only
the profile created by this change. Do not restore an old full file over newer
unrelated user edits.

This is a manually verified client setup change. It does not establish future
scheduled-business acceptance. Scheduler/provider promotion remains subject to
`runtime-acceptance.md`, with actual future Codex execution and verified email.

Official references: [configuration profiles](https://developers.openai.com/codex/config-advanced/)
and [provider configuration](https://developers.openai.com/codex/config-reference/).
