# Source selection and adaptation record

Reviewed 2026-10-30. The five skills now contain upstream workflow text and local
copies of supporting resources. They are not links to unavailable global skills.
Exact commits, original hashes and installed hashes are in `sources.lock.json`;
MIT notices are retained in `licenses/` and linked by each skill's `UPSTREAM.md`.

| Local skill | Upstream implementation | Retained substance |
| --- | --- | --- |
| research-supervisor | OthmanAdi/planning-with-files, plus obra/superpowers verification-before-completion | Persistent plan/findings/progress workflow, three templates, upstream read-only phase-format validator, resumption questions, error history, fresh completion evidence |
| progress-and-recovery | obra/superpowers systematic-debugging | Four investigation phases, boundary tracing, minimal hypothesis tests, root-cause and condition-waiting references, four pressure/academic cases and upstream creation log |
| experiment-design | K-Dense-AI/claude-scientific-skills (redirects to scientific-agent-skills), hypothesis-generation | Rival explanations, falsification, operationalization, preregistration, eight Python files implementing seven public CLIs, JSON/CSV/Markdown assets and methodological references |
| evidence-and-overfitting | K-Dense scientific-critical-thinking | Claim appraisal, methodology, bias taxonomy, statistical pitfalls, logical fallacies, experimental design and evidence synthesis |
| evaluation-design | muratcankoylan/Agent-Skills-for-Context-Engineering, evaluation + advanced-evaluation | Outcome dimensions, deterministic gates, difficulty strata, direct/pairwise judging, rubric construction, position swaps, calibration and four detailed judge references |

## Evidence behind the choice

Discovery used the working ChatGPT Work search route:
https://chatgpt.com/c/6ae45fd0-ac78-83ec-b5fe-15f0710d1ff9
Source inspection then used real Git checkouts and the exact files listed in the
lockfile. GitHub's unauthenticated API was rate limited; no star-count claim is
needed for selection. Licenses were read from the checkouts.

- Planning with Files has extensive script/host tests and author-run comparisons
  in its `docs/evals.md` and README. The historical recovery benchmark used a
  different recovery mode; it does not prove this manual local adaptation's effect.
- Superpowers' debugging `CREATION-LOG.md` reports four author-run pressure tests.
  The cases and detailed methods are useful evidence of development, not an
  independent controlled result for investment-agent supervision.
- K-Dense ships a hypothesis-generation test suite and local deterministic tools.
  This workspace reruns the imported tests. They check structural and operational
  invariants, not truth, profitability or hypothesis superiority.
- Context Engineering has routing tests and an effectiveness benchmark design.
  Routing accuracy is not proof that loading these two skills improves outcomes.
  We use the detailed methods and disclose that effectiveness remains unmeasured here.

These are established reusable implementations with inspectable testing assets.
We do not claim that all five are empirically proven for this investment agent.
Local validation is recorded in `../tests/upstream-validation.md`.

## Pruning rule

Keep relevant or plausibly transferable material. Remove a procedure only when
its mechanism, dependencies or domain have a concrete mismatch with this task.
Delete the operative text and active link, rather than appending a contradictory
warning. Retain provenance outside the active workflow so a future task can
reassess a removal from the pinned source.

| Removed or replaced | Concrete mismatch | Effective local change |
| --- | --- | --- |
| Planning plugin lifecycle hooks, transcript-store recovery, installation paths, optional gated continuation and shell initializers | This task configures workspace-local mentoring; no host hooks or session-store reader are installed. Those instructions would refer to absent mechanisms or global paths. | Omitted host setup and hook blocks; preserved manual file planning, templates and the read-only format-validation branch from `check-complete.sh`. Removed automatic path resolution and continuation behavior from that adapted helper. No hooks registered. |
| Mandatory save-every-two-actions and escalate-after-three-failures rules | The workspace requires proportionate effort and evidence-based blocker handling; operation counts alone do not identify a stall or external dependency. | Replaced the actual rules with evidence-batch capture and bounded recovery. |
| npm pollution helper and Lace-specific TypeScript waiting example | The helpers hard-code an npm test runner and private Lace imports absent from this mentor package. | Removed dangling invocation instructions; retained tracing and bounded condition-waiting techniques. |
| Mandatory external Superpowers TDD skill invocation | No such global dependency is installed by this package; routine reversible edits do not warrant fabricated tests. | Replaced with a minimal reproducer/meaningful code regression check and local verification guide. |
| Debugging claim that three failures prove architecture is wrong, and unsupported 95% claim | Attempt count is not causal evidence; a percentage without a measurement cannot support a diagnosis here. | Deleted fixed-count diagnosis and mandatory permission stop; retained architectural review when repeated failures expose coupling. |
| Paid schematic generation, OpenRouter credentials and scientific-schematics dependency | Evidence appraisal and agent tuning need neither paid image generation nor private-data transmission. | Deleted the complete figure procedure, compatibility dependency and active reference to that service. |
| Formal clinical appraisal algorithms and clinical hierarchy as a ranking | Agent-output quality and investment outcomes are not clinical trial endpoints. Formal clinical checklists cannot automatically grade these claims. | Removed clinical procedure sections from entrypoint, core capability and hierarchy references; removed clinical tool/version routing from source notes. Retained general bias, dependence, causal-design and synthesis methods. |
| Mandatory human/animal/biosafety review workflow for ordinary software experiments | The actual experiment concerns software prompts, tools and public/synthetic cases. Clinical review gates do not apply. | Replaced operative scope steps with software/data boundaries. The unmodified validator schema retains `not_applicable` fields; they do not trigger approvals. |
| Generic 0.7/0.9 acceptance thresholds, 50-case minimum and fixed alert rates | No workload calibration or power calculation justifies these cutoffs for our tasks. | Replaced active numeric rules with declared decision costs, coverage, dependence and uncertainty. Numeric toy examples remain examples, not defaults. |
| Evaluation demonstration scripts | The basic scorer assigns assumed scores and simulates an agent; the advanced script demonstrates output rather than invoking a real judge. Neither can establish a valid result. | Not installed or invoked; the substantive evaluation/judge procedures and references are retained. |
| Pairwise agreement converted directly into confidence/probability | Swapped-order consistency does not establish correctness or calibrated probability. | Replaced operative confidence rule with mapped identity consistency, explicit disagreement and separate calibration. |

## Deliberately retained

Randomization, causal estimands, positive/negative controls, rival predictions,
missingness, multiplicity, replication and independent sampling-unit reasoning
transfer to agent experiments. They remain even when upstream teaching examples
come from another scientific domain. Templates, substantive references and the
seven deterministic CLIs were preserved rather than replaced with summaries.

Original local investment constraints remain in each skill's required
`references/investment-context.md`: temporal information availability, model
knowledge contamination, prospective evidence, transaction costs, selection/entry
separation, all-variants logging and protected holdouts. Local changes are visible
through per-file hashes, and must be re-reviewed when updating an upstream commit.

## Update policy

Do not auto-update at runtime. Inspect a proposed upstream revision, its license,
changed workflows and executable resources; reapply only justified domain edits;
rerun the local checks; then update the commit and hashes. Never regenerate hashes
merely to hide an unexplained local change.

## Evidence-driven local refinement after screening

The atomic quality-gate screen preserved five correct verdicts and one label
failure: a missing required case was called `reject` while its rationale correctly
described incomplete evidence. The local `evaluation-design/references/promotion-gate.md`
now distinguishes acceptance blocking, observed quality failure and inconclusive
evidence. The full entrypoint links it at adoption decisions. This is a local
addition based on an observed decision ambiguity; it does not remove upstream
methods. Original and fresh follow-up results live in `tuning/evals/mentor-gates/`.
