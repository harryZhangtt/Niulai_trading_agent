---
name: ai-tuning
description: "Explicit AI tuning assistant: diagnose prompt, RAG, tool, memory, latency and evaluation problems; select source-grounded engineering guidance and produce a bounded baseline/candidate experiment. Advisory preview, not production activation."
disable-model-invocation: false
---

# AI tuning

## Scope and boundaries

Users may invoke this entrypoint directly, and assistants may select it for relevant
AI tuning requests. It composes the existing six
Mentor specialists; it is not a seventh specialist or a background controller.
The reviewed knowledge corpus is advisory. Candidate 1.0.2 has provider-free
validation, not protected evidence of improved performance. Do not claim otherwise.
Invoking this skill does not authorize paid calls, production changes, scheduled
emails, credential access, or protected benchmark access. Respect any separately
recorded authorization and budget; unknown outcomes require reconciliation.

## Locate and load selectively

Resolve this SKILL.md's real path. The workspace is its fourth parent
(`Path(skill_file).resolve().parents[3]`). All paths below are relative to that
workspace. Do not rely on the shell's current working directory.

Read `mentor/AGENTS.md` and `mentor/ROUTING.md`, unless already loaded. Read
`mentor/references/llm-engineering/guide.md` as the small card index. Select at most
three relevant cards from `mentor/references/llm-engineering/knowledge-cards.json`.
Do not load the PDF, whole source ledger, all specialist bodies, or private data
as a precaution. Select by the observed failure, not incidental words.

| Observed decision | Card | Existing specialist |
| --- | --- | --- |
| Missing baseline, incomparable results, promotion claims | KC-EVIDENCE-001 | evaluation-design |
| Choosing the cheapest adequate intervention | KC-ADMISSION-001 | development-discipline |
| Prompt, context, output-format or instruction failures | KC-PROMPT-001 | experiment-design |
| Retrieval misses, source fidelity, RAG complexity | KC-RETRIEVAL-001 | evidence-and-overfitting |
| Tool effects, duplicate execution, unknown delivery | KC-EFFECTS-001 | progress-and-recovery |
| State authority, stale memory, semantic recall | KC-STATE-001 | research-supervisor |

For example, extract only selected card bodies with the Python standard library:

```python
import json
from pathlib import Path
root = Path(skill_file).resolve().parents[3]
selected = {"KC-PROMPT-001", "KC-EVIDENCE-001"}
corpus = json.loads((root / "mentor/references/llm-engineering/knowledge-cards.json").read_text())
print(json.dumps([c for c in corpus["cards"] if c["card_id"] in selected], ensure_ascii=False))
```

Load the specialist procedure needed for the current decision via the existing
router. For experiment design read `mentor/skills/experiment-design/SKILL.md`;
for evaluation design read `mentor/skills/evaluation-design/SKILL.md` and its
investment context/promotion gate. Source citations are available through each
selected card's source_claim_ids and diagram_ids; open only needed references.

If no card fits, say so and use the appropriate existing Mentor specialist.
If files are missing or malformed, report guidance unavailable and continue with
clearly labeled general advice. Never block ordinary messages or recovery.

## Work the actual problem

1. Identify the target component, observed failure, current baseline and desired
   outcome. Separate user facts from assumptions. If no trace is available,
   propose the minimum measurement rather than inventing a diagnosis.
2. Select relevant cards, including contraindications and evidence limitations.
   Explain which mechanism applies. Do not equate source advice with measured
   project improvement. For latency, inspect the critical path before proposing
   more agents, caches, model changes or infrastructure.
3. Propose the smallest falsifiable intervention. Keep baseline and candidate
   workload, model, tools and budget matched except for the variable under test.
4. Define acceptance criteria before execution: quality, critical failures,
   latency/cost, repeated-run variability and an explicit stopping rule. Choose
   sample size and thresholds from the task; do not invent universal defaults.
5. Leave protected cases outside development. Do not tune against held-out results
   or expose card/route/arm metadata to a blinded judge. Use maintained tuning
   runners where applicable; do not bypass their frozen contracts.
6. Default to diagnosis and experiment design. Execute only when the user's
   request and existing authorization cover it. Do not silently expand scope.

## Deliverable

Answer in the user's language. Keep these fields concrete and concise:

- **Diagnosis:** observed problem, likely mechanism, and missing evidence.
- **Guidance:** selected principles and limits, with relevant repository sources.
- **Smallest experiment:** baseline, candidate, single changed variable and workload.
- **Measurement:** quality, safety, latency/cost, repetitions and evidence to retain.
- **Acceptance and stop rules:** explicit pass/fail/inconclusive conditions and budget.
- **Next action:** the immediate executable step, owner and required authorization.

End with the actual execution status: design only, executed with evidence, failed,
or inconclusive. Never report a proposal as a completed experiment.
