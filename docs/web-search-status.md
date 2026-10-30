# Native web search

Scope: this workspace only. The migrated `niulai/` source and its skills are unchanged.

`.codex/config.toml` explicitly selects native Codex live web search. No packages,
API keys, proxy changes, global skills, or user-level configuration were added.

Official configuration documentation:
https://developers.openai.com/codex/config-basic/

Project configuration is loaded for trusted projects and can be overridden by
higher-priority settings or requirements. Do not assume a running session reloads
this file; verify in a fresh session opened in this workspace.

## Observed on 2026-10-30

- After runtime network access was enabled, curl retrieved Anthropic and official
  OpenAI documentation successfully. Google search HTML and Bing RSS returned 200.
- Native `web__run` search still failed with a transport-level connection error.
- Native `web__run` opening the official configuration page failed with the same
  connection error, while curl fetched that page successfully.
- The alternate search connector reported unavailable.
- These observations do not establish the native transport's root cause.
- Successful HTTP access is not a native web-search acceptance test.

## Acceptance and recovery

1. Open a fresh session in this workspace so project configuration can be loaded.
2. Run a native search for an official documentation topic.
3. Open a returned source using the native tool and verify its page content.
4. Repeat with a different query. Record each outcome; a small smoke test does not
   establish a long-term reliability guarantee.
5. If the same transport failure repeats, stop identical retries. Capture the
   timestamp, tool name, and sanitized error for app/runtime diagnostics.

Do not invent retry, timeout, or proxy configuration keys for native web search.
Do not silently replace native search with HTTP and report native search healthy.
Cached search is a different freshness mode, not a demonstrated transport repair.

## Follow-up diagnostics, 2026-10-30

- Workspace trust is configured as `trusted`; project config still selects live search.
- CLI version is 0.165.0; the running shared app-server is 0.166.0; desktop reports 26.1007.30912. Different component versions alone do not prove a defect.
- `codex doctor --json` outside the shell sandbox reports a successful Responses WebSocket handshake (HTTP 101), but the required HTTPS provider check fails with `TLS handshake or certificate validation failed`; the optional desktop assets check times out.
- Desktop logs independently report `net::ERR_SSL_PROTOCOL_ERROR`. Daemon logs show repeated HTTP transport failures for the ChatGPT MCP endpoint, and model-list refresh timeouts.
- The sandboxed doctor run reports DNS failures; these must not be confused with the unrestricted diagnostic results.
- An unauthenticated curl request to the ChatGPT MCP endpoint reaches HTTPS but returns HTTP 451 with `no_biscuit_no_service`. This is not equivalent to an authenticated native-tool request and does not establish a regional block.
- No proxy environment variables were present. Unrestricted system proxy inspection shows HTTP, HTTPS, SOCKS and automatic proxy flags disabled. Doctor's suggestion about an unused manual system proxy is therefore not sufficient evidence to enable one.
- No authentication credentials, TLS verification settings, global configuration, or system network settings were changed.

Temporary fallback test delegated to ChatGPT Work in a separate browser conversation:
https://chatgpt.com/c/6ae45e3f-f3a4-83ec-be72-543d9a018987
The prompt requests native search plus opening an official result, and prohibits settings changes. Submission alone does not establish fallback success.

### Browser fallback smoke tests completed

- The troubleshooting conversation completed with visible web-search activity,
  official source links, and an explicit report that search and opening worked.
- A second, user-requested ServiceNow earnings search completed in about 85 seconds:
  https://chatgpt.com/c/6ae45e9f-81f4-83ec-96e7-37db90334165
  The UI showed web-search activity and dated citations. The delegated response
  reported opening the official Q3 2026 earnings release and Reuters; it also
  disclosed HTTP 429 from an additional Yahoo source.
- A separate local browser opening of the official release reached its correct
  title and URL, but exposed no article body to accessibility/DOM inspection.
  Financial details were therefore obtained through the delegated source-reading
  route, not independently reverified from that local browser page.
- These two successful fallback tests do not establish that Codex native web
  transport is repaired or guarantee future availability.
- `AGENTS.md` now activates the bounded, session-scoped circuit-breaker and
  verification workflow in `docs/web-search-routing.md`.
