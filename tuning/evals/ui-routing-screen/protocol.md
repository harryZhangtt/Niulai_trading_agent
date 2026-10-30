# UI routing screen v1

Freeze cases and a copy of ui/AGENTS.md and ui/ROUTING.md before dispatch.
A fresh worker receives only the public requests and these two documents.
No expected routes, skill bodies, prior conversation or other artifacts.
It selects minimal skill packages and conditional references without executing
the tasks. Eight author-created development cases cover visual direction, small
polish, components, React performance, state/browser overlap, animation and two
negative controls. This is a routing test, not a quality comparison of generated
interfaces. The separate React/Playwright fixture supplies runtime evidence.

Required/optional package sets and material playbooks are frozen in cases.json.
Pass each case only if all required packages and no unnecessary packages are
selected; also report required playbook coverage separately. No new skill exists
merely because a library name is mentioned. One worker, no semantic retries;
preserve a failed attempt. Instructions limit filesystem access but do not supply
OS isolation. Same inherited model/settings, no overrides or external access.

Measure the routing document and selected local SKILL.md/reference text with
tiktoken 0.12.0 o200k_base using a workspace-local cache. Report separate-decision
and cumulative-union contexts. The all-seven-entrypoints counterfactual excludes
their conditional references: state this asymmetry and do not infer billing,
latency or quality. Provider usage is unavailable. Protect controls from
gratuitous skill loading. Frozen source/snapshot hashes and complete unique IDs
are required before reporting a pass. Do not tune to the screen and call the
same cases fresh validation. Broader effectiveness remains unmeasured.
