# Lightweight web-search routing

This is an agent workflow, not a background service or transport repair. It adds
no dependencies, credentials, global settings, or automatic network changes.

## Routing and circuit breaker

1. Start a fresh session with one native search for the actual requested topic.
   If it succeeds, open a relevant returned source with the native tool.
2. If either operation returns a connection/transport error, mark the native
   route unavailable for the remainder of this session. Do not retry identical
   requests or change prompts, models, or search freshness to repair transport.
3. Use ChatGPT Work in a new dedicated browser conversation, via supported
   browser tools, under the user's standing authorization for this fallback.
   Send only the public research question and date constraints. Do not forward
   local files, logs, credentials, private project context, or account data.
4. Require live search, opening the primary source, direct source URLs, event
   and publication dates, and a clear account of what could not be verified.
   For earnings, require the official release and an independent report; keep
   GAAP/non-GAAP, fiscal periods, currency, and trading dates explicit.
5. Verify visible search/source activity and the completed response. Inspect
   important cited sources directly when possible. An AI answer alone is not
   primary evidence, and a generated response without sources is not success.
6. If the browser route fails, allow one retry only for an explicit transient
   page-loading error. Stop on login, policy, security, or repeated transport
   blockers. Use direct public source retrieval if available, clearly labeled
   as source retrieval rather than native search; otherwise report the gap.

## Bounded waiting and recovery

- Inspect progress after doing independent work, rather than polling in a tight
  loop. Give a user-facing update at least every 60 seconds while waiting.
- If no useful progress is visible for about two minutes, report the stalled
  route and use direct sources where possible; do not create duplicate jobs.
- Keep the conversation URL for audit. Preserve an unfinished browser tab for
  handoff; never claim it completed while it is still generating.
- Close the circuit breaker only in a fresh session or after a concrete runtime
  or network change, followed by a successful native search AND source opening.
- Report which route supplied the answer and any unverified facts. A successful
  fallback does not mean Codex native search has recovered.

## Delegation prompt

> Search the live web for [public topic] as of [date]. Open the primary official
> source and one independent source where relevant. Return a concise answer with
> direct URLs, publication/event dates, and clearly labeled facts versus
> interpretation. Report whether search and source opening both succeeded.
> Do not use local files, account integrations, or make settings changes.

Diagnostic evidence and smoke-test results: `docs/web-search-status.md`.

## Optional EgoLite candidate

`shared/web_access/` implements an opt-in session router and pinned navigation/
snapshot connector. It does not change this incumbent live workflow, intercept
native tools or install a browser/MCP. Native discovery and ordinary opening stay
first; rendered/authorized-session reads may escalate when the candidate is
explicitly configured and validated. Preserve existing PDF handling and route
provenance. Semantic snapshots are rendered extracts, not automatic full-source
or independent-corroboration evidence.

EgoLite is disabled in source configuration. Its external installation/onboarding
requires a workspace exception; current live paired results and scheduled
acceptance are unverified. See [setup and recovery](deployment/web-access.md)
and the [matched evaluation protocol](../tuning/evals/browser_cooperation/README.md).
The existing session-scoped native circuit and authorized Work fallback still
apply. A new diagnostic CLI process does not reset the real agent's circuit.
