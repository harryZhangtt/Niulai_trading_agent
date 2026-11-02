# UI intent routing: lightweight development evaluation

The agent interprets the request; `ui/route.py` deterministically resolves explicit
selectors. Resolver success alone is not intent accuracy. This round compares the
incumbent UI policy/router plus catalog with a frozen compact routing card,
without changing either the canonical resolver or the expert guides.

Thirty new development requests cover every catalogued expert, English/Chinese,
non-UI exclusions, quoted hostile page/log text, ambiguous scope, conflicting and
separate visual authorities, compositions, and missing Pencil capability.
Seventeen are critical. Cases and required/optional selections were frozen before
model dispatch. Gold is absent from the tool-free model prompt; host grading uses
the existing sealed `evidence_runtime.contracts` ledger. This is packet separation,
not a protected OS-blind holdout. Many cases explicitly name tools/styles, so it
is not a representative estimate of all natural-language traffic.

Both variants use the configured default model/profile, no fallback or automatic
retry, the same requests/schema and numeric ceilings. Four calls are
counterbalanced: incumbent forward, compact reverse, compact forward, incumbent
reverse. Every call has a fresh session, at most 120 seconds and 100,000 observed
input+output tokens; the study stops before another call at 300,000 total observed
tokens. Unknown usage/outcomes cannot be treated as passing. Source/card/grader
fingerprints are checked at claim and finish. Retain failures and all case IDs.

Host checks require the intended mandatory guides, permit only predeclared
optional guides, verify dependency closure and capability status, preserve
separate alternatives, and require clarification without loading a bundle for
material ambiguity. Five mutation checks exercise the grader. A critical miss
cannot be averaged away. `loaded_body_bytes` is a legacy metric name for selected
entrypoint bytes; it is a potential context proxy, not observed model exposure.

Report intent correctness, critical errors, missing/extra/optional selections,
local resolver timings, potential guide-context cost and actual model usage
separately. Do not add a standalone model router to production: classification
can occur in the agent's existing turn, followed by the zero-LLM resolver.

The scoped decision rule requires no observed critical failure and no reduction
in strict case correctness for the compact guidance. Passing permits only this
small development claim. Cross-repository discovery, installed-package invocation,
rendered UI quality and broader generalization need their own evidence.

Reproduce source tests and read the completed result:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest tuning.evals.ui_routing.test_grade -v
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m tuning.evals.ui_routing.summarize
```

`run.py prepare` refuses an existing study. Its sealed source closure must remain
unchanged during a round. Repeating the experiment requires a reviewed new study
identity; never overwrite the prior attempts. `measure.py` uses the existing
project-local tokenizer environment documented in the frontend runbook, with
`tiktoken==0.12.0` and a workspace-local cache. That encoding is explicitly a
proxy; no billed cost is inferred.
