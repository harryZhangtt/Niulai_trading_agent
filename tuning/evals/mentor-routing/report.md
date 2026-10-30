# Lightweight mentor routing screen — 2026-10-30

The selective router met the preregistered practical adoption rule for this small
screen and is the **provisional default** in `mentor/ROUTING.md`. The observed
quality differences are too small to establish general skill effectiveness.

| Condition | Guidance score / 32 | Critical failures | Loaded instruction-token proxy | Output-token proxy |
| --- | ---: | ---: | ---: | ---: |
| Existing general mentor policy, no full skills | 30 | 0 | 2,608 | 1,151 |
| Former routing: supervisor + evidence + needed specialist | 31 | 0 | 29,326 | 1,187 |
| Selective full-skill routing + compact contract | 32 | 0 | 20,134 | 1,204 |

Instruction context fell **31.34%** against former routing across the four
independent decision snapshots. No case score regressed. Answer size did not fall;
this is a reduction in loaded instructions, not an answer-shortening result.

| Case | General policy | Former routing | Selective routing |
| --- | ---: | ---: | ---: |
| Confounded selection experiment | 7 | 8 | 8 |
| Missing report and skipped cases | 8 | 8 | 8 |
| Broken judge identity/cost/failure accounting | 7 | 7 | 8 |
| Genuine licensed-data dependency | 8 | 8 | 8 |

The differences concerned retaining all attempted variants and specifying a grader
negative control. General policy already handled most decisions correctly.
These results do not support loading large skill bodies for every mentor turn.

## Separate routing check

A fresh worker received seven requests and the routing contract, without expected
routes. It selected the required specialists on **7/7**, included no unnecessary
specialist, handled experiment/evaluation overlap, and selected no mentor skill
for an ordinary summary. This checks basic semantic routing, not all ambiguous
future tasks. The answer-quality comparisons used author-selected skill subsets;
they do not themselves establish router accuracy.

## Execution and grading

- Four fresh synthetic cases × three conditions; each solver had a new context,
  the same inherited GPT-6.1 Sol model/settings, fixed output contract and 220-word cap.
- A separate same-family grader saw anonymized, shuffled answers. It correctly
  scored two extreme calibration anchors before receiving real responses.
- Four anchored criteria per case, 0–2 each; critical failures could not be averaged away.
- The root reviewed answers, arithmetic, critical failures and the score gaps.
- The grader's first result had invalid JSON quoting. Parsing stopped aggregation.
  One permitted serialization repair preserved all twelve score arrays; the
  malformed attempt remains in runtime. No missing answer or failed attempt was omitted.
- All twelve solver outputs were present, valid JSON and within the output cap.
- Isolation was instruction-level, not an OS-enforced sandbox; graders and workers
  retained tool capabilities. This is not a claim of secure evaluator isolation.

The protocol and cases were frozen before model responses. These cases are now
development evidence and must not be relabeled as fresh holdouts in later work.
No protected investment cases, private state, live trading or external search were used.
The skill snapshot predates the subsequent atomic gate refinement; its small
promotion-gate reference has a separate fresh check in `../mentor-gates/report.md`.
The routing scores and token counts above have not been relabeled as measurements
of that later revision.

## Cost and inference limits

Counts use tiktoken 0.12.0 `o200k_base` on serialized task instructions and answers.
They are a repeatable **tokenizer proxy**, excluding hidden provider instructions,
reasoning, tool overhead, billing and caching. No end-to-end token, dollar, latency
or long-session efficiency claim is made. In a session that eventually needs all
five specialists, cumulative context savings may be smaller. Already loaded text
is not removed by the router; avoid rereading it and preserve compact state across compaction.

One response per condition/case and same-family model grading cannot establish
statistical superiority, transfer to actual tuning execution, or durable behavior.
The skill-effectiveness conclusion is **inconclusive**. Routing adoption is
provisional because the observed quality floor held while instruction overhead fell.

## Artifacts and reproduction

- Frozen protocol: `protocol.md`; solver cases: `cases.json`; route cases: `routing-cases.json`.
- Numeric results and evidence excerpts: `results.json`.
- Local raw packets, responses, manifest, anchors, grades and failed format attempt:
  `tuning/runtime/mentor-routing-v1/` from the workspace root.
- `build_packets.py` builds immutable packets and refuses an existing run manifest.
  Workers were dispatched with fresh `fork_turns=none` contexts; this file is not
  an automatic model runner.
- To recheck the recorded artifacts, run `summarize.py` using the workspace-local
  validation environment with `TIKTOKEN_CACHE_DIR` under `tuning/runtime/`.

Keep the five substantive skill packages available. The router selects procedures
on demand; it introduces no additional model service. Follow up on the next real
tuning task with artifact-backed decision, execution and cost records before
claiming that the skills improve complete research sessions.
