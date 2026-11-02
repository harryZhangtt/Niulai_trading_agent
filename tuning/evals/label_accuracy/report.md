# Jev development screen,2026-11-02

Result: **partial transport coverage; no promotion**. Both arms and all eight
reviewed cases were sealed before dispatch. Read-only closure/output/regrading
verification passed. The rule arm completed eight cases. Jev returned two valid
responses, then its third call exceeded the45s hard deadline with unknown
provider/billing outcome. Five remaining cases were explicitly `not_dispatched`.
No failed/unknown request was retried. All eight cases remain in denominators.

| Measure | Existing metadata rules | Jev passage policy |
| --- | --- | --- |
| Required cases | 8 | 8 |
| Valid response cases | 8 | 2 |
| Unknown timeout / unstarted | 0 /0 | 1 /5 |
| Exact document correct / required | 3 /8 | 2 /8 |
| Document classified / required | 4 /8 | 2 /8 |
| Classified decisions / required | 7 /96 | 23 /96 |
| Semantic abstentions | 89 | 1 |
| Unavailable decisions | 0 | 72 |
| Positive-topic recall on six unique-gold cases | 2 /15 | 1 /15 |
| Positive-topic F1 on that subset | .2353 | .1250 |
| All critical exact-case gates passed | No | No |

The two successful Jev responses took1.091s and.750s; the unknown call took
45.007s. The arm used47.09s wall time and three observed dispatch attempts.
Reported usage for successful responses totals4370input/693output tokens;
the timeout's usage and total billed cost remain unknown. Mean latency over
three observed attempts is15.616s, not a general service SLA. No estimated token
price replaces missing billing evidence.

Case1 recognized the earnings document but missed an allowed positive topic
and abstained on one decision. Case2 passed the predeclared legal-terms case.
Rules' selective topic F1 is1.0 only over their few emitted positive hints; their
full positive-topic recall is.1333. Jev's selective document accuracy is1.0 on
two completed documents; its required-roster accuracy is.25. Neither selective
number supports superiority. The strict full-case gates fail for both workflows.

Gold was independently drafted by an evaluator agent, then reviewed against
the exact public passages by the coordinator before model output inspection.
This is coordinator-AI development review, not human gold. Predeclared document
and topic ambiguities were retained. There are eight source versions, four from
one issuer, and the earnings passage was already used for the source smoke.
The arms receive the same source/chunk/taxonomy/cutoff contract but consume
different features: URL/origin hints versus passage text. This is a small workflow
comparison, not an isolated model effect, held-out accuracy, calibration,
statistical significance or demonstrated investment value.

The `.60` probability/`.10` margin thresholds remain provisional and unchanged
after results. Future completion requires a separately reviewed/registered
attempt, retaining these outcomes and reconciling unknowns before replay. A
successful scheduled single-source E2E cannot fill the five missing predictions
or promote this screen. Private immutable run and verification references are
indexed under `mentor/runtime/jev-labeling-20261101/eval/`.

The separate future-triggered runtime test also remains failed. Its first slot
launched a real Codex session but failed workspace imports from the isolated cwd.
Explicit command-scoped `PYTHONPATH` then passed an isolated no-network import
check. Two later slots stopped under the non-replay-safe startup retry fence,
with no session or Jev output; auth-cache contention is inferred from that early
code path and supported by a subsequent live lock-holder snapshot. Existing
authorization, retry and production-job boundaries were preserved. All new Jev
test allocations were disabled; no scheduled provider acceptance is claimed.
