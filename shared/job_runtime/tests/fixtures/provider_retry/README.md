# Provider retry conformance fixtures

## Status and scope

This directory contains **provider-neutral synthetic schema examples only**. Every
JSON document declares `evidence_status: synthetic_not_live_evidence`; none is a
provider capture, production trace, Codex event, runtime test result, or proof of
provider behavior. The files contain no credentials, raw exception text, response
bodies, request bodies, account identifiers, or provider-specific payloads.

The fixtures are non-executable inputs for a future conformance harness. They do
not change retry behavior and do not authorize provider calls, submissions,
replays, or external effects.

## Common schema

Each JSON file is one object with:

- `schema_version`: integer, currently `1`.
- `fixture_id`: stable provider-neutral scenario name.
- `evidence_status`: exactly `synthetic_not_live_evidence`.
- `sanitization`: booleans that must all remain `false` for credentials, raw
  errors, and provider payloads.
- `input.transport_phase`: generic point at which the observation occurred.
- `input.request_body_state`: whether transmission was not started or fully sent.
- `input.observation`: sanitized status, selected control headers, and optional
  stream completion facts. `http_status` is an integer or `null`.
- `expected.classification`: the expected provider-neutral retry classification.
- `expected.retry_eligible`: classification-level retry eligibility, not an
  instruction to retry a live operation.
- `expected.submission_state`: whether submission is known, rejected, incomplete,
  or unknown.
- `expected.body_replay`: the replay precondition or prohibition.
- `expected.retry_delay_source`: `retry_after_seconds`, `local_backoff`, or `none`.

Headers are lower-case and limited to retry controls needed by the case. Absence
of a field is meaningful; consumers must not invent live-provider defaults.

## Cases

| Fixture | Expected classification | Key boundary |
| --- | --- | --- |
| `preconnect-failure.json` | `retryable_transient` | No request body started; replay is safe. |
| `typed-429-retry-after.json` | `retryable_rate_limit` | Valid delta-seconds `Retry-After`; body must be replayable. |
| `typed-529.json` | `retryable_provider_overload` | Provider-overload status; local backoff. |
| `permanent-auth.json` | `permanent_authentication` | Authentication rejection is not retried. |
| `permanent-config.json` | `permanent_configuration_or_request` | Configuration/request rejection is not retried. |
| `post-submit-reset.json` | `unknown_submission_outcome` | Reset after body transmission; no blind replay. |
| `partial-stream-missing-terminal.json` | `partial_response_missing_terminal` | Bytes observed but no terminal marker; EOF is not success. |
| `x-should-retry-true.json` | `retryable_server_override` | Explicit synthetic retry override wins over status default. |
| `x-should-retry-false.json` | `permanent_server_override` | Explicit synthetic no-retry override wins over status default. |
| `malformed-retry-after.json` | `retryable_rate_limit` | Invalid delay is ignored; bounded local backoff remains. |

The `x-should-retry` examples describe a generic header semantic reproduced by
some SDKs. They are not evidence that any particular scheduled provider or Codex
runtime emits that header.

## Codex fixture admission rule

Do **not** add Codex event fixtures or invent Codex event names from these generic
examples. A future Codex-specific fixture requires either:

1. a pinned, inspectable Codex source file and test that establish the exact event
   name and semantics; or
2. a sanitized actual capture whose provenance, version, redaction procedure, and
   terminal/completion interpretation are recorded.

Until one of those exists, keep Codex behavior as an explicit source limitation,
not a synthetic event contract.

## Validation requirements

A fixture change is conformant only when all checks below pass:

1. Parse every file with duplicate-key rejection.
2. Reject non-finite JSON numbers (`NaN`, `Infinity`, `-Infinity`).
3. Enforce a maximum of 16 KiB per JSON fixture.
4. Require an object root, `schema_version == 1`, the exact synthetic evidence
   marker, all three sanitization flags set to `false`, and an `expected`
   classification.
5. Diff-check the directory so only this README and intended fixture JSON files
   changed; no runtime, setup, code, or existing documentation may change.

A dependency-free validation example, run from the workspace root:

```sh
python3 -I - <<'PY'
from pathlib import Path
import json, math
root = Path("shared/job_runtime/tests/fixtures/provider_retry")

def pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ValueError(f"duplicate key: {key}")
        out[key] = value
    return out

def finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite number")
    if isinstance(value, dict):
        for child in value.values(): finite(child)
    elif isinstance(value, list):
        for child in value: finite(child)

for path in sorted(root.glob("*.json")):
    if path.stat().st_size > 16 * 1024:
        raise ValueError(f"oversize: {path}")
    data = json.loads(path.read_text("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda token: (_ for _ in ()).throw(
                          ValueError(f"non-finite: {token}")))
    finite(data)
    assert isinstance(data, dict)
    assert data["schema_version"] == 1
    assert data["evidence_status"] == "synthetic_not_live_evidence"
    assert data["sanitization"] == {
        "contains_credentials": False,
        "contains_provider_payloads": False,
        "contains_raw_errors": False,
    }
    assert isinstance(data["expected"]["classification"], str)
print("provider-retry fixtures valid")
PY

git diff -- \
  docs/references/scheduler-provider-retry-sources.md \
  shared/job_runtime/tests/fixtures/provider_retry
```

These checks establish fixture syntax and scope only. They do not establish live
provider conformance, scheduler integration, body replay safety, idempotency, or
successful stream completion.
