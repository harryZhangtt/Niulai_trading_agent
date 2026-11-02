# Lightweight UI intent evaluation — 2026-11-02

Final candidate v2 passes the frozen fresh-validation screen: 12/12 strict
correct, equal to baseline, with zero critical failures or unnecessary skill
loads. Its policy text is approximately half as long; actual reported input plus
output tokens fell 2.13% in these standalone calls. This supports the stated small
screen only. No global installation or runtime activation was performed by this
evaluation. A later installation decision belongs to the parent task.

| Fresh validation v2, one batch each | Baseline | Lightweight v2 |
| --- | ---: | ---: |
| Strict correct requests | 12/12 | 12/12 |
| Critical / missing / extra / optional skill selections | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Reported input tokens | 24,748 | 24,206 |
| Reported cached input tokens | 0 | 0 |
| Reported output tokens | 324 | 331 |
| Reported reasoning output tokens | 30 | 37 |
| Input + output tokens | 25,072 | 24,537 |
| Batch wall seconds | 15.82 | 13.67 |
| Policy-only tokenizer proxy | 1,083 | 541 |
| Full supplied prompt tokenizer proxy | 1,807 | 1,265 |
| Selected guide entrypoint bytes, hypothetical later load | 204,620 | 204,620 |

V2 was frozen after one development-discovered repair: distinguish native Pencil
capture from web browser verification, and avoid overlapping layout guidance
already covered by a visual or hardening workflow. The card editor did not see
the 12 fresh validation requests/gold before freezing v2. No tuning occurred after
validation. This is not an OS-protected holdout; the evaluation author knew gold.
V2 was not rerun on the 24 development cases. A separate authoring-subagent
unblinded reasoning screen checked the repair on three already-seen development
requests; it has no measured provider usage and is not a model accuracy result.

V2 input tokens fell 542 (2.19%), input + output fell 535 (2.13%), and its policy
proxy fell 542 (50.05%). Batch latency has only one observation per arm and is not
evidence of a stable speed improvement. No per-request latency was measured.
V2 raw SHA-256 is
`ec9c8d4f1ad404ff337806032c17c6a8ba86bd987cec6076af61f2f57e477c03`.

Candidate v1 fails the predeclared development gate: baseline 24/24 strict correct,
candidate 23/24, with one critical over-selection. There were no required skill
misses; clarification and resolver-status handling were correct in all 24 cases
for both arms. Its failure remains part of the evidence. The two candidate
versions must not be combined into a 36-case v2 score.

| Development v1, one batch each | Baseline | Lightweight v1 |
| --- | ---: | ---: |
| Strict correct requests | 24/24 | 23/24 |
| Critical failures | 0 | 1 |
| Missing required skills | 0 | 0 |
| Unneeded selected skills | 0 | 1 |
| Allowed optional skill selections | 0 | 2 |
| Reported input tokens | 25,435 | 24,753 |
| Reported cached input tokens | 0 | 0 |
| Reported output tokens | 673 | 688 |
| Reported reasoning output tokens | 66 | 74 |
| Input + output tokens | 26,108 | 25,441 |
| Wall seconds | 21.30 | 20.52 |
| Policy-only tokenizer proxy | 1,083 | 503 |
| Full supplied prompt tokenizer proxy | 2,356 | 1,776 |
| Selected guide entrypoint bytes, hypothetical later load | 486,830 | 524,763 |

Candidate v1 selected `pencil-design` and `browser` for D12, an unavailable native
Pencil `.pen` edit/screenshot task. The baseline selected only `pencil-design`.
Both correctly resolved `UI_ROUTE_BLOCKED`; the browser guide was still an
unnecessary body, so frozen gold remains unchanged. The criticality and gate
were defined before results. Its likely mechanism is the card's broad screenshot
to browser rule, which does not distinguish native Pencil capture.

The instruction text proxy shrank 53.55%; actual reported input tokens shrank
2.68% and input + output tokens shrank 2.55%. Common host context accounts for
most of the input, so these results do not support a 54% end-to-end saving.
The candidate's hypothetical subsequent guide bytes increased 7.79% through the
extra browser guide and two permitted layout selections. Those bodies were not
sent to the classifiers and are not included in the measured model-call savings.
Reasoning is retained as its provider-reported field, not added again to the
input + output accounting. Dollar billing is unknown.

Both runs requested the existing configured `gpt-6.1-sol` profile, reasoning `low`,
timeout 120 seconds, with no retries or fallback. The CLI did not emit an observed
model identity; the requested identifier is not independent backend identity
verification. Tools were disabled and gold was absent from the model prompts.
Packet separation is not an OS-protected holdout. The authoring subagent has seen
gold and does not count its own inspection as blinded performance.

The 24 development and 12 fresh validation cases, gold, budgets, grader and
candidate fingerprints were frozen before dispatch. Five grader boundary tests
passed. Existing evidence contracts were checked before dispatch and after host
grading. Raw prompts, responses, usage and event hashes remain in the ignored
project-local `.job-runtime/evaluations/ui-intent-lightweight-20261102/`; immutable
contract/prompt artifacts remain in `.research-sources/ui-intent-lightweight-20261102/`.
Sanitized arm results and output decisions are in
`tuning/runtime/ui-intent-lightweight-20261102/development-v1/`.

Candidate v1 raw SHA-256:
`272d6e628966098b579ec1756e2c34f02af51dfd8f51bd17d04d8f1ede7ff6f7`.
Baseline raw SHA-256:
`751e2deacd611bcd6f8d4f3e918b8f45dd99321321687b87b1c4a9b64d22984e`.
The full protocol is [protocol.md](protocol.md); executable host paths are
[run.py](run.py), [grade.py](grade.py), and optional [measure.py](measure.py).

Fresh validation results and decisions are in
`tuning/runtime/ui-intent-lightweight-20261102/validation-v2/`. The combined
machine-readable [summary](../../runtime/ui-intent-lightweight-20261102/summary.json)
retains all four attempts (101,158 reported input + output tokens, dollar cost
unknown) and separate split/version verdicts. Existing contracts were validated
at each original dispatch and completion; the intentional v1-to-v2 candidate
source change means old v1 source hashes describe that earlier revision.

The protocol's four-call ceiling is exhausted; no failure was retried. The five
grader boundary tests passed and the final v2 contract validates. These small
synthetic matched batches can expose a concrete failure; they cannot establish
universal routing accuracy, latency superiority or stochastic stability. This
manual evaluation is separate from required future-scheduled-session major
runtime acceptance. No external messages or scheduled business effects were sent.
