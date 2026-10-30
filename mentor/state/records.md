# Compact records

Copy task.template.json into ignored mentor/runtime/ only when durable continuity
is useful. This is a convention, not an enforced schema or autonomous supervisor.

Each deliverable: `id`, `description`, `acceptance`, `status`, `evidence` (paths or
observations). Status: pending, in_progress, verified, or removed_by_user.
Each scope change: user instruction, affected IDs, and reason. An agent's desire
to save effort is not authorization to remove a deliverable.
Each experiment: ID, hypothesis, baseline/candidate versions, case/split reference,
metrics, acceptance/stopping rule, attempt records, results and disposition.
Each blocker: dependency, observed error, alternatives with outcomes, independent
work remaining, and required external change. Leave null when absent.

Do not store credentials or copy private holdings into these records. Evidence
may be a reference to an authorized local artifact. Unknown usage remains null.
