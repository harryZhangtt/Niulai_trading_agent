# Local LangChain pilot acceptance

Scope: bounded development E2E with synthetic inputs and real model inference,
followed by source integration reviews. This is not a production or trading test.
Verification level: balanced under the workspace's narrow-E2E requirement.

Frozen before implementation on 2026-11-15:

| ID | Required observable behavior | Forbidden outcome |
| --- | --- | --- |
| LC-01 | Dependencies install only in a new workspace-local environment, with resolved pins and a reproducible command. | Global or existing production environment mutation. |
| LC-02 | A real LangChain agent selects and calls a tool wrapping the existing pure valuation calculator on synthetic inputs; a deterministic result gate independently confirms the answer. | Passing based on a model assertion without a tool result, or financial quality/alpha claims. |
| LC-03 | Invalid numeric input is rejected before any model request. | Invalid input reaches the provider. |
| LC-04 | Agent Server serves graph/schema and runs the same graph through its public API; run state can be retrieved after completion. | A health response or source import alone being called E2E success. |
| LC-05 | Tool/model failures are visible, bounded and cannot trigger trading, email, production data changes or automatic blind provider replay. | Hidden fallback or false success. |
| LC-06 | The dev server can be stopped cleanly and restarted with the completed local thread still inspectable. | Orphan process or claiming production-grade durability from this dev-only check. |
| LC-07 | Subsequent parallel source reviews cover existing acquisition/calculation, scheduler/runtime, skills and A/B integration, preserving owner boundaries and identifying minimal adaptations. | Unrequested migration or production activation. |
| LC-08 | Setup runbooks/inventory are updated and the repository setup audit passes. | Reporting setup complete with a failing consistency gate. |

All private evidence lives below .langchain-pilot/runtime/. Source fingerprints,
dependency versions, failure attempts and requested model are retained. Actual
backend identity and unavailable usage/cost remain unknown unless independently
reported by transport. The existing calculator is unmodified; synthetic arithmetic
checks do not certify valuation assumptions. Future scheduled production integration
requires docs/deployment/runtime-acceptance.md, including verified email; this
pilot's local execution cannot satisfy that contract.

## User-directed transport amendment, 2026-11-15

The user explicitly requested the default OpenAI route instead of Ferry.
Keep LC-01 through LC-08 and the original case/oracle unchanged. The candidate
now uses ChatOpenAI's Responses API at the explicit official endpoint
https://api.openai.com/v1 with requested model gpt-6.1-sol, low effort, the same
call/time limits and zero SDK retries. Ferry-prefixed models are rejected and
inherited base-URL variables cannot redirect this candidate to Ferry.

An OpenAI Platform API key is required for this path; native ChatGPT/Codex login
and LangSmith tracing keys are separate credentials. Resolve the key locally
from OPENAI_API_KEY or the owner-private .langchain-pilot/.env file only at model
dispatch. Graph/schema inspection and invalid-input rejection remain available
without a key. Missing credentials must produce zero model HTTP dispatches and
an explicit credential-free diagnostic. Do not copy native login tokens or fall
back to Ferry to obtain a pass. Preserve historical Ferry attempts and the
unsuccessful native-Codex preflight as separate evidence.

## User-directed session-engine amendment, 2026-11-15

The user chose the existing chat session as a pluggable model engine, without a
Platform key or Ferry. The direct API engine remains optional; its unverified
live path is not a prerequisite for the new default. This implements the
session-engine requirements recorded in task-plan Phase 7 before implementation.
LC-01 through LC-08 retain their tool, arithmetic, failure, setup and production
boundaries. Record cooperative host execution separately from a standalone API
inference or unattended host dispatcher.

| ID | Observable requirement | Forbidden outcome |
| --- | --- | --- |
| SE-01 | A model call pauses with a persisted, bounded message/tool request and no provider request. | Token extraction, API-key requirement, hidden provider fallback or busy waiting. |
| SE-02 | The host submits an assistant message only; unchanged LangChain create_agent executes the selected tool and the existing independent gate checks the answer. | Host-submitted tool receipts, host changes to financial inputs, or a model assertion being accepted alone. |
| SE-03 | A response matches the pending request, current session binding and revision; duplicate/stale replies cannot advance the workflow. | Reusing a response across turns, accepting a retired session revision or replaying an unknown response. |
| SE-04 | Rebinding changes only model ownership; the same graph thread, messages and completed tools remain. | Reconstructing workflow state in chat or starting a replacement thread to hide lost state. |
| SE-05 | Graceful owned-server stop/restart preserves a pending model request and its tool result; later completion executes the calculator once. | Calling this dev-only check production crash durability. |
| SE-06 | Malformed responses and invalid inputs remain visible/recoverable without broker, delivery, scheduler or host effects. | Blocking user prompts, diagnosis or recovery on engine readiness. |
| SE-07 | Caller/session/model identity is declared and explicitly not independently attested. | Treating a session ID as authentication, business permission or proof of backend identity. |
| SE-08 | A later session can configure a new binding, discover threads, read a request and supply its response through the public CLI/API. | Claiming an automatic wake-up/dispatch/background worker or requiring a copied conversation to resume. |
