# Engine-scoped typed classification and judging

This optional shared adapter exposes TypeSafe Jev boolean/enum decisions. It adds
no active registration, default model, schedule, MCP, source admission or semantic
approval. Mentor, tuning and investment consumers own their domain rules and
independent acceptance. Classification cannot replace deterministic hash, source,
quote, date, temporal-availability or production-owner checks.

## Transport recovery status

The first live POST observed by the integrating runtime hit its12-second hard
wall and returned `JUDGE_TIMEOUT_UNKNOWN_OUTCOME`, with no classifications,
resolved model or usage. That receipt remains immutable. A later authenticated
models diagnostic reportedly took about31seconds; a subsequently registered
unauthenticated public OpenAPI HEAD from this host took about1.69seconds. These
different requests/times neither prove POST latency nor establish a service SLA.

Adapter1.1 keeps the5-second attempt/10-second total defaults and live opt-in.
Callers may explicitly configure an attempt up to60seconds and total up to120.
A separately registered public-source smoke used45seconds per attempt,
60seconds total and zero retries. It returned the pinned model with valid typed
outputs/usage in about1.1seconds; a live-disabled repeat used cache with zero
provider calls. This is a host observation, not a default or service SLA. Raising
a cap does not authorize replay of the first unknown. See the integrating
[setup/recovery runbook](../../docs/deployment/jev-labeling.md) for current
evaluation and future-triggered acceptance status.

Socket timeouts inside the child, including timeout reasons wrapped in URLError,
now retain unknown-outcome classification. Hard subprocess timeouts still kill
and reap the child and are never automatically retried or positively cached.
Receipts add configured limits, per-attempt timeout/elapsed/HTTP status and a
provider-outcome marker (`not_started`, `unknown`, `response_received`, or
`cached_response`). A received HTTP response is not semantic or model acceptance.
These diagnostics contain no request text, error body or credential value.

Worker environment forwarding is allowlisted: ordinary OS/certificate/proxy
variables are retained, unrelated API-key/control variables are excluded,
user-site imports are disabled, and temporary output points inside the workspace.
No system network/proxy settings change. Retry-After accepts finite nonnegative
seconds or an HTTP date; invalid/nonfinite values cannot break error-envelope
serialization. Only explicitly configured429/529 retries remain eligible.

`PROBABILITY_SUM_TOLERANCE` is the shared declared0.001 enum-sum tolerance.
Consumers/graders must agree on it, or explicitly version a stricter contract.
Probabilities are never silently renormalized. Adapter version is part of cache
identity, so1.0 entries are not silently imported into1.1. There is no second
durable retry ledger in this module: an independent runtime registers each live
attempt, preserves unknown outcomes and owns any subsequent authorization.

Nineteen synthetic/conformance checks include a real sleeping-child kill/reap,
large-budget validation, timeout redaction, Retry-After and environment isolation.
No authenticated calls, key reads or billable POSTs were made in this transport
change. Live domain E2E, label accuracy and scheduled/email acceptance are owned
and recorded separately by the integration coordinator.

## Official contract reviewed on 2026-11-01

[TypeSafe's homepage](https://typesafe.ai/) links the official documentation and
console. [The quick start](https://docs.typesafe.ai/introduction/quickstart)
identifies Jev as TypeSafe's model. This identifies the service, not an account or
the issuer/validity of a supplied key. The full `apikey_<id>_<token>` format was
not located in the bounded official documentation search. The initial adapter
implementation used synthetic credentials under a mocked workspace root; later
integrating-runtime observations are distinguished above. Jev-named third-party
gateways were not adopted.

The public [OpenAPI contract](https://api.typesafe.ai/openapi.json) documents
Bearer authentication, `POST https://api.typesafe.ai/v1/systemone`, and
`GET /v1/models`. Requests contain `model`, `state`, and named `questions`.
Responses contain `model`, matching `answers`, and `usage.input_tokens` /
`usage.output_tokens`. This adapter implements two exact answer shapes:

```json
{"type":"noul","noul":0.8}
{"type":"choice","choice":"supported","probabilities":{"supported":0.9,"insufficient":0.1},"confidence":0.8}
```

These numbers are illustrative, not live results. A
[Noul](https://docs.typesafe.ai/primitives/noul) returns a yes probability and no
separate confidence. A [Choice](https://docs.typesafe.ai/primitives/choice) returns
one mutually exclusive label and a distribution over the supplied labels. It is
not a free-form generator or a multi-label distribution: use one BooleanQuestion
per independent topic, whose probabilities need not sum to one across topics.
Neither primitive documents a null/reject answer. Use an explicit unknown/other
enum option, or application abstention. The provider also offers an ordinal
[Score](https://docs.typesafe.ai/primitives/score), with expected zero-based level,
level probabilities and confidence. Score and experimental image/Box/long-context
features are outside this first adapter's current classification/judge need.

[Confidence](https://docs.typesafe.ai/confidence) is derived from the output
distribution, not an independent estimate that a classification is correct. For
n Choice options its documented formula is `(p_max - 1/n) / (1 - 1/n)`. Noul's
uncertainty is already visible in p_yes. The adapter preserves provider
confidence separately; acceptance policies use the supplied distribution.

[Models](https://docs.typesafe.ai/models) lists `jev-1.14.0`, released 2026-10-14,
at $0.042 per million input tokens, output free; default limits are 64k tokens
per request and 32k per question. Limits are per organization in requests/sec and
tokens/sec. Versioned IDs are accepted even if the model-list API returns aliases.
Aliases move, so this adapter rejects aliases and a mismatched resolved model.
The [launch post](https://typesafe.ai/blog/introducing-system-one-models-and-jev),
2026-09-15, claims 70–500 ms end-to-end latency and notes West Coast measurements.
Those are vendor claims, not a measured workspace SLA or throughput guarantee.

[Request errors](https://docs.typesafe.ai/api/errors) distinguish 401 auth, 400/422
validation, 429 rate limits and 529 overload. The official SDK retries by default;
this adapter instead defaults to zero retries and permits at most one explicitly
configured retry of 429/529, within its total deadline. It does not retry an
unknown timeout, connection failure, invalid response, auth failure or other 5xx.

[Data handling](https://help.typesafe.ai/articles/5974925716-how-is-submitted-data-used-or-retained),
updated 2026-10-11, says requests/responses are not used to train Jev, but service,
billing, abuse prevention and telemetry processing can occur. Retention is
contractual; [enterprise ZDR](https://docs.typesafe.ai/legal) is an arrangement,
not a default promise. Unlike the official SDK's optional debug logs, which
[include unredacted bodies](https://docs.typesafe.ai/sdk/python/usage/advanced),
this adapter records no request body, credential or raw provider response.

The vendor documents [1.13 failure modes](https://docs.typesafe.ai/model-jaggedness/jev-1.13),
reviewed 2026-10-02, including arithmetic/date comparison, irrelevant context,
adversarial content and option-order dependence. Those observations are version
specific, and do not establish 1.14 performance. Before using a threshold, assess
held-out labeled task cases, per-class errors, reliability bins, uncertainty and
coverage/error at abstention thresholds. [Scikit-learn's calibration guide](https://scikit-learn.org/stable/modules/calibration.html)
explains reliability diagrams and why Brier/log-loss measure more than
calibration alone. No domain calibration, semantic superiority or alpha is
established here.

The original documentation survey used native public search and opened primary
sources successfully. Official Markdown exports were unsupported by the tool's
content parser; official HTML was read instead. That survey made no model call.
Later host integration observations are recorded above and in the runbook;
the first unknown POST and the separate valid source smoke remain distinct.

## Public interface

Use the existing project-local research environment; the package itself uses the
Python standard library and existing shared artifact helpers. No new dependency
installation is needed.

```python
from shared.typed_judge import (
    BooleanQuestion, EnumQuestion, DecisionPolicy, JudgeClient,
)

questions = [
    EnumQuestion(
        'document_type', 'Which document type describes the supplied passage?',
        {'earnings_release': 'Issuer periodic earnings release',
         'legal_terms': 'Contract, entitlement, or legal terms',
         'unknown': 'Insufficient information or another document type'},
        abstain_options=('unknown',),
    ),
    BooleanQuestion('supports_claim', 'Does the scoped passage support the supplied claim?'),
]
client = JudgeClient('datasource-labels', cache_directory=approved_private_cache_directory)
result = client.judge(public_source_state, questions)  # Live OFF; no key lookup.
```

`DecisionPolicy(min_probability, min_margin=0)` is optional. With no policy a
valid result retains probabilities and candidate but abstains with `value=None`.
A domain caller chooses and versions its thresholds after evaluation. Explicit
abstain options always abstain. Invalid or unavailable input never becomes a
negative boolean or an unknown semantic label.

`result.to_dict()` returns:

- Overall status: `ok`, `partial`, `abstained`, `error`, or `disabled`.
- Per-question records: type, status (`classified` / `abstained`), value, candidate,
  canonical probabilities, provider confidence or null, reason code, resolved
  model and question schema hash. Boolean probabilities use `false` / `true` keys;
  enum probabilities use exactly the declared option names. The adapter checks
  finite [0,1], approximate sum one and selected argmax; it does not renormalize.
- A sanitized execution receipt: engine scope, provider, pinned/resolved model,
  request/schema/cache hashes, route, attempt count, token usage, elapsed seconds,
  cache-hit flag and stable error/warning codes. Cache hits retain original token
  usage, marked `usage_scope=original_cached_inference_no_new_call`; do not count
  them as newly billed inference. `semantic_approval` is always false.

## Live opt-in, cache and recovery

The only live endpoint is pinned in source to `api.typesafe.ai`. No alternate
base URL, redirect, environment-key fallback or fallback model exists. The host
must explicitly authorize a live call after review by passing `allow_live=True`.
Only then does a bounded child process open the fixed credential reference
`.job-runtime/credentials/jev.api-key`. The file must be workspace-local, owned by
the current user, non-symlink and inaccessible to other users (0600/0400). Do not
put the key in argv, a prompt, a fixture, documentation or a receipt. Credential
provisioning belongs to the runtime owner; this package does not create it.

Defaults: pinned `jev-1.14.0`, 5-second per-attempt hard child timeout, 10-second
total budget, zero retries, 64 KiB request and response caps. Explicit time limits
are bounded at60seconds per attempt and120seconds total. Configured byte caps are
bounded at 256 KiB, 32 questions and 32 enum choices per question. Native HTTP
error bodies are discarded. A timeout has unknown provider/billing outcome;
reconcile before replay rather than treating it as no call.

An injected `transport(body_bytes, timeout_seconds=..., max_response_bytes=...)`
returns `TransportResponse(status, body_bytes, retry_after_seconds=None)`. It uses
no credential lookup. Arbitrary in-process callbacks cannot be preempted; a late
fixture callback is rejected rather than cached. The real HTTP path is contained
in a child with a wall timeout; no background process or watchdog is installed.

The optional private cache directory must fit the existing shared artifact path
boundary. Cache identity includes adapter/provider/endpoint, engine scope,
canonical request, schema plus policy, pinned model and transport kind. Fixture
and live caches cannot mix. Positive entries hold only validated normalized
probability outputs, not raw request/response bodies. Singleflight locks are
deadline-bound; publication uses immutable hashed artifacts and an atomic durable
pointer. Errors/unknown outcomes are not cached as positive results. Corruption
fails closed without automatic refetch; preserve/quarantine the damaged entry and
reconcile before an explicit replay. Optional cache publication failure returns
the validated decision with a stable warning.

Verification:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  shared.typed_judge.tests.test_client -v
```

The tests exercise synthetic label and claim-support consumers, typed outputs,
abstention, invalid probabilities, model mismatch, canonical caching, corrupt
entries, unknown failure, bounded retries, process-timeout invocation, secret
redaction and a synthetic credential under a mocked root. They do not establish
live service access, actual latency/cost, task accuracy or future scheduled
acceptance. Root setup documentation/inventory and the required future Codex
business-path/email acceptance remain owned by the integrating runtime.
