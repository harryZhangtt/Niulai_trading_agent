---
name: ui-skill-router
description: Primary UI router for frontend implementation, React state/rendering, responsive layout, accessibility, UI polish, animation and browser checks. Restore opted-in conversations before routing follow-ups; respect disabled mode. Excludes backend-only and prose work.
---

# Harry UI skill set

Use the directory containing this file as `<bundle>` and the actual target
repository as `<project>`. Selection can recur implicitly on later UI turns;
this is a router, not a native sticky-skill switch.

## Explicit enable and disable

When the current user explicitly invokes `$harry-ui-skill-set` or asks to enable
it, run once:

```sh
python3 -B "<bundle>/scripts/activate.py" --project "<project>"
```

Only after actual `HARRY_UI_SESSION_ENABLED`, announce: **Harry UI skill set is
enabled for this conversation. I'll restore it and select the relevant guides on
later UI requests.** Retain the returned fingerprint and activation evidence in
context handoffs, but use the native-thread receipt as authoritative recovery
state. An old announcement is not proof of current state.

When the user disables this mode, execute:

```sh
python3 -B "<bundle>/scripts/session.py" disable --project "<project>"
```

Honor the disabled state until an explicit re-enable; never remove its receipt
or treat an upgrade, compaction, resume or implicit selection as re-enable.
When the conversation clearly remains disabled, do no Harry routing, guide
loading or helper work. If implicit selection occurs with uncertain state,
`session.py restore` may check the native receipt; DISABLED still means stay off.

## Every later UI turn, without another mention

For enabled or uncertain mode, before Harry UI advice, code changes or rendered
checks, perform this step even if you remember the earlier activation. A known
disabled conversation may skip it. Do not repeat `activate.py` on follow-ups:

```sh
python3 -B "<bundle>/scripts/session.py" restore --project "<project>"
```

- `HARRY_UI_SESSION_ACTIVE`: read the absolute `<bundle>/INTENT-CARD.md` (linked
  here as [INTENT-CARD.md](INTENT-CARD.md), not inside `references/`), execute the
  resolver for this turn's actual decision, then read returned guides/references
  needed now. Reuse a guide only while its body is actually in current context;
  reload it after compaction or when absent. Never just claim to have routed.
- `HARRY_UI_SESSION_INACTIVE` or `HARRY_UI_SESSION_DISABLED`: no bundle expert
  loading, routing or automatic activation. Continue the user's task with the
  target's ordinary instructions. A fresh thread has no inherited opt-in.
- `HARRY_UI_SESSION_FAILED`: report its sanitized code. Preserve unknown state;
  do not overwrite it as enabled or infer persistence from another session.

```sh
python3 -B "<bundle>/scripts/resolve.py" --decision <selector>
```

Repeat flags for compatible needs; load only returned `GUIDE.md` resources and
relevant references. Use [ROUTING-CARD.md](ROUTING-CARD.md) only for a real routing
ambiguity. State briefly which procedures were selected after the resolver
succeeds, or why execution is blocked. Backend/prose-only turns require no UI
state check, resolver or bundle expert. Follow the target's instructions, stack
and design system; skip broad visual workflows for isolated repairs.

The private receipt is target-owned under `.ui-skill-runtime/harry-ui-sessions/`,
keyed by the native `CODEX_THREAD_ID`, not a shared session-tree identifier.
This ID is an observed Codex runtime capability: if unavailable, persistence
fails visibly. No shared/global enable flag, hook or watchdog is supplied.
Compaction/resume can restore the same thread's state; a fork/new thread cannot
reuse its receipt. Runtime tool traces are required to substantiate actual use.

Consult [execution boundaries](references/EXECUTION.md) only before helper work.
Missing real tools stay blocked; caller declarations do not prove operations.
Do not install dependencies or activate MCP merely to select a guide.
