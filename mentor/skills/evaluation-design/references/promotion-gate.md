# Distinguish a blocked acceptance from a rejected candidate

Use when recommending adoption, rejection or further evaluation of a tuning
change. First identify the exact object and scope being judged: a prompt's
performance, a grader's correctness, a runner patch, or a bounded development gate.

| Verdict | Evidence required | Next action |
| --- | --- | --- |
| Accept / supported for the stated decision | Complete, valid evidence meets every applicable frozen criterion, with no unresolved critical failure | Permit only the scope actually tested; preserve evidence and broader limitations. |
| Reject | Observed valid evidence violates a predeclared quality criterion or critical failure gate | Identify the actual violation; fix or discard that version as appropriate. |
| Inconclusive | Missing, invalid, inaccessible or insufficient evidence prevents the stated decision, without an already established decisive quality violation | Block acceptance, preserve the candidate, and identify the smallest evidence/measurement repair. |

Blocking acceptance does not by itself establish that the candidate is worse.
For example, a required case with no grading output makes the performance decision
inconclusive. A verified material source error that breaches a zero-critical-error
rule is a rejection under that rule. If both occur, the observed decisive violation
can justify rejection; report the missing evidence too.

An invalid grader artifact fails deterministic validation and must not contribute
a favorable score. Its implication depends on the object: a demonstrated grader
bug can reject that grader version, while leaving the prompt-performance claim
inconclusive. Never silently exclude the failed attempt or call its absence a pass.

Report the verdict, decisive observed evidence, claim actually allowed, and next
action. Use the task's declared coverage, costs and tolerances. A small complete
deterministic regression suite can support its scoped software gate; repeating
the same inputs does not establish generalization or independent observations.

This distinction was added after the atomic gate screen classified a missing-case
decision as `reject` despite describing the evidence as incomplete. The original
failure and the fresh follow-up remain in `tuning/evals/mentor-gates/`.
