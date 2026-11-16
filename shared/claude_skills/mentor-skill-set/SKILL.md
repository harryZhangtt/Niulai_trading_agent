---
name: mentor-skill-set
description: "Route mentor guidance to six specialists for development discipline, task supervision, progress recovery, experiment design, evidence/overfitting and evaluation design. Use for engineering decisions or sustained research; not ordinary summaries."
---

# Mentor skill set for Claude Code

This is a compact entrypoint to six maintained specialists, not an autonomous
watchdog, model executor, release lock or Harry UI activation.

Resolve the symlink of the directory containing this skill as `<skill-dir>`.
Locate the maintained source checkout independently of the target project:

```sh
python3 -B -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parents[2])' "<skill-dir>"
```

Use the returned absolute path as `<source>`. Read `<source>/mentor/AGENTS.md`
and `<source>/mentor/ROUTING.md`. Select the full specialist for the actual
unresolved decision, not incidental keywords:

| Decision | Read under `<source>/mentor/skills/` |
| --- | --- |
| Boundaries, reuse/ROI, safe first E2E, failures/secrets, integration | `development-discipline/SKILL.md` |
| Recover task state, reconcile deliverables, verify completion | `research-supervisor/SKILL.md` |
| Stalls, repeated failures, blockers | `progress-and-recovery/SKILL.md` |
| Falsifiable interventions and experiments | `experiment-design/SKILL.md` |
| Evidence, leakage, correlated sources, overfitting/generalization | `evidence-and-overfitting/SKILL.md` |
| Cases, graders, metrics, splits, budgets, promotion gates | `evaluation-design/SKILL.md` |

Reuse loaded bodies; load only needed references and reload after compaction when
absent. Preserve deliverables, distinguish observed/assumed/unverified results,
protect data and require actual evidence before completion claims.

The target project's instructions govern implementation. Resolve source-relative
scripts/references under `<source>`, but keep task files, caches, dependencies and
results in explicitly authorized target-local locations. Investment-specific
contexts are adaptations, not authorization to inspect this checkout's private
state or change investment behavior in another repository.

The Codex SessionStart definition is not a Claude hook. Missing actual
`MENTOR_INIT_OK` output means automatic initialization is unverified; reading the
policy/router directly is the fallback, not evidence that a hook ran. This
installation changes no hooks, settings, tools, background services or credentials.
