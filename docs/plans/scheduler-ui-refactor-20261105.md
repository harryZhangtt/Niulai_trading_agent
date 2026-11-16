# Scheduler UI refactor

## Objective and decision

Help the workspace owner identify upcoming work, inspect a consequential problem,
and distinguish completed execution from accepted work and verified delivery.
The current screen defaulted to raw instructions, hid mentor/finite jobs, showed
technical fields before outcomes and could silently substitute another job for a
filtered deep link. Initial desktop capture is retained privately in
`ui/runtime/scheduler-refactor-before.png`.

The user authorized scope/planning fanout and implementation through acceptance.
Three scoped reviews covered business context, component scope and task-based
acceptance. The existing Claude scheduler owner was busy; its recorded handoff and
canonical contracts supplied context. No live Claude consultation or new business
acceptance is inferred from that historical material.

## Scope and ownership

This is a frontend rendering and navigation change. The parent owns the page,
current/attention/recurring classification, rows and CSS. Scoped implementation
owners changed standard detail, mentor detail and scheduler browser tests.
The source-reuse review selected Radix Themes' MIT tab rendering treatment;
its pin, original source and license are retained in target-local runtime and
`ui/datasource/licenses/radix-tabs.md`. No runtime UI dependency was added.

Preserve the current navy, blue, white and semantic status tokens; system sans
is retained for this operational product. Use a compact list beside a useful
outcome panel. A restrained schedule/attention/current overview precedes the
list. Selected detail uses line tabs and clear spacing rather than nested cards.
Mobile selection moves focus to details and offers Back to jobs with row-focus
restoration. Instructions and technical definitions remain deliberate views.

The active change touches only `ui/datasource/src/scheduler/`, scheduler browser
tests, source attribution and documentation. API projection, dispatch, scheduler
configuration, Gmail delivery, hooks and unknown-effect/replay authority remain
with their owning components. The render consumes the existing read-only schema.

## Source grounding

- NN/g progressive disclosure: https://www.nngroup.com/articles/progressive-disclosure/
- Radix Themes pinned source: https://github.com/radix-ui/themes/blob/1faff10ac26ae17f09944d418c6949b93fc6b566/packages/radix-ui-themes/src/components/_internal/base-tab-list.css
- shadcn alternative assessed: https://ui.shadcn.com/docs/components/radix/tabs

Harry UI was explicitly activated for the primary native thread and restored;
frontend-design, Impeccable operate/craft guidance, React guidance and local
browser tooling were selected. The UI/UX local searches did not return a relevant
progressive-disclosure match after one narrower retry; they are not source support
for that decision. Canonical product contracts and the sources above ground it.

## Acceptance before promotion

1. Overview exposes next scheduler run, dated service/snapshot evidence and current
   jobs needing attention. Counts derive from the same defined population.
2. Daily and interval are recurring; once and sequence are finite. Current jobs
   include enabled recurring work, upcoming finite tasks and enabled mentor
   evidence. Historical/completed tests remain inspectable under All jobs.
3. A valid job link selects that exact job, including disabled/historical work;
   an unknown link remains requested-but-not-found. It must not reveal another
   job's details as if they satisfied the link.
4. Standard execution, legitimate no-send, message acceptance and delivery
   verification remain separate. Mentor execution, acceptance, model-turn and
   result-email status remain separate, including the unavailable sentinel.
5. Every existing mentor gate, budget, work-order, safeguard, evaluation field and
   recovery event remains reachable. No private mentor prompt/output is exposed.
6. List, detail and saved preview independently label stale/partial/error data;
   obsolete reads cannot overwrite another entity. Refresh retains only the same
   entity's last good content. Safe saved HTML keeps its empty iframe sandbox/CSP.
7. Keyboard selection, mobile detail/back focus, RTL, long content and narrow
   layouts work without horizontal overflow. Shared navigation remains usable.
8. Typecheck/build, scheduler browser and server suites pass; inspect actual
   desktop/mobile screenshots and one guarded live read-only journey.

The final21 browser cases retain15 prior safety/correctness scenarios, add five
operational task scenarios and one observed mentor-priority regression. Tests are deterministic development evidence, not a
blind usability experiment or measured improvement in task completion time.

## Progress and evidence

The first integrated run passed16/20; four test assumptions about detail-view
location, status-context text and complete stale-warning paragraphs were updated.
Safety/identity assertions were preserved. A sanitized first-run record is retained
under `ui/runtime/scheduler-refactor/first-run/`. No repeated effect was triggered.

Final verification passed21/21 browser cases,10/10 server cases, typecheck and
the99-module build. A guarded live journey passed with8 scheduler GET requests,
zero unsafe requests/page errors and unchanged static guard files. The second
run exposed a mobile focus race, repaired at render commit; independent review
found a mentor header/row priority mismatch, repaired through the shared helper.
Desktop/mobile/mentor captures were inspected. Final verification is also
recorded in the scheduler runbook. UI acceptance cannot establish scheduled business
runtime acceptance, dispatch repair or Gmail delivery. A separate Codex session
accepted Gmail intake/readback ownership and waits for the concrete Claude request.
