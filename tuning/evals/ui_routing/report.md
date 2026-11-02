# UI router intent and token results — November 2, 2026

The compact policy matched the incumbent on this development screen: **30/30
requests correct in both forward and reverse order**, including all 17 critical
cases. There were no mandatory omissions or unnecessary skill loads. These are
60 observations per variant of the same 30 requests, not 60 independent cases or
proof of universal accuracy. Five grader fault checks passed.

| Measure | Incumbent | Compact |
| --- | ---: | ---: |
| Correct requests, forward / reverse | 30 / 30 | 30 / 30 |
| Critical failures, both orders | 0 | 0 |
| Mean actual input tokens per 30-request batch | 26,700 | 25,360 |
| Mean actual output tokens | 1,463 | 1,517 |
| Mean actual total tokens | 28,163 | 26,877 |
| Supplied classification policy, tokenizer proxy | 2,062 | 773 |

Actual input dropped **5.02%**, and total input+output dropped **4.57%** in these
standalone calls. Common host instructions dominate the input; reducing the
policy by 62.5% does not imply a comparable reduction in total session cost.
All four cache-token receipts were zero. Dollars and a resolved backend model
identity were unreported. The requested profile was the existing default
`gpt-6.1-sol`, low effort, unchanged for both variants.

Calls took 26.5–38.6 seconds per batch. This small order check does not establish a
latency gain. An extra standalone LLM classification round would be costly;
production should keep intent selection in the existing agent turn.

The resolver itself makes zero model calls and consumes zero LLM tokens. On this
host, 100 in-process calls per route yielded p95 from **0.17 to 0.53 ms**. Twenty
fresh CLI calls for the layout route had median **25.1 ms**, p95 **30.3 ms**.
These are local warm-file/process measurements, not provider latency or a
cross-machine throughput guarantee.

| Potential selected guide context | o200k_base proxy tokens |
| --- | ---: |
| Backend-only | 0 |
| Existing hardening | 466 |
| Focused layout | 3,716 |
| React race + render performance + browser | 7,368 |
| Cinematic landing + React + scroll + browser | 24,650 |

These guide sizes are potential full-entrypoint loads; they were not forwarded
to the model in the intent-only benchmark and exclude later references. Blocked
Pencil selection does not imply execution or automatic guide exposure. All 22
full entrypoints total 63,152 proxy tokens, but loading them all is a hypothetical
baseline: the incumbent already uses progressive loading. The raw incumbent
startup policy/router alone is 1,364 proxy tokens; the benchmark additionally
supplies its registry. Portable loader overhead must be counted separately.

The result supports a compact selective-guidance package for this tested scope.
It does not establish better generated UI or unrestricted automatic routing.
The remaining token bottleneck is reading large selected experts; keep further
reference loading specific to the requested phase rather than adding more
routing services or indiscriminately pruning source material.

Raw immutable evidence stays under
`.niulai-state/reports/research-sources/runtime/ui-router-intent-20261102-v1/`,
with authentic model events/responses under `.job-runtime/experiments/`.
Contract hash: `98ffd3f6a608e43071cc0277607375d880ea37bed0d768c21d5b64422ae4b5a7`.
Report hash: `8cc198dd953a0082e6d183d497c06b8466f4a8b22dc1b5507d2111aeaa524586`.
The [protocol](README.md), case roster and source pins retain the original rubric.

For user-level exposure, official OpenAI documentation supports
`~/.agents/skills` across repositories and metadata-first discovery. A single
router entrypoint with internal guides avoids adding 22 duplicate discovery
entries. Actual installed-host discovery/invocation must still be verified.
[Official OpenAI skill documentation](https://learn.chatgpt.com/docs/build-skills)
